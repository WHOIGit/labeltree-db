# Tasks

## 1. WoRMS client and cache

- [ ] 1.1 Add the `worms` app, the `WORMS_RECORD` model and migration, and Django's database cache (`CACHES`, cache table created by migration); verify migrations apply and cache values written in one process are read in another
- [ ] 1.2 Implement the WoRMS client (record, classification, search by name) with timeouts, retries and lineage normalisation; verify against recorded HTTP fixtures, with no live calls in tests
- [ ] 1.3 Implement `get_record(aphia_id, max_age)` with insert-on-`modified`-change and `fetched_at` refresh, and a unique `(aphia_id, worms_modified)` so concurrent fetches of one AphiaID insert one row; verify the `worms-records` cache scenarios
- [ ] 1.4 Implement `/worms/search`, `/worms/{aphia_id}`, `/lineage`, `/between` and `/common_ancestor`, with `400`, `404` and `503` handling and `fetched_at` in responses; verify each lookup scenario

## 2. Placement checks

- [ ] 2.1 Implement `check_nodes` for `out_of_lineage` (with unanchored pass-through and synonym `valid_AphiaID`), `unaccepted_aphia` (with suggestion) and `duplicate_aphia`; verify one test per scenario in `worms-placement-checks`
- [ ] 2.2 Implement recheck-scope computation per change (the node, first anchored node on each path below it, same-AphiaID nodes before and after); verify the moving-unanchored and removing-duplicate scenarios

## 3. Engine integration

- [ ] 3.1 Add `CHANGE.checks` and run checks on changeset save, storing per-change warnings or `"unavailable"`; verify the saved-draft scenario
- [ ] 3.2 Add the `NODE_WARNINGS` model and write changed warning sets on publish inside the transaction, with WoRMS fetches done before the lock; verify the clear and quiet-recheck scenarios and that warnings never block publishing or bump versions
- [ ] 3.3 Test WoRMS-down publish: changes record `unavailable`, publish succeeds, `worms_data` stays null; verify with the client stubbed to fail

## 4. Read API

- [ ] 4.1 Fill `worms_data` and `worms_warnings` in the detailed and export serialisers with batched queries, and remove the placeholder behaviour; verify the `node-read-api` WoRMS scenarios and that the `ETag` changes when warnings change
- [ ] 4.2 Implement `GET /nodes/{id}/warning_history` (newest first, paginated); verify the raised-then-cleared scenario
- [ ] 4.3 Add WoRMS scientific names to text search with `matched_on: "worms"` and de-duplication, and fill the `export_flat` `worms_*` columns; verify the `tree-read-api` scenarios

## 5. Drift

- [ ] 5.1 Implement the drift runner (collect AphiaIDs, re-fetch with `max_age=0`, then re-check and write changed rows in one transaction under the tree's publish lock against the latest revision), the `drift:<tree>` advisory lock, status with progress in the cache, and clearing drift status in `start-django`; verify the quiet-run, reclassified-family, outage, publish-during-run and interrupted-run scenarios with stubbed WoRMS
- [ ] 5.2 Implement `POST /trees/{tree}/drift` (`202`, `409`), `GET .../drift/status` and `GET .../drift` (paginated), plus the `run_drift` management command; verify the endpoint scenarios and that a run creates no revision
- [ ] 5.3 Document `run_drift` and a cron example in README.md; verify the documented command runs as written

## 6. Acceptance on NES2022_taxonomy

- [ ] 6.1 Import `labeldata/NES2022_taxonomy.json` as `NES2022_taxonomy` against recorded WoRMS fixtures in a test; verify 245 nodes at revision 1, every anchored node has `worms_data`, and the stored warnings match the expected fixture
- [ ] 6.2 Run the real import once against live WoRMS in the Compose environment; verify `GET /trees/NES2022_taxonomy`, a node read and `GET /trees/NES2022_taxonomy/drift` return sensible results, and record the warnings found in the change notes

## Workflow follow-up

- Archive only after `core-tree-model` is archived, since this change modifies its `node-read-api` and `tree-read-api` specs.
