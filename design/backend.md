# Backend

Data model, versioning rules and atomic changes. 

For the endpoints that expose them, see [api.md](api.md). 

For how edits are drafted and published, see [webapp.md](webapp.md).

![Data model](diagrams/02-data-model.png)

Source: [`diagrams/02-data-model.d2`](diagrams/02-data-model.d2)

- **Core** (dark headers): `TREE`, `TREE_REVISION`, `NODE` and `NODE_VERSION`,
  described in the [README](../README.md#how-it-works).
- **Changesets** (light green): `CHANGESET` and its ordered `CHANGE`s. Each
  published changeset produces one `TREE_REVISION`. See
  [Change records](#change-records) and
  [webapp.md](webapp.md#changesets-and-concurrency).
- **Auxilliary per-node data** (light blue). None of these ever bump a node version:
  - `NODE_ALIAS`: aliases over time; removed aliases are kept
    ([Labels and aliases](#labels-and-aliases))
  - `NODE_WARNINGS`: WoRMS warnings over time; the newest row per node is
    its current set ([worms.md](worms.md#how-warnings-are-stored-and-shown))
  - `SUCCESSOR`: pointers from a deprecated node to its replacements
    ([Deprecation](#deprecation-and-successors))
  - `WORMS_RECORD`: service-side cache of WoRMS records
    ([worms.md](worms.md#what-we-store))

## Trees and nodes

### Multiple trees

- labeltree-db supports multiple different disjoint trees. 
  Each has its own nodes and revisions. See [Example trees](#example-trees)
  for `NES2022_taxonomy` and `NES2022_tags`.
  API examples use "taxonomy" as the name for its example taxonomy tree.
- A ROI may be associated with a label from more than one labeltree, 
  e.g. a taxon plus an external parasite. 
  Downstream apps decide how to combine those labels.
- Node ids are **globally unique across trees**, so a node id alone is enough to
  resolve a node. Nodes in different trees may share an AphiaID.
- **The tree is the implicit root.** Nodes with `parent = null` are
  top-level nodes, and a tree may have any number of them. 

### Labels and aliases

- **Labels are unique within a tree at each revision.** `morphotype1` under two
  genera must be e.g. `Chaetoceros_morphotype1` and
  `Thalassiosira_morphotype1`. The comparison is case-sensitive.
- **Labels can be reused over time.** A label freed by a rename or a
  deprecation may later go to another node, so which node a label names depends
  on the revision. Only the node id identifies a node permanently.
- **Labels must be machine-safe:** `^[A-Za-z0-9][A-Za-z0-9_.-]*$`, so no spaces
  or slashes.
- **Aliases are a plain list of free-text strings**, and may include misspellings, common names 
  and legacy strings, display strings. As it stands, they have no type and don't need to be unique.
- **Aliases are search aids and are not versioned.** Drafters add or
  remove them one at a time, outside of changesets and revision review.
  Removing an alias marks it removed rather than deleting it, so each alias
  records who added and removed it, and when. The API always searches and
  returns current aliases (not removed), even for `?rev=` requests.
- Nodes can be looked up by-label for a given revision, and search matches
  labels, current aliases and cached WoRMS names. Because labels are impermanent,
  consumers should store node ids, not labels or aliases.

### Node fields

| Table | Field | Notes |
|---|---|---|
| `NODE` | `id` | global across trees, never reused |
| | `tree` | the tree the node belongs to |
| | `created_in_rev` | the revision in which the node was added |
| | `deprecated_in_rev` | null while still in the tree, else the revision from which it is no longer in the tree |
| `NODE_VERSION` | `version` | integer per node, starting at 1 ([Versioning](#versioning)) |
| | `valid_from_rev`, `valid_to_rev` | tree revisions this version is valid for; `valid_to_rev` null = current |
| | `label` | machine-safe string, unique per tree revision |
| | `parent` | node id, or null for a top-level node |
| | `aphia_id` | nullable WoRMS AphiaID |
| | `description` | free text: definition and annotation guidance |
| `NODE_ALIAS` | `alias` | free text, one row per alias. Associated with a `node`, not a `node_version`. Unique per node among current aliases. |
| | `added_by`, `added_at` | who added it, when |
| | `removed_by`, `removed_at` | who removed it, when; null = current |
| `SUCCESSOR` | `deprecated_node`, `successor_node` | one row per successor of a deprecated node; may be none. Unversioned. |

Only `NODE_VERSION` fields are versioned. The API returns aliases and
successors on the node as `aliases[]` and `successors[]`.

The API also returns derived, read-only values:

- `worms_data`: WoRMS name, rank, status and link from the cached record;
  `null` when `aphia_id` is null
- `worms_warnings`: the node's **current** [WoRMS warnings](worms.md#the-warnings),
  whatever revision is requested; empty list if none
- `children`: nodes whose `parent` is this node at the requested revision
  (not stored, see [Children](#children))
- `num_children`: number of children at the requested revision
- `tree_depth`: number of ancestors; top-level nodes have depth 0

### Combined (legacy) labels

Legacy combined labels, such as `Chaetoceros_didymus_TAG_external_flagellate`,
are ordinary nodes **placed under their base taxon**, with no `aphia_id`. The
parent is the only link to the taxon. They are a stopgap until consumers label
ROIs in several trees at once (taxon tree + parasite/tag tree). They and can be
deprecated later like any other node.

## Versioning

- **Node version**: an integer per node, starting at 1.
- **Tree revision**: an integer per tree, starting at 1. 
  It increases once per published changeset and identifies 
  the state of every node at that point.

### What changes a node's version

A node's version increases if any of these changed:

- label, description or `aphia_id`
- **parent** (the node was moved)
- **set of immediate children**: a child was added, deprecated, or moved in or
  out.

These do **not** change it:

- aliases (not versioned)
- WoRMS warnings (derived results, stored separately)
- a child's own edits, such as a rename
- changes to ancestors. If a grandparent moves, the node's path changes but
  its version doesn't. A node version describes the node and its immediate
  structure; the full path is captured only by the tree revision.

A node's version increases **at most once per tree revision**, even if it may
have been subject to mutliple atomic changes (e.g. moved AND renamed).

#### Example

Four nodes over five revisions. `Chaetoceros` and `Thalassiosira` are genera;
`C_didymus` starts under `Chaetoceros`. Each cell is the node's version at that
revision. **Bold** marks an increase.

| node | rev 1<br>init | rev 2<br>add `C_socialis` under `Chaetoceros` | rev 3<br>rename `C_didymus` → `C_didymus_sl` | rev 4<br>move `C_socialis` → `Thalassiosira` | rev 5<br>deprecate `C_didymus_sl`, edit `Chaetoceros` description |
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

### Reading a revision

The tree at revision `r` is every `NODE_VERSION` with
`valid_from_rev <= r < valid_to_rev`, where a null `valid_to_rev` counts as
infinity. Published revisions never change, so full-tree exports per revision
can be cached indefinitely, apart from aliases and warnings, which are always
current.

Node versions don't store which changes produced them, because the mapping is
many-to-many: one version can come from several changes (two children added
under one parent), and one change can bump several nodes (a `move` bumps the
node and both parents). Instead it's derived. A node changes at most once per
revision, so a version's `valid_from_rev` identifies the changeset, and its
changes are those whose `node`, `parent`, `from_parent` or `to_parent` is the
node. If this lookup gets slow, a `CHANGE_EFFECT(change, node, from_version,
to_version)` table filled at publish would serve it.

#### Children

Children are not stored. They are found from the children's `parent` pointers
at that revision, and the parent's version still increases when its set of
children changes. With an index on `(parent, valid_from_rev)` it's a single
fast lookup. Ancestors and descendants use a recursive query on the same
columns (`WITH RECURSIVE`), filtered to revision `r`.

```sql
SELECT * FROM node_version
WHERE parent = X
  AND valid_from_rev <= r
  AND (valid_to_rev IS NULL OR valid_to_rev > r)
```

#### Why not mptt or treebeard?

Both libraries assume each node has exactly one position at any time. They keep
bookkeeping columns per node (lft/rght numbers in mptt, a materialised path in
treebeard) and rewrite them on every move.

Here, a node's parent depends on the revision, because the parent lives on
`NODE_VERSION`. A single set of bookkeeping columns can't describe every
revision at once; you'd have to recompute them per revision or keep a copy per
revision, which works against how those libraries are designed.

At this scale (thousands of nodes, hundreds of revisions), plain parent
pointers should be fast. If deep descendant queries ever get slow, an
ancestor/descendant table can be computed once per revision at publish time,
since published revisions never change.

## Atomic changes

Every tracked edit is one of four atomic operations. A changeset is an ordered
sequence of them, and each change's preconditions are checked against the
state left by the changes before it.

| Op | Effect | Preconditions |
|---|---|---|
| `add` | Create a node with a new id, under a parent or at top level. | parent in the tree, same tree, label not used in the tree |
| `edit` | Change label, description or `aphia_id` (set or clear). | node in the tree; a new label not used in the tree |
| `move` | Change parent (or make the node top-level). | new parent in the tree, same tree, no cycle |
| `deprecate` | Remove the node from the tree from this revision on, with optional `successors[]`. | node has **no children** |

Merge and split are not operations of their own. They are UI presets that
expand into these four ([webapp.md](webapp.md#merge-and-split)).

### Deprecation and successors

Nothing is ever deleted; "delete" means deprecate. **A deprecated node is one
that is no longer part of the tree.** Publishing a `deprecate` at revision `r`
closes the node's last version (`valid_to_rev = r`) and sets
`deprecated_in_rev = r` and `successors` on the node. No new version is created.

- **At revisions before `r`** the node appears normally, because it was part of
  the tree then.
- **At `r` and later** it is absent from children, descendants, label lookups,
  search and exports, and its label is free for another node.
- **A lookup by id always works.** If the node was deprecated by the requested
  revision, the API returns its
  [deprecation record](api.md#deprecated-nodes).

**Successors** are informational pointers ("ROIs labelled with this node
probably belong to one of these now"). They are the only record that a merge or
split happened. Old ROIs keep pointing to the deprecated id; how to display or
migrate them is up to downstream apps.

- Successors are optional. Merge-with-replacement and split-with-replacement always set them
  ([diagrams](webapp.md#merge-and-split)). A node that is simply removed need not have successors. 
- Requesting a node at revision `r` or later when it is depricated returns its
  [deprecation record](api.md#deprecated-nodes), which lists its successors.
- Successors may themselves be deprecated later, so a consumer may have to
  follow a chain (A → B → C).

### Change records

Each `CHANGE` row is one atomic operation: its `op`, its position `seq` in the
changeset, an optional `group` naming the macro that produced it (e.g.
`split#3`), its arguments in `payload`, and its WoRMS results in `checks`.

| Op | Payload |
|---|---|
| `add` | `node` (placeholder, see below), `label`, `parent`, optional `description`, `aphia_id` and initial `aliases` |
| `edit` | `node`, and only the fields being changed: `label`, `description`, `aphia_id` (null clears it) |
| `move` | `node`, `from_parent`, `to_parent` (null = top-level) |
| `deprecate` | `node`, `successors[]` (may be empty) |

`from_parent` is recorded so the change list reads on its own, without
reconstructing the base revision.

A node added in a draft has no id yet. Within the draft it is referred to by a
placeholder such as `new:1`, which later changes may use as a `parent`,
`to_parent` or successor. Publishing assigns real ids and rewrites the
placeholders, so published changes contain only real ids, and discarded drafts
never use up ids.

`checks` holds the [WoRMS warnings](worms.md#the-warnings) the change would
cause, as a list of `{warning, node, detail}`, or `unavailable` if WoRMS
couldn't be reached. It is refreshed on every save and again on publish, and on
publish the final results are written to `NODE_WARNINGS`. Conflicts and
structural errors aren't stored: `validate` and publish report them each time
they run.

## Example trees

`labeldata/` holds two example trees, for reference and as sample
[import](webapp.md#import) files. A user can load one as a
[new tree](webapp.md#new-trees): it creates the tree and the import draft, and
publishes it when run by a user holding `approver` on that tree.

| File | Tree | Contents |
|---|---|---|
| `labeldata/NES2022_taxonomy.json` | `NES2022_taxonomy` | 246 nodes. Top level: `Chromista`, `Protozoa`, `Plantae`, `Animalia`, `Bacteria`, `other` |
| `labeldata/NES2022_tags.json` | `NES2022_tags` | 18 nodes. Tag categories: `interaction`, `morphology`, `organism_state`, `parasite`, and `external_detritus` |
