# Spec Delta

## ADDED Requirements

### Requirement: WoRMS link in quick add responses
A preview's `plan` and a published quick add's `node` SHALL include `worms_url`:
the WoRMS page of the node's AphiaID, or `null` when the node has no AphiaID.

#### Scenario: Preview with an AphiaID
- **WHEN** an approver previews `{aphia_id: 149219}`
- **THEN** the plan's `worms_url` is `https://www.marinespecies.org/aphia.php?p=taxdetails&id=149219`

#### Scenario: Label only
- **WHEN** an approver previews `{label: "detritus"}`
- **THEN** the plan's `worms_url` is `null`

#### Scenario: Published
- **WHEN** an approver confirms a quick add of AphiaID 149219
- **THEN** the `201` response's `node.worms_url` is the WoRMS page of AphiaID 149219

## MODIFIED Requirements

### Requirement: Quick add request
The body SHALL be JSON with the optional fields `aphia_id`, `label`, `parent`,
`lowercase_label`, `description`, `aliases`, `notes` and `confirm`. A `parent`
given as a node id SHALL be a live node of the tree, and a `parent` given as
`null` SHALL mean the top level. A missing `parent` SHALL mean "work it out".
`lowercase_label` SHALL be a boolean, `true` when missing. Without an
`aphia_id`, `label` SHALL be required.

#### Scenario: Neither AphiaID nor label
- **WHEN** a quick add body has neither `aphia_id` nor `label`
- **THEN** the response is `400` and no confirm key is returned

#### Scenario: Label only
- **WHEN** a quick add body is `{label: "detritus"}`
- **THEN** the plan adds `detritus` at the top level of the tree

#### Scenario: Toggling lowercase changes the request
- **WHEN** a client confirms with the key of a preview of `{aphia_id: 149219}` but sends `{aphia_id: 149219, lowercase_label: false, confirm: <key>}`
- **THEN** nothing is published, and the response is a new preview with `confirm_status: "body_changed"`

### Requirement: Label from WoRMS
When `label` is missing, the label SHALL be the record's scientific name with
whitespace replaced by `_`, characters that are not machine-safe dropped and
leading punctuation removed, which is the rule the web app's Add from WoRMS
uses, and then lowercased unless `lowercase_label` is `false`. A given `label`
SHALL be used as is, whatever `lowercase_label` is.

#### Scenario: Derived label
- **WHEN** a quick add gives AphiaID 149219, whose name is `Chaetoceros debilis`, and no label
- **THEN** the plan's label is `chaetoceros_debilis`

#### Scenario: Derived label keeping the case
- **WHEN** a quick add gives AphiaID 149219, no label, and `lowercase_label: false`
- **THEN** the plan's label is `Chaetoceros_debilis`

#### Scenario: Unsafe characters
- **WHEN** the record's name is `Chaetoceros (Hyalochaete) debilis` and no label is given
- **THEN** the plan's label is `chaetoceros_hyalochaete_debilis`

#### Scenario: Given label
- **WHEN** a quick add gives AphiaID 149219 and the label `Chaetoceros_debilis`
- **THEN** the plan's label is `Chaetoceros_debilis`
