# Proposal

## Why

Placement checks miss a common inconsistency: a taxon that sits beside its own
ancestor taxon. If a tree has `Bacillariophyceae → Chaetoceros` and someone adds
`Chaetocerotaceae` under the class, both nodes are in lineage, so neither gets a
warning, yet the family and its genus end up as siblings. Quick add makes such
additions quick, so it should spot them and offer to fix them in the same
publish.

## What Changes

- New WoRMS warning `misplaced_lineage_ancestor`, on the node that's in the wrong
  place: the node's WoRMS lineage, below its nearest anchored ancestor, holds an
  AphiaID another node of the tree has, so the node could sit under that node.
  It's a warning like the others: shown in the tree editor's validation, stored
  in warning history, filled in by syncs, never blocking.
- The recheck scope of an edit grows to include nodes whose cached WoRMS lineage
  holds an AphiaID the change gives or removes, so adding the ancestor warns its
  would-be children.
- Quick add reports the nodes the new node should adopt as a
  `misplaced_lineage_ancestor` issue. A new request field,
  `allow_cross_node_updates` (default `false`), is the issue's option: when
  `true`, the plan also moves **all** such nodes that are direct children of the
  planned parent under the new node, in the same changeset. The client can't
  choose which ones.
- The Quick add page has an "Allow updates to other nodes" toggle bound to that
  field, and shows the planned moves.

## Capabilities

### New Capabilities

None.

### Modified Capabilities
- `worms-placement-checks`: adds the `misplaced_lineage_ancestor` warning;
  "Recheck scope of an edit" includes nodes whose lineage holds a changed
  AphiaID.
- `quick-add`: request gains `allow_cross_node_updates`; issues include
  `misplaced_lineage_ancestor`; a plan and a published quick add can hold moves.
  (Introduced by `quick-add`, not yet archived.)
- `webapp`: the Quick add page's toggle and planned moves. (Introduced by
  `quick-add`, not yet archived.)

## Impact

- `src/worms/checks.py` (new check, recheck scope, `WARNINGS`), a lineage
  lookup over cached records in `src/worms/records.py`.
- `src/api/quick_add.py`, `src/static/app/quick_add.js`, `quick_add.html`.
- Syncs will add the warning to existing trees' nodes on their next run.
- Docs: `design/worms.md` (warning table), `design/api.md` (Quick add),
  `design/webapp.md`, `design/diagrams/07-quick-add.mmd` if the plan shape shown
  changes.
- Archive order: `webapp-and-write-api`, then `quick-add`, then this change.
  Independent of `worms-label-and-links`.
