# Design

## Context

The repository holds only design documents (`design/`) and the two example
trees (`labeldata/`). See proposal.md for scope. The `design/` documents remain
the background reference; where this change's specs differ from them (conflicts
require `base_rev` = latest, op reduction on save, no empty trees), the specs
win.

Scale: a few trees of up to a few thousand nodes, hundreds of revisions, a
handful of editors and read traffic from a few services.

## Goals / Non-Goals

**Goals:**

- A schema and publish engine that every later change (WoRMS checks, write API,
  web app) builds on without rework.
- One code path that applies, validates and reduces change lists, used by the
  import command now and by `validate`, draft save and publish later.
- The read API serving `NES2022_tags` end to end.

**Non-Goals:**

- Authentication, roles, write endpoints, draft CRUD over HTTP and the web app
  (`webapp-and-write-api`).
- WoRMS fetching, caching, checks, warnings and drift (`worms-integration`).
  The `CHANGE.checks` and `NODE_WARNINGS` storage is not created here.
- Loading `NES2022_taxonomy` (after `worms-integration`).

## Decisions

### Stack and layout

Django + django-ninja on PostgreSQL 16, run with Docker Compose (`web`, `db`).
Python dependencies are pinned with `uv`. Tests use pytest + pytest-django
against a real PostgreSQL. Two Django apps:

- `trees`: models, the changeset engine and the management commands
- `api`: django-ninja routers, response schemas and serialisation

Alternative: one app. Rejected because the engine must stay importable without
HTTP concerns, since the web app and API both drive it later.

### Schema

Tables follow `design/diagrams/02-data-model.d2` for the core and changeset
tables, plus `NODE_ALIAS` and `SUCCESSOR`. Deviations:

- `CHANGESET.tree` is nullable, and a new-tree changeset stores
  `new_tree_id`, `new_tree_title` and `new_tree_description` instead.
  Publishing creates the `TREE` row in the same transaction.
- `NODE_VERSION` carries a denormalised `tree` column so that "the tree at
  revision r" and label lookups don't need a join to `NODE`.
- `TREE_REVISION` has a surrogate integer primary key plus a unique
  `(tree, number)`. `NODE.created_in_rev`, `NODE.deprecated_in_rev` and the
  `NODE_VERSION` range columns store revision **numbers** (ints), not foreign
  keys, because the range comparisons are numeric and always within one tree.
- `published_by`, `author`, `added_by` and `removed_by` are plain username
  strings for now, so that access control can arrive later without a data
  migration of these columns.

Indexes: `node_version (tree, valid_from_rev)`, `(parent, valid_from_rev)`,
`(tree, label)`, `(node, version)` unique, and `(aphia_id)`. A partial unique
index on `node_version (node) WHERE valid_to_rev IS NULL` guarantees at most one
open version per node.

Label uniqueness per revision is enforced by the engine at publish and
covered by tests. A PostgreSQL exclusion constraint over
`(tree, label, int4range(valid_from_rev, valid_to_rev))` with `btree_gist` is
added as a safety net. Alternative: rely on the engine alone. Rejected, because
the constraint is cheap and catches engine bugs that would corrupt history.

### Engine: apply, reduce, validate, publish

The engine works on an in-memory `TreeState` built from the latest revision:
for each node in the tree, its label, parent, description, `aphia_id` and
version, plus label and children indexes. At this scale (thousands of nodes)
loading a full revision is a few milliseconds and keeps every check simple and
exact.

1. **Apply** steps through the changes, checking each against the current
   `TreeState` and recording a structural error if it fails. A failing change
   is skipped and later changes continue against the state the valid ones left.
2. **Reduce** rewrites the list per node and group (spec: changesets, "Op
   reduction on save"). Each candidate merge is applied tentatively and kept
   only if re-applying the list yields no new errors and the same final state.
   It repeats until nothing changes. The final-state comparison makes "reduction
   never changes the result" a checked property, not just an intention.
3. **Diff** compares the final `TreeState` with the initial one per node
   (fields, parent, child set) to get version changes. This net comparison is
   also why a rename and rename back produce no bump.
4. **Publish** takes the tree's publish lock (see below), checks
   `base_rev = latest`, runs reduce and apply, and
   refuses on any error. It then allocates ids from a PostgreSQL sequence,
   rewrites placeholders in the stored change payloads, closes and opens node
   versions according to the diff, writes successors and initial aliases, and
   creates the revision.

Alternative for (3): bump from the list of touched nodes. Rejected, because it
cannot tell a net no-op from a real change.

### Publish lock-out

The lock is a PostgreSQL transaction-scoped advisory lock keyed on the tree id,
or on the proposed id for a new tree: `pg_try_advisory_xact_lock(hashtext('publish:' || tree_id))`
as the first statement of the publish transaction. If it returns false, the
publish is refused at once with `publish_in_progress`.

- Like the in-memory or Redis flag it replaces, it is a named "publishing now"
  marker that other publishers check without waiting.
- Every web process and management command shares the database, so they all
  see it. An in-process variable would only be seen by one process.
- It is released automatically when the transaction commits, rolls back or the
  connection dies, so a crashed publish cannot leave the tree locked. A Redis
  key would need a TTL and could expire during a slow publish or outlive a
  crash.
- It needs no extra service in this change. Redis only arrives with
  `worms-integration`.

### Version changes are derived

Revision `version_changes` are derived from `NODE_VERSION` ranges: versions
opened at `r` (`valid_from_rev = r`) and closed at `r`. No `CHANGE_EFFECT`
table is needed.

### Import command

`manage.py import_tree <file> --tree <id> --title <title> [--description]
[--user <name>]`. It builds a new-tree changeset (`base_rev: null`, group
`import#1`) in memory and runs reduce and apply on it. If there are structural
errors it prints them and stores nothing; otherwise it saves the changeset,
publishes it, and prints the revision summary. The file-to-changes expansion is a plain function so
the web app's import wizard reuses it.

### Read API

- Serialisation builds the requested revision's `TreeState` once per request,
  then renders shapes from it. Descendants, `nodes_as_tree`, `export` and
  `export_flat` are walks over that in-memory state rather than recursive SQL.
  `WITH RECURSIVE` is kept for `ancestors` and single-node depth.
- `ETag` is a SHA-256 of the serialised body. `X-Tree-Revision` is added when
  `?rev` is omitted.
- Search uses PostgreSQL `pg_trgm` for the fuzzy step; exact, prefix and
  substring run on a normalised form (lowercase, `_` → space) over labels and
  current aliases of the revision's nodes.
- Not-found entries in batch lookups are `{id or label, error: "not_found"}`.

### Aliases without a write API

This change creates aliases only from `add` changes. Django admin is enabled
for `NODE_ALIAS` so an operator can correct one; the API endpoints come in
`webapp-and-write-api`.

## Risks / Trade-offs

- [Loading a full `TreeState` per request] → Fine at this scale; cache
  per `(tree, rev)` in process memory if profiling says so, since published
  revisions never change.
- [Reduction rule edge cases] → Property-style tests: for random change lists
  over the tags tree, the reduced list must apply to the same final state with
  no new errors.
- [Read API is unauthenticated until access control lands] → Deploy only on an
  internal network until `webapp-and-write-api`.
- [`design/` and specs drift apart] → Specs are the source of truth for
  behaviour; `design/` is kept as-is by decision.

## Migration Plan

Greenfield. `docker compose up` brings up PostgreSQL and the app; migrations
create the schema. Load the first tree with
`manage.py import_tree labeldata/NES2022_tags.json --tree NES2022_tags --title "NES2022 tags"`.
