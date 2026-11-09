# Spec Delta

## ADDED Requirements

### Requirement: Quick add page
Each tree SHALL have a Quick add page at `/trees/{tree}/quick-add/` for approvers
of its organization. The tree browser SHALL link to it for them, and other
users SHALL get the "not allowed" page. The page SHALL search WoRMS by name, let
the user pick a record or type a label, optionally give a label and parent, and
Preview through the quick add endpoint.

#### Scenario: Link for approvers
- **WHEN** an approver views a tree in the browser
- **THEN** a Quick add link opens `/trees/{tree}/quick-add/`

#### Scenario: Drafter
- **WHEN** a drafter opens the Quick add page
- **THEN** the page returns `403` and explains that quick add needs `approver`

### Requirement: Quick add preview and confirm
The page SHALL show a preview's plan, with its parent's label, and its issues.
Each issue's options SHALL be buttons that apply the edit to the form and
preview again. Confirm SHALL send the previewed request with its key. A fresh
preview instead of a publish SHALL be shown with the reason. Errors SHALL be
shown without Confirm.

#### Scenario: Choosing an option
- **WHEN** the preview has an `unaccepted_aphia` issue and the user clicks its option to use the accepted name
- **THEN** the form's AphiaID becomes the accepted one and a new preview is shown

#### Scenario: Confirming
- **WHEN** the user clicks Confirm on a preview whose plan is unchanged
- **THEN** the page says the node was added in the new revision, and links to the node and the tree

#### Scenario: Plan changed before confirming
- **WHEN** the tree changed in a way that alters the plan and the user clicks Confirm
- **THEN** nothing is published, and the page shows the new preview and says the plan changed

#### Scenario: Label in use
- **WHEN** the preview request fails with `label_in_use`
- **THEN** the page shows the error next to the label field and no Confirm button
