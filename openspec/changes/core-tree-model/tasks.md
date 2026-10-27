# Tasks

## 1. Project scaffolding

- [x] 1.1 Create the Django project in `src/` with `core`, `api` and `accounts` apps, django-ninja mounted at `/api/v1`, dependencies declared in `pyproject.toml` and installed with pip; verify `manage.py check` passes
- [x] 1.2 Add Docker Compose (`web`, `db` on PostgreSQL 18) with `pg_trgm` and `btree_gist` enabled; verify `docker compose up` serves an empty `GET /api/v1/trees`
- [x] 1.3 Set up pytest + pytest-django against the local and Compose databases, runnable with `pytest`; verify a smoke test passes

## 2. Data model

- [x] 2.1 Add models and migrations for `TREE`, `TREE_REVISION`, `NODE`, `NODE_VERSION`, `NODE_ALIAS`, `SUCCESSOR`, `CHANGESET` and `CHANGE` per design.md (nullable `CHANGESET.tree`, new-tree fields, denormalised `NODE_VERSION.tree`); verify migrations apply on a fresh database
- [x] 2.2 Add the indexes, the one-open-version partial unique index and the label exclusion constraint; verify with a test that inserting overlapping same-label versions fails
- [x] 2.3 Add a node id sequence and label validation helper; verify unit tests for the machine-safe regex
- [x] 2.4 Register the models in Django admin (read-only for versioned tables, editable for `NODE_ALIAS`); verify the admin pages load

## 3. Tree state and apply

- [x] 3.1 Implement loading a `TreeState` for `(tree, rev)` from node versions; verify against hand-built fixtures that children, depths and labels match the revision
- [x] 3.2 Implement applying `add`, `edit`, `move` and `deprecate` with placeholder resolution; verify each op's effect in unit tests
- [x] 3.3 Implement every structural error condition (`node_not_in_tree`, `parent_not_in_tree`, `cycle`, `invalid_label`, `label_in_use`, `has_children`, `from_parent_mismatch`, `invalid_successor`, `empty_changeset`) with `seq`, node and detail, continuing after failures; verify one test per spec scenario in `changesets`
- [x] 3.4 Implement the net per-node diff that yields version changes; verify the five-revision example from `design/backend.md` (Chaetoceros v1 to v4) as a test

## 4. Reduction

- [x] 4.1 Implement merging of repeated edits and moves per node and group, folding into `add`, and dropping net no-ops and add+deprecate pairs; verify the `Op reduction on save` and `Reduction drops no-ops` scenarios
- [x] 4.2 Implement the validity and final-state guard that skips unsafe merges and never merges across groups; verify the label-swap and different-groups scenarios
- [x] 4.3 Add a property-style test over random change lists on the tags tree checking that reduction preserves the final state and adds no errors; verify it passes over at least 500 generated cases

## 5. Changesets and publish

- [x] 5.1 Implement changeset save (reduce, then store) and the draft/published/discarded states with frozen changes; verify state-transition tests
- [x] 5.2 Implement publish: tree lock, `base_rev = latest` check (`stale_base`), re-run reduce and apply, id allocation, placeholder rewrite, version close/open, successors, initial aliases, revision row; verify the publish scenarios including split-with-replacement version changes
- [x] 5.3 Implement new-tree changesets (`base_rev: null`, `tree_exists`) creating the tree and revision 1 in one transaction; verify both scenarios
- [x] 5.4 Implement rebase (set `base_rev` to latest and recheck); verify the fell-behind then rebased scenario
- [x] 5.5 Implement the per-tree publish lock-out with a transaction-scoped advisory lock (`publish_in_progress`); verify that a forced failure mid-publish leaves no rows and no lock, and that a publish attempted while another is held open in a test transaction is refused immediately

## 6. Import

- [x] 6.1 Implement parsing and validating the import format (ignore unknown keys, require `label`, report position of malformed nodes) and expansion into an `import#n` group of `add`s with aliases; verify the `tree-import` scenarios
- [x] 6.2 Implement `manage.py import_tree` checking the new-tree changeset in memory, then saving and publishing it only if error-free; verify importing `labeldata/NES2022_tags.json` gives 18 nodes, 5 top-level, all version 1, and that a file with a duplicate label stores no changeset
- [x] 6.3 Document the command in README.md; verify the documented command runs as written

## 7. Read API: conventions

- [x] 7.1 Implement the error body, `?rev` resolution with `404`s, `?dropempty`, `X-Tree-Revision`, body-hash `ETag` with `304`, and `limit`/`offset`/`count` pagination as shared helpers; verify each `api-conventions` scenario

## 8. Read API: nodes

- [x] 8.1 Implement lite, content and detailed serialisers from a `TreeState`, with `worms_data: null` and `worms_warnings: []`; verify shape tests including `?dropempty`
- [x] 8.2 Implement `GET /nodes/{id}` with deprecation records and not-yet-created `404`; verify the `node-read-api` scenarios
- [x] 8.3 Implement `/ancestors` and `/descendants?depth=`; verify path and depth scenarios
- [x] 8.4 Implement `/versions` and `/versions/{v}?rev=` with the range check; verify the `400` and children-within-a-version scenarios

## 9. Read API: trees

- [x] 9.1 Implement `GET /trees` and `GET /trees/{tree}?rev=`; verify listing and summary scenarios
- [x] 9.2 Implement `/revisions` (paginated) and `/revisions/{r}/changes` with derived `version_changes`; verify the revision-1 scenario on the tags tree
- [x] 9.3 Implement `/diff?from=&to=`; verify rename, moved-and-edited, added-in-range and added-then-deprecated scenarios
- [x] 9.4 Implement `/nodes_as_tree`, `/export` and `/export_flat`; verify that `nodes_as_tree?dropempty=true` re-imports to an identical structure
- [x] 9.5 Implement `/nodes/{label}` and `/nodes?ids=&labels=`; verify rename and mixed-batch scenarios
- [x] 9.6 Implement `/search?q=` (exact, prefix, substring, `pg_trgm` fuzzy; labels and current aliases; `?method`, `?limit`) and `/search?aphia_id=`; verify the search scenarios

## 10. Acceptance on NES2022_tags

- [x] 10.1 End-to-end test: import `NES2022_tags`, publish a second revision (rename, move, deprecate with successor), then check `GET /trees`, node, ancestors, descendants, versions, revisions, changes, diff, export and search against expected JSON fixtures; verify the test passes in `docker compose`

## Workflow follow-up

- Archive this change once implemented, so its specs land in `openspec/specs/` before `worms-integration` and `webapp-and-write-api` are archived.
