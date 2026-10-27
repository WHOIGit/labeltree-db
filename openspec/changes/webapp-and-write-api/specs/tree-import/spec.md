# Spec Delta

## ADDED Requirements

### Requirement: Clone a revision as a new tree
Cloning SHALL turn a published revision of an existing tree into a new-tree
changeset (`base_rev: null`) with the new tree's id, title and description, and
one `import#1` group of `add` changes copying labels, descriptions, AphiaIDs,
current aliases and structure. Publishing it SHALL create revision 1 of the new
tree with new node ids.

#### Scenario: Clone revision 3
- **WHEN** an authorised user clones revision 3 of `NES2022_taxonomy` as `lab_taxonomy`
- **THEN** a draft new-tree changeset exists whose `add`s reproduce revision 3's nodes, and publishing it creates `lab_taxonomy` at revision 1

#### Scenario: Clone is independent
- **WHEN** the clone is published and the source tree later changes
- **THEN** the clone is unaffected, and its nodes have ids different from the source nodes
