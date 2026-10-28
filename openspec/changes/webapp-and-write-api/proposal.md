# Proposal

## Why

After `core-tree-model` and `worms-integration`, trees can only be created or
changed from the command line, and nothing records who may change which tree.
Curators need to draft, review and publish edits in a browser, tree owners need
to decide who may edit their trees, and edits must go through role-checked
endpoints, while published trees stay readable by anyone. Saves
and publishes also wait on WoRMS today, which makes them slow and unpredictable
when WoRMS is slow.

## What Changes

- Tree and node reads stay anonymous. Everything else (drafts, `validate`,
  WoRMS lookups and jobs, alias and description writes, members) requires
  authentication: a session for the web app, a per-user API token for scripts.
- Per-tree roles on a ladder, `reader` < `drafter` < `approver` < `owner`, one
  per user and tree, each including the ones below. Owners manage their tree's
  members in the web app. Site admins (Django superusers) manage users, tokens
  and the global tree-creator role in Django admin, own every tree, and run
  full cache syncs.
- Write API: `validate`, changeset create/list/get/update/publish/discard with
  `ETag`/`If-Match`, direct alias add/remove/history, and direct description
  set/history. `validate` returns each reduced change's `sources` and the net
  changes per node (`node_changes`).
- WoRMS work moves into **WoRMS jobs** with visible progress: `fetch` (before
  validating a draft), `sync_new`, `sync_tree` and `sync_all`. Failed AphiaIDs
  are skipped and reported instead of stopping the job, and rate limiting
  pauses the whole job.
- `validate`, saves and publishes no longer call WoRMS; they check against the
  cache. The 10-minute re-fetch on publish is dropped.
- "Drift runs" are renamed **syncs** throughout: API, management command,
  module, locks and docs. **BREAKING** (no consumers yet): `POST
  /trees/{tree}/drift`, `GET /trees/{tree}/drift/status` and `GET
  /trees/{tree}/drift` are replaced by `POST /worms/jobs`, `GET
  /worms/jobs?tree=`, `GET /worms/jobs/{job}` and `GET /worms/warnings?tree=`,
  and `drift_in_progress` becomes `sync_in_progress`.
- Server-rendered web app: tree browser with revision picker, AphiaID pills,
  warnings panel and sync menu; node page with warning history; draft editor
  with a Validate step, tabbed changes panel and jump-to-node; draft list and
  review by node; a Members page per tree; merge and split wizards; import
  wizard; Add from WoRMS; alias and description editing; and clone as new
  tree. Anonymous visitors can browse read only. The page scripts run under a
  strict Content Security Policy.
- Cloning turns a published revision into a stand-alone new-tree changeset,
  which an approved publish turns into revision 1 of a new tree.

## Capabilities

### New Capabilities

- `access-control`: which endpoints are anonymous, authentication (sessions,
  API tokens), the per-tree role ladder and what each role may do, tree
  members, site admins and tree creators.
- `changeset-api`: the `validate` endpoint and the changeset endpoints,
  including change provenance, net changes per node, cache-only WoRMS checks,
  concurrency control (`ETag`/`If-Match`), rebasing, publishing and their
  status codes.
- `worms-sync`: syncs (`sync_new`, `sync_tree`, `sync_all`) that refresh
  cached records and re-check warnings, their status, one-at-a-time rule,
  failure handling and the warnings report. Replaces `worms-drift`.
- `webapp`: the tree-management web app: pages, AphiaID pills, warnings panel,
  sync menu and job progress, edit mode with Validate before save, the changes
  panel tabs, draft markings, the merge/split/import wizards, Add from WoRMS,
  alias and description editing and cloning.

### Modified Capabilities

- `node-aliases`: adds the alias write and history endpoints.
- `node-descriptions`: adds the description write and history endpoints.
- `tree-import`: adds cloning a published revision into a new-tree changeset.
- `worms-records`: only lookups and WoRMS jobs call WoRMS; adds fetch jobs, job
  status, skipping failed AphiaIDs, retry schedules and rate-limit pauses.
- `worms-placement-checks`: checks use cached records only; uncached records
  make checks unavailable; nodes whose refresh failed get no history row.
- `worms-drift`: retired; every requirement moves, reworded, to `worms-sync`.

## Impact

- API consumers that only read (roi-db, datasetman, annotation tools) are
  unaffected. Scripts that write need a token.
- New tables for API tokens and tree members.
- `src/worms` gains a job runner that generalises the drift runner, renamed
  `worms/sync.py`; the `run_drift` and `clear_drift_status` commands become
  `worms_sync` and `clear_worms_jobs`;
  `src/core/changesets.py` stops fetching from WoRMS; `reduce_changes` tracks
  sources.
- The cron example in README.md changes to `worms_sync`.
- New Django templates, static assets (Bootstrap 5, Alpine.js, as in the
  mockup), and session/CSRF configuration.
