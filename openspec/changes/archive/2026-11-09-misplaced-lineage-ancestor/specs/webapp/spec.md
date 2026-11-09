# Spec Delta

## ADDED Requirements

### Requirement: Quick add cross-node updates
The Quick add page SHALL have an "Allow updates to other nodes" toggle, off
when the page opens, sent as `allow_cross_node_updates`. A
`misplaced_lineage_ancestor` issue's option SHALL turn it on and preview again. The
preview SHALL list the plan's moves, and the published message SHALL list the
nodes moved.

#### Scenario: Option turns the toggle on
- **WHEN** the preview has a `misplaced_lineage_ancestor` issue and the user clicks its option
- **THEN** the toggle is on and a new preview lists the nodes that will move under the new node

#### Scenario: Published with moves
- **WHEN** the user confirms a preview that moves `Chaetoceros`
- **THEN** the page says the node was added and that `Chaetoceros` was moved under it

#### Scenario: Warning in the tree editor
- **WHEN** a draft in the tree editor adds `Chaetocerotaceae` beside `Chaetoceros` and is validated
- **THEN** the validation's WoRMS warnings list `misplaced_lineage_ancestor` on `Chaetoceros`
