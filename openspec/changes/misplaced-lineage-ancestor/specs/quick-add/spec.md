# Spec Delta

## ADDED Requirements

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

## MODIFIED Requirements

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
