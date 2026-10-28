# Proposal

## Why

Most nodes in `NES2022_taxonomy` carry WoRMS AphiaIDs, and their value depends
on placement being checked against WoRMS: disagreements must be visible, and
WoRMS changes (synonyms, reclassifications) must surface without silently
altering the tree. This change adds the WoRMS cache, placement checks, warnings
and drift reports, after which the taxonomy tree can be loaded with its
warnings computed from the start.

Depends on `core-tree-model`.

## What Changes

- A service-side cache of WoRMS records and lineages, with a new row whenever a
  record or its lineage changes. Reads never call WoRMS.
- WoRMS lookup endpoints (`/worms/search`, `/worms/{aphia_id}`, `lineage`,
  `between`, `common_ancestor`) served from the cache, fetching on a miss.
- Placement checks producing `out_of_lineage`, `unaccepted_aphia`,
  `unknown_aphia` and `duplicate_aphia` warnings, run when a changeset is saved and published. The
  results are stored on each change and, on publish, as per-node warning history.
  Warnings never block publishing and never bump versions.
- Drift reports: an asynchronous whole-tree re-fetch and re-check that updates
  warnings, startable through the API or a management command.
- Detailed nodes return real `worms_data` and current `worms_warnings`; a new
  `warning_history` endpoint; search also matches cached WoRMS names; the flat
  export's `worms_*` columns are filled.
- Acceptance: `NES2022_taxonomy` is imported as a new tree.

## Capabilities

### New Capabilities

- `worms-records`: the WoRMS record cache, its history, and the WoRMS lookup
  endpoints.
- `worms-placement-checks`: the warning types, what each edit rechecks, when
  checks run, behaviour when WoRMS is unreachable, and how warnings are stored.
- `worms-drift`: whole-tree drift runs, their status, and the report of nodes
  with warnings.

### Modified Capabilities

- `node-read-api`: `worms_data` and `worms_warnings` are filled from the cache
  and stored warnings instead of `null` and `[]`; adds `warning_history`.
- `tree-read-api`: text search also matches cached WoRMS scientific names.

## Impact

- Outbound HTTPS to the WoRMS REST API (`marinespecies.org/rest`) from the
  service only, while editing, publishing and running drift reports.
- New tables `WORMS_RECORD` and `NODE_WARNINGS`, and a `checks` column on
  `CHANGE`.
- Publishing now calls WoRMS for new or changed AphiaIDs, so it gets slower and
  degrades to "checks unavailable" if WoRMS is down.
- Uses Django's database cache (a table in PostgreSQL, no extra service) for
  drift-run status, and a PostgreSQL advisory lock for one run per tree.
