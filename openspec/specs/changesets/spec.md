# changesets Specification

## Purpose

Defines how tree edits are expressed and applied: changesets of ordered atomic
changes, their validation and reduction, and publishing a changeset as the next
tree revision, including a new tree's first revision.

## Requirements

### Requirement: Changeset is an ordered list of atomic changes
A changeset SHALL be an ordered list of changes against a `base_rev`, with an
author and notes. Each change SHALL have a position `seq`, an `op` of `add`,
`edit`, `move` or `deprecate`, an optional `group` naming the macro that
produced it (e.g. `split#3`), and a payload of its arguments.

#### Scenario: Grouped changes
- **WHEN** a split is drafted as two `add`s, two `move`s and a `deprecate`
- **THEN** the changeset holds five changes in that order, all with group `split#n`

### Requirement: Change payloads
Payloads SHALL be: `add` with `node`, `label`, `parent` (null = top level) and
optional `aphia_id`, initial `description` and initial `aliases`; `edit` with
`node` and only the changed fields among `label` and `aphia_id` (null clears it);
`move` with `node`, `from_parent` and `to_parent` (null = top level);
`deprecate` with `node` and a possibly empty `successors` list.

#### Scenario: Edit carries only changed fields
- **WHEN** only a node's AphiaID is changed
- **THEN** its `edit` payload holds `node` and `aphia_id` and no other field

#### Scenario: Clearing an AphiaID
- **WHEN** an `edit` payload has `aphia_id: null`
- **THEN** publishing it leaves the node with no `aphia_id`

### Requirement: Placeholder ids for new nodes
A node added in a changeset SHALL be referred to by a placeholder such as
`new:1` until publish. Later changes in the same changeset SHALL be able to use
a placeholder as `node`, `parent`, `to_parent` or successor. Publishing SHALL
assign real ids and rewrite every placeholder, so that published changes contain
only real ids. Unpublished changesets SHALL NOT consume node ids.

#### Scenario: Child of a new node
- **WHEN** a changeset adds `new:1` and then adds `new:2` with parent `new:1`
- **THEN** after publish both have real ids and the published `add` of the second node names the first node's real id as parent

#### Scenario: Discarded draft
- **WHEN** a changeset with placeholder nodes is discarded
- **THEN** no node ids are allocated for it

### Requirement: Changes are checked in order
Each change SHALL be checked against the state left by the changes before it in
the same changeset, starting from the tree at `base_rev`. A failing change SHALL
NOT stop later changes from being checked against the state the earlier valid
changes leave.

#### Scenario: Label swap through a temporary label
- **WHEN** a changeset renames A from `x` to `tmp`, B from `y` to `x`, then A from `tmp` to `y`
- **THEN** every change is valid

#### Scenario: Direct label swap
- **WHEN** a changeset renames A from `x` to `y` while B still holds `y`
- **THEN** that change fails with `label_in_use`

### Requirement: Structural errors are reported per change
A failing change SHALL be reported with its `seq`, an error code, the node it
concerns and a human-readable detail. Structural errors SHALL be recomputed on
every check and SHALL NOT be stored.

#### Scenario: Error report
- **WHEN** change 4 adds a node with label `Chaetoceros` already held by node 402
- **THEN** the result includes `{seq: 4, error: "label_in_use", node: "new:2", detail: ...}`

### Requirement: Structural error conditions
A change SHALL fail when its target is unknown or not in the tree
(`node_not_in_tree`); a parent or `to_parent` is not in the tree or belongs to
another tree (`parent_not_in_tree`); a move creates a cycle (`cycle`); a label
is not machine-safe (`invalid_label`) or in use (`label_in_use`); a deprecated
node still has children (`has_children`); or `from_parent` is not the current
parent (`from_parent_mismatch`).

#### Scenario: Cycle
- **WHEN** a changeset moves node A under one of A's descendants
- **THEN** that change fails with `cycle`

#### Scenario: Deprecating a node with children
- **WHEN** a changeset deprecates a node that still has children at that point
- **THEN** that change fails with `has_children`

#### Scenario: Stale from_parent
- **WHEN** a `move` names `from_parent` 30 but the node's parent at that point is 31
- **THEN** that change fails with `from_parent_mismatch`

#### Scenario: Parent in another tree
- **WHEN** an `add` names a parent node that belongs to a different tree
- **THEN** that change fails with `parent_not_in_tree`

### Requirement: No references to deprecated nodes
After a changeset is applied, no node remaining in the tree SHALL reference a
deprecated node, and every successor named by a `deprecate` in the changeset
SHALL be in the tree, in the same tree, and not the deprecated node itself.
Successors SHALL be checked against the tree as it is after the whole changeset
(after reduction, see "Successor chains collapse"). Violations SHALL be
structural errors on the `deprecate` that names the successor.

#### Scenario: Move under a deprecated node
- **WHEN** a changeset moves node X under node D that was deprecated in an earlier revision
- **THEN** that change fails with `parent_not_in_tree`

#### Scenario: Successor deprecated earlier in the same changeset
- **WHEN** a changeset deprecates B and then deprecates A with successor B
- **THEN** the second `deprecate` fails with `invalid_successor`

#### Scenario: Successor deprecated later without successors
- **WHEN** a changeset deprecates A with successor B and later deprecates B with no successors
- **THEN** the first `deprecate` fails with `invalid_successor`

#### Scenario: Successor added later in the same changeset
- **WHEN** a changeset deprecates A with successor `new:1` and later adds `new:1`
- **THEN** both changes are valid

#### Scenario: Self as successor
- **WHEN** a `deprecate` of A lists A as a successor
- **THEN** it fails with `invalid_successor`

### Requirement: Op reduction on save
When a changeset is saved, the system SHALL reduce its changes per node,
whatever their groups: repeated `edit`s merge into one `edit` holding the net
field changes; repeated `move`s merge into one `move` from the original to the
final parent; `edit`s and `move`s of a node added in the changeset fold into its
`add`. Groups SHALL NOT affect checking or reduction; they only label changes
for reviewers.

#### Scenario: Two renames
- **WHEN** a changeset renames node A from `x` to `y` and later from `y` to `z`, both ungrouped
- **THEN** the saved changeset holds one `edit` of A to label `z`, at the second rename's position

#### Scenario: Two moves
- **WHEN** a changeset moves A from parent P to Q and later from Q to R
- **THEN** the saved changeset holds one `move` of A with `from_parent` P and `to_parent` R

#### Scenario: Edit of a new node
- **WHEN** a changeset adds `new:1` with label `a` and later renames `new:1` to `b`
- **THEN** the saved changeset holds one `add` of `new:1` with label `b`

### Requirement: Placement of merged changes
A merged change SHALL take the position of the last change it replaces, or of
the first if only that position is valid. A merged `move` placed first MAY bring
the `add` of its new parent forward with it. A merged change SHALL keep the group
of the last change it replaces.

#### Scenario: Edit of a new node with new children
- **WHEN** a changeset adds `new:1`, adds `new:2` under `new:1`, then renames `new:1`
- **THEN** the saved changeset holds the `add` of `new:1` with the new label, at its original position, followed by the `add` of `new:2`

#### Scenario: Different groups
- **WHEN** node A is moved in group `merge#1` and moved again in group `split#2`
- **THEN** the saved changeset holds one `move` of A, in group `split#2`

### Requirement: Reduction drops no-ops
Reduction SHALL drop an `edit` whose net field values equal the node's state
before the changeset, a `move` whose final parent equals its original parent,
the `edit`s and `move`s of a node that is deprecated later in the changeset
(bringing its `deprecate` forward to their position when that is the only valid
placement), and an `add` together with a later `deprecate` of the same new node.

#### Scenario: Rename and rename back
- **WHEN** a changeset renames A from `x` to `y` and later back to `x`, with no other change touching A
- **THEN** the saved changeset holds no change for A, and publishing it does not increase A's version

#### Scenario: Add then deprecate
- **WHEN** a changeset adds `new:1` and later deprecates `new:1`
- **THEN** the saved changeset holds neither change

#### Scenario: Moved by a split, then deprecated
- **WHEN** a split in group `split#1` moves node C under `new:1`, and a later ungrouped change deprecates C
- **THEN** the saved changeset deprecates C before the split's remaining changes and holds no `move` of C

### Requirement: Successor chains collapse
When a `deprecate` of X names a successor S that a later `deprecate` in the same
changeset removes with a non-empty successor list, reduction SHALL replace S in
X's successors with S's successors, keeping order and dropping duplicates. If S
was added in the same changeset, its `add` and `deprecate` SHALL then be dropped,
with moves into and out of S merged. A successor removed earlier in the
changeset, or later with no successors, SHALL NOT be collapsed and remains an
`invalid_successor` error.

#### Scenario: Split of a split
- **WHEN** a changeset splits P into `new:1` and `new:2` (group `split#1`), then splits `new:1` into `new:3` and `new:4` (group `split#2`)
- **THEN** the saved changeset adds `new:2`, `new:3` and `new:4`, moves P's children directly to their final parents, deprecates P with successors `new:3`, `new:4` and `new:2`, and holds no change of `new:1`

#### Scenario: Chain through an existing node
- **WHEN** a changeset deprecates A with successor B, then deprecates B with successor C
- **THEN** the saved changeset deprecates A with successor C and B with successor C

### Requirement: Reduction preserves validity
Reduction SHALL skip any merge that would make a valid change list invalid, and
SHALL leave the tree state produced by the changeset unchanged.

#### Scenario: Label swap is kept
- **WHEN** a changeset renames A from `x` to `tmp`, B from `y` to `x`, then A from `tmp` to `y`
- **THEN** the saved changeset keeps all three changes

### Requirement: Changeset states
A changeset SHALL be in one of the states `draft`, `published` or `discarded`.
Only a draft SHALL be changed, published or discarded. A published or discarded
changeset SHALL be kept with its changes frozen.

#### Scenario: Publishing a discarded changeset
- **WHEN** a discarded changeset is published
- **THEN** the publish is refused and no revision is created

### Requirement: Publishing requires the latest base revision
Publishing SHALL be refused with a `stale_base` conflict unless the changeset's
`base_rev` equals the tree's latest revision. A draft that has fallen behind
SHALL be rebased (its `base_rev` set to the latest revision and its changes
rechecked) before it can be published.

#### Scenario: Draft fell behind
- **WHEN** a draft with `base_rev` 37 is published while the tree's latest revision is 38
- **THEN** the publish is refused with `stale_base` and no revision is created

#### Scenario: Rebased draft
- **WHEN** the same draft is rebased to 38 and has no structural errors
- **THEN** it publishes as revision 39

### Requirement: Publishing re-runs all checks
Publishing SHALL re-run reduction and all structural checks against the latest
revision and SHALL be refused if any change fails or if the reduced changeset is
empty (`empty_changeset`).

#### Scenario: Two drafts add the same label
- **WHEN** two drafts each add a node labelled `bleb` and the first is published
- **THEN** the second, once rebased, fails with `label_in_use`

### Requirement: Publishing is atomic
A successful publish SHALL, in one transaction, create revision `latest + 1`,
assign node ids, close the superseded node versions (`valid_to_rev = latest +
1`), open new versions for every node whose state changed, record
deprecations, successors, initial descriptions and initial aliases, and mark
the changeset
`published`.

#### Scenario: Failure leaves no trace
- **WHEN** a publish fails partway
- **THEN** no revision, node, node version, description or alias from it exists

### Requirement: Publish lock-out per tree
While a publish on a tree is in progress, any other publish on that tree SHALL
be refused immediately with `publish_in_progress`, without waiting. The
lock-out SHALL end as soon as the first publish completes or fails, including
when its process crashes. A new-tree publish SHALL lock its proposed tree id.

#### Scenario: Concurrent publishes
- **WHEN** a second draft on the same tree is published while the first publish is still running
- **THEN** the second is refused with `publish_in_progress`, and after the first completes, publishing it again gives `stale_base` until it is rebased

#### Scenario: Crashed publish
- **WHEN** the process running a publish dies mid-publish
- **THEN** the next publish on that tree is not locked out

### Requirement: Version changes of a revision
For every published revision, the system SHALL be able to list each node whose
version changed as `{node, from, to}`, where `from: null` means added and
`to: null` means its last version was closed by deprecation. Parents bumped only
because their children changed SHALL be included.

#### Scenario: Split with replacement
- **WHEN** revision 37 adds 1201 and 1202 under 450, moves 830 and 831 out of 812, and deprecates 812
- **THEN** its version changes are 450 increased, 1201 and 1202 `from: null`, 830 and 831 increased, and 812 `to: null`

### Requirement: New-tree changesets
A changeset with `base_rev: null` SHALL carry the new tree's id, title and
description and be attached to no existing tree. Publishing it SHALL create the
tree and its revision 1 together. It SHALL be refused with `tree_exists` if a
tree with that id already exists.

#### Scenario: First revision
- **WHEN** a new-tree changeset for `NES2022_tags` with 18 `add`s is published
- **THEN** tree `NES2022_tags` exists with revision 1 holding 18 nodes, each at version 1

#### Scenario: Tree id taken
- **WHEN** a new-tree changeset names an id that an existing tree already has
- **THEN** publishing is refused with `tree_exists`
