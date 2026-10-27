# Spec Delta

## Purpose

Defines the `/nodes/{id}` read endpoints that consumers use to resolve a stored
node id, at the latest or any past revision, into its data, its place in the
tree and its version history.

## ADDED Requirements

### Requirement: Lite node shape
Wherever nodes are listed or nested (children, descendants, ancestors, a
detailed node's parent), they SHALL use the lite shape
`{id, label, version, num_children, children}`. `children` SHALL be a list of
lite nodes if the node was expanded and `null` if not; an expanded leaf SHALL
have `children: []`.

#### Scenario: Leaf versus unexpanded
- **WHEN** a lite node has `num_children: 0` and `children: null`
- **THEN** the client can tell it is a leaf that was not expanded

### Requirement: Detailed node shape
A detailed node SHALL contain `id`, `version`, `tree`, `rev`, `label`,
`description`, `aliases` (current, each `{id, alias}`), `aphia_id`,
`worms_data`, `worms_warnings`, `tree_depth`, `num_children`, `parent` (lite,
unexpanded, or null), `children` (lite, unexpanded), `created_in_rev`,
`deprecated_in_rev` and `successors`.

#### Scenario: Top-level node
- **WHEN** a top-level node is fetched
- **THEN** its `parent` is null and its `tree_depth` is 0

#### Scenario: Lifetime fields describe the whole node
- **WHEN** a node deprecated in revision 37 is fetched at `?rev=30`
- **THEN** the response is the detailed node at revision 30 with `deprecated_in_rev: 37` and its successors

### Requirement: WoRMS fields before WoRMS integration
Until WoRMS integration exists, every detailed node SHALL return
`worms_data: null` and `worms_warnings: []`.

#### Scenario: Anchored node
- **WHEN** a node with `aphia_id` 149122 is fetched
- **THEN** it returns `aphia_id: 149122`, `worms_data: null` and `worms_warnings: []`

### Requirement: Get a node
`GET /nodes/{id}` SHALL return the detailed node at the requested revision of
its tree.

#### Scenario: Node at a past revision
- **WHEN** a client requests `GET /nodes/431?rev=3` and node 431 was renamed in revision 5
- **THEN** the response shows its label as of revision 3 and `rev: 3`

### Requirement: Deprecation record
When the requested node was deprecated at or before the requested revision,
node endpoints, including `/ancestors` and `/descendants`, SHALL return `200`
with the record `{id, tree, rev, label, last_version, deprecated_in_rev,
successors}`, where `label` is the label of its last version. A node not yet
created at the requested revision SHALL return `404`.

#### Scenario: Deprecated node
- **WHEN** a client requests `GET /nodes/812?rev=42` and node 812 was deprecated in revision 37
- **THEN** the API returns `200` with its deprecation record, including `successors: [1201, 1202]`

#### Scenario: Node not yet created
- **WHEN** a client requests `GET /nodes/1201?rev=10` and node 1201 was created in revision 37
- **THEN** the API returns `404`

### Requirement: Ancestors
`GET /nodes/{id}/ancestors` SHALL return `{tree, rev, node, ancestors}` where
`node` is the requested node and `ancestors` lists lite, unexpanded nodes from
the top-level node down to the immediate parent.

#### Scenario: Path to a species
- **WHEN** a client requests the ancestors of `Chaetoceros_didymus`
- **THEN** `ancestors` runs `Chromista`, `Bacillariophyceae`, `Chaetocerotaceae`, `Chaetoceros`

#### Scenario: Top-level node
- **WHEN** a client requests the ancestors of a top-level node
- **THEN** `ancestors` is empty

### Requirement: Descendants
`GET /nodes/{id}/descendants?depth=` SHALL return `{tree, rev, node}` where
`node` is the requested node as a lite node expanded down to `depth` levels
(default `all`). Nodes at the depth limit SHALL have `children: null`.

#### Scenario: Depth 1
- **WHEN** a client requests `descendants?depth=1` of a node whose children have children
- **THEN** the children are listed with `children: null` and grandchildren are absent

#### Scenario: Full subtree
- **WHEN** a client requests `descendants` with no depth
- **THEN** every descendant is included and every leaf has `children: []`

### Requirement: Version history
`GET /nodes/{id}/versions` SHALL return `{id, tree, created_in_rev,
deprecated_in_rev, versions}` listing each version with `valid_from_rev` and
`valid_to_rev` (null = current). It SHALL NOT accept `?rev`.

#### Scenario: Deprecated node history
- **WHEN** a client requests the versions of a node deprecated in revision 5 whose last version started at revision 3
- **THEN** its last version has `valid_from_rev: 3` and `valid_to_rev: 5`

### Requirement: Node at a given version
`GET /nodes/{id}/versions/{v}` SHALL return the detailed node at version `v`.
Its `?rev` SHALL pick the revision at which parent and children are shown, SHALL
default to the last revision in version `v`'s range, and SHALL return `400` if
outside that range.

#### Scenario: Rev outside the version's range
- **WHEN** version 2 of a node is valid for revisions 2-3 and a client requests `versions/2?rev=4`
- **THEN** the API returns `400`

#### Scenario: Children change within one version
- **WHEN** a node's child is renamed in revision 3 while the node stays at version 2
- **THEN** `versions/2?rev=2` and `versions/2?rev=3` show the child under its old and new labels
