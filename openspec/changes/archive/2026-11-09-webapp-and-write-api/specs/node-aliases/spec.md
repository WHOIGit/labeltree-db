# Spec Delta

## ADDED Requirements

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
