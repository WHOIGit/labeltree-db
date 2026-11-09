# Spec Delta

## ADDED Requirements

### Requirement: misplaced_lineage_ancestor warning
An anchored node X SHALL get `misplaced_lineage_ancestor` for each AphiaID of its
WoRMS lineage that lies below its nearest anchored ancestor's AphiaID (anywhere
in the lineage if X has no anchored ancestor) and that another live node of the
tree has. A node whose AphiaID is unaccepted SHALL match through its cached
`valid_AphiaID`. The detail SHALL name that node. X SHALL get no such warning
while it has `out_of_lineage`.

#### Scenario: Family beside its genus
- **WHEN** `Bacillariophyceae` has the children `Chaetoceros` and `Chaetocerotaceae`, and `Chaetocerotaceae` is in the WoRMS lineage of `Chaetoceros`
- **THEN** `Chaetoceros` gets `misplaced_lineage_ancestor` naming `Chaetocerotaceae`, and `Chaetocerotaceae` gets no warning

#### Scenario: Ancestor elsewhere in the tree
- **WHEN** `Chaetoceros` is at the top level and `Bacillariophyceae`, in its lineage, is elsewhere in the tree
- **THEN** `Chaetoceros` gets `misplaced_lineage_ancestor` naming `Bacillariophyceae`

#### Scenario: Already under it
- **WHEN** `Chaetoceros` is under `Chaetocerotaceae`, which is under `Bacillariophyceae`
- **THEN** `Chaetoceros` gets no `misplaced_lineage_ancestor`

#### Scenario: Synonym node
- **WHEN** a node beside `Chaetoceros` has an unaccepted AphiaID whose cached `valid_AphiaID` is in the lineage of `Chaetoceros` below its anchored ancestor
- **THEN** `Chaetoceros` gets `misplaced_lineage_ancestor` naming that node

#### Scenario: Never blocks
- **WHEN** a changeset causes `misplaced_lineage_ancestor` and is published
- **THEN** the revision is created and the warning is recorded in the node's warning history

## MODIFIED Requirements

### Requirement: Recheck scope of an edit
A change SHALL recheck the node it changes, the first anchored node on each path
below it, every other node in the tree with an AphiaID it had or now has, and
every anchored node of the tree whose cached WoRMS lineage holds an AphiaID it
had or now has. Ancestors SHALL NOT be rechecked otherwise.

#### Scenario: Moving an unanchored node
- **WHEN** an unanchored node with anchored children is moved
- **THEN** the anchored children are rechecked and their grandchildren are not

#### Scenario: Removing a duplicate
- **WHEN** one of two nodes sharing an AphiaID has its AphiaID cleared
- **THEN** the other node is rechecked and loses `duplicate_aphia`

#### Scenario: Adding an ancestor taxon
- **WHEN** a change adds `Chaetocerotaceae` under `Bacillariophyceae`, beside `Chaetoceros`
- **THEN** `Chaetoceros` is rechecked and the `add` change's `checks` hold its `misplaced_lineage_ancestor`
