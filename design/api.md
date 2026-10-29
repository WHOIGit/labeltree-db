# API

REST API built with django-ninja, served under `/api/v1`. Consumers **pull**;
the service pushes no notifications or events.

- [Authentication and roles](#authentication-and-roles)
- [Read endpoints](#read-endpoints): [nodes](#nodes), [trees](#trees), [organizations](#organizations)
- [Write endpoints](#write-endpoints): [WoRMS jobs and warnings](#worms-jobs-and-warnings)
- [Caching](#caching)
- [Errors and status codes](#errors-and-status-codes)
- [Pagination and limits](#pagination-and-limits)
- [Consumer guide](#consumer-guide)

## Authentication and roles

Published trees are open: the [read endpoints](#read-endpoints), including
organizations, alias and description history, the WoRMS warnings report and
`/health` need no credentials, so consumers such as roi-db and datasetman read anonymously.
Everything else needs a logged-in user and returns `401` without one:

- Django users and sessions for the web app (CSRF-checked).
- Per-user API tokens for scripts, sent as `Authorization: Token <key>`. A
  token acts as its user. Its key is shown once when a site admin creates it.

Every tree belongs to one **organization**, such as `amplify` (AMPLIfy). Each
user holds at most one role per organization, which applies to all its trees.
Roles form a ladder, and each includes everything below it:

| Role | Can, on every tree of the organization |
|---|---|
| `reader` | See drafts, WoRMS jobs and the organization's members. Use the WoRMS lookups. |
| `drafter` | Create, update, rebase and discard any draft, validate, run fetch jobs and sync WoRMS data. Add and remove aliases, set descriptions. |
| `approver` | Publish drafts, including their own. |
| `owner` | Manage the organization's members: add users, change roles (including to `owner`), remove members; the last owner can't be removed or demoted. Create new trees in the organization (changesets with `base_rev: null`). |

**Site admins** (Django superusers) manage users, tokens and organizations in
Django admin, move trees between organizations, are `owner` in every
organization, and alone can start a full cache sync (`sync_all`).

## Read endpoints

### Nodes

Node endpoints accept `?rev=N`, a tree revision (default: latest). A node id
identifies its tree, so `N` is a revision of that node's tree. Every response
is the tree as it was at that revision, including nodes that were deprecated
later.

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
  aliases: [{id: 88, alias: "Chaetoceros didymus"}],
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

`description` is the node's current description, whatever revision is
requested, because descriptions are not versioned
([backend.md](backend.md#labels-aliases-and-descriptions)).

`aliases` are the current aliases, each with the id used to
[remove it](#write-endpoints). The content shape and `export_flat` list them as
plain strings, because ids mean nothing to an import.

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
GET /trees/{tree}/search?q=&method=&limit=   ranked typeahead (default: exact → prefix → substring → fuzzy)
GET /trees/{tree}/search?aphia_id=           every node with that AphiaID
```

#### Tree info

`GET /trees`:

```
{trees: [{id: "taxonomy", title, description, org: "amplify", latest_rev: 42, published_at, num_nodes: 1180}, ...]}
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

`GET /trees/{tree}/diff?from=3&to=42` collapses everything in between,
comparing each node's state at `from` with its state at `to`. Descriptions,
aliases and WoRMS warnings aren't versioned, so they don't appear.

```
{tree: "taxonomy", from: 3, to: 42,
 added:      [lite...],
 deprecated: [{id, label, deprecated_in_rev, successors}],
 moved:      [{id, label, from_parent, to_parent}],
 edited:     [{id, label, fields: {label: [old, new], aphia_id: [old, new]}}]}
```

- `label` in each entry is the node's label at `to`, or its last label if
  deprecated. A rename appears in `edited` as `fields.label`.
- `edited.fields` holds only the fields that differ.
- A node that was both moved and edited appears in both lists.
- A node added in the range appears only in `added`, with its state at `to`.
  One added and then deprecated in the range doesn't appear at all.

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
  space treated as the same. By default it tries exact, then prefix, then
  substring, then fuzzy matching, ranking earlier methods first.
  `?method={exact|prefix|substring|fuzzy}` forces one method; `exact` returns
  only whole-string matches. See [Limits](#pagination-and-limits).
- `?aphia_id=149122` returns every node in the tree with that AphiaID, unranked.
  There can be several, because duplicate AphiaIDs are only a
  [warning](worms.md#the-warnings).

Results are lite nodes with their path and what they matched on:

```
{tree: "taxonomy", rev: 42, q: "chaeto",
 results: [{id: 402, label: "Chaetoceros", version: 7, num_children: 2, children: null,
            path: "Chromista/Bacillariophyceae/Chaetoceros", matched_on: "label"}, ...]}
```

### Organizations

```
GET /orgs                                    organizations with their trees
GET /orgs/{org}                              one organization
```

```
{orgs: [{id: "amplify", name: "AMPLIfy", trees: ["NES2022_tags", "NES2022_taxonomy"]}]}
```

Members and their roles need a login; see [write endpoints](#write-endpoints).

## Write endpoints

Token or session auth, role-checked. The browser composes changes as a
changeset; how drafts are saved, reviewed and published is described in
[webapp.md](webapp.md#changesets-and-concurrency). Aliases and descriptions are
edited directly, outside changesets.

```
# Checking (no side effects)
POST   /changesets/validate             {tree, base_rev, changes[]}, or
                                        {new_tree: {id, title, description, org}, changes[]}
                                        → errors, conflicts, reduced changes with sources,
                                        version bumps, net changes per node, WoRMS warnings
                                        and warning changes from cached records, AphiaIDs
                                        missing from the cache

# Changesets
GET    /changesets?state=&tree=&org=    the changesets you may see, newest first, e.g.
                                        drafts awaiting approval
POST   /changesets                      {tree, base_rev, changes[], notes} → new draft (drafter),
                                        or {new_tree: {...}, changes[], notes}
                                        → new-tree draft (owner of org)
PUT    /changesets/{cs}                 replace a draft's changes, notes and base_rev (If-Match)
GET    /changesets/{cs}                 a changeset's atomic changes, plus validation results if a draft
POST   /changesets/{cs}/publish {notes} approver; draft → new tree revision (If-Match)
DELETE /changesets/{cs}                 discard a draft (kept, with state "discarded")

# WoRMS lookups (server-side cache; the browser never calls WoRMS directly)
GET    /worms/search?name=              candidate WoRMS records
GET    /worms/{aphia_id}                the WoRMS record alone
GET    /worms/{aphia_id}/lineage        the record's WoRMS ancestors, top-level first
GET    /worms/{a}/between/{b}           all records on the lineage path between a and b, inclusive.
                                        400 unless one is an ancestor of the other.
GET    /worms/{a}/common_ancestor/{b}   the nearest common WoRMS ancestor of a and b, inclusive:
                                        if a is an ancestor of b, a is returned, and vice versa

# Aliases (direct, no changeset)
GET    /nodes/{id}/aliases?history=     current aliases; history=true includes removed ones,
                                        each with added_by/at and removed_by/at
POST   /nodes/{id}/aliases {alias}      add one alias (drafter)
DELETE /nodes/{id}/aliases/{alias_id}   remove one alias (drafter); the row is kept, marked removed

# Descriptions (direct, no changeset)
GET    /nodes/{id}/description?history= current description; history=true lists every entry,
                                        newest first, each with added_by/at
PUT    /nodes/{id}/description {description}
                                        set the description (drafter); "" clears it.
                                        Earlier entries are kept

# Organization members
GET    /orgs/{org}/members              members with their roles (reader)
POST   /orgs/{org}/members {username, role}
                                        add a user (owner); 409 already_member if they are one
PUT    /orgs/{org}/members/{username} {role}
                                        set a user's role (owner);
                                        409 last_owner if it would leave no owner
DELETE /orgs/{org}/members/{username}   remove a member (owner); 409 last_owner as above
```

WoRMS jobs and the warnings report are [under `/worms`](#worms-jobs-and-warnings).

`changes[]` holds [change records](backend.md#change-records). Merge, split,
import and "Add from WoRMS" have no endpoints of their own: the browser expands
them into groups of atomic changes ([webapp.md](webapp.md#merge-and-split)).

Alias ids for `DELETE` come from a detailed node's `aliases` or from
`GET /nodes/{id}/aliases`.

### WoRMS jobs and warnings

Anything that fetches from WoRMS in bulk is an asynchronous
[job](worms.md#worms-jobs-and-syncs). Jobs aren't tree content, and a full
cache sync spans every tree, so they live under `/worms` with the tree as a
parameter. A fetch job only fills the cache, so it belongs to an organization
rather than a tree, and also serves new-tree drafts.

```
POST   /worms/jobs                      start a job; 202 Accepted with its status
         {kind: "fetch", org, aphia_ids[]}        cache the given AphiaIDs not yet cached (drafter)
         {kind: "sync_new" | "sync_tree", tree, aphia_ids?}
                                                  sync the tree (drafter, approver, admin);
                                                  409 sync_in_progress if one overlaps
         {kind: "sync_all", aphia_ids?}           sync every tree (superuser)
GET    /worms/jobs/{job}                a job's status
GET    /worms/jobs?tree=                the tree's active sync, if any, and its last finished one;
                                        without tree, the active and last sync_all
GET    /worms/warnings?tree=            nodes in the latest revision that currently have WoRMS warnings
```

`aphia_ids` on a sync restricts its fetching to those AphiaIDs, to try failed
ones again; the whole tree is still re-checked. A job's status:

```
{id: "8b0f...", kind: "sync_tree", tree: "NES2022_taxonomy", org: null,   # org: fetch jobs
 started_by: "curator1", started_at: "...", finished_at: null,
 state: "running",                       # running | finished | interrupted
 total: 175, done: 120,
 retrying: [{aphia_id: 149122, attempt: 2, retries: 4, wait_until: "..."}],
 paused: null,                           # or {reason: "worms_rate_limited", until: "..."}
 failed: [{aphia_id: 148985, reason: "worms_unreachable", detail: "..."}],
 aphia_ids: null,                        # the AphiaIDs asked for, if any
 checked: []}                            # syncs, once finished: [{tree, rev, rows_added}]
```

### Draft edits and publishing

Any drafter may update any draft, so `GET /changesets/{cs}` returns an `ETag`,
and `PUT` and `publish` must send it back as `If-Match`. If the draft changed
in the meantime, the API returns `412` and the client re-fetches. For
`publish`, this also guarantees the approver publishes exactly what they
reviewed.

`POST /changesets/{cs}/publish` takes an optional `{notes}` from the approver.
These become the revision's `notes`; if omitted, the changeset's own notes
(written by the drafter) are used. On success it returns `201` with the new
revision, in the same shape as `GET /trees/{tree}?rev={r}`. The draft's
`base_rev` must be the latest revision; a draft that has fallen behind is
rebased with a `PUT` that sets `base_rev` to the latest revision. While one
publish on a tree is running, other publishes on that tree get `409`
`publish_in_progress` at once.

### Example: validate

`validate` checks a change list against the latest revision without saving
anything and without calling WoRMS; for a draft behind the latest revision,
the result shows what publishing after a rebase would do. A blocked `publish` returns the same body ([Errors](#errors-and-status-codes)).

```
POST /changesets/validate
{tree: "taxonomy", base_rev: 37,
 changes: [
   {op: "add",  node: "new:1", label: "Chaetoceros_curvisetus", parent: 402, aphia_id: 149122},
   {op: "edit", node: 431, label: "Chaetoceros_didymus_sl"},
   {op: "move", node: 433, from_parent: 431, to_parent: 30},
   {op: "add",  node: "new:2", label: "Chaetoceros", parent: 30}
 ]}
```

```
{tree: "taxonomy", base_rev: 37, latest_rev: 42,
 ok: false,
 errors: [
   {seq: 4, error: "label_in_use", node: "new:2",
    detail: "Label Chaetoceros is already used by node 402."}
 ],
 conflicts: [
   {error: "stale_base", detail: "Base revision 37 is behind latest revision 42.",
    nodes: [{node: 402, base_version: 6, latest_version: 7, detail: "Changed in revision 38."}]}
 ],
 warnings: [
   {seq: 1, warning: "duplicate_aphia", node: "new:1",
    detail: "Node 431 has the same AphiaID 149122."}
 ],
 warning_changes: [
   {node: 431, added: ["duplicate_aphia"], removed: []}
 ],
 version_changes: [
   {node: 402, from: 7, to: 8}, {node: "new:1", from: null, to: 1},
   {node: 431, from: 3, to: 4}, {node: 433, from: 1, to: 2},
   {node: 30, from: 9, to: 10}
 ],
 reduced_changes: [
   {seq: 1, op: "add", node: "new:1", ..., sources: [1]}, ...
 ],
 node_changes: [
   {node: 431, from: 3, to: 4, fields: {label: ["Chaetoceros_didymus", "Chaetoceros_didymus_sl"]},
    children_gained: [], children_lost: [433], seqs: [2, 3], groups: []}, ...
 ],
 unchecked: [],
 worms_missing: [],
 worms: "ok"}
```

- `ok` is true when there are no `errors` and `base_rev` is the latest
  revision. Warnings never block.
- `errors` are [structural errors](webapp.md#changesets-and-concurrency), each
  tied to the change (`seq`) that fails. Later changes are still checked
  against the state the earlier valid ones leave.
- `conflicts` reports `stale_base` when `base_rev` is behind the latest
  revision; the draft must be rebased before publishing. Its `nodes` list the
  touched nodes that later revisions changed, to help with the rebase. Here 402
  gains a child (change 1) but changed after revision 37.
- `reduced_changes` is the change list as saving would store it, after
  [reduction](backend.md#reduction-on-save). Each carries `sources`, the
  positions in the submitted `changes` it was built from, so a client can show
  errors and groups against the list the user composed. Errors' `seq` refer to
  `reduced_changes`.
- `node_changes` is the net change of each affected node, from the revision
  the changes were checked against (the latest) to the result: changed `fields` as `[old, new]`, children gained and
  lost, `successors` if deprecated, the `seqs` that touch it and the `groups`
  of their sources. It doesn't depend on the order of the changes.
- `warnings` are the [WoRMS warnings](worms.md#the-warnings) the changes would
  cause. `warning_changes` covers existing nodes whose current warnings would
  change, here 431, which now shares its AphiaID.
- `version_changes` has the same meaning as in a
  [revision's changes](#history). 431 is renamed and loses its child, and
  increases once.
- WoRMS checks use cached records only. `worms_missing` lists AphiaIDs the
  checks need that aren't cached, and `unchecked` the changes whose checks
  couldn't run because of them; `worms` is then `unavailable`. A
  [fetch job](#worms-jobs-and-warnings) for `worms_missing` followed by another
  `validate` fills them in. Publishing is allowed either way.

## Caching

The versioned content of a response pinned with `?rev=` never changes.
Descriptions, aliases and warnings are always current, so they can differ
between two fetches of the same `?rev=`.

Responses for "latest" (no `?rev=`) include two headers:

- `X-Tree-Revision`: the revision the response was built from. Pin follow-up
  calls to it with `?rev=`, so that e.g. a label lookup and its descendants
  can't come from different revisions if a publish happens in between.
- `ETag`: a fingerprint of the response. Send it back as `If-None-Match` to get
  `304 Not Modified` if nothing changed. It covers descriptions, aliases and
  warnings too,
  so it is a hash of the response, not just the revision number.

Consumers poll `GET /trees/{tree}` to see whether the revision has moved.

## Errors and status codes

Errors have one body shape:

```
{status: 404, error: "not_found", detail: "Node 9999 does not exist."}
```

| Status | When |
|---|---|
| `200` | Success. A deprecated node requested at a later revision is a `200` with its [deprecation record](#deprecated-nodes), not an error. Also: description set. |
| `201` | Created: new draft, published revision, added alias. |
| `202` | Accepted: WoRMS job started. |
| `204` | No content: draft discarded, alias removed. |
| `304` | Not modified, after `If-None-Match` ([Caching](#caching)). |
| `400` | Bad parameter, e.g. `?rev` outside a version's range on `/versions/{v}`, or `between` on records where neither is an ancestor of the other. |
| `401` | Not authenticated, on an endpoint that needs a login. |
| `403` | Authenticated, but the user's role in the tree's organization is too low, or not a site admin for `sync_all`. |
| `404` | Unknown tree, node, label, changeset or AphiaID. Also a node that didn't exist yet at `?rev`, or a `?rev` later than the tree's latest. |
| `409` | Publish blocked by `stale_base`, or refused with `publish_in_progress` while another publish on the tree runs. Also: updating or publishing a changeset that isn't a draft, publishing a new-tree changeset whose tree id exists (`tree_exists`), adding an alias the node already has or adding one to a deprecated node, setting the description of a deprecated node, or starting a sync that overlaps an active one (`sync_in_progress`), or removing or demoting an organization's last owner (`last_owner`), or adding an existing member (`already_member`). |
| `412` | `If-Match` didn't match: the draft changed since it was fetched. |
| `422` | Request body invalid, or publish blocked by structural errors. |
| `428` | `If-Match` missing on `PUT` or `publish` of a changeset. |
| `503` | WoRMS failed and the record isn't cached (WoRMS lookup endpoints only); `error` is `worms_unreachable`, `worms_rate_limited` or `worms_error`. |

A blocked publish (`409` or `422`) adds `validation`, holding the full
[validate response](#example-validate), to the error body.

## Pagination and limits

Most responses are bounded by the size of one tree (a few thousand nodes) and
are returned whole. Long, growing lists are paginated with `?limit=&offset=`
and add `count` (the total) to the response.

| Endpoint | Behaviour |
|---|---|
| `GET /trees/{tree}/search?q=` | `limit`, default 20, max 100. No `offset`: it's a typeahead. |
| `GET /trees/{tree}/revisions` | paginated; default `limit` 100 |
| `GET /changesets` | paginated; default `limit` 100 |
| `GET /nodes/{id}/warning_history` | paginated; default `limit` 100 |
| `GET /nodes/{id}/aliases?history=true` | paginated; default `limit` 100 |
| `GET /nodes/{id}/description?history=true` | paginated; default `limit` 100 |
| `GET /worms/warnings?tree=` | paginated; default `limit` 100 |
| `GET /worms/search` | `limit`, default 20, max 100 |
| Everything else | whole response. Use `?depth=` to limit `descendants` and `nodes_as_tree`. |

## Consumer guide

A ROI annotation should store `(node_id, tree_rev)`. The node version follows
from those two values, and the revision also captures the hierarchy at that
moment. Storing `(node_id, node_version)` is supported too. Never store labels
or aliases: [labels can be reused](backend.md#labels-aliases-and-descriptions).

![Consumer lookups](diagrams/05-consumer-lookups.png)

The diagram follows roi-db as the tree changes underneath it. Its calls are
anonymous reads.

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
