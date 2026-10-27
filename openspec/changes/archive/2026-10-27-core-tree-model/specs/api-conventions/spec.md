# Spec Delta

## Purpose

Defines the conventions shared by every REST endpoint: base path, revision
selection, response shape options, error bodies and status codes, caching
headers and pagination.

## ADDED Requirements

### Requirement: Base path and pull model
The REST API SHALL be served under `/api/v1` and SHALL be pull-only: the
service SHALL NOT push notifications or events to consumers.

#### Scenario: Endpoint location
- **WHEN** a client requests `GET /api/v1/trees`
- **THEN** it receives the list of trees

### Requirement: Revision selection with ?rev
Endpoints that accept `?rev=N` SHALL answer as of revision N of the relevant
tree, and SHALL use the tree's latest revision when `?rev` is omitted. A `?rev`
later than the tree's latest revision or below 1 SHALL return `404`.

#### Scenario: Future revision
- **WHEN** a client requests `?rev=50` on a tree whose latest revision is 42
- **THEN** the API returns `404`

### Requirement: Stable response shapes and ?dropempty
Every node in a response SHALL include all fields of its shape, even when null
or empty. With `?dropempty=true`, fields that are null, empty strings or empty
lists SHALL be omitted.

#### Scenario: Empty description
- **WHEN** a node with an empty description is fetched without `?dropempty`
- **THEN** the response includes `description: ""`

#### Scenario: Dropping empties
- **WHEN** the same node is fetched with `?dropempty=true`
- **THEN** the response has no `description` key

### Requirement: Error body
Every error response SHALL have the body `{status, error, detail}`, where
`error` is a machine-readable code and `detail` a human-readable message.

#### Scenario: Unknown node
- **WHEN** a client requests `GET /api/v1/nodes/9999` and no such node exists
- **THEN** the API returns `404` with `{status: 404, error: "not_found", detail: "Node 9999 does not exist."}`

### Requirement: Read status codes
Read endpoints SHALL return `200` on success, including a deprecation record for
a node deprecated by the requested revision; `304` after a matching
`If-None-Match`; `400` for a bad parameter; and `404` for an unknown tree,
node or label, a node that did not yet exist at `?rev`, or an out-of-range
`?rev`.

#### Scenario: Bad parameter
- **WHEN** a client requests `descendants?depth=-1`
- **THEN** the API returns `400`

### Requirement: Revision header on latest responses
A response built from a tree's latest revision because `?rev` was omitted SHALL
include `X-Tree-Revision` naming that revision, so follow-up calls can pin to
it.

#### Scenario: Pinning follow-up calls
- **WHEN** a client requests `GET /api/v1/trees/T/nodes/L2` without `?rev` while the latest revision is 42
- **THEN** the response carries `X-Tree-Revision: 42`

### Requirement: Conditional GET with ETag
Every successful read response SHALL include an `ETag` that fingerprints the
whole response body, including descriptions, aliases and warnings. A request whose
`If-None-Match` matches the current `ETag` SHALL receive `304 Not Modified`.

#### Scenario: Nothing changed
- **WHEN** a client repeats a request with `If-None-Match` set to the `ETag` it received and nothing changed
- **THEN** the API returns `304` with no body

#### Scenario: Alias changed
- **WHEN** an alias was added to a node in the response since the `ETag` was issued
- **THEN** the API returns `200` with a new `ETag`

### Requirement: Pagination of long lists
Lists that grow over time SHALL be paginated with `?limit=&offset=` and SHALL
include `count`, the total number of items. Responses bounded by the size of one
tree SHALL be returned whole.

#### Scenario: Revision history page
- **WHEN** a client requests `GET /api/v1/trees/T/revisions?limit=10&offset=10` on a tree with 42 revisions
- **THEN** it receives revisions 32 down to 23 and `count: 42`
