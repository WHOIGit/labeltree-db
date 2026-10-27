# Spec Delta

## Purpose

Defines the `/trees` read endpoints that consumers use to list trees, follow
their revision history, compare revisions, browse and export a whole revision,
and find nodes by label or by search.

## ADDED Requirements

### Requirement: List trees
`GET /trees` SHALL return `{trees: [...]}`, each with `id`, `title`,
`description`, `latest_rev`, `published_at` of the latest revision and
`num_nodes` at the latest revision.

#### Scenario: Two loaded trees
- **WHEN** `NES2022_tags` and `NES2022_taxonomy` are loaded
- **THEN** `GET /trees` lists both with their latest revisions and node counts

### Requirement: Tree summary and revision metadata
`GET /trees/{tree}?rev=` SHALL return the tree's `id`, `title`, `description`,
`rev`, `latest_rev`, the revision's `published_at`, `published_by`, `author`,
`notes` and `changeset`, and `num_nodes`, `num_top_level` and `max_depth` at
that revision.

#### Scenario: Polling for change
- **WHEN** a consumer requests `GET /trees/NES2022_tags` after a new revision is published
- **THEN** `latest_rev` and `rev` reflect the new revision

#### Scenario: Unknown tree
- **WHEN** a client requests `GET /trees/nope`
- **THEN** the API returns `404`

### Requirement: Revision history
`GET /trees/{tree}/revisions` SHALL list all revisions, newest first, each with
`rev`, `published_at`, `published_by`, `author`, `notes`, `changeset` and
`num_changes`. It SHALL NOT accept `?rev` and SHALL be paginated.

#### Scenario: History order
- **WHEN** a tree has revisions 1 to 3
- **THEN** the list starts with revision 3

### Requirement: Changes of a revision
`GET /trees/{tree}/revisions/{r}/changes` SHALL return `{tree, rev, notes,
changes, version_changes}` where `changes` are the published atomic changes in
`seq` order with `op`, `group` and their payload using real node ids, and
`version_changes` lists every node whose version changed.

#### Scenario: Revision 1 of an imported tree
- **WHEN** a client requests the changes of revision 1 of `NES2022_tags`
- **THEN** it receives 18 `add` changes in group `import#1` and 18 version changes with `from: null, to: 1`

### Requirement: Diff between revisions
`GET /trees/{tree}/diff?from=&to=` SHALL return `added` (lite nodes),
`deprecated` (`{id, label, deprecated_in_rev, successors}`), `moved` (`{id,
label, from_parent, to_parent}`) and `edited` (`{id, label, fields}` with only
differing fields as `[old, new]`), comparing each node at `from` with `to`.

#### Scenario: Rename appears as an edit
- **WHEN** a node was renamed between `from` and `to`
- **THEN** it appears in `edited` with `fields.label: [old, new]` and its `label` is the new one

#### Scenario: Moved and edited
- **WHEN** a node was both moved and edited in the range
- **THEN** it appears in both `moved` and `edited`

#### Scenario: Added then deprecated in range
- **WHEN** a node was added and later deprecated within the range
- **THEN** it appears in no list

#### Scenario: Added in range
- **WHEN** a node was added in the range and later edited in the range
- **THEN** it appears only in `added`, with its state at `to`

### Requirement: Whole tree as content nodes
`GET /trees/{tree}/nodes_as_tree?depth=` SHALL return `{tree, rev, nodes}`
holding the top-level nodes as nested content nodes `{id, label, version,
aphia_id, description, aliases, num_children, children}`, with aliases as plain
strings, expanded down to `depth` (default `all`).

#### Scenario: Re-importable output
- **WHEN** `nodes_as_tree?dropempty=true` is fetched
- **THEN** the response is valid as an import file

### Requirement: Nested export
`GET /trees/{tree}/export` SHALL return the whole tree at the revision as nested
detailed nodes. Each node's `parent` SHALL be omitted unless `?parents=true`.

#### Scenario: With parents
- **WHEN** a client requests `export?parents=true`
- **THEN** each node includes its lite `parent`

### Requirement: Flat CSV export
`GET /trees/{tree}/export_flat` SHALL return CSV with one row per node and the
columns `id, label, version, parent, children, tree_depth, description, aliases,
aphia_id, worms_scientificname, worms_rank, worms_status, worms_link,
worms_warnings, created_in_rev`, where `parent` and `children` are node ids and
list columns use `|` as separator.

#### Scenario: Children column
- **WHEN** node 402 has children 431 and 440
- **THEN** its row has `431|440` in the `children` column

### Requirement: Lookup by label
`GET /trees/{tree}/nodes/{label}` SHALL return the detailed node holding that
label at the requested revision, matching exactly and case-sensitively, and
`404` if no node holds it at that revision.

#### Scenario: Renamed label
- **WHEN** node L was renamed from `L1` to `L2` in revision R2
- **THEN** `nodes/L1` returns `404`, `nodes/L2` returns L, and `nodes/L1?rev=R1` returns L

### Requirement: Batch lookup by ids and labels
`GET /trees/{tree}/nodes?ids=&labels=` SHALL return detailed nodes in the order
given, ids first then labels. A deprecated id SHALL yield its deprecation
record; an unknown id or label, or an id from another tree, SHALL yield a
not-found entry without failing the request.

#### Scenario: Mixed batch
- **WHEN** a client requests `nodes?ids=431,812,9999&labels=Chaetoceros` where 812 is deprecated and 9999 unknown
- **THEN** the response lists node 431, the deprecation record of 812, a not-found entry for 9999 and the node labelled `Chaetoceros`, in that order

### Requirement: Search by text
`GET /trees/{tree}/search?q=` SHALL match labels and current aliases of nodes in
the revision, case-insensitively and treating `_` and space as equal, trying
exact, then prefix, then substring, then fuzzy matching and ranking earlier
methods first. `?method=` SHALL force one method. Results SHALL be lite nodes
with `path` and `matched_on`, limited by `?limit` (default 20, max 100).

#### Scenario: Prefix match
- **WHEN** a client searches `q=chaeto`
- **THEN** `Chaetoceros` is returned with `path` `Chromista/Bacillariophyceae/Chaetocerotaceae/Chaetoceros` and `matched_on: "label"`

#### Scenario: Alias match
- **WHEN** node L has alias `L1` and a client searches `q=L1`
- **THEN** L is returned with `matched_on: "alias"`

#### Scenario: Exact only
- **WHEN** a client searches `q=chaeto&method=exact`
- **THEN** no node is returned unless a label or alias equals `chaeto`

#### Scenario: Deprecated nodes excluded
- **WHEN** a node deprecated before the requested revision has a matching label
- **THEN** it is not returned

### Requirement: Search by AphiaID
`GET /trees/{tree}/search?aphia_id=` SHALL return every node in the revision
with that AphiaID, unranked.

#### Scenario: AphiaID lookup
- **WHEN** a client searches `aphia_id=148985`
- **THEN** the node `Chaetoceros` is returned
