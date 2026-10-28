# Spec Delta

## Purpose

Checks the placement of nodes that carry an AphiaID against WoRMS and records
any disagreement as a warning, so differences between the owned tree and WoRMS
are visible without ever blocking edits or changing node versions.

## ADDED Requirements

### Requirement: Anchored nodes and unanchored pass-through
A node SHALL be anchored if it has an `aphia_id`. Placement checks SHALL treat
unanchored nodes as if they were absent when looking for a node's nearest
anchored ancestor. A node with no anchored ancestor SHALL get no
`out_of_lineage` check.

#### Scenario: Morphotype in between
- **WHEN** an anchored species sits under unanchored `Chaetoceros_morphotype1`, which sits under anchored `Chaetoceros`
- **THEN** the species' nearest anchored ancestor is `Chaetoceros`

### Requirement: out_of_lineage warning
An anchored node SHALL get `out_of_lineage` when its nearest anchored
ancestor's AphiaID is not in the node's WoRMS lineage. If that ancestor's
AphiaID is unaccepted, its `valid_AphiaID` SHALL be compared instead.

#### Scenario: Genus under the wrong class
- **WHEN** `Chaetoceros` is placed under `Dinophyceae`
- **THEN** `Chaetoceros` gets `out_of_lineage` with a detail naming `Dinophyceae`

#### Scenario: Rank inversion
- **WHEN** a genus is placed under one of its own species
- **THEN** the genus gets `out_of_lineage`

#### Scenario: Ancestor is a synonym
- **WHEN** the nearest anchored ancestor has an unaccepted AphiaID whose `valid_AphiaID` is in the node's lineage
- **THEN** the node gets no `out_of_lineage`

### Requirement: unaccepted_aphia warning
An anchored node SHALL get `unaccepted_aphia` when WoRMS marks its AphiaID as
unaccepted, that is, its `valid_AphiaID` is a different AphiaID, whatever its
status (e.g. `unaccepted`, `superseded combination`, `junior subjective
synonym`, or `unassessed` with an accepted name given). A record whose
`valid_AphiaID` is its own AphiaID SHALL NOT get it. The warning detail SHALL
suggest the accepted AphiaID.

#### Scenario: Name became a synonym
- **WHEN** a node's AphiaID is now unaccepted with `valid_AphiaID` 149120
- **THEN** the node gets `unaccepted_aphia` suggesting 149120

#### Scenario: Unassessed name
- **WHEN** a node's AphiaID has status `unassessed` and is its own `valid_AphiaID`
- **THEN** the node gets no `unaccepted_aphia`

#### Scenario: Unassessed name with an accepted name
- **WHEN** a node's AphiaID has status `unassessed` and `valid_AphiaID` 149114
- **THEN** the node gets `unaccepted_aphia` suggesting 149114

### Requirement: unknown_aphia warning
An anchored node SHALL get `unknown_aphia` when WoRMS reports no record for its
AphiaID. Such a node SHALL get no other WoRMS warning except `duplicate_aphia`,
and its `worms_data` SHALL be `null`. Being unreachable is not the same: a
WoRMS outage SHALL make the checks unavailable instead.

#### Scenario: AphiaID not in WoRMS
- **WHEN** a node has AphiaID 999999999 and WoRMS answers that it has no such record
- **THEN** the node gets `unknown_aphia`

### Requirement: duplicate_aphia warning
An anchored node SHALL get `duplicate_aphia` when another node in the same tree
and revision has the same AphiaID. Nodes in different trees sharing an AphiaID
SHALL NOT get it.

#### Scenario: Same species twice
- **WHEN** two nodes in one tree both have AphiaID 149122
- **THEN** both get `duplicate_aphia`, each naming the other

### Requirement: Recheck scope of an edit
A change SHALL recheck the node it changes, the first anchored node on each path
below it, and every other node in the tree with an AphiaID it had or now has.
Ancestors SHALL NOT be rechecked.

#### Scenario: Moving an unanchored node
- **WHEN** an unanchored node with anchored children is moved
- **THEN** the anchored children are rechecked and their grandchildren are not

#### Scenario: Removing a duplicate
- **WHEN** one of two nodes sharing an AphiaID has its AphiaID cleared
- **THEN** the other node is rechecked and loses `duplicate_aphia`

### Requirement: Checks run on save and publish
Placement checks SHALL run when a changeset is saved and again when it is
published. Each change SHALL store the warnings it would cause as `checks`, a
list of `{warning, node, detail}`.

#### Scenario: Saved draft
- **WHEN** a draft adds a node with an AphiaID already used in the tree
- **THEN** that `add` change's `checks` hold `duplicate_aphia`

### Requirement: Warnings never block or bump
WoRMS warnings SHALL NOT block publishing and SHALL NOT change node versions.

#### Scenario: Publish with warnings
- **WHEN** a changeset whose changes cause `out_of_lineage` is published
- **THEN** the revision is created and only the nodes the changes touch structurally get new versions

### Requirement: WoRMS unreachable
If WoRMS cannot be reached and the needed records are not cached, the affected
changes SHALL record `checks: "unavailable"`, and saving and publishing SHALL
still be allowed. A later drift run SHALL fill in the missing warnings.

#### Scenario: Publish during an outage
- **WHEN** a changeset adds a node with an uncached AphiaID while WoRMS is down
- **THEN** the change records `unavailable`, the publish succeeds, and the node's `worms_data` is null until the record is fetched

### Requirement: Warning history storage
Each node SHALL have a warning history of rows `{computed_at, warnings}`. A
publish or drift run SHALL add a row only when a node's warnings differ from its
newest row, including an empty list when they clear. The newest row SHALL be the
node's current warnings.

#### Scenario: Warnings clear
- **WHEN** a node with `out_of_lineage` is moved to a correct parent and published
- **THEN** a row with an empty warning list is added and its current warnings are empty

#### Scenario: Quiet re-check
- **WHEN** a node's warnings are recomputed and unchanged
- **THEN** no row is added
