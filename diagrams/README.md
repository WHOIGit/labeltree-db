# labeltree-db diagrams

Mermaid sources illustrating the decisions in [`../DESIGN.md`](../DESIGN.md).
The section references below point into that document.

## Rendering

The diagrams render in any Mermaid-aware viewer, such as VS Code with a Mermaid
extension or https://mermaid.live. To export them with the Mermaid CLI:

```bash
# on NixOS, use: "nix-shell -p mermaid-cli" to set environment
mmdc -c mermaid-config.json -i diagramX.mmd -o diagramX.png -s 4 -b white
# where -s is resolution, 3-4 is good for print
#       -b is background color
#       -w is page width in pixels
#       -c mermaid-config.json turns off HTML labels, so text shows in SVG output
# Bulk command (05a-c live in 05-node-merge-and-split-options/):
for f in *.mmd 05-*/*.mmd; do mmdc -c mermaid-config.json -i "$f" -o "${f%.mmd}.png" -s 4 -b white; done
```

Colour key used throughout: **green** = new node, **yellow** = node version
increased or warning raised, **grey dashed** = deprecated node, **blue** =
event or change description.

---

### 01 · System context — `01-system-context.mmd`
*Flowchart. DESIGN §6, §7*

Shows who talks to labeltree-db:

- People reach the management web app with one of four roles: reader, drafter,
  approver, admin. Every request is authenticated, reads included.
- Consumers (roi-db, datasetman, annotation tools, crawlers) **pull** from the
  REST API with a `reader` token. Nothing is pushed to them.
- The only outbound dependency is **live WoRMS lookups** while editing,
  publishing and running drift reports. Reads never contact WoRMS.

### 02 · Data model — `02-data-model.mmd`
*ER diagram. DESIGN §2, §3*

- `NODE` is only an identity: a global id that is never reused.
- Versioned fields (label, description, `aphia_id`, parent) live in
  `NODE_VERSION`. Each node version records the tree revisions it is valid for
  (`valid_from_rev` / `valid_to_rev`).
- WoRMS warning flags (`NODE_FLAGS`) hold **current values only**, outside
  `NODE_VERSION`. They're overwritten on publish and by drift reports, and never
  bump the node version.
- Aliases (`NODE_ALIAS`) are search aids only. They are **not versioned**; they
  are edited directly and record who added them and when.
- WoRMS records live in a service-side cache (`WORMS_RECORD`), not in node
  versions, so refreshing the cache never changes a node version.
- `CHANGESET` → ordered `CHANGE`s → one `TREE_REVISION` on publish. The seed
  import creates revision 1 without a changeset, so those links are nullable.
- Labels are machine-safe but **not unique**. Only the node id is unique.

### 03 · Node versions vs tree revisions — `03-node-versions-vs-tree-revisions.mmd`
*Flowchart, one row per revision. DESIGN §3*

A worked example of the two versioning levels. Each row is a tree revision,
which is a slice across every node's current version.

- **rev 2:** adding a child increases the parent's version (`Chaetoceros v2`).
- **rev 3:** renaming a child does **not** increase the parent's version. The
  renamed node gets v2.
- **rev 4:** editing `Chaetoceros`'s description bumps only that node (v3).
  The other nodes keep their versions.

### 04 · Changeset lifecycle — `04-changeset-lifecycle.mmd`
*State diagram. DESIGN §4, §6*

A changeset is a `draft` until an approver publishes it or a drafter discards
it. Any drafter may update or discard any draft. Changes are composed in the
browser and saved to the draft as a whole list:

- Updating a draft replaces its changes.
- Conflict is not a state. It's a publish check: if a touched node has changed
  or been deprecated since `base_rev`, the draft stays a draft, and a drafter
  updates it against the latest revision.
- Checks re-run on publish. A user holding both drafter and approver may
  publish their own draft.
- A published changeset can no longer be edited.
- Publishing is atomic and creates exactly one new tree revision.
- **Only structural errors block publishing.** WoRMS problems are warnings.

### 05a · Merge macro — `05-node-merge-and-split-options/05a-merge-macro.mmd`
### 05b · Narrowing split — `05-node-merge-and-split-options/05b-narrowing-split-macro.mmd`
### 05c · Replacing split — `05-node-merge-and-split-options/05c-replacing-split-macro.mmd`
*Before → atomic changes → after. DESIGN §3 "Atomic operations", "Merge and split are UI macros"*

Merge and split are not operations of their own. They are UI presets that
expand into **ordered atomic changes** sharing a group id, and reviewers see
that expanded list.

- **Merge A into B:** move A's children to B, then deprecate A with
  `successors=[B]`. After publishing, the UI copies A's label and aliases into
  B's aliases.
- **Narrowing split:** add a sibling and move some children. A keeps its id
  *and* its meaning. Use this only if ROIs already labelled A are still correct.
- **Replacing split (default):** add A1 and A2, move every child, then deprecate
  A with `successors=[A1, A2]`. Old ROIs still point to A and can follow the
  successor pointers.

Comparing 05b and 05c shows why the replacing form is the default.

### 06 · WoRMS placement checks — `06-worms-placement-checks.mmd`
*Flowchart. DESIGN §5*

The checks run against live WoRMS. For every node that was added, moved,
deprecated or had its `aphia_id` changed, they recheck that node, its nearest
anchored descendants (down the lineage) and nodes with the same AphiaID:

| Flag | Raised when |
|---|---|
| `unaccepted_aphia` | WoRMS marks the AphiaID unaccepted |
| `out_of_lineage` | The nearest anchored ancestor isn't in the node's WoRMS lineage |
| `duplicate_aphia` | Another node in the tree has the same AphiaID |

Nodes without an AphiaID are skipped when walking up or down. If the nearest
anchored ancestor's AphiaID is unaccepted, its `valid_AphiaID` is compared
instead. Every outcome is a **warning**. Warnings are stored on the change and,
on publish, overwrite the node's current flags in `NODE_FLAGS` (no history).
Flag changes never bump node versions. If WoRMS can't be reached, the change
records "checks unavailable" and publishing is still allowed.

### 07 · Node lifecycle — `07-node-lifecycle.mmd`
*State diagram. DESIGN §3*

A node is in the tree from creation until it is deprecated, which is only
possible once it has no children. Editing the label, description or `aphia_id`,
moving the node, or a change to its set of children creates a new node version.
Aliases and WoRMS flags aren't versioned at all.

Deprecating at revision r closes the node's last version, with no new version,
and records `deprecated_in_rev = r` and successors on the node. The node still
appears at revisions before r and is absent from r onwards. A lookup by id
always works and returns the deprecation record.

### 08 · Consumer lookups — `08-consumer-lookups.mmd`
*Sequence diagram. DESIGN §3 "What consumers store", §7*

How roi-db is expected to use the service:

1. Search during annotation, then store `(tree, node_id, rev)`.
2. Later, poll the tree revision, find the node deprecated, and fetch its
   successors by id. Successors may be deprecated too, so follow the chain.
   What to do next is roi-db's decision.
3. Reproduce history with `?rev=`. Those responses are immutable and can be
   cached indefinitely.

### 09 · WoRMS drift report — `09-worms-drift-report.mmd`
*Sequence diagram. DESIGN §5, §10*

Run by a drafter, approver or admin, or on a schedule:

1. Collect every AphiaID used in the latest revision.
2. Re-fetch each record and its lineage from WoRMS. This covers reclassifications
   higher up that `AphiaRecordsByDate` would miss, because only the moved
   taxon's record changes.
3. Re-run the placement checks for the whole tree and overwrite `NODE_FLAGS`.
   No drift history is kept.
4. Report the nodes that currently have WoRMS warnings
   (`GET /trees/{tree}/drift`).

Drift reports never propose or make changes to the tree, and never modify
published node versions. Any fix is made by a drafter in an ordinary draft.

### 10 · Owned tree vs WoRMS portal — `10-owned-vs-portal.mmd`
*Flowchart, side by side. DESIGN §1*

The core architectural decision.

- **Portal (rejected):** reclassifications in WoRMS silently change the meaning
  of existing labels.
- **Owned tree (chosen):** stable node ids and versioned history. WoRMS is
  consulted for checks and drift reports, which inform drafters. Its changes
  enter the tree only through reviewed drafts.
