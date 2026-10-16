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
  examples are `taxonomy` (general) and `parasites` (internal/external).
- A ROI may be labelled in several trees at once, e.g. a taxon plus an external
  parasite. Combining those labels is up to downstream apps to handle.
- Node ids are **globally unique across trees**, so a node id alone is enough to
  resolve a node. Nodes in different trees may share an AphiaID.
- **The tree is the implicit root.** Nodes with `parent = null` are its
  top-level nodes, and a tree may have any number of them. Adding, moving or
  deprecating a top-level node changes the tree's top-level set. That is captured by
  the tree revision; there is no root node to version.

### Labels and aliases

- **Only the node id is unique.** Labels may repeat within a tree, e.g.
  `morphotype1` under two genera.
- **Labels must be machine-safe:** `^[A-Za-z0-9][A-Za-z0-9_.-]*$`, so no spaces
  or slashes.
- **Aliases are a plain list of free-text strings**, such as
  `Chaetoceros didymus`, misspellings, common names and legacy strings. They
  have no type or category and don't need to be unique.
- **Aliases are search aids only and are not versioned.** Users with the
  `drafter` role add or remove them directly, outside changesets and review.
  Each alias records who added it and when. Aliases don't bump node versions or
  create tree revisions, and the API always returns the current aliases, even
  for `?rev=` requests.
- `resolve` and `search` match labels, current aliases and cached WoRMS names,
  and return **every** matching node at the requested revision (§7). Consumers should store node ids, not
  labels or aliases.
- A warning mechanism (not enforcement) will flag duplicate labels, especially
  among sibling nodes.

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
- `worms_data`: WoRMS name, rank, status and link from the cached record (§11);
  `null` when `aphia_id` is null
- `worms_flags`: the node's **current** WoRMS placement warnings (§5), whatever
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
- **WoRMS flags.** They are derived results, not edits, and only the current
  ones are stored (§5).
- **A child's own edits**, such as a rename.
- **Changes to ancestors.** If a grandparent moves, the node's path to the root
  changes but its version doesn't. A node version describes the node and its
  immediate structure; the full path is captured only by the tree revision.

Changes don't cascade beyond immediate parent and children.

A node's version increases **at most once per tree revision**, however many
changes in the changeset touch it.

### Storage model

![Data model](diagrams/02-data-model.png)

Source: [`diagrams/02-data-model.mmd`](diagrams/02-data-model.mmd)

The tree at revision `r` is every `NODE_VERSION` with
`valid_from_rev <= r < valid_to_rev`, where a null `valid_to_rev` counts as
infinity. `NODE_ALIAS` and `NODE_FLAGS` are **not versioned**. They hold
current values only, one set per node, outside `NODE_VERSION` (§2, §5).

Full-tree exports per revision can be cached indefinitely, because published
revisions never change. Aliases and flags are the exception (see caching, §7).

#### Children

Children are not stored. They are found from the children's `parent` pointers
at that revision, and the parent's version still increases when its set of
children changes. With an index on `(parent, valid_from_rev)`, it's a single fast lookup. Ancestors and descendants use a recursive query on the same columns (WITH RECURSIVE), filtered to revision r.
```sql
SELECT * FROM node_version
WHERE parent = X
  AND valid_from_rev <= r
  AND (valid_to_rev IS NULL OR valid_to_rev > r)
```

#### Why not mptt or treebeard for tree management?

Both libraries assume each node has exactly one position at any time. They keep extra bookkeeping columns per node (lft/rght numbers in mptt, a materialised path in treebeard) and rewrite them on every move.

Here, a node’s parent depends on which revision you ask about, because the parent lives on NODE_VERSION, which is valid for a range of revisions. A single set of bookkeeping columns can’t describe every revision at once. You’d have to recompute them for each revision, or keep a separate copy per revision, which works against how those libraries are designed.

At this scale (thousands of nodes, hundreds of revisions), the plain parent-pointer approach should be fast. If deep descendant queries ever get slow, a published revision never changes, so you could compute an ancestor/descendant table for it once at publish time and never update it. That’s an optimisation to add only if needed.

### Atomic operations

Every tracked edit is one of four atomic operations. Changes in a changeset are
an ordered sequence of operations. Each change's preconditions are checked against the state
left by the changes before it.

| Op | Effect | Preconditions |
|---|---|---|
| `add` | Create a node with a new id, under a parent or at top level. | parent in the tree, same tree |
| `edit` | Change label, description or `aphia_id` (set or clear). | node in the tree |
| `move` | Change parent (or make the node top-level). | new parent in the tree, same tree, no cycle |
| `deprecate` | Remove the node from the tree from this revision on, with optional `successors[]`. | node has **no children** |

Nothing is ever deleted. "Delete" means deprecate. **A deprecated node is one
that is no longer part of the tree.** Publishing a `deprecate` closes the node's
last version (`valid_to_rev = r`) and sets `deprecated_in_rev = r` and
`successors` on the node itself. No new version is created.

- **At revisions before r** the node appears normally, because it was part of
  the tree then. No `?include_deprecated` switch is needed.
- **At revision r and later** it is absent from children, descendants, search,
  resolve and exports.
- **A lookup by id always works.** If the node isn't in the requested revision
  because it was deprecated, the API returns its deprecation record (§7).

**Successors** are informational pointers ("ROIs labelled with this node probably
belong to one of these now"). They are the only record that a merge or split
happened. Old ROIs keep pointing to the deprecated id. How to display or migrate
them is up to downstream apps.

### Merge and split are macros

The UI offers presets that expand into ordered atomic changes sharing a `group`
id. Reviewers see the expanded list and every node it touches.

**Merge A into B:**
```
1..n  move     each child of A → B
n+1   deprecate A  successors=[B]
```

**Split A**, with two variants depending on whether A's meaning changes:

*Narrowing split.* A keeps its meaning, and a sibling takes some children:
```
1     add      A2 (sibling of A)
2..n  move     selected children of A → A2
```
Use this only when old ROIs labelled A are still correct as A.

*Replacing split* (the default preset). A's meaning is no longer valid:
```
1     add      A1 (sibling of A)
2     add      A2 (sibling of A)
3..n  move     each child of A → A1 or A2   (UI requires every child to be assigned)
n+1   deprecate A  successors=[A1, A2]
```

Use the replacing form whenever existing ROIs labelled A might belong to either
new node. Otherwise those ROIs would silently keep a label whose meaning has
narrowed.

### What consumers store

The recommendation is that a ROI annotation stores `(node_id, tree_rev)`. The
node version follows from those two values, and the revision also captures the
hierarchy context at that moment. Storing `(node_id, node_version)` is supported
too.

## 4. Changesets and concurrency

- Edits accumulate in a draft changeset that records its `base_rev`.
- When a draft is submitted, approved or published, all checks run again against
  the latest revision.
- **Conflict rule:** if any node touched by the changeset has a newer version
  than at `base_rev`, publishing is blocked. The drafter must rebase (re-apply on
  latest, re-run checks) and resubmit.
- Publishing is atomic. It creates `TREE_REVISION r+1`, closes the old node
  versions (`valid_to_rev = r+1`) and opens the new ones.

**Blocking errors** (structural only):
- a cycle
- a parent that is not in the tree (deprecated) or is in a different tree
- deprecating a node that still has children
- a label that isn't machine-safe
- a conflicting base revision

**WoRMS problems are warnings, never errors** (see §5).

## 5. WoRMS placement checks (warnings and flags)

When a node has an AphiaID, the service compares where we put it with where
WoRMS puts it. Any disagreement becomes a **warning**: our tree
is allowed to differ from WoRMS, but the difference should be visible.

### The warnings

A node is *anchored* if it has an `aphia_id`. Checks walk past nodes without
one, such as `morphotype1` or `artifact`, as if they weren't there.

| Flag | Meaning | Example |
|---|---|---|
| `out_of_lineage` | The node's nearest anchored ancestor isn't one of its WoRMS ancestors. | *Chaetoceros* placed under *Dinophyceae*. Also catches rank inversions, e.g. a genus under a species. |
| `unaccepted_aphia` | WoRMS marks this AphiaID as unaccepted (e.g. now a synonym). The accepted AphiaID is suggested. | A species renamed in WoRMS since it was added. |
| `duplicate_aphia` | Another active node in the same tree has the same AphiaID. | The same species added twice under different labels. |

"WoRMS ancestors" means the node's lineage from WoRMS
(`AphiaClassificationByAphiaID`).

### When checks run

The check that updates the WoRMs placement warning flags should happen during/as-a-part-of tree editing. 
Updating flags can also be triggered manually or on a schedule.

Moving or re-anchoring one node during tree-editing can change warnings on nearby nodes, so each
run rechecks all of these:

- the node itself
- **looking down:** the first anchored node on each path below it, since its
  nearest anchored ancestor may have changed. Nodes further down still have the
  same nearest anchored ancestor, so they don't need rechecking.
- any other node in the tree with the same AphiaID

Ancestors don't need rechecking.

The draft preview lists "warnings that will change" separately from "nodes whose
version will increase", because the two don't always overlap, since warning flags aren't versioned.
They reflect a check against the most recently polled WoRMs structure.

### How warnings are stored and shown

- `NODE_FLAGS` holds each node's **current** warnings only, with no history.
  Publishing and drift reports overwrite them.
- Warnings never bump node versions (§3) and never block publishing (§4).
- The API returns them on every detailed node as `worms_flags`, a list that is
  empty when there are no warnings:

  ```
  worms_flags: [
    {flag: "out_of_lineage",
     detail: "Nearest anchored ancestor Dinophyceae is not in the WoRMS lineage of Chaetoceros."}
  ]
  ```
- When a drift report finds something worth changing in the tree itself, such
  as moving a node to follow a WoRMS reclassification, it proposes a draft
  changeset for normal review. It never edits published node versions.

## 6. Users and permissions

Roles are assigned per tree and can be combined:

| Role | Can |
|---|---|
| `reader` | Read published revisions. Most downstream apps have this permission. |
| `drafter` | Create and edit drafts, run checks, and submit. |
| `approver` | Approve or reject submitted drafts, and publish. Holding both `drafter` and `approver` lets a user approve and publish their own changes. |
| `admin` | Manage tree settings and assign roles. |

**Authentication** is kept simple:
- Django users and sessions for the web app.
- Per-user or per-service API tokens, sent in a header (django-ninja `APIKey`),
  for scripts and services.

Service accounts for roi-db and datasetman get the `reader` role.

## 7. API sketch (django-ninja, `/api/v1`)

### Read

#### Taxon Nodes

Taxon node endpoints accept `?rev=N`, a tree revision (default: latest). Every
response is the tree as it was at that revision, including nodes that were
deprecated later.

```
GET /nodes/{id}                        detailed taxon node at the latest version and revision
GET /nodes/{id}?rev={r}                detailed taxon node at tree revision r
GET /nodes/{id}/ancestors              path from the top-level node down to the parent
GET /nodes/{id}/descendants?depth={d}  subtree from the given node; depth=all (default) or an integer
GET /nodes/{id}/versions               version history with tree-revision ranges
GET /nodes/{id}/versions/{v}           detailed taxon node at version v 
```

`/versions/` and `/versions/{v}` do not accept `?rev` flag.

##### Lite shape

Used wherever taxon nodes are listed or nested: children, descendants, ancestors and
the `parent` of a detailed node.

```
{id, label, version, num_children, children}
```

- `num_children == 0` means the node is a leaf.
- `children` is a list of lite nodes if the node was expanded, and `null` if it
  wasn't (depth limit reached, or an ancestors list). An expanded leaf node has `children: []`.

##### Detailed shape

Used for `GET /nodes/{id}` and `GET /nodes/{id}/versions/{v}`.

```
{
  id: 431, version: 3,
  tree: "taxonomy", rev: 42,
  label: "Chaetoceros_didymus",
  description: "",
  aliases: ["Chaetoceros didymus"],
  aphia_id: 149120,
  worms_data: {scientificname: "Chaetoceros didymus", rank: "Species", status: "accepted",
               link: "https://www.marinespecies.org/aphia.php?p=taxdetails&id=149120",
               fetched_at: "2026-10-01T12:00:00Z"},
  worms_flags: [],
  tree_depth: 3,
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

##### Deprecated taxon nodes

If `{id}` isn't in the requested revision because it was deprecated, the API
returns `200` with the deprecation record instead of a node:

```
{
  id: 812, tree: "taxonomy", rev: 42,
  label: "Chaetoceros_morphotype1",     # label of its last version
  last_version: 4, deprecated_in_rev: 37,
  successors: [1201, 1202]
}
```

A taxon node that didn't exist yet at the requested revision returns `404`.

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
`children: null`, because the depth limit stops expansion there. Node 440 still
shows `num_children: 0`, so a client can tell it's a leaf.

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
GET /trees/{tree}/nodes?depth={d}            top-level nodes as nested lite nodes; depth=all (default)
GET /trees/{tree}/export                     whole tree as nested detailed nodes (JSON)
GET /trees/{tree}/export_flat                whole tree as CSV, one detailed node per row
GET /trees/{tree}/resolve?label=|name=|aphia_id=
                                             exact lookups; list of detailed nodes
GET /trees/{tree}/search?q=                  ranked typeahead
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
 published_at, published_by, author, approved_by, notes, changeset: 117,
 num_nodes: 1180, num_top_level: 6, max_depth: 9}
```

##### History

`GET /trees/{tree}/revisions` takes no `?rev`:

```
{tree: "taxonomy",
 revisions: [{rev: 42, published_at, published_by, author, approved_by,
              notes, changeset: 117, num_changes: 5}, ...]}
```

`GET /trees/{tree}/revisions/43/changes` lists every atomic change in order.
`seq` runs 1, 2, 3, … with no gaps. `version_changes` lists every node whose
version increased, including parents bumped only because their set of children
changed.

```
{tree: "taxonomy", rev: 43, notes,
 changes: [
   {seq: 1, op: "add",       group: "split#3", node: 1201, label: "Chaetoceros_morphotype1a", parent: 402},
   {seq: 2, op: "add",       group: "split#3", node: 1202, label: "Chaetoceros_morphotype1b", parent: 402},
   {seq: 3, op: "move",      group: "split#3", node: 830,  from_parent: 812, to_parent: 1201},
   {seq: 4, op: "move",      group: "split#3", node: 831,  from_parent: 812, to_parent: 1202},
   {seq: 5, op: "deprecate", group: "split#3", node: 812,  successors: [1201, 1202]}
 ],
 version_changes: [{node: 402, from: 7, to: 8}, {node: 830, from: 2, to: 3},
                   {node: 831, from: 1, to: 2}, {node: 812, from: 4, to: null}]}
```

`to: null` means the node's last version was closed by deprecation.

`GET /trees/{tree}/diff?from=3&to=42` collapses everything in between. Aliases
and WoRMS flags aren't versioned, so they don't appear.

```
{tree: "taxonomy", from: 3, to: 42,
 added:      [lite...],
 deprecated: [{id, label, deprecated_in_rev, successors}],
 moved:      [{id, label, from_parent, to_parent}],
 edited:     [{id, label, fields: {description: [old, new], aphia_id: [old, new]}}]}
```

##### Browsing and export

`GET /trees/{tree}/nodes?rev=42&depth=1` returns the top-level nodes in the lite
shape. It behaves like `descendants`, with the tree as the implicit root.

```
{tree: "taxonomy", rev: 42, depth: 1,
 nodes: [{id: 12, label: "Chromista", version: 4, num_children: 3, children: null}, ...]}
```

`GET /trees/{tree}/export?rev=42` returns the whole tree at that revision as
nested **detailed** nodes. Each node's `children` holds its detailed children,
recursively.

```
{tree: "taxonomy", rev: 42,
 nodes: [{id: 12, label: "Chromista", ...detailed fields..., children: [ ... ]}, ...]}
```

`GET /trees/{tree}/export_flat?rev=42` returns CSV, one row per node. `parent`
and `children` are node ids. Columns holding lists use `|` as separator, and
`worms_data` is flattened into `worms_*` columns:

```
id,label,version,parent,children,tree_depth,description,aliases,aphia_id,worms_scientificname,worms_rank,worms_status,worms_link,worms_flags,created_in_rev
402,Chaetoceros,7,30,431|440,2,,,…,Chaetoceros,Genus,accepted,https://…,,1
```

Pinned with `?rev`, both exports can be cached indefinitely, except for aliases
and WoRMS flags, which are always current.

##### Finding nodes

`GET /trees/{tree}/resolve` takes exactly one of:

- `?label=`: **exact** match on the label.
- `?name=`: matches labels, aliases and the cached WoRMS scientific names of
  anchored nodes. Case-insensitive, with `_` and space treated as the same.
- `?aphia_id=`: every node in the tree with that AphiaID.

It returns **all** matches as detailed nodes, because labels and AphiaIDs aren't
unique:

```
{tree: "taxonomy", rev: 42, query: {name: "chaetoceros didymus"},
 matches: [{...detailed node 431..., matched_on: "worms_name"}]}
```

`GET /trees/{tree}/search?q=chaeto` is a ranked typeahead over the same fields as
`?name=`, using prefix, then substring, then fuzzy matching. 
Method can be forced with `?method={prefix|substring|fuzzy}`. 
Results are lite nodes with their path, to tell apart nodes with the same label:

```
{tree: "taxonomy", rev: 42, q: "chaeto",
 results: [{id: 402, label: "Chaetoceros", version: 7, num_children: 2, children: null,
            path: "Chromista/Bacillariophyceae/Chaetoceros", matched_on: "label"}, ...]}
```

### Write (token or session auth, role-checked)

```
POST /trees/{tree}/changesets                  open a draft (records base_rev)
POST /changesets/{cs}/changes                  append one or more atomic changes (ordered)
PATCH/DELETE /changesets/{cs}/changes/{seq}    edit, reorder or remove a pending change
POST /changesets/{cs}/macros/merge {node, into}            expands to atomic changes
POST /changesets/{cs}/macros/split {node, new_nodes, child_assignment, replace: true}
POST /changesets/{cs}/import/worms {aphia_id, under, with_lineage}
GET  /changesets/{cs}/preview                  draft tree, diff, check results
POST /changesets/{cs}/rebase
POST /changesets/{cs}/submit                   drafter
POST /changesets/{cs}/approve | reject         approver
POST /changesets/{cs}/publish                  approver
GET  /trees/{tree}/drift                       WoRMS drift report (can open a draft)

POST   /nodes/{id}/aliases {alias}             drafter; applies immediately, no changeset
DELETE /nodes/{id}/aliases/{alias}             drafter; applies immediately
```

**Caching:** the versioned content of a response pinned with `?rev=` never
changes. Aliases and flags are always current, so they can differ between two
fetches of the same `?rev=`.
Responses for "latest" include `X-Tree-Revision` and an `ETag`. Consumers poll
`GET /trees/{tree}` to see whether the revision has moved.

## 8. Management web app

Same Django project, using server-rendered templates.

- Tree browser: search, warning badges, and a revision picker to view past
  revision treess (including nodes deprecated since).
- Node page: current state, version history, WoRMS card, successors if depricated.
- Draft editing, with each check result shown inline. Merge and split are
  wizards that expand into an ordered list of atomic changes, which can be
  edited before submitting.
- Review shows the ordered change list, grouped by macro, and the set of
  affected nodes with their old → new versions.
- "Add from WoRMS": search by name, pick a record, and accept the suggested
  parent from the lineage.
- Review: diff view, approve or reject, publish with notes.

## 9. Bootstrapping

Revision 1 of `taxonomy` is seeded by an admin import, without approval, from
`amplify-datasetman/data/labeltrees/Jan2022_NES_taxonomy.json`:

- `aphia_id` → `aphia_id`. WoRMS lineage nodes become nodes with their own
  AphiaIDs.
- `non_worms` buckets (artifact, organic_debris, informal_group, ambiguous)
  become top-level grouping nodes with no AphiaID. Morphotypes stay under their
  parent taxon.
- Dataset labels → labels (already machine-safe). The display form, with
  spaces, becomes an alias.
- `_TAG_` labels → ordinary nodes under their base taxon.

Revision 1 of `parasites` is seeded from the parasite `_TAG_` suffixes.

## 10. Decisions log (latest round)

- Successors on deprecate: **optional**. The UI nudges for them on merge and
  split presets.
- `node_type`, `base_node` and `rank` are **not** node fields. Combined labels
  sit under their base taxon. WoRMS rank is still shown, read-only, from the
  cached WoRMS record.
- Aliases: a **plain list of strings**, unversioned and edited directly
  (search aids only).
- External references: a single **nullable `aphia_id`**.
- Draft visibility: **drafters, approvers and admins** of that tree.
- WoRMS checks run **live**, while editing and again at publish. The service
  needs network access to marinespecies.org. If WoRMS is unreachable, the change
  records `checks: unavailable` and publishing is still allowed, because WoRMS
  issues are warnings only.

## 11. WoRMS versioning and what we store

WoRMS has no releases or version numbers. It is edited continuously.

- **AphiaIDs are permanent.** When a name becomes a synonym, its record stays
  and gets `status: unaccepted`, with `valid_AphiaID` pointing to the accepted
  name.
- Each record has a `modified` timestamp. `AphiaRecordsByDate` lists the
  records changed in a date range.
- The API has no per-record history. The website shows some edit history.
- Dated snapshots exist outside the live API: periodic DwC-A exports and
  archived WoRMS versions in GBIF ChecklistBank.

What this service does as a result:

- A service-side `WORMS_RECORD` cache stores each WoRMS record as fetched,
  with `fetched_at` and WoRMS's `modified` time. A new row is added whenever
  WoRMS's `modified` time changes, so the record seen when a node version was
  published can always be looked up. This is our own snapshot of the parts of
  WoRMS we use. The cache is not a node field, so refreshing it doesn't change
  node versions.
- **Drift reports** call `AphiaRecordsByDate` since the last drift run, filtered
  to AphiaIDs used in the tree, and re-check lineage for those. They refresh
  `NODE_FLAGS` directly, and structural fixes become a proposed draft.
- Citation and provenance: "WoRMS, accessed <fetched_at>", per AphiaID.

## 12. Further development

- **Rank as a node field.** Whether to add `rank`, and if so where it comes
  from: WoRMS for anchored nodes and free text otherwise, free text always, or
  WoRMS only. It would allow ranks on un-anchored nodes, e.g. `morphotype`.
- **References to sources other than WoRMS** (e.g. AlgaeBase, NCBI), which
  would turn `aphia_id` into a list of typed references.
