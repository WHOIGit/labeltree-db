# quick-add Specification

## Purpose

Lets other applications and approvers add a single node to a tree and publish
it in one confirmed step, with the label and parent worked out from WoRMS.

## Requirements

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
(`unaccepted_aphia`, `duplicate_aphia`, `out_of_lineage`), `ambiguous_parent`,
and, when the new node would give `misplaced_lineage_ancestor` to direct
children of the planned parent that the plan doesn't move, one
`misplaced_lineage_ancestor` issue naming them. Each issue SHALL have a `code`, a `message`, and `options`:
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

#### Scenario: Nodes to adopt
- **WHEN** the new node would give `misplaced_lineage_ancestor` to a direct child of the planned parent and cross-node updates aren't allowed
- **THEN** the preview has a `misplaced_lineage_ancestor` issue with one option, which sets `allow_cross_node_updates` to `true`

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
publish one changeset holding one `add`, followed by a `move` for each of the
plan's `moves`, and return `201`. Otherwise it SHALL return a fresh preview with
a new key and `confirm_status` set to `body_changed`, `plan_changed`, `expired`
or `invalid`.

#### Scenario: Confirmed
- **WHEN** a client sends the previewed request again with its key, and the plan is unchanged
- **THEN** the response is `201` with `confirm_status: "accepted"`, the new node (`id`, `label`, `parent`, `aphia_id`), the new `rev`, the `changeset` id and `moved`, the nodes moved under it

#### Scenario: Confirmed with moves
- **WHEN** a client confirms a preview whose plan moves `Chaetoceros` under the new `Chaetocerotaceae`
- **THEN** one changeset adds `Chaetocerotaceae` and moves `Chaetoceros` under it, and `moved` lists `Chaetoceros`

#### Scenario: Modified request
- **WHEN** a client sends a different request with an earlier key
- **THEN** nothing is published and the response is a preview with `confirm_status: "body_changed"` and a new key

#### Scenario: Tree changed the plan
- **WHEN** another publish since the preview makes the derived parent different, and the client confirms
- **THEN** nothing is published and the response is a preview of the new plan with `confirm_status: "plan_changed"`

#### Scenario: New node to adopt since the preview
- **WHEN** cross-node updates are allowed and another publish since the preview adds a node the new node would adopt, and the client confirms
- **THEN** nothing is published and the response is a preview whose `moves` include it, with `confirm_status: "plan_changed"`

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

### Requirement: Cross-node updates
The request SHALL accept `allow_cross_node_updates`, a boolean, `false` when
missing. When `true`, the plan SHALL also move under the new node every direct
child of the planned parent (every top-level node, for the top level) that the
new node would give `misplaced_lineage_ancestor`. The client SHALL NOT choose
which nodes move. The plan's `moves` SHALL list them as `{id, label}`, empty
when there are none.

#### Scenario: Not allowed
- **WHEN** a quick add of `Chaetocerotaceae` under `Bacillariophyceae`, which has the child `Chaetoceros`, doesn't allow cross-node updates
- **THEN** the plan's `moves` is empty and the preview has a `misplaced_lineage_ancestor` issue naming `Chaetoceros`

#### Scenario: Allowed
- **WHEN** the same quick add has `allow_cross_node_updates: true`
- **THEN** the plan's `moves` lists `Chaetoceros`, and the preview has no `misplaced_lineage_ancestor` issue for it

#### Scenario: Only direct children
- **WHEN** a node that the new node would warn isn't a direct child of the planned parent (it sits under an unanchored node, or elsewhere in the tree)
- **THEN** that node isn't in `moves` and isn't named by the preview's `misplaced_lineage_ancestor` issue

#### Scenario: Toggling changes the request
- **WHEN** a client confirms with the key of a preview without `allow_cross_node_updates` but sends it as `true`
- **THEN** nothing is published and the response is a preview with `confirm_status: "body_changed"`
