# Spec Delta

## ADDED Requirements

### Requirement: WoRMS link for the picked record
When a WoRMS record is picked in Add from WoRMS or on the Quick add page, the
page SHALL show the record's WoRMS page as a full, plain link that opens in a
new tab. The Quick add preview and the published message SHALL show the
response's `worms_url` the same way when it is not `null`.

#### Scenario: Add from WoRMS
- **WHEN** a user picks `Chaetoceros debilis` (149219) in Add from WoRMS
- **THEN** the dialog shows the link `https://www.marinespecies.org/aphia.php?p=taxdetails&id=149219`

#### Scenario: Quick add preview
- **WHEN** a Quick add preview's plan has AphiaID 149219
- **THEN** the preview shows the plan's `worms_url` as a link

#### Scenario: No AphiaID
- **WHEN** a Quick add preview's plan has no AphiaID
- **THEN** the preview shows no WoRMS link

### Requirement: Lowercase label toggle
Add from WoRMS and the Quick add page SHALL have a Lowercase label toggle, on
when the page opens. While the user hasn't typed their own label, the label
derived from the picked record's name SHALL follow the toggle. On the Quick
add page the toggle SHALL be sent as `lowercase_label`.

#### Scenario: Default
- **WHEN** a user picks `Chaetoceros debilis` in Add from WoRMS
- **THEN** the proposed label is `chaetoceros_debilis`

#### Scenario: Toggled off
- **WHEN** the user turns Lowercase label off before typing a label
- **THEN** the proposed label becomes `Chaetoceros_debilis`

#### Scenario: Typed label
- **WHEN** the user has typed the label `Chaetoceros_debilis` and turns Lowercase label on
- **THEN** the label stays `Chaetoceros_debilis`

#### Scenario: Quick add request
- **WHEN** the user previews on the Quick add page with Lowercase label off
- **THEN** the request has `lowercase_label: false`

## MODIFIED Requirements

### Requirement: Add from WoRMS
Add from WoRMS SHALL search WoRMS by name through the lookup endpoints, let the
user pick a record, and propose an `add` with that AphiaID, under the nearest
node in the tree whose AphiaID is in the record's lineage, which the user may
change. The proposed label SHALL be the record's scientific name with spaces
replaced by underscores and characters that are not machine-safe dropped,
lowercased while the Lowercase label toggle is on.

#### Scenario: Suggested parent
- **WHEN** a user picks `Chaetoceros debilis` and the tree has `Chaetoceros` anchored
- **THEN** the proposed `add` has parent `Chaetoceros` and label `chaetoceros_debilis`

#### Scenario: Unsafe characters
- **WHEN** a user picks a record named `Chaetoceros (Hyalochaete) debilis`
- **THEN** the proposed label is `chaetoceros_hyalochaete_debilis`
