# Spec Delta

## Purpose

Exposes changeset drafting, checking and publishing over HTTP, so the web app
and scripts can propose tree edits, see their effects before publishing, and
publish exactly what was reviewed.

## ADDED Requirements

### Requirement: Validate without side effects
`POST /trees/{tree}/validate` with `{base_rev, changes[]}` SHALL reduce and
check the changes against the tree's latest revision without storing anything
and without calling WoRMS, and return `{tree, base_rev, latest_rev, ok, errors,
conflicts, reduced_changes, version_changes, node_changes, warnings,
warning_changes, unchecked, worms_missing, worms}`.

#### Scenario: Errors and warnings
- **WHEN** a change list adds a label already in use and a node with a duplicate AphiaID whose record is cached
- **THEN** `errors` holds `label_in_use` for that change, `warnings` holds `duplicate_aphia`, and nothing is saved

#### Scenario: Version preview
- **WHEN** a change list renames node 431 and moves its only child elsewhere
- **THEN** `version_changes` lists 431 once, and both the child and its new parent

### Requirement: Validate result semantics
`ok` SHALL be true only when there are no `errors` and `base_rev` equals the
latest revision. `conflicts` SHALL list `stale_base` when `base_rev` is behind,
with the nodes the changes touch that later revisions changed. Errors SHALL
refer to positions in `reduced_changes`. Warnings SHALL never make `ok` false.

#### Scenario: Behind but clean
- **WHEN** a change list with no errors is validated with `base_rev` 37 while the latest revision is 42
- **THEN** `ok` is false and `conflicts` reports `stale_base`, naming the touched nodes that changed in revisions 38 to 42

### Requirement: Change provenance
Each entry of `reduced_changes` SHALL carry `sources`, the positions (1-based)
in the submitted `changes` that it was built from, so clients can show errors
and groups against the list the user composed.

#### Scenario: Add folded with a later edit
- **WHEN** change 1 adds `new:1` in group `split#1` and change 6 renames `new:1` without a group
- **THEN** the reduced `add` of `new:1` has `sources` `[1, 6]`

#### Scenario: Label swap kept apart
- **WHEN** node A is renamed to a temporary label, node B takes A's old label, and A takes B's old label
- **THEN** `reduced_changes` holds three edits whose `sources` are `[1]`, `[2]` and `[3]`

### Requirement: Net changes per node
`node_changes` SHALL list, for each node whose content, parent, children or
deprecation differs between the base revision and the state the changes leave,
its version `from` and `to`, the fields that changed with their old and new
values, the children it gains and loses, its successors if deprecated, the
positions in `reduced_changes` that changed it, and the groups of those
changes' `sources`. It SHALL depend only on the base and final states, not on
the order of the changes.

#### Scenario: Split
- **WHEN** a change list splits A into new nodes A1 and A2 under parent P, as group `split#1`
- **THEN** `node_changes` lists A as deprecated with successors A1 and A2, A1 and A2 as new with their children, and P gaining A1 and A2, each tagged `split#1`

#### Scenario: Temporary label hidden
- **WHEN** a change list swaps the labels of A and B through a temporary label
- **THEN** `node_changes` shows A's label from its old to its new value, with no temporary label

### Requirement: WoRMS warnings in validate
`validate` SHALL check placement against cached WoRMS records only.
`warnings` SHALL list each warning a reduced change causes as `{seq, warning,
node, detail}`. `warning_changes` SHALL list existing nodes whose current
warnings would change, with the warnings added and removed.

#### Scenario: Warning change on an existing node
- **WHEN** a change list adds a node with the cached AphiaID of existing node 431
- **THEN** `warnings` holds `duplicate_aphia` for the `add`, and `warning_changes` lists 431 with `duplicate_aphia` added

### Requirement: Uncached records in validate
`worms_missing` SHALL list the AphiaIDs the checks need whose records are not
cached, and `unchecked` the positions in `reduced_changes` whose checks could
not run because of them. `worms` SHALL be `ok` when `unchecked` is empty and
`unavailable` otherwise.

#### Scenario: New AphiaID not cached
- **WHEN** a change list adds a node with AphiaID 149122, which is not cached
- **THEN** `worms_missing` holds 149122, that `add` is in `unchecked`, `worms` is `unavailable`, and WoRMS is not called

#### Scenario: After fetching
- **WHEN** the same list is validated after a fetch job cached 149122
- **THEN** `worms_missing` and `unchecked` are empty and `worms` is `ok`

### Requirement: Create and list changesets
`POST /trees/{tree}/changesets` with `{base_rev, changes[], notes}` SHALL save a
new draft, reducing its changes, and return `201` with it. Saving SHALL store
only the reduced changes, SHALL succeed even when the changes have structural
errors, and SHALL NOT call WoRMS.
`GET /trees/{tree}/changesets?state=` SHALL list the tree's changesets filtered
by state, paginated. A new-tree changeset SHALL be created at `POST
/changesets` with `{new_tree: {id, title, description}, changes[], notes}`.

#### Scenario: New draft
- **WHEN** a drafter posts a draft with two renames of the same node
- **THEN** the API returns `201` and the stored draft holds one rename

#### Scenario: Draft with errors
- **WHEN** a drafter saves a draft containing a cycle
- **THEN** the API returns `201` and the draft's validation reports `cycle`

#### Scenario: Drafts awaiting approval
- **WHEN** an approver requests `changesets?state=draft`
- **THEN** every open draft of the tree is listed with its author, `base_rev` and change count

### Requirement: Get a changeset
`GET /changesets/{cs}` SHALL return the changeset's state, `base_rev`, author,
notes and changes, plus, if it is a draft, its validation result computed as
`validate` would for its stored changes, and an `ETag` identifying the draft's
current content.

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
