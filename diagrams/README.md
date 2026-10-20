# labeltree-db diagrams

Mermaid sources illustrating the decisions in [`../DESIGN.md`](../DESIGN.md).
The section references below point into that document.

## Rendering

The diagrams render in any Mermaid-aware viewer, such as VS Code with a Mermaid
extension or https://mermaid.live. To export them with the Mermaid CLI:

```bash
# on NixOS, use: "nix-shell -p mermaid-cli" to set environment
mmdc -i diagramX.mmd -o diagramX.png -s 4 -b white
# where -s is resolution, 3-4 is good for print
#       -b is background color
#       -w is page width in pixels
# Bulk command (04a-d live in 04-node-merge-and-split-options/):
for f in *.mmd 04-*/*.mmd; do mmdc -i "$f" -o "${f%.mmd}.png" -s 4 -b white; done
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

### 02 · Data model — `02-data-model.d2`
*ER diagram in [D2](https://d2lang.com/tour/sql-tables/), so edges connect
specific columns. DESIGN §2, §3, §4 "Change records".*

Render with the ELK layout. D2's own PNG export needs Playwright, which fails
to install on NixOS, so rasterise the SVG with headless Chromium (it honours
the fonts D2 embeds; `rsvg-convert` doesn't, and the text overlaps):

```bash
nix-shell -p d2 --run 'd2 --layout elk 02-data-model.d2 02-data-model.svg'
# width/height come from the SVG header
nix-shell -p chromium --run 'chromium --headless --no-sandbox --hide-scrollbars \
  --force-device-scale-factor=2 --window-size=3376,1276 \
  --screenshot=$PWD/02-data-model.png file://$PWD/02-data-model.svg'
```

- `NODE` is only an identity: a global id that is never reused.
- Versioned fields (label, description, `aphia_id`, parent) live in
  `NODE_VERSION`. Each node version records the tree revisions it is valid for
  (`valid_from_rev` / `valid_to_rev`).
- WoRMS warnings (`NODE_WARNINGS`) live outside `NODE_VERSION` and never bump
  the node version. Publishes and drift runs add a row only when a node's
  warnings change; the newest row per node is its current set.
- Aliases (`NODE_ALIAS`) are search aids only. They are **not versioned**; they
  are edited directly and record who added them and when.
- WoRMS records live in a service-side cache (`WORMS_RECORD`), not in node
  versions, so refreshing the cache never changes a node version.
- `CHANGESET` → ordered `CHANGE`s → one `TREE_REVISION` on publish. Every
  revision comes from a changeset, revision 1 included: a changeset with
  `base_rev = null` proposes the first revision of an empty tree, so imports
  and new trees go through the same review as any other edit.
- Node versions don't point to the changes that produced them. One version can
  come from several changes (two children added under one parent), and one
  change can bump several nodes (a move bumps the node and both parents). The
  link is derived instead: `valid_from_rev` → that revision's changeset → the
  changes that name the node.
- Labels are machine-safe and **unique within a tree at each revision**, but a
  label can be reused after a rename or deprecation. Only the node id is
  permanent.

### 03 · Changeset lifecycle — `03-changeset-lifecycle.mmd`
*Flowchart. DESIGN §4, §6*

A changeset has three states: `draft`, `published` and `discarded`. The
diamond is the publish check, not a state.

- Changes are composed in the browser and saved to the draft as a whole list
  with `base_rev`. Any drafter may update (replacing the list) or discard any
  draft.
- An approver publishes. Checks re-run against the latest revision, and the
  draft stays a draft if they find:
  - a **conflict**: a touched node changed or was deprecated since `base_rev`
  - a **structural error**: cycle, target or parent not in the tree, foreign
    parent, deprecate with children, or a non-machine-safe label
- WoRMS problems are warnings and never block.
- A user holding both drafter and approver may publish their own draft.
- Publishing is atomic and creates revision latest + 1. Published changesets
  can't be edited.
- Discarded changesets are kept with their changes frozen.

### 04a · Merge without replacement — `04-node-merge-and-split-options/04a-merge-without-replacement.mmd`
### 04b · Merge with replacement — `04-node-merge-and-split-options/04b-merge-with-replacement.mmd`
### 04c · Split without replacement — `04-node-merge-and-split-options/04c-split-without-replacement.mmd`
### 04d · Split with replacement — `04-node-merge-and-split-options/04d-split-with-replacement.mmd`
*Before → atomic changes → after. DESIGN §3 "Merge and split are macros"*

Merge and split are not operations of their own. They are UI presets that
expand into **ordered atomic changes** sharing a group id, and reviewers see
that expanded list. *With replacement* means the original node(s) are
deprecated with the new node(s) as successors. *Without replacement* means a
node keeps its id and its meaning broadens or narrows.

- **04a Merge without replacement:** move A's children to B, then deprecate A
  with `successors=[B]`. B keeps its id and broadens (yellow: version bumped,
  because its children changed).
- **04b Merge with replacement (default):** add C, move the children of A and B to C,
  then deprecate both with `successors=[C]`.
- **04c Split without replacement:** add a sibling A2 and move some children to
  it. A keeps its id and narrows. Use this only if ROIs already labelled A are
  still correct.
- **04d Split with replacement (default):** add A1 and A2, move every child,
  then deprecate A with `successors=[A1, A2]`. Old ROIs still point to A and can
  follow the successor pointers.

After publishing a merge, the UI copies the deprecated nodes' labels and aliases
into the surviving or new node's aliases.

Replacement is the default for both. Comparing 04a with 04b, and 04c with 04d,
shows why: without replacement, a surviving node's meaning changes under the
same id. In a merge where A has no children, B's version doesn't even bump.

### 05 · Consumer lookups — `05-consumer-lookups.mmd`
*Sequence diagram. DESIGN §2 "Labels and aliases", §3 "What consumers store", §7*

How roi-db stores labels and answers label queries while the tree changes
underneath it. Every call carries a `reader` token (not shown).

**Setup.**

- **Rev R1:** tree T has K › L › A, B, where node L has the label `L1`.
  roi-db holds 100 rois each for A and B. Roi-X is labelled `L1`: roi-db looks
  the label up and stores `(T, id(L), R1)`.
- **Rev R2:** `L1` was a typo. A published edit renames node L to `L2`, and
  `L1` is kept as an alias. The node id doesn't change, so roi-X is unaffected:
  - `GET /trees/T/nodes/L1` returns `404`; `GET /trees/T/nodes/L2` returns
    `id(L)`.
  - `GET /trees/T/nodes/L1?rev=R1` still returns `id(L)`.
  - `GET /trees/T/search?q=L1` finds node L through the alias.
  - `GET /nodes/id(L)` always works.
- **Rev R3, months later:** L has moved under J and gained children C, D and E,
  with 10 rois each. Roi-Y is labelled `L2` and stored as `(T, id(L), R3)`. No
  rois are labelled K or J themselves.

roi-db stores node ids, never labels, plus when each annotation was saved. To
answer a query by label it looks the label up (`/trees/T/nodes/{label}`), and
for descendants it fetches the subtree (`/nodes/{id}/descendants`).

**Scenarios.**

1. **Rois with label `L2`:** roi-X and roi-Y. Both carry `id(L)`, so neither
   the rename nor the revision each was stored at matters.
2. **Descendants of K, at R3:** none. L is no longer under K, so neither L nor
   anything below it is included, even though roi-X was labelled while L was
   under K.
3. **Descendants of J, at R3:** 232 rois: roi-X and roi-Y for L, 100 each for A
   and B, and 10 each for C, D and E.
4. **Descendants of K as of time t, between R2 and R3:** roi-db answers as if
   the request had been made at t:
   1. `GET /trees/T/revisions` lists revisions with `published_at`. The
      newest one published at or before t is R2.
   2. `GET /trees/T/nodes/K?rev=R2`, then `GET /nodes/id(K)/descendants?rev=R2`,
      gives L, A and B.
   3. roi-db selects rois with those node ids that were **saved at or before
      t**. The stored revision alone isn't enough, because a roi saved after t
      but before R3 would also carry R2.

   The result is 201 rois: roi-X, and 100 each for A and B.

Hierarchy queries follow the tree at the revision they're asked about, which
is the latest one unless `?rev=` is given. Responses pinned with `?rev=` are
immutable and can be cached indefinitely.

**Deprecation (not shown).** When the tree revision moves on, one
`diff?from=&to=` call lists every node deprecated in between, with its
successors, and one batch `nodes?ids=` call fetches those successors. A
successor may be deprecated too, in which case it comes back as a deprecation
record; follow its successors with another batch call. What to do next is
roi-db's decision.

### 06 · WoRMS drift report — `06-worms-drift-report.mmd`
*Sequence diagram. DESIGN §5, §10*

Run by a drafter, approver or admin, or on a schedule. `POST
/trees/{tree}/drift` starts the run and returns `202 Accepted`, because
fetching every AphiaID from WoRMS takes minutes:

1. Collect every AphiaID used in the latest revision.
2. Re-fetch each record and its lineage from WoRMS. This covers reclassifications
   higher up that `AphiaRecordsByDate` would miss, because only the moved
   taxon's record changes.
3. Re-run the placement checks for the whole tree, and add a `NODE_WARNINGS` row
   for each node whose warnings changed (an empty list when they cleared).
   Earlier rows are kept as history (`GET /nodes/{id}/warning_history`); by
   default only the newest is shown. Runs themselves aren't recorded.
4. `GET /trees/{tree}/drift` reports the nodes that currently have WoRMS
   warnings.

Drift reports never propose or make changes to the tree, and never modify
published node versions. Any fix is made by a drafter in an ordinary draft.
