# API

REST API built with django-ninja, served under `/api/v1`. Consumers **pull**;
the service pushes no notifications or events.

- [Authentication and roles](#authentication-and-roles)
- [Consumer guide](#consumer-guide)
- [Read endpoints](#read-endpoints): [nodes](#nodes), [trees](#trees)
- [Write endpoints](#write-endpoints)
- [Caching](#caching)

## Authentication and roles

All access, including reads, requires authentication. There is no anonymous
access.

- Django users and sessions for the web app.
- Per-user or per-service API tokens, sent in a header (django-ninja `APIKey`),
  for scripts and services.

Roles are assigned per tree and can be combined:

| Role | Can |
|---|---|
| `reader` | Read published revisions. Most downstream apps have this role. |
| `drafter` | Create, update and discard any draft, and run checks and drift reports. Add and remove aliases. |
| `approver` | Publish drafts and run drift reports. Holding both `drafter` and `approver` lets a user publish their own drafts. |
| `admin` | Create empty trees, manage tree settings and assign roles. Run drift reports. |

Service accounts for roi-db and datasetman get `reader`. Trees and roles are
managed through Django admin, not the API.

## Consumer guide

A ROI annotation should store `(node_id, tree_rev)`. The node version follows
from those two values, and the revision also captures the hierarchy at that
moment. Storing `(node_id, node_version)` is supported too. Never store labels
or aliases: [labels can be reused](backend.md#labels-and-aliases).

![Consumer lookups](diagrams/05-consumer-lookups.png)

The diagram follows roi-db as the tree changes underneath it. Every call
carries a `reader` token (not shown).

**Setup.**

- **Rev R1:** tree T has K › L › A, B, where node L has the label `L1`.
  roi-db holds 100 ROIs each for A and B. Roi-X is labelled `L1`: roi-db looks
  the label up and stores `(T, id(L), R1)`.
- **Rev R2:** `L1` was a typo. A published edit renames node L to `L2`, and
  `L1` is kept as an alias. The node id doesn't change, so roi-X is unaffected:
  - `GET /trees/T/nodes/L1` returns `404`; `GET /trees/T/nodes/L2` returns
    `id(L)`.
  - `GET /trees/T/nodes/L1?rev=R1` still returns `id(L)`.
  - `GET /trees/T/search?q=L1` finds node L through the alias.
  - `GET /nodes/id(L)` always works.
- **Rev R3, months later:** L has moved under J and gained children C, D and E,
  with 10 ROIs each. Roi-Y is labelled `L2` and stored as `(T, id(L), R3)`. No
  ROIs are labelled K or J themselves.

roi-db stores node ids, never labels, plus when each annotation was saved. To
answer a query by label it looks the label up (`/trees/T/nodes/{label}`), and
for descendants it fetches the subtree (`/nodes/{id}/descendants`).

**Scenarios.**

1. **ROIs with label `L2`:** roi-X and roi-Y. Both carry `id(L)`, so neither
   the rename nor the revision each was stored at matters.
2. **Descendants of K, at R3:** none. L is no longer under K, so neither L nor
   anything below it is included, even though roi-X was labelled while L was
   under K.
3. **Descendants of J, at R3:** 232 ROIs: roi-X and roi-Y for L, 100 each for A
   and B, and 10 each for C, D and E.
4. **Descendants of K as of time t, between R2 and R3:** roi-db answers as if
   the request had been made at t:
   1. `GET /trees/T/revisions` lists revisions with `published_at`. The
      newest one published at or before t is R2.
   2. `GET /trees/T/nodes/K?rev=R2`, then `GET /nodes/id(K)/descendants?rev=R2`,
      gives L, A and B.
   3. roi-db selects ROIs with those node ids that were **saved at or before
      t**. The stored revision alone isn't enough, because a ROI saved after t
      but before R3 would also carry R2.

   The result is 201 ROIs: roi-X, and 100 each for A and B.

Hierarchy queries follow the tree at the revision they're asked about: the
latest, unless `?rev=` is given.

**Deprecated nodes (not shown).** When the tree revision moves on, one
`diff?from=&to=` call lists every node deprecated in between, with its
successors, and one batch `nodes?ids=` call fetches those successors. A
successor may be deprecated too, in which case it comes back as a deprecation
record; follow its successors with another batch call. What to do next is up
to the consumer.

## Read endpoints

### Nodes

Node endpoints accept `?rev=N`, a tree revision (default: latest). Every
response is the tree as it was at that revision, including nodes that were
deprecated later.

Every endpoint that returns nodes includes all fields, even when empty, so
clients can rely on the shape. `?dropempty=true` omits fields that are null,
empty strings or empty lists.

```
GET /nodes/{id}                        detailed node at the latest version and revision
GET /nodes/{id}?rev={r}                detailed node at tree revision r
GET /nodes/{id}/ancestors              path from the top-level node down to the parent
GET /nodes/{id}/descendants?depth={d}  subtree from the given node; depth=all (default) or an integer
GET /nodes/{id}/versions               version history with tree-revision ranges
GET /nodes/{id}/versions/{v}           detailed node at version v
GET /nodes/{id}/warning_history        WoRMS warnings over time, newest first, with computed_at
```

`/versions` and `/warning_history` don't accept `?rev`. `/versions/{v}` does: a
node's `children`, `num_children` and `parent` can change while it stays at
version v (their labels and versions move on), so `?rev` picks which revision
to show them at. It must fall within version v's revision range, otherwise the
API returns `400`. The default is the **last** revision in that range.

#### Lite shape

Used wherever nodes are listed or nested: children, descendants, ancestors and
the `parent` of a detailed node.

```
{id, label, version, num_children, children}
```

- `num_children == 0` means the node is a leaf.
- `children` is a list of lite nodes if the node was expanded, and `null` if it
  wasn't (depth limit reached, or an ancestors list). An expanded leaf has
  `children: []`.

#### Content shape

Used for whole-tree listings (`GET /trees/{tree}/nodes_as_tree`), and accepted
as the [import format](webapp.md#import-format). It carries everything that
defines the tree's content, without the derived and WoRMS fields:

```
{id, label, version, aphia_id, description, aliases, num_children, children}
```

`children` follows the same rules as in the lite shape, but holds content nodes.

#### Detailed shape

Used for `GET /nodes/{id}`, `GET /nodes/{id}/versions/{v}`,
`GET /trees/{tree}/nodes/{label}` and `GET /trees/{tree}/nodes`. Fields are
described in [backend.md](backend.md#node-fields).

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
whole, not the requested revision. A node viewed at an earlier revision still
shows that it was deprecated later.

#### Deprecated nodes

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

#### Example: ancestors

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

#### Example: descendants

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

With `depth=1`, nodes 431 and 440 would have `children: null`, because the
depth limit stops expansion there, and node 433 would be absent. Node 440 still
shows `num_children: 0`, so a client can tell it's a leaf.

#### Example: versions

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

### Trees

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

#### Tree info

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

#### History

`GET /trees/{tree}/revisions` takes no `?rev`:

```
{tree: "taxonomy",
 revisions: [{rev: 42, published_at, published_by, author,
              notes, changeset: 117, num_changes: 5}, ...]}
```

`GET /trees/{tree}/revisions/37/changes` lists every atomic change in `seq`
order. `version_changes` lists every node whose version changed, including
parents bumped only because their set of children changed.

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

`from: null` means the node was added. `to: null` means its last version was
closed by deprecation. `from_parent: null` or `to_parent: null` means top level.

`GET /trees/{tree}/diff?from=3&to=42` collapses everything in between. Aliases
and WoRMS warnings aren't versioned, so they don't appear.

```
{tree: "taxonomy", from: 3, to: 42,
 added:      [lite...],
 deprecated: [{id, label, deprecated_in_rev, successors}],
 moved:      [{id, label, from_parent, to_parent}],
 edited:     [{id, label, fields: {description: [old, new], aphia_id: [old, new]}}]}
```

#### Browsing and export

`GET /trees/{tree}/nodes_as_tree?rev=42` returns the whole tree as nested
**content** nodes. It behaves like `descendants`, with the tree as the implicit
root, and `?depth=` limits it as usual. With `?dropempty=true`, the response is
the readable form used for import files:

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

`GET /trees/{tree}/export?rev=42` returns the whole tree as nested **detailed**
nodes. Each node's `parent` is implied by the nesting, so it is omitted by
default; `?parents=true` includes it.

```
{tree: "taxonomy", rev: 42,
 nodes: [{id: 12, label: "Chromista", ...detailed fields..., children: [ ... ]}, ...]}
```

`GET /trees/{tree}/export_flat?rev=42` returns CSV, one row per node. `parent`
and `children` are node ids. List columns use `|` as separator, `worms_data` is
flattened into `worms_*` columns, and `worms_warnings` holds the warning names
only:

```
id,label,version,parent,children,tree_depth,description,aliases,aphia_id,worms_scientificname,worms_rank,worms_status,worms_link,worms_warnings,created_in_rev
402,Chaetoceros,7,30,431|440,2,,,…,Chaetoceros,Genus,accepted,https://…,,1
```

#### Finding nodes

`GET /trees/{tree}/nodes/{label}` returns the detailed node holding that label
at the requested revision. The match is exact and case-sensitive. If no node
holds the label at that revision, the API returns `404`, even if a deprecated or
renamed node once had it.

`GET /trees/{tree}/nodes?ids=431,812&labels=Chaetoceros` returns detailed nodes
for a list of ids and/or labels, in the order given (ids first, then labels).
An id deprecated by that revision returns its deprecation record. An unknown id
or label, or an id from another tree, returns a not-found entry instead of
failing the whole request. A `POST` variant may be added later for lists too
long for a URL.

```
{tree: "taxonomy", rev: 42,
 nodes: [{...detailed node 431...},
         {...deprecation record 812...},
         {...detailed node 402...}]}
```

`GET /trees/{tree}/search` takes either `?q=` or `?aphia_id=`.

- `?q=chaeto` is a ranked typeahead over labels, current aliases and the cached
  WoRMS scientific names of anchored nodes. It is case-insensitive, with `_` and
  space treated as the same, and tries prefix, then substring, then fuzzy
  matching. `?method={exact|prefix|substring|fuzzy}` forces one method;
  `exact` returns only whole-string matches.
- `?aphia_id=149122` returns every node in the tree with that AphiaID, unranked.
  There can be several, because duplicate AphiaIDs are only a
  [warning](worms.md#the-warnings).

Results are lite nodes with their path and what they matched on:

```
{tree: "taxonomy", rev: 42, q: "chaeto",
 results: [{id: 402, label: "Chaetoceros", version: 7, num_children: 2, children: null,
            path: "Chromista/Bacillariophyceae/Chaetoceros", matched_on: "label"}, ...]}
```

## Write endpoints

Token or session auth, role-checked. The browser composes changes as a
changeset; how drafts are saved, reviewed and published is described in
[webapp.md](webapp.md#changesets-and-concurrency). Aliases are edited directly,
outside changesets.

```
# Checking (no side effects)
POST   /trees/{tree}/validate           {base_rev, changes[]} → errors, WoRMS warnings,
                                        version bumps, warning changes, conflicts

# Changesets
GET    /trees/{tree}/changesets?state=  list changesets, e.g. drafts awaiting approval
POST   /trees/{tree}/changesets         {base_rev, changes[], notes} → new draft
PUT    /changesets/{cs}                 replace a draft's changes, notes and base_rev
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

`changes[]` holds [change records](backend.md#change-records). Merge, split,
import and "Add from WoRMS" have no endpoints of their own: the browser expands
them into groups of atomic changes ([webapp.md](webapp.md#merge-and-split)).

## Caching

The versioned content of a response pinned with `?rev=` never changes. Aliases
and warnings are always current, so they can differ between two fetches of the
same `?rev=`. Responses for "latest" include `X-Tree-Revision` and an `ETag`.
Consumers poll `GET /trees/{tree}` to see whether the revision has moved.
