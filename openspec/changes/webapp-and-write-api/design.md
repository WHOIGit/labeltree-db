# Design

## Context

Builds on `core-tree-model` (engine, read API, `import_tree`) and
`worms-integration` (record cache, placement checks, warning history, and
drift runs, which this change renames syncs). The engine already reduces, validates and publishes changesets and is
called only from management commands. Saving and publishing currently fetch
missing or stale WoRMS records before their transaction, and drift runs stop at
the first AphiaID that keeps failing. The interactive mockup
`design/mockups/webapp-mockup.html` and its spec define the intended look and
interaction. See proposal.md for motivation.

## Goals / Non-Goals

**Goals:**

- One authorisation layer shared by API and web app.
- Keep the engine the only place that reduces, validates and publishes. The
  browser only composes change lists and renders server results.
- Plain call-and-response between browser and server: no live checking while
  composing, and every slow WoRMS operation is a job the browser polls.
- Reuse the mockup's layout and Alpine.js state model rather than redesign.

**Non-Goals:**

- A visual diff of a draft against its base revision beyond the draft markings
  and the By node tab.
- Reordering changes by drag and drop.
- Highlighting between changes-panel tabs (only tab entries to tree nodes).
- Keeping the as-composed list of a saved draft: only the reduced list is
  stored.
- Linking a clone to its source tree.
- Managing roles or tokens outside Django admin.

## Decisions

### Authentication

- **Sessions** via Django auth for the web app, with standard login and CSRF.
  django-ninja's `SessionAuth` (CSRF-checked) covers API calls the browser
  makes.
- **Tokens:** an `ApiToken` model (hashed key, owning user, name, created,
  revoked) checked by a django-ninja `APIKeyHeader` (`Authorization: Token
  <key>`). Service accounts are ordinary Django users with no password.
- Both auth classes are set as the API's global `auth`, so a route can't be
  left unauthenticated by forgetting it.

Alternative: django-rest-knox or OAuth. Rejected, since nothing here needs
expiry flows or third-party login.

### Roles

A `TreeRole(user, tree, role)` table with a unique `(user, tree, role)`. The
global tree-creation permission is the Django model permission
`core.add_tree`, assignable to users or groups in Django admin. A single helper
`require(user, tree, *roles)` raises `403`, and every router and view calls it.
The rules come from the `access-control` spec in one place:

- reads, job status: any role
- draft, validate, fetch jobs, aliases, descriptions: `drafter`
- publish: `approver`
- `sync_new`, `sync_tree`: `drafter`, `approver` or `admin`
- `sync_all`: Django superuser

Publishing a new tree inserts `TreeRole(publisher, tree, admin)` in the publish
transaction. `GET /trees` filters to trees the user has a role on.

### WoRMS stays out of saves and publishes

`fetch_records` and `PUBLISH_MAX_AGE` go. `validate`, save and publish build
their records from the cache only (`newest_rows`, complete rows), and anything
missing makes the affected changes `unavailable`, exactly as an outage did
before. Keeping the cache current is the job of the fetch step behind the
Validate button and of sync runs, on demand or from cron.

Alternative: keep fetching on save and publish with a short budget. Rejected:
a request that may take 30 s on a bad WoRMS day, with no progress shown, is
what this change removes.

### WoRMS jobs

The drift runner in `worms/drift.py` generalises into one job runner in
`worms/sync.py`, for four kinds. "Drift" disappears from the API, code and docs:
the three re-fetching kinds are **syncs**.

| Kind | Fetches | Then | Lock |
|---|---|---|---|
| `fetch` | given AphiaIDs without a complete cached row | nothing (cache only) | none |
| `sync_new` | the tree's AphiaIDs without a complete cached row | re-check tree, write warnings | `worms-sync:<tree>` |
| `sync_tree` | every AphiaID in the tree (today's drift run) | re-check tree, write warnings | `worms-sync:<tree>` |
| `sync_all` | every cached AphiaID and every tree's AphiaIDs | re-check every tree | `worms-sync:all`; refused while any `worms-sync:<tree>` is held, and tree syncs are refused while it is held |

- **Endpoints**, all under `/worms`, since jobs aren't tree content and
  `sync_all` has no tree:
  - `POST /worms/jobs {kind, tree?, aphia_ids?}` (`tree` required except for
    `sync_all`) returns `202` with the job's status, or `409 sync_in_progress`;
  - `GET /worms/jobs/{job}`;
  - `GET /worms/jobs?tree=` returns the tree's active and last sync, or, without
    `tree`, the active and last `sync_all`;
  - `GET /worms/warnings?tree=` is the warnings report, feeding the warnings
    panel.

  They replace `POST /trees/{tree}/drift`, `.../drift/status` and `.../drift`.
- **Status** lives in the DatabaseCache as drift status does now, keyed by a
  job id (UUID), with `worms-sync:<tree>` (and `worms-sync:all`) pointing to the
  active and last sync. Each job holds a session advisory lock `worms-job:<id>` for its
  lifetime, so a status whose lock is free is reported `interrupted`; startup
  clears these through `clear_worms_jobs`, which replaces `clear_drift_status`.
- **Retry visibility:** `WormsClient` takes an `on_wait(aphia_id, attempt,
  retries, seconds)` hook next to `sleep`; the runner records it in the job's
  `retrying` map and clears it when the AphiaID finishes. The browser draws one
  bar per entry from `wait_until` and the schedule.
- **Schedules:** `JOB_BACKOFF = (1, 2, 5, 12)` for API-started jobs,
  `SCHEDULED_BACKOFF = (10, 30, 60, 120)` (today's `DRIFT_BACKOFF`) for the
  management command, `BACKOFF =
  (1, 2)` for lookup endpoints.
- **Failures skip:** `get_records` loses `stop_on_error`; each failing AphiaID
  goes to `failed` and the pool carries on. Sync kinds then re-check with the
  records they have and write rows only for nodes whose needed records are all
  present and were not in `failed` (`check_nodes` already returns `None` for a
  node missing a record; the run additionally treats failed AphiaIDs as
  missing).
- **429:** the client raises a distinct `RateLimited(retry_after)` instead of
  sleeping itself. The runner sets `paused`, stops handing out AphiaIDs, waits,
  and resumes. A second 429 after resuming ends an API-started job (remaining
  AphiaIDs to `failed`); management-command jobs allow 4 pauses. Lookups keep
  today's per-request handling.
- **Try again** in the web app starts the same kind with `aphia_ids` set to the
  failed ones. For sync kinds the whole tree is still re-checked.
- **Management command:** `worms_sync <tree>` (`sync_tree`), `worms_sync <tree>
  --new` (`sync_new`), `worms_sync --all` (`sync_all`), replacing `run_drift`.
  It exits non-zero if any
  AphiaID failed, so cron mail reports it, after writing what it could.

Alternative: stream progress over one long HTTP response. Rejected: it ties a
server worker for minutes, and drift runs already use polled status in the
cache.

### Validate flow

```
 [Validate] -> POST validate (cache only)
                 |
        worms_missing empty? --yes--> show result, enable Save
                 | no
                 v
          POST worms/jobs {kind: fetch, aphia_ids: worms_missing}
          poll GET /worms/jobs/{job} ~1 s: job bar, retry bars, pause bar
                 |
           failed empty? --no--> list failures: [Try again] | [Proceed anyway]
                 | yes                               |
                 v                                   v
          POST validate again ---------------> show result, enable Save
```

Save is gated only in the browser. The server always reduces and runs
structural checks on save; an API client that skips the fetch step gets
`unavailable` checks for uncached AphiaIDs, which the next sync fills in.
Structural errors don't block save (the web app asks for confirmation), only
publish.

### Changeset endpoints

These are thin wrappers around the engine. The `ETag` of a draft is a hash of
`(id, updated_at, base_rev, changes)`. `PUT` and `publish` compare `If-Match`
inside a `SELECT ... FOR UPDATE` on the changeset row, so the `412` check and
the write are atomic. `validate` runs the same path as save, without the final
write, and `GET /changesets/{cs}` computes the same result for a stored draft.
New-tree changesets live at `POST /changesets` because they have no tree in the
path.

### Change provenance (`sources`)

`ChangeSpec` gains `sources: tuple[int, ...]`, set to `(seq,)` by
`specs_from_dicts`. Every rewrite in reduction combines them: `_merged` takes
the union of both changes' sources, a successor collapse keeps the earlier
deprecate's sources plus the later one's, and drops discard theirs. `renumber`
keeps them. `validate` returns them on `reduced_changes`; they are not stored,
since a saved draft's reduced list becomes the new as-composed list when it is
reopened.

This answers the question left open by `core-tree-model` (groups are only labels
and reduction keeps the last change's group): group tags are taken from every
source, so a split's `add` that was later renamed by hand still shows under
`split#1` in By node, while `reduced_changes[].group` keeps today's rule.

### Net changes per node (`node_changes`)

Computed from the base state and the final state only, alongside
`version_changes`: for each node whose content, parent, child set or
deprecation differs, the changed fields as `[old, new]`, children gained and
lost, successors, the reduced `seq`s that touch it (as node, parent or
successor), and the union of those changes' source groups. Because it ignores
order, temporary labels and moves undone by hand never show. For a draft with
errors, the final state is what applied, so the review shows errors next to the
net changes.

Alternative: regroup the ordered changes under nodes. Rejected: a change
belongs to several nodes, interleaving (e.g. label swaps) is lost, and editing
from that view would act on a list the user can't see in order.

### Web app

- Server-rendered Django templates for the page frame, login, node page and
  draft list. The tree browser and draft editor are one page whose state is an
  Alpine.js store, ported from the mockup, that talks to `/api/v1` with the
  session.
- **No live checks.** The mockup's local JavaScript checks are dropped; the
  only check before Validate is what composing itself needs (Move to excludes
  descendants, Deprecate is blocked on nodes with children).
- **Changes panel tabs:** As edited (the editable list), As reduced, By node,
  Summary, WoRMS warnings and Errors. Each tab remembers the validation id it
  last showed; a newer result sets its unread dot. After an edit, the
  result tabs are greyed with "out of date, press Validate".
- **Jump to node:** a tab entry maps to node ids (for a move: the node, and the
  old and new parents for hover); click expands ancestors via the store,
  scrolls into view and flashes the row.
- **AphiaID pill:** colour from `worms_data` and current `worms_warnings` in
  the node payload: no `worms_data` and no `unknown_aphia` is grey (never
  fetched), `unknown_aphia` red, any other warning orange, else green. The link
  is `https://www.marinespecies.org/aphia.php?p=taxdetails&id=<id>`.
- **Sync menu and progress** share one progress component with Validate's
  fetch step; the menu polls `GET /trees/{tree}/worms/jobs` while open, so a
  cron run is visible.
- Merge, split, import, clone and Add from WoRMS are client-side expanders that
  produce grouped change lists, with no endpoints of their own. Import parsing
  runs in the browser using the same rules as the server format, and clone
  fetches `/trees/{tree}/nodes_as_tree?rev=` and runs it through the same
  client expander. The server re-validates everything on save.
- **Labels from WoRMS names:** spaces become `_`, then characters outside
  `[A-Za-z0-9_.-]` are dropped, as is leading punctuation.
- Aliases after a merge: after a successful publish response, the client issues
  `POST /nodes/{id}/aliases` for each missing label and alias. A failure is
  shown to the user with a retry. It is not transactional with the publish,
  which matches the spec, since aliases sit outside changesets.

Alternative: an HTMX-style fully server-rendered editor. Rejected, because the
mockup's interaction (markings, pick mode, wizards) is already built in
Alpine.js and maps directly onto the API.

### Bootstrap and Alpine from static files

Bootstrap 5 and Alpine.js are vendored into `static/`, not loaded from a CDN,
so the app works on isolated lab networks.

## Risks / Trade-offs

- [BREAKING auth on reads cuts off existing consumers] → Issue `reader` tokens
  to roi-db and datasetman before deploy, and announce the cut-over date.
- [Warnings computed at publish may use an older cached record] → A record is
  as fresh as the last fetch or sync; nightly `sync_tree` runs and Sync this
  tree bound the age. Each warning-history row's `computed_at` is unchanged in
  meaning.
- [API clients that skip the fetch step publish `unavailable` checks] →
  Acceptable by design; `sync_new` (and cron) fills them in.
- [Client-side import parsing diverges from the server's] → The server is
  authoritative and returns errors per change. A shared JSON fixture set is
  tested against both parsers.
- [`sources` tracking makes reduction rewrites harder to get right] → The
  existing reduction tests gain `sources` assertions, plus the worked examples
  (split then rename, label swap, move undone by hand).
- [Polling many job statuses] → One poll per second per open progress view, on
  a cached value; stop polling when the job finishes or the view closes.
- [Alias copy after a merge can partially fail] → The UI lists any aliases it
  could not copy and offers a retry.

## Migration Plan

1. Deploy the `ApiToken` and `TreeRole` migrations.
2. In Django admin, create service accounts and tokens for roi-db and
   datasetman with `reader` on both NES2022 trees, and create curator accounts
   with their roles. Grant `core.add_tree` to tree administrators. Assign
   `admin` on existing trees to the operator who loaded them.
3. Switch consumers to send tokens, then deploy the auth-enforcing release.
4. Replace `run_drift` with `worms_sync` in the cron entry. Its exit status
   now reports any failed AphiaID rather than a stopped run.

Rollback: revert to the previous release. Tokens and roles stay in place,
unused.
