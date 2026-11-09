# Design

## Context

Placement checks (`src/worms/checks.py`) run per node on a `TreeState`, with a
`records` dict of the WoRMS records they need; a missing record makes the check
"unavailable". `change_checks` attributes a warning to a change when a node in
the change's recheck scope has it afterwards and didn't before. Records,
including lineages, are cached in `WormsRecord` (JSON `record` with a `lineage`
list of `{AphiaID, ...}`, top level first). Quick add plans one `add` and runs
`validate`, turning the new node's warnings into issues.

## Goals / Non-Goals

**Goals:**
- A check that depends only on the node, its nearest anchored ancestor and the
  tree's AphiaIDs, so the existing "first anchored node below" scope still
  covers moves.
- Quick add adopts whole sets of direct children, decided by the server.

**Non-Goals:**
- Adoption in the tree editor's Add from WoRMS. The editor shows the warning;
  fixing it is an ordinary move.
- Fetching records to find would-be children. Only cached lineages are searched.

## Decisions

- **Only the part of the lineage below the nearest anchored ancestor.** A
  lineage AphiaID held by a node elsewhere, but above X's anchored ancestor P,
  is P's problem (P gets its own warning, or `out_of_lineage`), so X isn't
  warned twice up the chain. And if a node with such an AphiaID were an
  ancestor of X, it would be anchored and nearer than P, so "not an ancestor"
  needs no separate test. P's position in the lineage uses its `valid_AphiaID`
  when P is a synonym, as `out_of_lineage` does; with `out_of_lineage` the
  position is undefined, so the check is skipped.
- **One warning per AphiaID.** A node can be missing more than one ancestor (a
  genus beside both its family and its order). Separate warnings attribute
  cleanly to the change that added each node.
- **Synonym nodes match through cached records only.** The tree's AphiaID index
  gets an extra entry for each anchored node whose cached record is unaccepted,
  under its `valid_AphiaID`. Uncached records don't match, and a sync,
  which caches them, fills in what was missed.
  *Alternative:* fetch records for every anchored node. Rejected: a whole-tree
  fetch on every save.
- **Recheck scope through a lineage query.** For an AphiaID a change gives or
  removes, the scope adds the tree's anchored nodes whose newest cached record's
  lineage contains it (a JSON containment query, limited to the tree's
  AphiaIDs). Nodes without a cached record are left to syncs, the same as
  the check itself.
- **Quick add plans in two passes.** Pass one validates the `add` alone. The new
  `misplaced_lineage_ancestor` warnings it causes on existing nodes name the nodes
  to adopt: any such warning is new, so the `add` caused it. If
  `allow_cross_node_updates` is true, the direct children of the planned parent
  among them get a `move` (`from_parent` the parent, `to_parent` the placeholder
  `new:1`). Pass two validates the add with the moves, and its result gives the
  issues and errors. `moves` is part of the plan, so the plan hash covers it,
  and a confirm sees `plan_changed` if the set changed.
- **The issue lists only the direct children, the nodes the option would move.**
  Other nodes the new node warns (under an unanchored node, or elsewhere in the
  tree) aren't in the issue: Quick add won't change them, and they show up as
  tree warnings after publishing, to fix in the editor. Descendants of the
  adopted nodes never get the warning, since the new node is above their
  nearest anchored ancestor.

## Risks / Trade-offs

- [Syncs add the new warning to many nodes in existing trees at once] →
  Expected: it reports real inconsistencies. The warning history gets one new
  row per affected node.
- [The lineage query scans cached records] → Limited to the tree's AphiaIDs and
  only run for changes that give or remove an AphiaID; an index on the lineage
  JSON can follow if it shows up as slow.
- [A large adoption in one quick add (a class adopting dozens of genera)] → All
  moves are listed in the preview before confirming.
