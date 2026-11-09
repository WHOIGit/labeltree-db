# Tasks

## 1. The warning

- [x] 1.1 Add `misplaced_lineage_ancestor` to `worms/checks.py` (lineage below the nearest anchored ancestor, synonym ancestor via `valid_AphiaID`, skipped with `out_of_lineage`, one warning per AphiaID naming the node by label, synonym nodes matched through cached records); verify unit tests for the family beside its genus, an ancestor elsewhere, already under it, a synonym node, a node missing two ancestors, and no warning with `out_of_lineage`
- [x] 1.2 Extend the recheck scope with the tree's anchored nodes whose newest cached lineage contains an AphiaID the change gives or removes; verify tests that adding `Chaetocerotaceae` attributes the warning on `Chaetoceros` to the `add`, that removing it clears the warning, and the existing scope tests still pass
- [x] 1.3 Confirm drift runs and warning history pick up the new code; update `worms/tests/expected_taxonomy_warnings.json` for the warnings the imported taxonomy now gets, reviewing each new one; verify a drift test where the warning appears and a publish test where it clears after a move

## 2. Quick add

- [x] 2.1 Add `allow_cross_node_updates` and two-pass planning: find the nodes the new node would warn, plan moves for the direct children of the planned parent when allowed, `plan.moves`, the `misplaced_lineage_ancestor` issue naming only the direct children still to move, with its option; verify API tests for not allowed, allowed, non-direct nodes neither moved nor named, and toggling giving `body_changed`
- [x] 2.2 Publish the moves in the same changeset and return `moved`; verify API tests for confirming with moves and for a node to adopt added between preview and confirm (`plan_changed`)
- [x] 2.3 Document the warning in `design/worms.md`, and the field, `moves`, `moved` and the issue in `design/api.md`; update `design/diagrams/07-quick-add.mmd` if its plan shape no longer matches and re-render it; verify the docs' links resolve

## 3. Web app

- [x] 3.1 Quick add page: the "Allow updates to other nodes" toggle, the option turning it on, the planned moves in the preview and the moved nodes after publishing; verify browser tests for the option and for publishing with moves
- [x] 3.2 Tree editor: verify a browser test that validating a draft adding `Chaetocerotaceae` beside `Chaetoceros` lists `misplaced_lineage_ancestor`; describe the toggle in `design/webapp.md`

## 4. Integration

- [x] 4.1 Run the full test suite (including Playwright), `ruff check`, `ruff format --check` and `openspec validate misplaced-lineage-ancestor --strict`; verify all pass

## Workflow follow-up

- Archive `webapp-and-write-api`, then `quick-add`, before archiving this change: its deltas modify requirements those changes introduce.
