# Spec Delta

## Purpose

Gives curators a browser interface to browse trees at any revision, compose
changesets with immediate feedback, review and publish them, and manage aliases,
all through the same write endpoints that scripts use.

## ADDED Requirements

### Requirement: Edits go through the write API
Every change the web app makes SHALL go through the write endpoints, with the
same role checks as API clients. Controls the user's roles do not allow SHALL be
shown disabled, with the reason as a tooltip.

#### Scenario: Reader opens the edit menu
- **WHEN** a user with only `reader` views a tree
- **THEN** the Edit button is disabled with a tooltip naming the missing role

### Requirement: Tree browser
The tree browser SHALL show a selected tree at a selected published revision as
an expandable nested list, with each node's label and child count, Expand all
and Collapse all, and a filter matching labels and aliases that expands the
matches' ancestors. The revision picker SHALL list each revision with its
publish date and author.

#### Scenario: Viewing a past revision
- **WHEN** a user picks revision 2 of a tree whose latest revision is 3
- **THEN** the tree shows revision 2, including nodes deprecated in revision 3

#### Scenario: Filter
- **WHEN** a user types `didymus` in the filter
- **THEN** the matching nodes are shown with their ancestors expanded

### Requirement: Node badges
Each node SHALL show a WoRMS badge with its AphiaID linking to its WoRMS page
when it has an `aphia_id`, and a warning badge with the count of its current
WoRMS warnings, listing them in a tooltip, when it has any.

#### Scenario: Node with warnings
- **WHEN** a node has two current warnings
- **THEN** it shows a warning badge with count 2 whose tooltip lists both details

### Requirement: Revision changes in static mode
When browsing a published revision, the changes panel SHALL show the changeset
that produced it, frozen, grouped by macro.

#### Scenario: What changed in revision 3
- **WHEN** a user views revision 3, which was a `merge#1`
- **THEN** the changes panel lists the merge's changes under a `merge#1` header without remove buttons

### Requirement: Node page
The node page SHALL show a node's current state, its version history with
revision ranges, its WoRMS card with `worms_data` and warnings, its aliases,
and its successors if deprecated.

#### Scenario: Deprecated node
- **WHEN** a user opens the page of a deprecated node
- **THEN** it shows the revision it was deprecated in and links to its successors

### Requirement: Edit mode
Edit mode SHALL compose a changeset against a fixed `base_rev`, starting from a
new draft at the latest revision or an open draft chosen from the Edit menu.
The top bar SHALL show the draft number and status (`None`, `Draft (unsaved)`,
`Draft (saved)`). Leaving with unsaved changes SHALL ask for confirmation.

#### Scenario: Open an existing draft
- **WHEN** a drafter chooses draft #6 from the Edit menu
- **THEN** edit mode opens on draft #6's `base_rev` with its changes listed

#### Scenario: Leave with unsaved changes
- **WHEN** a user exits edit mode with unsaved changes
- **THEN** they are asked to confirm before the changes are dropped

### Requirement: Composing atomic changes
In edit mode, each node's menu SHALL offer Edit, New child, Move to, Split,
Merge and Deprecate, and the tree SHALL offer New node. Each dialog SHALL check
label safety and uniqueness as the user types. Move to SHALL NOT allow picking
the node or its descendants. Deprecate SHALL be blocked with an explanation if
the node has children.

#### Scenario: Move to a descendant
- **WHEN** a user moves node A and hovers one of A's descendants as the new parent
- **THEN** that node cannot be picked

#### Scenario: Deprecate a parent
- **WHEN** a user chooses Deprecate on a node with children
- **THEN** the dialog explains that the children must be moved, merged or split first

### Requirement: Live checks in the changes panel
The changes panel SHALL list the changes in order, groups collapsible, and SHALL
call `validate` as the list changes, showing structural errors in red and WoRMS
warnings in yellow under the change that caused them, plus a summary line of
counts.

#### Scenario: Label clash appears
- **WHEN** a user adds a node with a label already in use
- **THEN** a red `label_in_use` error appears under that change and Publish is disabled

### Requirement: Draft markings in the tree
In edit mode, the tree SHALL mark added nodes green, nodes whose version will
increase yellow with a `vN -> vN+1` badge, and nodes deprecated in the draft grey
and struck through, left in place until publish.

#### Scenario: Child added
- **WHEN** a draft adds a child under `Chaetoceros` at version 7
- **THEN** the child is green and `Chaetoceros` is yellow with `v7 -> v8`

### Requirement: Removing changes safely
Each change and each group SHALL be removable in edit mode. Removing a change
that later changes depend on SHALL mark those later changes as errors rather than
removing them.

#### Scenario: Remove an add with dependants
- **WHEN** a user removes the `add` of `new:1` while a later `move` uses `new:1` as parent
- **THEN** the `move` stays in the list and shows an error

### Requirement: Saving, rebasing, publishing and discarding
Save Draft SHALL send the whole list and show the reduced result. A stale draft
SHALL show a conflict with a Rebase button that sets `base_rev` to the latest
revision. Publish SHALL be enabled for approvers on a saved, error-free,
up-to-date draft, ask for notes, and show the new revision. Discard SHALL keep
the draft as read-only.

#### Scenario: Rebase then publish
- **WHEN** an approver opens a draft based on revision 2 while the latest is 3 and clicks Rebase
- **THEN** the draft's `base_rev` becomes 3, changes that no longer apply show errors, and Publish is enabled once they are fixed

### Requirement: Draft list and review
The draft list SHALL show each open draft of a tree with its `base_rev`, author
and change count, with discarded drafts in a separate read-only section.
Reviewing a draft SHALL show its changes grouped by macro, the affected nodes
with old and new versions, and warnings that will change.

#### Scenario: Review a draft
- **WHEN** an approver opens draft #6 for review
- **THEN** they see its grouped changes, each affected node's `from -> to` version, and the warning changes

### Requirement: Merge wizard
Merge from node A SHALL let the user choose nodes to merge (siblings first),
choose with replacement (default) or without, and, with replacement, set the
new node's fields and parent (default: the common parent). It SHALL show the
expanded changes, then append them as one `merge#n` group.

#### Scenario: Merge with replacement
- **WHEN** a user merges A and B with replacement into new node C
- **THEN** the draft gains, in group `merge#n`: an `add` of C, `move`s of every child of A and B to C, and `deprecate`s of A and B each with successor C

#### Scenario: Merge without replacement
- **WHEN** a user merges A into surviving node B
- **THEN** the draft gains `move`s of A's children to B and a `deprecate` of A with successor B

### Requirement: Split wizard
Split from node A SHALL let the user choose with replacement (default; at least
two new nodes, every child assigned) or without (at least one new sibling;
unassigned children stay with A), show the expanded changes, and append them as
one `split#n` group.

#### Scenario: Split with replacement
- **WHEN** a user splits A into A1 and A2, assigning every child
- **THEN** the draft gains `add`s of A1 and A2, `move`s of each child, and a `deprecate` of A with successors A1 and A2, all in `split#n`

#### Scenario: Unassigned child
- **WHEN** a split with replacement leaves a child unassigned
- **THEN** the wizard does not allow continuing

### Requirement: Aliases after a merge
After a merge is published, the web app SHALL add each deprecated node's label
and current aliases as aliases of the surviving or new node, skipping ones it
already has. The merge review step SHALL say so.

#### Scenario: Merge publish
- **WHEN** a merge of A (alias `a_old`) into new node C is published
- **THEN** C gains aliases `A` and `a_old`

### Requirement: Import wizard
The draft editor SHALL accept an uploaded or pasted import file, expand it into
an `import#n` group placed at top level or under a chosen node, and let the
user edit the changes before saving.

#### Scenario: Import under a node
- **WHEN** a drafter imports a file under node `interaction`
- **THEN** the file's top-level nodes are added with `interaction` as parent, in one collapsed `import#n` group

### Requirement: Add from WoRMS
Add from WoRMS SHALL search WoRMS by name through the lookup endpoints, let the
user pick a record, and propose an `add` with that AphiaID and its scientific
name as label, under the nearest node in the tree whose AphiaID is in the
record's lineage, which the user may change.

#### Scenario: Suggested parent
- **WHEN** a user picks `Chaetoceros debilis` and the tree has `Chaetoceros` anchored
- **THEN** the proposed `add` has parent `Chaetoceros` and label `Chaetoceros_debilis`

### Requirement: Alias editing
Drafters SHALL be able to edit a node's aliases from its menu in any mode. The
change SHALL apply immediately, outside any changeset, and the dialog SHALL say
so. It SHALL be unavailable for nodes added in the draft.

#### Scenario: Edit aliases in static mode
- **WHEN** a drafter adds an alias while browsing a published revision
- **THEN** the alias is saved immediately and no draft is created

### Requirement: Description editing
Drafters SHALL be able to edit a node's description from its menu in any mode.
The change SHALL apply immediately, outside any changeset, and the dialog SHALL
say so. For a node added in the draft, the description SHALL instead be part of
its `add` and be written on publish.

#### Scenario: Edit a description in static mode
- **WHEN** a drafter changes a node's description while browsing a published revision
- **THEN** the description is saved immediately and no draft is created

### Requirement: Clone as new tree
Users with the tree-creation permission SHALL be able to clone the displayed
revision as a new tree by entering its id, title and description. This SHALL
create a new-tree draft that opens in edit mode for review before publishing.

#### Scenario: Clone flow
- **WHEN** a permitted user clones revision 3 as `lab_taxonomy`
- **THEN** a new-tree draft for `lab_taxonomy` opens in edit mode with one collapsed `import#1` group
