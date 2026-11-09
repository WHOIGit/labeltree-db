# node-aliases Specification

## Purpose

Defines node aliases: unversioned free-text search aids attached to a node, kept
with their add and remove history, and always shown in their current state.

## Requirements

### Requirement: Aliases are free text attached to a node
A node SHALL have zero or more aliases, each a free-text string with no type,
attached to the node rather than to a node version. Alias strings SHALL be
unique per node among its current aliases and SHALL NOT need to be unique
across nodes.

#### Scenario: Same alias on two nodes
- **WHEN** two nodes each have the alias `flagellate`
- **THEN** both aliases are stored

### Requirement: Aliases are unversioned and kept when removed
Adding or removing an alias SHALL NOT create a node version or a tree revision.
Each alias SHALL record who added it and when; removing it SHALL record who
removed it and when, and SHALL keep the alias row.

#### Scenario: Removed alias history
- **WHEN** an alias is removed from a node
- **THEN** it no longer appears among the node's current aliases, and its record keeps `added_by`, `added_at`, `removed_by` and `removed_at`

### Requirement: Initial aliases from add changes
Aliases carried on an `add` change SHALL become current aliases of the new node
when the changeset is published, recorded as added by the changeset's author at
the publish time.

#### Scenario: Imported aliases
- **WHEN** an imported node carries `aliases: ["Chaetoceros didymus"]` and its changeset is published
- **THEN** the new node has current alias `Chaetoceros didymus`, added by the changeset's author

### Requirement: Aliases are always current in reads
Every read that returns aliases SHALL return the node's current aliases, even
when a past revision is requested.

#### Scenario: Alias added after a revision
- **WHEN** an alias is added after revision 4 and the node is read at `?rev=4`
- **THEN** the alias is included

### Requirement: Add an alias
`POST /nodes/{id}/aliases` with `{alias}` SHALL add one current alias to the
node, outside any changeset, and return `201` with `{id, alias}`. Adding an
alias the node already has as a current alias, or adding one to a deprecated
node, SHALL return `409`.

#### Scenario: Add a legacy string
- **WHEN** a drafter adds alias `L1` to node L
- **THEN** the API returns `201` and node L's current aliases include `L1` immediately, with no new revision

#### Scenario: Duplicate alias
- **WHEN** a drafter adds alias `L1` to a node that already has it
- **THEN** the API returns `409`

### Requirement: Remove an alias
`DELETE /nodes/{id}/aliases/{alias_id}` SHALL mark the alias removed, recording
who and when, keep the row, and return `204`.

#### Scenario: Remove
- **WHEN** a drafter removes alias 88 from node 431
- **THEN** the API returns `204` and alias 88 no longer appears on node 431

### Requirement: List aliases with history
`GET /nodes/{id}/aliases` SHALL return the node's current aliases.
`?history=true` SHALL also include removed ones, each with `added_by`,
`added_at`, `removed_by` and `removed_at`, paginated.

#### Scenario: History
- **WHEN** a node had alias `L1` removed and has alias `L2`
- **THEN** `aliases?history=true` lists both, with `L1` carrying its removal fields
