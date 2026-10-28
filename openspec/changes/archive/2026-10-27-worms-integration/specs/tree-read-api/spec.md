# Spec Delta

## ADDED Requirements

### Requirement: Search matches WoRMS names
Text search SHALL also match the cached WoRMS scientific names of anchored nodes
in the revision, with the same normalisation and methods as labels and aliases,
reporting `matched_on: "worms"`.

#### Scenario: Scientific name with a space
- **WHEN** a client searches `q=Chaetoceros didymus` and the node's label already matched
- **THEN** the node is returned once, with the best-ranked match

#### Scenario: WoRMS name only
- **WHEN** a node labelled `Thalassiosira_morphotype1` has no match on label or alias but its cached WoRMS name matches
- **THEN** it is returned with `matched_on: "worms"`

### Requirement: Flat export WoRMS columns
`export_flat` SHALL fill `worms_scientificname`, `worms_rank`, `worms_status`
and `worms_link` from the node's `worms_data`, and `worms_warnings` with the
names of its current warnings separated by `|`.

#### Scenario: Node with a warning
- **WHEN** a node has current warnings `out_of_lineage` and `duplicate_aphia`
- **THEN** its `worms_warnings` cell is `out_of_lineage|duplicate_aphia`
