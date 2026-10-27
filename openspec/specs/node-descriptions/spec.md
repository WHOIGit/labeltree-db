# node-descriptions Specification

## Purpose

Defines node descriptions: unversioned free-text definitions and annotation
guidance attached to a node, kept with their history, and always shown in their
current state.

## Requirements

### Requirement: Descriptions are unversioned text attached to a node
A node SHALL have a description history: zero or more entries, each with the
description text, `added_by` and `added_at`, attached to the node rather than to
a node version. The node's description SHALL be the text of its newest entry,
or the empty string if it has none. Changing a description SHALL add an entry
and SHALL NOT create a node version or a tree revision. Entries SHALL never be
deleted.

#### Scenario: Description updated
- **WHEN** a node's description is set to `Cells with a bleb` and later to `Cells with one or more blebs`
- **THEN** the node's description is `Cells with one or more blebs`, and both entries are kept with who added them and when

#### Scenario: No description
- **WHEN** a node has never had a description
- **THEN** its description is `""`

### Requirement: Clearing a description
Setting a description to the empty string SHALL clear it, by adding an entry
with the text `""`.

#### Scenario: Cleared description
- **WHEN** a node's description is set to `""` after having text
- **THEN** its description is `""` and the earlier entries are kept

### Requirement: Initial description from add changes
A non-empty `description` carried on an `add` change SHALL become the new
node's first description entry when the changeset is published, recorded as
added by the changeset's author at the publish time.

#### Scenario: Imported description
- **WHEN** an imported node carries `description: "Diatom genus"` and its changeset is published
- **THEN** the new node's description is `Diatom genus`, added by the changeset's author

### Requirement: Descriptions are always current in reads
Every read that returns a description SHALL return the node's current
description, even when a past revision is requested.

#### Scenario: Description changed after a revision
- **WHEN** a node's description is changed after revision 4 and the node is read at `?rev=4`
- **THEN** the new description is returned
