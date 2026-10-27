# Spec Delta

## Purpose

Adds the description write and history endpoints to node descriptions.

## ADDED Requirements

### Requirement: Set a description
`PUT /nodes/{id}/description` with `{description}` SHALL add a description
entry to the node, outside any changeset, recording the authenticated user and
the time, and return `200` with the node's current description. An empty string
SHALL clear the description. Setting a description on a deprecated node SHALL
return `409`.

#### Scenario: Description set
- **WHEN** a drafter sets node L's description to `Cells with a bleb`
- **THEN** the API returns `200` and node L's description is `Cells with a bleb` immediately, with no new revision

#### Scenario: Description cleared
- **WHEN** a drafter sets node L's description to `""`
- **THEN** node L's description is `""` and its earlier entries are kept

### Requirement: Description history
`GET /nodes/{id}/description?history=true` SHALL list the node's description
entries, newest first, each with `description`, `added_by` and `added_at`, and
SHALL be paginated. Without `history`, it SHALL return the current description.

#### Scenario: History after two edits
- **WHEN** a node's description was set twice
- **THEN** the history lists both entries, newest first
