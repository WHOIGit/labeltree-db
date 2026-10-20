# labeltree-db — Design (draft)

Source-of-truth service for AMPLIfy label hierarchies. Other services
(amplify-datasetman, roi-db, annotation tools) reference labels by
`(tree, node_id)`, optionally pinned to a node version or tree revision. They use
this API to resolve labels, aliases, parents, children and WoRMS AphiaIDs.

Proposed stack, matching amplify-mediastore: Django + django-ninja (API),
PostgreSQL, Docker Compose. The tree-management web app lives in the same Django
project.

Consumers **pull**. The service pushes no notifications or events.

## 1. Core decision: owned tree, anchored to WoRMS

We own every node in the tree. A node may carry a WoRMS AphiaID, and its
placement is *checked* against WoRMS rather than *derived* from it. WoRMS is
used in two further ways:

- *Import from WoRMS*: create a node or subtree from an AphiaID, pulling in
  name and lineage.
- *Drift reports*: compare our anchored nodes with current WoRMS hierarchy to
  identify drift.

This approach seemed better than the alternative of a WoRMS portal with an
intermediary overlay, for these reasons:

- **Stable ROI labels.** Node ids are ours and never change meaning. Changes in
  WoRMS (reclassifications, new synonyms) reach the tree only as reviewed edits,
  so existing annotations never shift silently.
- **Curated label sets.** Annotators need tens to hundreds of usable classes,
  not WoRMS's ~500k taxa. Our tree *is* that curated set.
- **Non-biological and informal labels.** Detritus, bubbles, "flagellate",
  morphotypes and "X_or_Y" mixes are ordinary nodes, not exceptions to WoRMS.
- **Multiple trees (flexibility).** The same machinery serves taxonomy, parasites,
  morphology and lab-specific trees (incl. flat trees, i.e. unsorted elements).
- **No runtime dependency.** Reads never touch marinespecies.org. WoRMS is
  needed only while editing, publishing and running drift reports.
- **Simpler versioning.** We version our own data. WoRMS has no releases, so
  a portal would have to snapshot WoRMS and the overlay together.

The cost is maintaining the tree ourselves. Import from WoRMS, placement checks
and drift reports keep that cost low.

## 2. Trees and nodes

### Multiple trees

- Trees are **disjoint**. Each has its own nodes and revisions. Two
  examples are the seed trees `NES2022_taxonomy` and `NES2022_tags` (§9). API
  examples in §7 use a hypothetical, more mature tree called `taxonomy`.
- A ROI may be labelled in several trees at once, e.g. a taxon plus an external
  parasite. Combining those labels is up to downstream apps to handle.
- Node ids are **globally unique across trees**, so a node id alone is enough to
  resolve a node. Nodes in different trees may share an AphiaID.
- **The tree is the implicit root.** Nodes with `parent = null` are its
  top-level nodes, and a tree may have any number of them. Adding, moving or
  deprecating a top-level node changes the tree's top-level set. That is captured by
  the tree revision; there is no root node to version.

### Labels and aliases

- **Labels are unique within a tree at each revision.** No two nodes in the
  tree at the same revision share a label, so `morphotype1` under two genera
  must be e.g. `Chaetoceros_morphotype1` and `Thalassiosira_morphotype1`. The
  comparison is case-sensitive: `Chaetoceros` and `chaetoceros` are different
  labels. Different trees may share labels.
- **Labels can be reused over time.** A label freed by a rename or a
  deprecation may later be given to another node, so which node a label names
  depends on the revision. Only the node id identifies a node permanently.
- **Labels must be machine-safe:** `^[A-Za-z0-9][A-Za-z0-9_.-]*$`, so no spaces
  or slashes.
- **Aliases are a plain list of free-text strings**, such as
  `Chaetoceros didymus`, misspellings, common names and legacy strings. They
  have no type or category and don't need to be unique.
- **Aliases are search aids only and are not versioned.** Users with the
  `drafter` role add or remove them directly, outside changesets and review.
  The one exception is a new node's initial aliases, which can come with its
  `add` change, e.g. from an import (§9). Each alias records who added it and when. Aliases don't bump node versions or
  create tree revisions, and the API always returns the current aliases, even
  for `?rev=` requests.
- Nodes can be looked up by label at a given revision, and `search` matches
  labels, current aliases and cached WoRMS names (§7). Because labels can be
  reused, consumers should store node ids, not labels or aliases.

### Fixed node fields

| Field | Notes |
|---|---|
| `label` | machine-safe string |
| `parent` | node id, or null for a top-level node |
| `description` | free text: definition and annotation guidance |
| `aliases[]` | list of free-text strings; unversioned, edited directly |
| `aphia_id` | nullable WoRMS AphiaID |
| `created_in_rev` | the revision in which the node was added. Not versioned. |
| `deprecated_in_rev` | null, or the revision from which the node is no longer in the tree (§3). Not versioned. |
| `successors[]` | set only on deprecated nodes, may be empty (§3). Not versioned. |

The API also returns derived, read-only values:
- `worms_data`: WoRMS name, rank, status and link from the cached record (§10);
  `null` when `aphia_id` is null
- `worms_warnings`: the node's **current** WoRMS placement warnings (§5), whatever
  revision is requested; empty list if none
- `children`: nodes whose `parent` is this node at the requested revision. Not
  stored (§3, "Children")
- `num_children`: number of children at the requested revision
- `tree_depth`: number of ancestors; top-level nodes have depth 0

### Combined (legacy) labels

Legacy combined labels, such as `Chaetoceros_didymus_TAG_external_flagellate`,
are ordinary nodes **placed under their base taxon**, with no `aphia_id`. The
parent is the only link to the taxon. They are a stopgap until consumers label
ROIs in several trees at once (taxon tree + parasite tree), and they can be
deprecated later like any other node.

## 3. Versioning

There are two levels of versioning.

- **Node version** (`node_id@v`): an integer per node, starting at 1. It
  increases when the node's versioned fields or immediate structure change
  (below).
- **Tree revision** (`tree@r`): an integer per tree. It increases once for each
  published changeset and identifies the state of every node at that point.

### What changes a node's version

A node's version increases if any of these changed:

- label, description or `aphia_id`
- **parent** (the node was moved)
- **set of immediate children**: a child was added, deprecated, or moved in or
  out

These do **not** change a node's version:

- **Aliases.** They aren't versioned at all (§2).
- **WoRMS warnings.** They are derived results, not edits, and are stored
  separately (§5).
- **A child's own edits**, such as a rename.
- **Changes to ancestors.** If a grandparent moves, the node's path to the root
  changes but its version doesn't. A node version describes the node and its
  immediate structure; the full path is captured only by the tree revision.

Changes don't cascade beyond immediate parent and children.

A node's version increases **at most once per tree revision**, however many
changes in the changeset touch it.

#### Example

Four nodes over five revisions. `Chaetoceros` and `Thalassiosira` are genera;
`C_didymus` starts under `Chaetoceros`. Each row is a node, each column a tree
revision, and each cell the node's version at that revision. **Bold** marks a
version increase.

| node | rev 1<br>seed | rev 2<br>add `C_socialis` under `Chaetoceros` | rev 3<br>rename `C_didymus` → `C_didymus_sl` | rev 4<br>move `C_socialis` → `Thalassiosira` | rev 5<br>deprecate `C_didymus_sl`, edit `Chaetoceros` description |
|---|---|---|---|---|---|
| `Chaetoceros` | v1 | **v2** child added | v2 child renamed: no bump | **v3** child moved out | **v4** child deprecated + edit: one bump |
| `C_didymus` | v1 | v1 | **v2** renamed | v2 | deprecated: v2 closed, no v3 |
| `C_socialis` | – | **v1** new | v1 | **v2** moved | v2 |
| `Thalassiosira` | v1 | v1 | v1 | **v2** child moved in | v2 |

An alias added between rev 4 and rev 5 appears nowhere: it creates no version
and no revision.

Each run of equal versions in a row is one `NODE_VERSION` row. For
`Chaetoceros`: v1 `[1, 2)`, v2 `[2, 4)`, v3 `[4, 5)`, v4 `[5, null)`. For
`C_didymus`, v2 is `[3, 5)` and is never followed by a v3, and the node records
`deprecated_in_rev = 5`.

### Storage model

![Data model](diagrams/02-data-model.png)

Source: [`diagrams/02-data-model.d2`](diagrams/02-data-model.d2)

The tree at revision `r` is every `NODE_VERSION` with
`valid_from_rev <= r < valid_to_rev`, where a null `valid_to_rev` counts as
infinity. `NODE_ALIAS` and `NODE_WARNINGS` are **not versioned**: they live
outside `NODE_VERSION` and never bump it (§2, §5). `NODE_ALIAS` holds current
values only. `NODE_WARNINGS` keeps a row each time a node's warnings change, and
the newest row is the current set.

Full-tree exports per revision can be cached indefinitely, because published
revisions never change. Aliases and warnings are the exception (see caching, §7).

Node versions don't store which changes produced them, because the mapping is
many-to-many: one version can come from several changes (two children added
under the same parent), and one change can bump several nodes (a `move` bumps
the node, its old parent and its new parent). Instead it's derived. A node
changes at most once per revision, so a version's `valid_from_rev` identifies
the changeset, and its changes are those whose `node`, `parent`, `from_parent`
or `to_parent` is the node. The same goes for the change that created a node,
via `created_in_rev`. If this lookup ever gets slow, a `CHANGE_EFFECT(change, node, from_version,
to_version)` table filled at publish would serve it, along with the
`version_changes` list in the API.

#### Children

Children are not stored. They are found from the children's `parent` pointers
at that revision, and the parent's version still increases when its set of
children changes. With an index on `(parent, valid_from_rev)`, it's a single
fast lookup. Ancestors and descendants use a recursive query on the same columns
(`WITH RECURSIVE`), filtered to revision r.

```sql
SELECT * FROM node_version
WHERE parent = X
  AND valid_from_rev <= r
  AND (valid_to_rev IS NULL OR valid_to_rev > r)
```

#### Why not mptt or treebeard for tree management?

Both libraries assume each node has exactly one position at any time. They keep
extra bookkeeping columns per node (lft/rght numbers in mptt, a materialised path
in treebeard) and rewrite them on every move.

Here, a node's parent depends on which revision you ask about, because the
parent lives on `NODE_VERSION`, which is valid for a range of revisions. A single
set of bookkeeping columns can't describe every revision at once. You'd have to
recompute them for each revision, or keep a separate copy per revision, which
works against how those libraries are designed.

At this scale (thousands of nodes, hundreds of revisions), the plain
parent-pointer approach should be fast. If deep descendant queries ever get
slow, a published revision never changes, so you could compute an
ancestor/descendant table for it once at publish time and never update it.
That's an optimisation to add only if needed.

### Atomic operations

Every tracked edit is one of four atomic operations. Changes in a changeset are
an ordered sequence of operations. Each change's preconditions are checked against the state
left by the changes before it.

| Op | Effect | Preconditions |
|---|---|---|
| `add` | Create a node with a new id, under a parent or at top level. | parent in the tree, same tree, label not used in the tree |
| `edit` | Change label, description or `aphia_id` (set or clear). | node in the tree; a new label not used in the tree |
| `move` | Change parent (or make the node top-level). | new parent in the tree, same tree, no cycle |
| `deprecate` | Remove the node from the tree from this revision on, with optional `successors[]`. | node has **no children** |

Nothing is ever deleted. "Delete" means deprecate. **A deprecated node is one
that is no longer part of the tree.** Publishing a `deprecate` closes the node's
last version (`valid_to_rev = r`) and sets `deprecated_in_rev = r` and
`successors` on the node itself. No new version is created.

- **At revisions before r** the node appears normally, because it was part of
  the tree then. No `?include_deprecated` switch is needed.
- **At revision r and later** it is absent from children, descendants, label
  lookups, search and exports, and its label is free for another node.
- **A lookup by id always works.** If the node isn't in the requested revision
  because it was deprecated, the API returns its deprecation record (§7).

**Successors** are informational pointers ("ROIs labelled with this node probably
belong to one of these now"). They are the only record that a merge or split
happened. Old ROIs keep pointing to the deprecated id. How to display or migrate
them is up to downstream apps.

- Successors are optional. The macros that deprecate a node (merges, and
  split with replacement) always set them. A node that is simply removed has
  none.
- Successors may themselves be deprecated later, so a consumer may have to
  follow a chain (A → B → C). That's acceptable.

### Merge and split are macros

The UI offers presets that expand into ordered atomic changes sharing a `group`
id. Reviewers see the expanded list and every node it touches.

There are four presets. **With replacement** means the original node(s) are
deprecated, with the new node(s) as successors. **Without replacement** means a
node keeps its id while its meaning broadens (merge) or narrows (split).

**Merge without replacement**: A into B. B keeps its id and broadens.

```
1..n  move     each child of A → B
n+1   deprecate A  successors=[B]
```

![Merge without replacement](diagrams/04-node-merge-and-split-options/04a-merge-without-replacement.png)

Old ROIs labelled B stay correct, because B only got broader. But if A had no
children, B's set of children doesn't change, so B's version doesn't increase
and nothing records that B's meaning changed. Use this only when that's
acceptable to consumers, e.g. when A was a misspelt duplicate of B. Otherwise
use merge with replacement, so B's change of meaning is explicit.

**Merge with replacement** (the default merge preset): A and B are both
deprecated, and a new C replaces them.

```
1     add      C (sibling of A and B)
2..n  move     each child of A and B → C
n+1   deprecate A  successors=[C]
n+2   deprecate B  successors=[C]
```

![Merge with replacement](diagrams/04-node-merge-and-split-options/04b-merge-with-replacement.png)

**Split without replacement**: A keeps its id and narrows, and a new sibling
takes some children.

```
1     add      A2 (sibling of A)
2..n  move     selected children of A → A2
```

![Split without replacement](diagrams/04-node-merge-and-split-options/04c-split-without-replacement.png)

Use this only when old ROIs labelled A are still correct as A.

**Split with replacement** (the default split preset): A is deprecated, and two
new nodes replace it.

```
1     add      A1 (sibling of A)
2     add      A2 (sibling of A)
3..n  move     each child of A → A1 or A2   (UI requires every child to be assigned)
n+1   deprecate A  successors=[A1, A2]
```

![Split with replacement](diagrams/04-node-merge-and-split-options/04d-split-with-replacement.png)

Use the replacement form whenever existing ROIs labelled A might belong to
either new node. Otherwise those ROIs would silently keep a label whose meaning
has narrowed.

Aliases aren't part of changesets, so after publishing a merge the UI copies
each deprecated node's label and aliases into the surviving or new node's alias
list.

### What consumers store

The recommendation is that a ROI annotation stores `(node_id, tree_rev)`. The
node version follows from those two values, and the revision also captures the
hierarchy context at that moment. Storing `(node_id, node_version)` is supported
too.

## 4. Changesets and concurrency

A changeset has three states: `draft`, `published` and `discarded`.

A changeset is a proposed tree revision, written as an ordered list of changes
against `base_rev`. Publishing it creates the next revision (latest + 1, which
may be later than `base_rev + 1`). A discarded changeset never becomes a
revision. A changeset with `base_rev: null` proposes the first revision of an
empty tree (§9).

- **Composing happens in the browser.** The user builds an ordered list of
  atomic changes locally, including merge and split presets. The browser calls
  `validate` (§7) as the list changes, so check results appear as the user works.
- **Saving a draft** sends the whole list to the server. Creating a draft creates
  a new changeset that records its `base_rev`. Updating a draft replaces the
  changeset's changes, notes and `base_rev`. Drafts can be updated any number of
  times and are visible to the tree's drafters, approvers and admins, who
  review them there. Any drafter may update or discard any draft, not only
  their own.
- **Publishing** is done by an approver, on a draft. All checks run again
  against the latest revision `r`, which may be later than `base_rev`. If they
  pass, publishing atomically creates `TREE_REVISION r+1`, closes the old node
  versions (`valid_to_rev = r+1`), opens the new ones, and records new
  `NODE_WARNINGS` for touched nodes whose warnings changed. A published changeset
  can no longer be edited.
- **Discarding** a draft sets its state to `discarded`. It is kept for the
  record with its changes frozen, and can't be edited or published.
- **Conflict rule:** if any node touched by the changeset has a newer version
  than at `base_rev`, or has been deprecated since, publishing is blocked. The
  drafter fetches the latest revision, adjusts the changes in the browser, and
  updates the draft with the new `base_rev`. Touched nodes include parents
  whose children change, so two drafts adding different children under the
  same parent will conflict. That's accepted. A draft with `base_rev: null`
  conflicts as soon as the tree has any revision, so if two first-revision
  drafts exist, the second must be rebased onto revision 1.

Publishing is blocked by a **conflict** (above) or by a **structural error**:
- a cycle
- a target node that is not in the tree (deprecated)
- a parent that is not in the tree (deprecated) or is in a different tree
- deprecating (deleting) a node that still has children (must decide what happens to the children)
- a label that isn't machine-safe
- a label already used by another node in the tree. Because each change is
  checked against the state left by the changes before it, swapping two labels
  needs a temporary label in between. If two drafts add the same label,
  whichever is published second is blocked.

**WoRMS problems are warnings, never errors** (see §5).

### Change records

Each `CHANGE` row is one atomic operation: its `op`, its position `seq` in the
changeset, an optional `group` naming the macro that produced it (e.g.
`split#3`), its arguments in `payload`, and its WoRMS results in `checks`.

`payload` holds the op's arguments:

| Op | Payload |
|---|---|
| `add` | `node` (placeholder, see below), `label`, `parent`, optional `description`, `aphia_id` and initial `aliases` (§9) |
| `edit` | `node`, and only the fields being changed: `label`, `description`, `aphia_id` (null clears it) |
| `move` | `node`, `from_parent`, `to_parent` (null = top-level) |
| `deprecate` | `node`, `successors[]` (may be empty) |

`from_parent` is recorded so the change list reads on its own, without
reconstructing the base revision. The §7 changes listing shows these fields
inline.

A node added in a draft has no id yet. Within the draft it is referred to by a
placeholder such as `new:1`, which later changes may use as a `parent`,
`to_parent` or successor. Publishing assigns real node ids and rewrites the
placeholders, so published changes contain only real ids, and discarded drafts
never use up ids.

`checks` holds the WoRMS warnings (§5) the change would cause, as a list of
`{warning, node, detail}`, or `unavailable` if WoRMS couldn't be reached. It is
refreshed on every save and again on publish, and reviewers see it on the
draft. On publish, the final results are written to `NODE_WARNINGS`. Conflicts and
structural errors aren't stored: `validate` and publish report them each time
they run.

## 5. WoRMS placement checks (warnings)

When a node has an AphiaID, the service compares where we put it with where
WoRMS puts it. Any disagreement becomes a **warning**: our tree
is allowed to differ from WoRMS, but the difference should be visible.

### The warnings

A node is *anchored* if it has an `aphia_id`. Checks walk past nodes without
one, such as `morphotype1` or `artifact`, as if they weren't there.

| Warning | Meaning | Example |
|---|---|---|
| `out_of_lineage` | The node's nearest anchored ancestor isn't one of its WoRMS ancestors. | *Chaetoceros* placed under *Dinophyceae*. Also catches rank inversions, e.g. a genus under a species. |
| `unaccepted_aphia` | WoRMS marks this AphiaID as unaccepted (e.g. now a synonym). The accepted AphiaID is suggested. | A species renamed in WoRMS since it was added. |
| `duplicate_aphia` | Another node in the same tree has the same AphiaID. | The same species added twice under different labels. |

"WoRMS ancestors" means the node's lineage from WoRMS
(`AphiaClassificationByAphiaID`). WoRMS lineages contain accepted names only, so
if the nearest anchored ancestor has an unaccepted AphiaID, its `valid_AphiaID`
is compared instead. Otherwise every descendant of a synonym would get an
`out_of_lineage` warning. A node with no anchored ancestor gets no `out_of_lineage`
check.

### When checks run

Checks run as part of tree editing: on `validate`, when saving a draft, and
again on publish. A drift report (§10) reruns them for the whole tree, on
demand or on a schedule.

Moving or re-anchoring one node can change warnings on nearby nodes, so an
edit rechecks all of these:

- the node itself
- **looking down:** the first anchored node on each path below it, since its
  nearest anchored ancestor may have changed. Nodes further down still have the
  same nearest anchored ancestor, so they don't need rechecking.
- any other node in the tree with the same AphiaID

Ancestors don't need rechecking.

The draft preview lists "warnings that will change" separately from "nodes whose
version will increase", because the two don't always overlap: warnings
aren't versioned, and reflect the most recently fetched WoRMS data.

If WoRMS can't be reached, the affected changes record "checks unavailable" and
publishing is still allowed. The next drift report fills the warnings in.

### How warnings are stored and shown

- `NODE_WARNINGS` keeps each node's warnings over time. Publishing and drift
  reports add a row only when a node's warnings differ from its newest row,
  including a row with an empty list when its warnings clear. The newest row
  is the node's **current** set, which is all the API shows by default.
- Each row records when it was computed (`computed_at`).
- Warnings never bump node versions (§3) and never block publishing (§4).
- The API returns them on every detailed node as `worms_warnings`, a list that is
  empty when there are no warnings:

  ```
  worms_warnings: [
    {warning: "out_of_lineage",
     detail: "Nearest anchored ancestor Dinophyceae is not in the WoRMS lineage of Chaetoceros."}
  ]
  ```
- Drift reports only refresh warnings and report on them. They never propose or
  make changes to the tree, and never edit published node versions. Any fix is
  made by a drafter in an ordinary draft.

## 6. Users and permissions

Roles are assigned per tree and can be combined:

| Role | Can |
|---|---|
| `reader` | Read published revisions. Most downstream apps have this permission. |
| `drafter` | Create, update and discard any draft, and run checks and drift reports. Add and remove aliases. |
| `approver` | Publish drafts and run drift reports. Holding both `drafter` and `approver` lets a user publish their own drafts. |
| `admin` | Create empty trees, manage tree settings and assign roles. Run drift reports. |

All access, including reads, requires authentication. There is no anonymous
access.

**Authentication** is kept simple:
- Django users and sessions for the web app.
- Per-user or per-service API tokens, sent in a header (django-ninja `APIKey`),
  for scripts and services.

Service accounts for roi-db and datasetman get the `reader` role.

## 7. API sketch (django-ninja, `/api/v1`)

### Read

#### Nodes

Node endpoints accept `?rev=N`, a tree revision (default: latest). Every
response is the tree as it was at that revision, including nodes that were
deprecated later.

Every endpoint that returns nodes includes all fields, even when empty, so
clients can rely on the shape. `?dropempty=true` omits fields that are null,
empty strings or empty lists, for smaller, more readable output.

```
GET /nodes/{id}                        detailed node at the latest version and revision
GET /nodes/{id}?rev={r}                detailed node at tree revision r
GET /nodes/{id}/ancestors              path from the top-level node down to the parent
GET /nodes/{id}/descendants?depth={d}  subtree from the given node; depth=all (default) or an integer
GET /nodes/{id}/versions               version history with tree-revision ranges
GET /nodes/{id}/versions/{v}           detailed node at version v
GET /nodes/{id}/warning_history           WoRMS warnings over time, newest first, with computed_at
```

`/versions` and `/warning_history` don't accept `?rev`. `/versions/{v}` does: a node's `children`,
`num_children` and `parent` can change while it stays at version v (their labels
and versions move on), so `?rev` picks which revision to show them at. It must
fall within version v's revision range, otherwise the API returns `400`. The
default is the **last** revision in that range.

##### Lite shape

Used wherever nodes are listed or nested: children, descendants, ancestors and
the `parent` of a detailed node.

```
{id, label, version, num_children, children}
```

- `num_children == 0` means the node is a leaf.
- `children` is a list of lite nodes if the node was expanded, and `null` if it
  wasn't (depth limit reached, or an ancestors list). An expanded leaf node has `children: []`.

##### Content shape

Used for whole-tree listings (`GET /trees/{tree}/nodes_as_tree`), and accepted as the
**import format** (§9). It carries everything that defines the tree's content,
without the detailed shape's derived and WoRMS fields:

```
{id, label, version, aphia_id, description, aliases, num_children, children}
```

`children` follows the same rules as in the lite shape, but holds content nodes.

##### Detailed shape

Used for `GET /nodes/{id}`, `GET /nodes/{id}/versions/{v}`,
`GET /trees/{tree}/nodes/{label}` and `GET /trees/{tree}/nodes`.

```
{
  id: 431, version: 3,
  tree: "taxonomy", rev: 42,
  label: "Chaetoceros_didymus",
  description: "",
  aliases: ["Chaetoceros didymus"],
  aphia_id: 149122,
  worms_data: {scientificname: "Chaetoceros didymus", rank: "Species", status: "accepted",
               link: "https://www.marinespecies.org/aphia.php?p=taxdetails&id=149122",
               fetched_at: "2026-10-01T12:00:00Z"},
  worms_warnings: [],
  tree_depth: 3,
  num_children: 1,
  parent:   {id: 402, label: "Chaetoceros", version: 7, num_children: 2, children: null},
  children: [{id: 433, label: "Chaetoceros_didymus_TAG_external_flagellate",
              version: 1, num_children: 0, children: null}],
  created_in_rev: 3,
  deprecated_in_rev: null,
  successors: []
}
```

`created_in_rev`, `deprecated_in_rev` and `successors` describe the node as a
whole, not the requested revision. A node viewed at an earlier revision still shows that it was
deprecated later.

##### Deprecated nodes

If `{id}` isn't in the requested revision because it was deprecated, the API
returns `200` with the deprecation record instead of a node. This applies to
`/ancestors` and `/descendants` too.

```
{
  id: 812, tree: "taxonomy", rev: 42,
  label: "Thalassiosira_morphotype1",   # label of its last version
  last_version: 4, deprecated_in_rev: 37,
  successors: [1201, 1202]
}
```

A node that didn't exist yet at the requested revision returns `404`.

##### Example: ancestors

`GET /nodes/431/ancestors?rev=42`. The list runs from the top-level node down to
the immediate parent. The requested node is in `node`.

```
{
  tree: "taxonomy", rev: 42,
  node: {id: 431, label: "Chaetoceros_didymus", version: 3, num_children: 1, children: null},
  ancestors: [
    {id: 12,  label: "Chromista",         version: 4, num_children: 3, children: null},
    {id: 30,  label: "Bacillariophyceae", version: 9, num_children: 5, children: null},
    {id: 402, label: "Chaetoceros",       version: 7, num_children: 2, children: null}
  ]
}
```

##### Example: descendants

`GET /nodes/402/descendants?rev=42` (default `depth=all`):

```
{
  tree: "taxonomy", rev: 42,
  node: {id: 402, label: "Chaetoceros", version: 7, num_children: 2, children: [
    {id: 431, label: "Chaetoceros_didymus", version: 3, num_children: 1, children: [
      {id: 433, label: "Chaetoceros_didymus_TAG_external_flagellate",
       version: 1, num_children: 0, children: []}
    ]},
    {id: 440, label: "Chaetoceros_socialis", version: 1, num_children: 0, children: []}
  ]}
}
```

With `GET /nodes/402/descendants?rev=42&depth=1`, nodes 431 and 440 would have
`children: null`, because the depth limit stops expansion there, and node 433 would be absent.
Node 440 still shows `num_children: 0`, so a client can tell it's a leaf.

##### Example: versions

`GET /nodes/402/versions`:

```
{
  id: 402, tree: "taxonomy", created_in_rev: 1, deprecated_in_rev: null,
  versions: [
    {version: 1, valid_from_rev: 1,  valid_to_rev: 5},
    ...
    {version: 7, valid_from_rev: 38, valid_to_rev: null}    # null = current
  ]
}
```

#### Trees

All tree endpoints accept `?rev=N` (default: latest), except where noted.

```
GET /trees                                   list of trees
GET /trees/{tree}                            tree summary and revision metadata at ?rev
GET /trees/{tree}/revisions                  all revisions, newest first
GET /trees/{tree}/revisions/{r}/changes      the atomic changes published in revision r
GET /trees/{tree}/diff?from={a}&to={b}       net difference between two revisions
GET /trees/{tree}/nodes_as_tree?depth={d}    top-level nodes as nested content nodes; depth=all (default)
GET /trees/{tree}/export?parents=false       whole tree as nested detailed nodes (JSON)
GET /trees/{tree}/export_flat                whole tree as CSV, one detailed node per row
GET /trees/{tree}/nodes/{label}              detailed node with that label
GET /trees/{tree}/nodes?ids=&labels=         detailed nodes for a list of ids and/or labels
GET /trees/{tree}/search?q=&method=          ranked typeahead (methods: exact, prefix->substring->fuzzy)
GET /trees/{tree}/search?aphia_id=           every node with that AphiaID
```

##### Tree info

`GET /trees`:

```
{trees: [{id: "taxonomy", title, description, latest_rev: 42, published_at, num_nodes: 1180}, ...]}
```

`GET /trees/{tree}?rev=42` returns the tree summary **and** the metadata of
revision 42. There is no separate `/revisions/{r}` endpoint. This is also the
endpoint consumers poll to see whether the tree has moved on.

```
{id: "taxonomy", title, description,
 rev: 42, latest_rev: 42,
 published_at, published_by, author, notes, changeset: 117,
 num_nodes: 1180, num_top_level: 6, max_depth: 9}
```

##### History

`GET /trees/{tree}/revisions` takes no `?rev`:

```
{tree: "taxonomy",
 revisions: [{rev: 42, published_at, published_by, author,
              notes, changeset: 117, num_changes: 5}, ...]}
```

`GET /trees/{tree}/revisions/37/changes` lists every atomic change in `seq` order.
`version_changes` lists every node whose version changed, including parents
bumped only because their set of children changed.

```
{tree: "taxonomy", rev: 37, notes,
 changes: [
   {seq: 1, op: "add",       group: "split#3", node: 1201, label: "Thalassiosira_morphotype1a", parent: 450},
   {seq: 2, op: "add",       group: "split#3", node: 1202, label: "Thalassiosira_morphotype1b", parent: 450},
   {seq: 3, op: "move",      group: "split#3", node: 830,  from_parent: 812, to_parent: 1201},
   {seq: 4, op: "move",      group: "split#3", node: 831,  from_parent: 812, to_parent: 1202},
   {seq: 5, op: "deprecate", group: "split#3", node: 812,  successors: [1201, 1202]}
 ],
 version_changes: [{node: 450, from: 3, to: 4},
                   {node: 1201, from: null, to: 1}, {node: 1202, from: null, to: 1},
                   {node: 830, from: 2, to: 3}, {node: 831, from: 1, to: 2},
                   {node: 812, from: 4, to: null}]}
```

`from: null` means the node was added. `to: null` means the node's last version
was closed by deprecation.
`to_parent: null` or `from_parent: null` denotes tree top-level.

`GET /trees/{tree}/diff?from=3&to=42` collapses everything in between.
Aliases and WoRMS warnings aren't versioned, so they don't appear.

```
{tree: "taxonomy", from: 3, to: 42,
 added:      [lite...],
 deprecated: [{id, label, deprecated_in_rev, successors}],
 moved:      [{id, label, from_parent, to_parent}],
 edited:     [{id, label, fields: {description: [old, new], aphia_id: [old, new]}}]}
```

##### Browsing and export

`GET /trees/{tree}/nodes_as_tree?rev=42` returns the whole tree as nested **content**
nodes. It behaves like `descendants`, with the tree as the implicit root, and
`?depth=` limits it as usual. With `?dropempty=true`, the response is the
readable form used for import files, e.g.
`GET /trees/taxonomy/nodes_as_tree?rev=42&dropempty=true`:

```
{tree: "taxonomy", rev: 42,
 nodes: [
   {id: 12, label: "Chromista", version: 4, aphia_id: 7, num_children: 3, children: [
     {id: 30, label: "Bacillariophyceae", version: 9, aphia_id: 148899, num_children: 5, children: [...]},
     ...
   ]},
   {id: 200, label: "other", version: 1, num_children: 3, children: [...]}
 ]}
```

`GET /trees/{tree}/export?rev=42` returns the whole tree at that revision as
nested **detailed** nodes. Each node's `children` holds its detailed children,
recursively. Each node's `parent` is implied by the nesting, so it is omitted by
default; `?parents=true` includes it.

```
{tree: "taxonomy", rev: 42,
 nodes: [{id: 12, label: "Chromista", ...detailed fields..., children: [ ... ]}, ...]}
```

`GET /trees/{tree}/export_flat?rev=42` returns CSV, one row per node. `parent`
and `children` are node ids. Columns holding lists use `|` as separator,
`worms_data` is flattened into `worms_*` columns, and `worms_warnings` holds the
warning names only:

```
id,label,version,parent,children,tree_depth,description,aliases,aphia_id,worms_scientificname,worms_rank,worms_status,worms_link,worms_warnings,created_in_rev
402,Chaetoceros,7,30,431|440,2,,,…,Chaetoceros,Genus,accepted,https://…,,1
```

Pinned with `?rev`, both exports can be cached indefinitely, except for aliases
and WoRMS warnings, which are always current.

##### Finding nodes

`GET /trees/{tree}/nodes/{label}` returns the detailed node holding that label
at the requested revision. The match is exact and case-sensitive. If no node
holds the label at that revision, the API returns `404`, even if a deprecated or
renamed node once had it, because a label may name different nodes over time
(§2).

`GET /trees/{tree}/nodes?ids=431,812&labels=Chaetoceros` returns detailed nodes
for a list of ids and/or labels, in the order given (ids first, then labels).
An id whose node was deprecated by that revision returns its deprecation record.
An unknown id or label, or an id from another tree, returns a not-found entry
instead of failing the whole request:

```
{tree: "taxonomy", rev: 42,
 nodes: [{...detailed node 431...},
         {...deprecation record 812...},
         {...detailed node 402...}]}
```

A `POST` variant may be added later for lists too long for a URL.

`GET /trees/{tree}/search` takes either `?q=` or `?aphia_id=`.

- `?q=chaeto` is a ranked typeahead over labels, current aliases and the cached
  WoRMS scientific names of anchored nodes. It is case-insensitive, with `_` and
  space treated as the same, and tries prefix, then substring, then fuzzy
  matching. `?method={exact|prefix|substring|fuzzy}` forces one method;
  `exact` returns only whole-string matches.
- `?aphia_id=149122` returns every node in the tree with that AphiaID, unranked.
  There can be several, because duplicate AphiaIDs are only a warning (§5).

Results are lite nodes with their path and what they matched on:

```
{tree: "taxonomy", rev: 42, q: "chaeto",
 results: [{id: 402, label: "Chaetoceros", version: 7, num_children: 2, children: null,
            path: "Chromista/Bacillariophyceae/Chaetoceros", matched_on: "label"}, ...]}
```

### Write (token or session auth, role-checked)

The browser composes tree and node changes as a changeset and previews them.
When a user saves a new set of changes, a draft changeset is created. It becomes
an official tree revision when an approver publishes it, after which the
changeset can't be updated. Aliases are edited directly, outside changesets.

```
# Checking (no side effects)
POST   /trees/{tree}/validate           {base_rev, changes[]} → errors, WoRMS warnings,
                                        version bumps, warning changes, conflicts

# Changesets
GET    /trees/{tree}/changesets?state=  list changesets, eg to list drafts for approval
POST   /trees/{tree}/changesets         {base_rev, changes[], notes} → new draft
PUT    /changesets/{cs}                 replace/update a draft's changes, notes and base_rev
GET    /changesets/{cs}                 the draft's atomic changes, plus validation results
POST   /changesets/{cs}/publish         approver; draft → new tree revision
DELETE /changesets/{cs}                 discard a draft (kept, with state "discarded")

# WoRMS lookups (server-side cache; the browser never calls WoRMS directly)
GET    /worms/search?name=              candidate WoRMS records
GET    /worms/{aphia_id}                the WoRMS record alone
GET    /worms/{aphia_id}/lineage        the record's WoRMS ancestors, top-level first
GET    /worms/{a}/between/{b}           all records on the lineage path between a and b, inclusive.
                                        400 unless one is an ancestor of the other.
GET    /worms/{a}/common_ancestor/{b}   the nearest common WoRMS ancestor of a and b, inclusive:
                                        if a is an ancestor of b, a is returned, and vice versa

# Drift
POST   /trees/{tree}/drift              start a run (drafter, approver, admin): refreshes worms_warnings.
                                        Asynchronous: returns 202 Accepted
GET    /trees/{tree}/drift              nodes that currently have WoRMS warnings

# Aliases (direct, no changeset)
PUT    /nodes/{id}/aliases {aliases[]}  replace a node's alias list (drafter)
```

Merge, split, import and "Add from WoRMS" are handled in-browser as atomic changeset element groups.

Trees and roles are managed through Django admin, not the API. Imports are
ordinary changesets (§9).

**Caching:** the versioned content of a response pinned with `?rev=` never
changes. Aliases and warnings are always current, so they can differ between two
fetches of the same `?rev=`.
Responses for "latest" include `X-Tree-Revision` and an `ETag`. Consumers poll
`GET /trees/{tree}` to see whether the revision has moved.

## 8. Management web app

Same Django project, using server-rendered templates.

- Tree browser: search, warning badges, and a revision picker to view past
  revision trees (including nodes deprecated since).
- Node page: current state, version history, WoRMS card, successors if deprecated.
- Draft editing in the browser, with each check result shown inline. Merge,
  split and import (upload or paste a file in the import format, §9) are
  wizards that expand into an ordered list of atomic changes, which can be
  edited before saving. A draft for an empty tree has `base_rev: null`.
- Draft list and review: the ordered change list, grouped by macro, the set of
  affected nodes with their old → new versions, and a diff view. Approvers
  publish from here, with notes.
- "Add from WoRMS": search by name, pick a record, and accept the suggested
  parent from the lineage.

## 9. Bootstrapping and import

### Import format

The import format is the **content shape** (§7), nested, with only `label`
required:

```
{tree: "NES2022_taxonomy",
 nodes: [
   {label: "Chromista", aphia_id: 7, children: [
     {label: "Acantharia", aphia_id: 586732},
     ...
   ]}
 ]}
```

- The structure comes from the nesting.
- Per node, only `label`, `aphia_id`, `description`, `aliases` and `children`
  are read, and any of them except `label` may be left out.
- Everything else is **ignored**, including `id` and `tree`. New ids are
  assigned when the import is published. Any response in the content or
  detailed shape can therefore be imported again as is, e.g. the output of
  `/trees/{tree}/nodes_as_tree` or `/export`.

### Import is a changeset

There is no separate import mechanism. Importing is a feature of the draft
editor (§8): the drafter uploads or pastes a file, and it expands into `add`
changes sharing one group (e.g. `import#4`), using placeholder refs for the new
nodes (§4 "Change records"). The imported nodes go at top level or under a
chosen node, and the changes can be edited before saving like any macro's.
From there it is an ordinary draft: checked, reviewed and published by an
approver, creating the next revision. Its labels must not clash with labels
already in the tree. A node's `aliases` from the file are carried on its `add`
change and written as its initial aliases on publish.

A **new tree** is made the same way:

1. An admin creates an empty tree (id, title, description) and assigns its
   roles. It has no revisions and is hidden from `GET /trees` until it has one.
2. A drafter creates a changeset with `base_rev: null`, by importing, building
   it by hand, or both.
3. An approver publishes it, creating revision 1.

So every revision, including revision 1, comes from a published changeset.

### Seed trees

The seed trees are created this way from the files in `labeldata/`. A
management command can create the tree and the import draft, and publish it
when run by a user holding `approver` on that tree. The result is the same as
publishing from the web app.

| File | Tree | Contents |
|---|---|---|
| `labeldata/NES2022_taxonomy.json` | `NES2022_taxonomy` | 246 nodes. Top level: `Chromista`, `Protozoa`, `Plantae`, `Animalia`, `Bacteria`, `other` |
| `labeldata/NES2022_tags.json` | `NES2022_tags` | 18 nodes. Tag categories: `interaction`, `morphology`, `organism_state`, `parasite`, plus `external_detritus` |

`NES2022_taxonomy.json` has one duplicate label: the top-level `other` and
`other/ambiguous/other`. The second must be renamed (e.g. `ambiguous_other`)
before import, since labels are unique within a tree (§2).

## 10. WoRMS versioning and what we store

WoRMS has no releases or version numbers. It is edited continuously.

- **AphiaIDs are permanent.** When a name becomes a synonym, its record stays
  and gets `status: unaccepted`, with `valid_AphiaID` pointing to the accepted
  name.
- Each record has a `modified` timestamp. `AphiaRecordsByDate` lists the
  records changed in a date range.
- The API has no per-record history. The website shows some edit history.

What this service does as a result:

- A service-side `WORMS_RECORD` cache stores each WoRMS record as fetched,
  with `fetched_at` and WoRMS's `modified` time. A new row is added whenever
  WoRMS's `modified` time changes, so the record seen when a node version was
  published can always be looked up. This is our own snapshot of the parts of
  WoRMS we use. The cache is not a node field, so refreshing it doesn't change
  node versions.
- **Drift reports** re-fetch the record and lineage of every AphiaID used in
  the latest revision, and rerun the placement checks (§5) for the whole tree.
  `AphiaRecordsByDate` isn't enough on its own: if WoRMS moves a family our
  tree doesn't hold, only the family's record changes, not those of our genera
  below it. A tree uses a few hundred AphiaIDs, so a full run takes minutes.
- Drift runs themselves aren't recorded. A run adds `NODE_WARNINGS` rows only for
  nodes whose warnings changed (§5), so a quiet run writes almost nothing. The report is the nodes
  that currently have warnings. Drift reports don't propose changes to the
  tree.
- Citation and provenance: "WoRMS, accessed <fetched_at>", per AphiaID.

## 11. Further development

- **Rank as a node field.** Whether to add `rank`, and if so where it comes
  from: WoRMS for anchored nodes and free text otherwise, free text always, or
  WoRMS only. It would allow ranks on un-anchored nodes, e.g. `morphotype`.
- **References to sources other than WoRMS** (e.g. AlgaeBase, NCBI), which
  would turn `aphia_id` into a list of typed references.
- **Historical WoRMS states.** The live WoRMS API has no history, so it can't
  say what WoRMS looked like on a past date. If that's ever needed, e.g. to
  re-check an old revision against WoRMS as it was then, dated snapshots exist
  outside the API: periodic WoRMS exports in Darwin Core Archive (DwC-A) format,
  and archived WoRMS versions in GBIF ChecklistBank.
