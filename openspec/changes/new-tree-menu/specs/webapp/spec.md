# Spec Delta

## REMOVED Requirements

### Requirement: Clone as new tree
**Reason**: Cloning becomes one of three ways to start a new tree, under the "New tree menu" requirement.
**Migration**: Use **New tree ▾ → From this revision…** in the tree browser; it behaves as cloning did.

## ADDED Requirements

### Requirement: New tree menu
The tree browser SHALL offer owners a **New tree** menu with **Empty tree**,
**From an import file** and **From this revision**. Each SHALL ask for the
organization, from those the user owns, and the new tree's id, title and
description, and SHALL create a new-tree draft that opens in edit mode for
review before publishing. Users who own no organization SHALL see the menu
disabled with the reason.

#### Scenario: Empty tree
- **WHEN** an owner of `lab_a` starts an empty tree `lab_tags` in `lab_a`
- **THEN** a saved new-tree draft for `lab_tags` with no changes opens in edit mode

#### Scenario: Tree from an import file
- **WHEN** an owner of `lab_a` starts tree `lab_tags` from an import file with three nodes
- **THEN** a saved new-tree draft for `lab_tags` opens in edit mode with one collapsed `import#1` group of three `add` changes

#### Scenario: Clone flow
- **WHEN** an owner of `lab_a` starts `lab_taxonomy` in `lab_a` from revision 3 of `NES2022_taxonomy`
- **THEN** a new-tree draft for `lab_taxonomy` opens in edit mode with one collapsed `import#1` group

#### Scenario: Not an owner
- **WHEN** a user who owns no organization views a tree
- **THEN** the New tree menu is disabled with "Needs the owner role in an organization"

### Requirement: Import file checks for a new tree
Starting a tree from an import file SHALL check the file before creating
anything: malformed JSON or a file not in the import format SHALL be reported
in the dialog, with the position for format errors, and no draft SHALL be
created. Label problems SHALL be reported by validation in the editor, as for
any draft.

#### Scenario: Malformed import file
- **WHEN** an owner starts a tree from an import file with a node without a `label`
- **THEN** the dialog reports the node's position and no draft is created

### Requirement: New tree from the organization page
The organization page SHALL show its owners a **New tree** button, which opens
the new-tree dialog for that organization, empty or from an import file. Others
SHALL not see it, and the page it opens SHALL return `403` to them.

#### Scenario: Owner starts a tree from the organization page
- **WHEN** an owner of `lab_a`, which has no trees, clicks New tree on its page and starts an empty tree `lab_tags`
- **THEN** a saved new-tree draft for `lab_tags` in `lab_a` opens in edit mode

#### Scenario: Member of the organization
- **WHEN** a drafter of `lab_a` opens its organization page
- **THEN** there is no New tree button, and opening the new-tree page directly returns `403`
