# Spec Delta

## RENAMED Requirements

- FROM: `### Requirement: WoRMS unreachable`
- TO: `### Requirement: Records not cached`

## MODIFIED Requirements

### Requirement: Checks run on save and publish
Placement checks SHALL run on `validate`, when a changeset is saved and again
when it is published, using cached WoRMS records only. Each saved change SHALL
store the warnings it would cause as `checks`, a list of `{warning, node,
detail}`.

#### Scenario: Saved draft
- **WHEN** a draft adds a node with an AphiaID already used in the tree
- **THEN** that `add` change's `checks` hold `duplicate_aphia`

### Requirement: Records not cached
If a record the checks need is not cached, because it was never fetched or every
fetch of it failed, the affected changes SHALL record `checks: "unavailable"`,
and saving and publishing SHALL still be allowed. A later fetch or sync job
SHALL fill in the missing warnings.

#### Scenario: Publish during an outage
- **WHEN** a changeset that adds a node with an uncached AphiaID is published while WoRMS is down
- **THEN** the change records `unavailable`, the publish succeeds, and the node's `worms_data` is null until a sync fetches the record

### Requirement: Warning history storage
Each node SHALL have a warning history of rows `{computed_at, warnings}`. A
publish or sync SHALL add a row only when a node's warnings differ from its
newest row, including an empty list when they clear. The newest row SHALL be the
node's current warnings. A node whose warnings could not be computed, because a
record they need is not cached or failed to refresh in that sync, SHALL get
no row.

#### Scenario: Warnings clear
- **WHEN** a node with `out_of_lineage` is moved to a correct parent and published
- **THEN** a row with an empty warning list is added and its current warnings are empty

#### Scenario: Quiet re-check
- **WHEN** a node's warnings are recomputed and unchanged
- **THEN** no row is added

#### Scenario: Refresh failed
- **WHEN** a sync fails to refresh the record of a node's AphiaID after its retries
- **THEN** the node gets no warning-history row from that sync
