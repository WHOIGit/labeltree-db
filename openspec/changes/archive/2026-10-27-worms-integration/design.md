# Design

## Context

Builds on `core-tree-model`: the in-memory `TreeState`, the apply/reduce/publish
engine and the read API serialisers already exist. Their `worms_data` and
`worms_warnings` placeholders are filled here. The WoRMS REST API
(`https://www.marinespecies.org/rest`) has no releases and no per-record
history; the relevant calls are `AphiaRecordByAphiaID`,
`AphiaClassificationByAphiaID` and `AphiaRecordsByName`. See proposal.md for
motivation and `design/worms.md` for the background reasoning.

## Goals / Non-Goals

**Goals:**

- One WoRMS client with timeouts, retries and caching that every caller
  (lookups, checks, drift) goes through.
- Placement checks as a pure function of a `TreeState` plus cached records, so
  they are fast to test and identical on save, publish and drift.

**Non-Goals:**

- Authentication on the lookup and drift endpoints (added by
  `webapp-and-write-api`).
- "Add from WoRMS" and the WoRMS card in the web app (also
  `webapp-and-write-api`).
- Historical WoRMS states from DwC-A exports or ChecklistBank.

## Decisions

### WoRMS client and cache

A `worms` Django app holds `WORMS_RECORD` (`aphia_id`, `record` jsonb with name,
rank, status, `valid_AphiaID` and the flattened lineage, `fetched_at`,
`worms_modified`) and a client wrapping `httpx` with a 10 s timeout and two
retries. `get_record(aphia_id, max_age)` returns the newest cached row (latest
`fetched_at`) if it is younger than `max_age`, else fetches record and lineage
and stores them with `INSERT .. ON CONFLICT (aphia_id, content_hash) DO UPDATE
SET fetched_at`. `content_hash` is a SHA-256 of the stored record including its
lineage, so a changed record **or** a changed lineage adds a row, an unchanged
one only bumps `fetched_at`, and concurrent fetches of one AphiaID store one
row. Comparing `modified` alone isn't enough: when WoRMS moves a family, the
genera below it get a new lineage but keep their record and `modified` time.

WoRMS answering "no such record" is cached too (a row with `record` null), so
`unknown_aphia` is stable and isn't re-fetched on every save.

- Lookups and saves use a long `max_age` (cache first, fetch on miss).
- Publish re-fetches the AphiaIDs that its changes add or alter if their row is
  older than 10 minutes, so new anchors are checked against current WoRMS
  without fetching twice when a draft is saved and published right away (as
  `import_tree` does).
- Drift uses `max_age = 0`.

Search results come without lineages, and fetching one per hit would make a
search cost up to 100 extra calls. They are cached with `lineage` null, which
`get_record` treats as a miss; the first full fetch fills the lineage into that
row if the record is unchanged, instead of adding a row.

Lineage is stored with the record, because `out_of_lineage` needs it for every
anchored node and it is fetched in the same pass. Alternative: separate lineage
rows. Rejected, because nothing queries lineage independently of the record.

The client classifies failures as `worms_unreachable` (timeout or connection
error), `worms_rate_limited` (HTTP 429) or `worms_error` (other non-2xx). On a
429 it waits for `Retry-After` (default 30 s) before retrying, up to the retry
limit. Other transient failures (timeouts, connection errors, 5xx) are retried
twice, after 1 s and then 2 s, when a user is waiting on the answer (lookups,
saves, publishes). Drift runs, which run in the background, retry four times,
after 10 s, 30 s, 1 min and 2 min, so they ride out a WoRMS outage of about four
minutes per AphiaID before failing. Callers get the classified reason: drift
records it in its status, and the lookup endpoints return it as the `error`
code of their `503`.

`between` and `common_ancestor` are computed from the two cached lineages, with
no extra WoRMS calls.

### Checks as a pure function

`check_nodes(state, node_ids, records) -> {node_id: [warning]}` computes the
four warnings (`out_of_lineage`, `unaccepted_aphia`, `unknown_aphia`,
`duplicate_aphia`) for the given nodes, or None for a node whose records are
unavailable. The recheck scope (spec: "Recheck scope of
an edit") is computed by the engine from the change list and the before and
after states, and passed in as `node_ids`. Drift passes every anchored node.
`duplicate_aphia` uses an AphiaID → nodes index built on the `TreeState`.

### Where checks plug into the engine

- **Save:** after reduce and apply, the engine computes the recheck scope per
  change, runs `check_nodes` against the state after that change, and stores the
  warnings that change introduces in `CHANGE.checks`. If any needed record is
  unavailable, that change's `checks` is `"unavailable"`.
- **Publish:** same, then for every rechecked node compares the result with its
  newest `NODE_WARNINGS` row and inserts a row if it differs, inside the publish
  transaction. WoRMS fetches happen **before** the transaction opens, so a slow
  WoRMS never holds the tree lock.

### Drift runner

A management command `run_drift <tree>` and the `POST` endpoint both enqueue a
run on a background thread pool inside the web process (a `ThreadPoolExecutor`
with one worker per tree). The command form runs synchronously so cron can
schedule it.

- **One run per tree:** the worker takes an advisory lock,
  `pg_try_advisory_lock(hashtext('drift:' || tree))`, on its own connection.
  Like every advisory lock it is database-wide, so every web process, container
  and management command sees it. It is the session-level kind (unlike publish's
  transaction-level lock) only so that it outlives the run's many transactions:
  the worker holds it for the whole run and releases it at the end. If it is
  taken, starting a run returns `409`. PostgreSQL also releases it when the
  worker's connection closes, so a crashed run never blocks the next one and
  needs no TTL.
- **Status and progress** live in Django's cache under `drift:<tree>`, using the
  database cache backend (`DatabaseCache`), so every server process sees them
  without an extra service. `start-django` clears these keys on startup, so a
  run interrupted by a restart doesn't show as active.
- **Writing warnings:** WoRMS fetches happen with no tree lock held. The run
  then opens one short transaction, waits for the tree's `publish:<tree>`
  advisory lock, re-checks against the latest revision at that moment, and
  writes the changed `NODE_WARNINGS` rows. A publish during the run therefore
  can't be overwritten with warnings computed from an older revision.

Alternatives: Celery, rejected for now, since a run takes minutes, happens
rarely, and losing the status on restart is acceptable per the spec. Redis as
the cache, rejected: drift status is its only use, PostgreSQL covers it, and it
would add a service (and Redis's licensing questions) to dev and deployment.

### Read-side changes

The serialisers look up the newest `WORMS_RECORD` per AphiaID for all nodes in
the response in one query, and the newest `NODE_WARNINGS` row per node in one
`DISTINCT ON (node)` query. The body-hash `ETag` already covers these values.
Search adds a normalised `worms_name` source to the existing ranked query.

## Risks / Trade-offs

- [WoRMS rate limits or slowness during a 200-AphiaID import] → Fetch
  concurrently with a small pool (4) before the transaction, and treat failures
  as `unavailable` instead of failing the publish.
- [In-process drift thread dies with the worker] → The advisory lock is released
  with the connection, and startup clears the stale status; rerun it. Move to a
  task queue if this bites.
- [A publish arrives while drift is writing warnings] → Drift holds the publish
  lock only for one short transaction, so the publish is refused with
  `publish_in_progress` for at most that moment and can be retried.
- [Lineage format changes in WoRMS responses] → The client normalises to a
  stored list of `{AphiaID, rank, scientificname}` and tests run against
  recorded fixtures.

## Migration Plan

1. Deploy: migrations add `WORMS_RECORD`, `NODE_WARNINGS` and `CHANGE.checks`,
   and the database cache table (`createcachetable`).
2. Run `run_drift NES2022_tags` (no AphiaIDs, so a no-op sanity check).
3. Import the taxonomy:
   `manage.py import_tree labeldata/NES2022_taxonomy.json --tree NES2022_taxonomy --title "NES2022 taxonomy"`.
   Then run `run_drift NES2022_taxonomy` to fill any `unavailable` checks.

Rollback: the new tables are additive. Reverting the code restores
`worms_data: null` and `worms_warnings: []`.
