# Spec Delta

## Purpose

Exposes changeset drafting, checking and publishing over HTTP, so the web app
and scripts can propose tree edits, see their effects before publishing, and
publish exactly what was reviewed.

## ADDED Requirements

### Requirement: Validate without side effects
`POST /trees/{tree}/validate` with `{base_rev, changes[]}` SHALL reduce and
check the changes against the tree's latest revision without storing anything,
and return `{tree, base_rev, latest_rev, ok, errors, conflicts, warnings,
warning_changes, version_changes, reduced_changes, worms}`.

#### Scenario: Errors and warnings
- **WHEN** a change list adds a label already in use and a node with a duplicate AphiaID
- **THEN** `errors` holds `label_in_use` for that change, `warnings` holds `duplicate_aphia`, and nothing is saved

#### Scenario: Version preview
- **WHEN** a change list renames node 431 and moves its only child elsewhere
- **THEN** `version_changes` lists 431 once, and both the child and its new parent

### Requirement: Validate result semantics
`ok` SHALL be true only when there are no `errors` and `base_rev` equals the
latest revision. `conflicts` SHALL list `stale_base` when `base_rev` is behind,
with the nodes the changes touch that later revisions changed. `worms` SHALL be
`unavailable` when WoRMS checks could not run; warnings SHALL never make `ok`
false.

#### Scenario: Behind but clean
- **WHEN** a change list with no errors is validated with `base_rev` 37 while the latest revision is 42
- **THEN** `ok` is false and `conflicts` reports `stale_base`, naming the touched nodes that changed in revisions 38 to 42

### Requirement: Create and list changesets
`POST /trees/{tree}/changesets` with `{base_rev, changes[], notes}` SHALL save a
new draft, reducing its changes, and return `201` with it.
`GET /trees/{tree}/changesets?state=` SHALL list the tree's changesets filtered
by state, paginated. A new-tree changeset SHALL be created at `POST
/changesets` with `{new_tree: {id, title, description}, changes[], notes}`.

#### Scenario: New draft
- **WHEN** a drafter posts a draft with two renames of the same node
- **THEN** the API returns `201` and the stored draft holds one rename

#### Scenario: Drafts awaiting approval
- **WHEN** an approver requests `changesets?state=draft`
- **THEN** every open draft of the tree is listed with its author, `base_rev` and change count

### Requirement: Get a changeset
`GET /changesets/{cs}` SHALL return the changeset's state, `base_rev`, author,
notes and changes, plus the current validation result if it is a draft, and an
`ETag` identifying the draft's current content.

#### Scenario: Published changeset
- **WHEN** a published changeset is fetched
- **THEN** its changes use real node ids and no validation result is included

### Requirement: Update and rebase a draft
`PUT /changesets/{cs}` SHALL replace a draft's changes, notes and `base_rev`,
reducing the changes. Rebasing SHALL be a `PUT` that sets `base_rev` to the
latest revision. Updating a changeset that is not a draft SHALL return `409`.

#### Scenario: Rebase
- **WHEN** a draft behind the latest revision is updated with `base_rev` set to the latest revision
- **THEN** the draft is stored and its validation no longer reports `stale_base`

#### Scenario: Update a published changeset
- **WHEN** a client updates a published changeset
- **THEN** the API returns `409`

### Requirement: Optimistic concurrency on drafts
`PUT` and `publish` SHALL require `If-Match` with the draft's `ETag`. A missing
`If-Match` SHALL return `428`. A stale one SHALL return `412`, so the client
re-fetches and the approver publishes exactly what they reviewed.

#### Scenario: Concurrent edit
- **WHEN** drafter A fetches a draft, drafter B updates it, and A then sends `PUT` with the old `ETag`
- **THEN** A gets `412`

#### Scenario: Missing If-Match
- **WHEN** `publish` is called without `If-Match`
- **THEN** the API returns `428`

### Requirement: Publish a draft
`POST /changesets/{cs}/publish` with optional `{notes}` SHALL publish the draft.
Approver notes SHALL replace the drafter's notes as the revision's notes if
given. Success SHALL return `201` with the new revision in the shape of
`GET /trees/{tree}?rev=`.

#### Scenario: Publish with approver notes
- **WHEN** an approver publishes a clean, up-to-date draft with notes `"Split Thalassiosira"`
- **THEN** the API returns `201` with the new revision whose `notes` are `"Split Thalassiosira"`

### Requirement: Blocked publish
A publish blocked by `stale_base` SHALL return `409`; one blocked by structural
errors SHALL return `422`. Both SHALL include the full validate response as
`validation` in the error body. A publish refused because another publish on the
tree is in progress SHALL return `409` with error `publish_in_progress`. Publishing a changeset that is not a draft SHALL
return `409`.

#### Scenario: Stale draft
- **WHEN** a draft whose `base_rev` is behind is published
- **THEN** the API returns `409` with `validation.conflicts` reporting `stale_base`

#### Scenario: Structural error
- **WHEN** a draft containing a cycle is published
- **THEN** the API returns `422` with `validation.errors` holding `cycle`

#### Scenario: Publish in progress
- **WHEN** an approver publishes a draft while another publish on the same tree is running
- **THEN** the API returns `409` with error `publish_in_progress`

### Requirement: Discard a draft
`DELETE /changesets/{cs}` SHALL mark a draft `discarded`, keep it with its
changes frozen, and return `204`.

#### Scenario: Discarded draft is kept
- **WHEN** a draft is discarded and then fetched
- **THEN** it is returned with state `discarded`

### Requirement: Macros have no endpoints
Merge, split, import, clone and Add from WoRMS SHALL have no endpoints of their
own. Clients SHALL submit them as ordinary grouped changes.

#### Scenario: Submitting a split
- **WHEN** the web app saves a split
- **THEN** it sends `add`, `move` and `deprecate` changes sharing group `split#n` through the ordinary changeset endpoints
