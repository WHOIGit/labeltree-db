# Spec Delta

## Purpose

Lets other applications and approvers add a single node to a tree and publish
it in one confirmed step, with the label and parent worked out from WoRMS.

## ADDED Requirements

### Requirement: Quick add access
`POST /trees/{tree}/quick_add` SHALL require `approver` (or `owner`) in the
tree's organization, by API token or by web app session, as for other writes.
Anonymous requests SHALL get `401`, and other users `403`. An unknown tree
SHALL get `404`.

#### Scenario: Drafter refused
- **WHEN** a user who is `drafter` in the tree's organization posts a quick add
- **THEN** the response is `403` and nothing is published

#### Scenario: Approver token
- **WHEN** a client with an API token of an `approver` posts a quick add
- **THEN** the response is a preview (`200`)

### Requirement: Quick add request
The body SHALL be JSON with the optional fields `aphia_id`, `label`, `parent`,
`description`, `aliases`, `notes` and `confirm`. A `parent` given as a node id
SHALL be a live node of the tree, and a `parent` given as `null` SHALL mean the
top level. A missing `parent` SHALL mean "work it out". Without an `aphia_id`,
`label` SHALL be required.

#### Scenario: Neither AphiaID nor label
- **WHEN** a quick add body has neither `aphia_id` nor `label`
- **THEN** the response is `400` and no confirm key is returned

#### Scenario: Label only
- **WHEN** a quick add body is `{label: "detritus"}`
- **THEN** the plan adds `detritus` at the top level of the tree

### Requirement: Label from WoRMS
When `label` is missing, the label SHALL be the record's scientific name with
whitespace replaced by `_`, characters that are not machine-safe dropped and
leading punctuation removed, which is the rule the web app's Add from WoRMS
uses. A given `label` SHALL be used as is.

#### Scenario: Derived label
- **WHEN** a quick add gives AphiaID 149219, whose name is `Chaetoceros debilis`, and no label
- **THEN** the plan's label is `Chaetoceros_debilis`

#### Scenario: Unsafe characters
- **WHEN** the record's name is `Chaetoceros (Hyalochaete) debilis` and no label is given
- **THEN** the plan's label is `Chaetoceros_Hyalochaete_debilis`

### Requirement: Parent from the lineage
When `parent` is missing and an `aphia_id` is given, the parent SHALL be the
live node anchored to the deepest AphiaID of the record's lineage (excluding
the record itself) that any live node is anchored to. If no lineage AphiaID is
in the tree, the parent SHALL be the top level. Without an `aphia_id`, a missing
`parent` SHALL be the top level.

#### Scenario: Nearest anchored ancestor
- **WHEN** the tree has `Bacillariophyceae` and, below it, `Chaetoceros` anchored to their AphiaIDs, and a quick add gives AphiaID 149219 with no parent
- **THEN** the plan's parent is `Chaetoceros`

#### Scenario: Nothing anchored
- **WHEN** no live node is anchored to an AphiaID in the record's lineage
- **THEN** the plan's parent is the top level

#### Scenario: Explicit top level
- **WHEN** a quick add gives an AphiaID and `parent: null`
- **THEN** the plan's parent is the top level, whatever the lineage

### Requirement: Ambiguous parent
When two or more live nodes are anchored to the deepest anchored lineage
AphiaID, the parent SHALL be the top level, and the preview SHALL report an
`ambiguous_parent` issue that lists those nodes.

#### Scenario: Two candidates
- **WHEN** nodes 812 and 977 are both anchored to `Chaetoceros`, the deepest anchored lineage AphiaID, and a quick add gives no parent
- **THEN** the plan's parent is the top level and the preview has an `ambiguous_parent` issue listing nodes 812 and 977

### Requirement: WoRMS record for a quick add
With an `aphia_id`, the record SHALL come from the WoRMS cache, and be fetched
from WoRMS on a miss. An AphiaID with no WoRMS record SHALL get `404`, and
WoRMS being unreachable for an uncached record SHALL get `503`. Neither
response SHALL carry a confirm key.

#### Scenario: Uncached record
- **WHEN** a quick add gives an AphiaID whose record isn't cached and WoRMS answers
- **THEN** the record is cached and the preview uses it

#### Scenario: WoRMS unreachable
- **WHEN** a quick add gives an uncached AphiaID and WoRMS can't be reached
- **THEN** the response is `503` `worms_unreachable` with no confirm key

### Requirement: Quick add preview
A quick add without a valid confirm key SHALL publish and store nothing. It
SHALL return `200` with `status: "preview"`, the `rev` it was planned on, the
`plan` (`label`, `parent`, `aphia_id`, `description`, `aliases`), the `issues`,
`confirm_status`, and a `confirm` key.

#### Scenario: First call
- **WHEN** an approver posts `{aphia_id: 149219}` without `confirm`
- **THEN** the response is `200` with the plan, its issues, `confirm_status: "none"` and a confirm key, and the tree's latest revision is unchanged

### Requirement: Quick add issues
The issues SHALL be the WoRMS warnings the planned node would get
(`unaccepted_aphia`, `duplicate_aphia`, `out_of_lineage`) plus
`ambiguous_parent`. Each issue SHALL have a `code`, a `message`, and `options`:
suggested request edits, each with a `label` and the fields to `set`. Issues
SHALL NOT prevent a confirm key.

#### Scenario: Unaccepted AphiaID
- **WHEN** a quick add gives AphiaID 148942 (`Thalassiosira rotula`), which WoRMS lists as a synonym of accepted AphiaID 149102
- **THEN** the preview has an `unaccepted_aphia` issue with an option that sets `aphia_id` to 149102, and still has a confirm key

#### Scenario: Ambiguous parent options
- **WHEN** the preview has an `ambiguous_parent` issue for nodes 812 and 977
- **THEN** its options set `parent` to 812, to 977, and to `null`

#### Scenario: AphiaID already in the tree
- **WHEN** a quick add gives an AphiaID a live node of the tree already has, with a new label
- **THEN** the preview has a `duplicate_aphia` issue naming that node, and still has a confirm key

### Requirement: Errors get no confirm key
A plan with structural errors, such as `invalid_label`, `label_in_use` or
`parent_not_in_tree`, SHALL get `422` with the errors
and no confirm key, and nothing SHALL be published.

#### Scenario: Label in use
- **WHEN** a quick add's label, given or derived, is already used in the tree
- **THEN** the response is `422` with a `label_in_use` error and no confirm key

#### Scenario: Unknown parent
- **WHEN** a quick add gives a `parent` that is deprecated or in another tree
- **THEN** the response is `422` with a `parent_not_in_tree` error and no confirm key

### Requirement: Confirm key binds request and plan
The confirm key SHALL be signed by the server and SHALL bind the tree, the
user, the request without `confirm` and `notes`, and the plan with its issues.
Keys SHALL expire after 15 minutes. Clients cannot forge or alter a key.

#### Scenario: Notes changed at confirm
- **WHEN** a client sends the previewed request with its key and different `notes`
- **THEN** the quick add is published with those notes

#### Scenario: Key from another user
- **WHEN** an approver sends a request with a key issued to a different user
- **THEN** nothing is published and a fresh preview is returned with `confirm_status: "invalid"`

### Requirement: Confirming a quick add
A request with a valid key SHALL be re-planned on the tree's latest revision.
If the request and the plan with its issues both match the key, it SHALL
publish one changeset holding one `add` and return `201`. Otherwise it SHALL
return a fresh preview with a new key and `confirm_status` set to
`body_changed`, `plan_changed`, `expired` or `invalid`.

#### Scenario: Confirmed
- **WHEN** a client sends the previewed request again with its key, and the plan is unchanged
- **THEN** the response is `201` with `confirm_status: "accepted"`, the new node (`id`, `label`, `parent`, `aphia_id`), the new `rev` and the `changeset` id

#### Scenario: Modified request
- **WHEN** a client sends a different request with an earlier key
- **THEN** nothing is published and the response is a preview with `confirm_status: "body_changed"` and a new key

#### Scenario: Tree changed the plan
- **WHEN** another publish since the preview makes the derived parent different, and the client confirms
- **THEN** nothing is published and the response is a preview of the new plan with `confirm_status: "plan_changed"`

#### Scenario: Unrelated publish
- **WHEN** another publish since the preview changes nodes that don't affect the plan, and the client confirms
- **THEN** the quick add is published

#### Scenario: Expired key
- **WHEN** a client confirms with a key older than 15 minutes
- **THEN** nothing is published and the response is a preview with `confirm_status: "expired"`

### Requirement: Retried confirm adds nothing twice
Sending a confirmed request and key again after it was published SHALL NOT add
a second node.

#### Scenario: Retry after a timeout
- **WHEN** a client resends a request and key that were already published
- **THEN** no node is added: the response is `422` `label_in_use`, or a preview with `confirm_status: "plan_changed"` and a `duplicate_aphia` issue

### Requirement: Published quick adds
A published quick add SHALL be an ordinary changeset and revision: its author
and publisher are the caller, and its notes are the request's `notes`, or
`Quick add` when none are given. It SHALL use the tree's publish lock, and a
publish already running on the tree SHALL get `409` `publish_in_progress`.

#### Scenario: History
- **WHEN** approver `curator1` confirms a quick add of `Chaetoceros_debilis`
- **THEN** the tree's new revision lists one change adding `Chaetoceros_debilis`, with author and publisher `curator1`
