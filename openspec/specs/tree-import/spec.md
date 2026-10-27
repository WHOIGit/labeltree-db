# tree-import Specification

## Purpose

Defines how a nested label file becomes tree content: the import format, its
expansion into an ordinary changeset of `add` changes, and importing a file as a
new tree's first revision.

## Requirements

### Requirement: Import format
An import file SHALL be JSON of the form `{tree, nodes: [...]}` where each node
is `{label, aphia_id?, description?, aliases?, children?}` and structure comes
from nesting. Only `label` SHALL be required. All other keys, including `id`,
`version` and `tree` inside nodes, SHALL be ignored, so content-shape and
detailed-shape responses can be imported as they are.

#### Scenario: Minimal node
- **WHEN** a file contains `{label: "bleb"}` with no other keys
- **THEN** it imports as a node labelled `bleb` with no AphiaID, an empty description and no aliases

#### Scenario: Re-importing an export
- **WHEN** the output of `GET /trees/{tree}/nodes_as_tree` is imported
- **THEN** its `id`, `version` and `num_children` keys are ignored and the same structure and content are reproduced with new ids

#### Scenario: Malformed file
- **WHEN** a file has a node without `label`
- **THEN** the import is rejected, naming the offending node's position, and no changeset is created

### Requirement: Import expands into add changes
Importing SHALL expand the file into `add` changes, parents before children in
file order, sharing one group `import#n` and using placeholder ids. Imported
nodes SHALL go at top level or under a chosen existing node. Each node's
`description` and `aliases` SHALL ride on its `add` and be written as its
initial description and aliases on publish.
The result SHALL be an ordinary changeset subject to all changeset rules.

#### Scenario: Nested import
- **WHEN** a file holds `organism_state` with children `bleb` and `dividing`
- **THEN** the changeset holds an `add` of `organism_state` followed by `add`s of `bleb` and `dividing` whose parent is its placeholder, all in one `import#n` group

#### Scenario: Label clash
- **WHEN** an imported label is already used in the target tree
- **THEN** that `add` fails with `label_in_use`

### Requirement: Import a file as a new tree
An operator SHALL be able to import a file as a new tree from the command line,
giving the tree id, title, description and acting user. This SHALL build a
new-tree changeset from the file and check it before storing anything; only a
changeset with no structural errors SHALL be saved and published as revision 1.

#### Scenario: Load NES2022_tags
- **WHEN** `labeldata/NES2022_tags.json` is imported as new tree `NES2022_tags`
- **THEN** the tree has revision 1 with 18 nodes, 5 of them top-level, all at version 1

#### Scenario: Errors abort the import
- **WHEN** an imported file contains a duplicate or non-machine-safe label
- **THEN** the structural errors are reported per change, and no changeset, tree or revision is stored
