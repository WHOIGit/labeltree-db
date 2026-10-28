# Spec Delta

## Purpose

Gives curators a browser interface to browse trees at any revision, compose
changesets and check them on demand, review and publish them, keep WoRMS data
current, and manage aliases, all through the same endpoints that scripts use.

## ADDED Requirements

### Requirement: Edits go through the write API
Every change the web app makes SHALL go through the write endpoints, with the
same role checks as API clients. Controls the user's roles do not allow SHALL be
shown disabled, with the reason as a tooltip.

#### Scenario: Reader opens the edit menu
- **WHEN** a user who is `reader` in a tree's organization views it
- **THEN** the Edit button is disabled with a tooltip naming the role needed

#### Scenario: Anonymous visitor
- **WHEN** a visitor who is not logged in views a tree
- **THEN** a "Log in to edit" button is shown instead of the Edit and sync controls

### Requirement: Tree browser
The tree browser SHALL show a selected tree at a selected published revision as
an expandable nested list, with each node's label and child count, Expand all
and Collapse all, and a filter matching labels and aliases that expands the
matches' ancestors. The tree picker SHALL group trees by organization. The
revision picker SHALL list each revision with its publish date and author.

#### Scenario: Viewing a past revision
- **WHEN** a user picks revision 2 of a tree whose latest revision is 3
- **THEN** the tree shows revision 2, including nodes deprecated in revision 3

#### Scenario: Filter
- **WHEN** a user types `didymus` in the filter
- **THEN** the matching nodes are shown with their ancestors expanded

### Requirement: AphiaID pill
A node with an `aphia_id` SHALL show a round pill containing a worm emoji
(🪱), coloured by its WoRMS state: green with no current warnings, orange with
a `!` badge with any warning, red with a `?` badge with `unknown_aphia`
(whatever its other warnings), and grey when its record has never been
fetched. A node without an `aphia_id` SHALL show no
pill.

#### Scenario: Node with warnings
- **WHEN** a node has `out_of_lineage` and `duplicate_aphia`
- **THEN** its pill is orange with a `!` badge and its tooltip shows its AphiaID and both warnings

#### Scenario: Unknown and duplicated
- **WHEN** a node has `unknown_aphia` and `duplicate_aphia`
- **THEN** its pill is red with a `?` badge and its tooltip lists both warnings

#### Scenario: Never fetched
- **WHEN** a node's AphiaID has no cached record
- **THEN** its pill is grey

### Requirement: AphiaID pill tooltip and link
An AphiaID pill's tooltip SHALL show the AphiaID and every current warning.
Clicking it SHALL open the AphiaID's WoRMS page in a new tab, also for
`unknown_aphia`.

#### Scenario: Open in WoRMS
- **WHEN** a user clicks the pill of a node with AphiaID 149122
- **THEN** the WoRMS page of AphiaID 149122 opens in a new tab

### Requirement: Warnings panel
The tree browser SHALL have a hideable panel listing the nodes of the latest
revision that currently have WoRMS warnings, with their warnings. Selecting an
entry SHALL jump to the node in the tree.

#### Scenario: Open the warnings panel
- **WHEN** a user opens the warnings panel on a tree where 13 nodes have warnings
- **THEN** the panel lists those 13 nodes with their warnings

### Requirement: WoRMS sync menu
The tree browser SHALL offer a sync menu with Sync new AphiaIDs (`sync_new`),
Sync this tree (`sync_tree`) and, for superusers only, Full cache sync
(`sync_all`). A running sync, including one started by the schedule or another
user, SHALL show its progress. When the sync finishes, the tree's pills and
warnings panel SHALL refresh.

#### Scenario: Sync in progress elsewhere
- **WHEN** a scheduled sync is running on the tree and a drafter opens the sync menu
- **THEN** the menu shows the running sync's progress and does not offer to start another

### Requirement: WoRMS job progress
While a WoRMS job runs, the web app SHALL show one progress bar for the job's
AphiaIDs done out of its total. For each AphiaID being retried, it SHALL show an
additional bar advancing through that AphiaID's retry waits, removed when the
AphiaID succeeds or fails. While the job is paused by WoRMS rate limiting, it
SHALL show one bar for the pause instead.

#### Scenario: One AphiaID retrying
- **WHEN** a job has fetched 40 of 60 AphiaIDs and AphiaID 149122 is waiting for its second retry
- **THEN** the job bar shows 40 of 60 and a second bar for 149122 shows its progress through its retry waits

### Requirement: Failed AphiaIDs after a job
When a WoRMS job started from the web app finishes with failed AphiaIDs, the web
app SHALL list them with their reasons and offer Try again, which starts the same
kind of job for the failed AphiaIDs only, or Proceed anyway.

#### Scenario: Proceed anyway
- **WHEN** a fetch job started by Validate finishes with AphiaID 149122 failed and the user chooses Proceed anyway
- **THEN** the validation result is shown with the changes needing 149122 marked as unchecked, and Save is enabled

### Requirement: Organization page
Each organization SHALL have a page listing its trees, and, for its members,
its members with their role. Owners SHALL be able to add an existing user at a
role, change a member's role and remove a member there. The page SHALL explain
that each role includes the ones below it and applies to every tree of the
organization, and a user's own page SHALL list their organizations and roles.

#### Scenario: Owner adds a drafter
- **WHEN** an owner adds user `curator2` as `drafter` on the organization page
- **THEN** `curator2` is listed as `drafter` and can save drafts on every tree of the organization

#### Scenario: Last owner
- **WHEN** the only owner tries to demote themselves on the organization page
- **THEN** the change is refused with an explanation that the organization needs an owner

### Requirement: Revision changes in static mode
When browsing a published revision, the changes panel SHALL show the changeset
that produced it, frozen, grouped by macro.

#### Scenario: What changed in revision 3
- **WHEN** a user views revision 3, which was a `merge#1`
- **THEN** the changes panel lists the merge's changes under a `merge#1` header without remove buttons

### Requirement: Node page
The node page SHALL show a node's current state, its version history with
revision ranges, its WoRMS card with `worms_data` and current warnings, its
warning history, its aliases, and its successors if deprecated.

#### Scenario: Deprecated node
- **WHEN** a user opens the page of a deprecated node
- **THEN** it shows the revision it was deprecated in and links to its successors

#### Scenario: Warning history
- **WHEN** a node gained `unaccepted_aphia` in a sync and lost it in a later publish
- **THEN** its page lists both warning-history rows, newest first

### Requirement: Edit mode
Edit mode SHALL compose a changeset against a fixed `base_rev`, starting from a
new draft at the latest revision or an open draft chosen from the Edit menu. An
opened draft SHALL start from its stored, reduced changes. The top bar SHALL
show the draft number and status (`None`, `Draft (unsaved)`, `Draft (saved)`).
Leaving with unsaved changes SHALL ask for confirmation.

#### Scenario: Open an existing draft
- **WHEN** a drafter chooses draft #6 from the Edit menu
- **THEN** edit mode opens on draft #6's `base_rev` with its stored changes listed

#### Scenario: Leave with unsaved changes
- **WHEN** a user exits edit mode with unsaved changes
- **THEN** they are asked to confirm before the changes are dropped

### Requirement: Composing atomic changes
In edit mode, each node's menu SHALL offer Edit, New child, Move to, Split,
Merge and Deprecate, and the tree SHALL offer New node. Move to SHALL NOT allow
picking the node or its descendants. Deprecate SHALL be blocked with an
explanation if the node has children. Composing SHALL NOT call the server;
changes are checked when the user validates.

#### Scenario: Move to a descendant
- **WHEN** a user moves node A and hovers one of A's descendants as the new parent
- **THEN** that node cannot be picked

#### Scenario: Deprecate a parent
- **WHEN** a user chooses Deprecate on a node with children
- **THEN** the dialog explains that the children must be moved, merged or split first

### Requirement: Validate before save
Edit mode SHALL have a Validate button. Validating SHALL first run a WoRMS fetch
job for the AphiaIDs the changes need that are not cached, showing its progress,
and then show the `validate` result. Save SHALL be enabled only once the
current change list has been validated. Any further edit SHALL disable Save,
mark the validation results as out of date and enable Validate again.

#### Scenario: Edit after validating
- **WHEN** a user validates, then adds another change
- **THEN** Save is disabled, the result tabs are marked out of date, and Validate is enabled

#### Scenario: New AphiaID
- **WHEN** a user adds a node with an uncached AphiaID and presses Validate
- **THEN** a fetch job for that AphiaID runs with a progress bar, and the result then shows the node's WoRMS warnings

### Requirement: Changes panel tabs
The changes panel SHALL have tabs: As edited (the editable list, in order,
groups collapsible), As reduced, By node, Summary, WoRMS warnings and Errors.
All but As edited SHALL show the last validation result. As edited SHALL show
each error under the change it comes from, through `sources`. By node SHALL
show `node_changes`, each node tagged with its groups.

#### Scenario: Label clash appears
- **WHEN** a user adds a node with a label already in use and validates
- **THEN** a red `label_in_use` error appears under that change in As edited, and Publish is disabled

### Requirement: Tab notifications
A changes-panel tab whose content changed since the user last viewed it SHALL
show an unread marker. The Errors and WoRMS warnings tabs SHALL show their
counts.

#### Scenario: New error while on another tab
- **WHEN** a user on the By node tab validates a list with one new error
- **THEN** the Errors tab shows a count of 1 and an unread marker until the user opens it

### Requirement: Jump to node
Hovering an entry in any changes-panel tab or the warnings panel SHALL highlight
its node in the tree. Clicking it SHALL expand the node's ancestors, scroll the
tree to the node and highlight it.

#### Scenario: Jump to a collapsed node
- **WHEN** a user clicks a By node entry for a node inside a collapsed branch
- **THEN** the branch expands and the tree scrolls to the highlighted node

### Requirement: Draft markings in the tree
In edit mode, the tree SHALL mark added nodes green, nodes whose version will
increase yellow with a `vN -> vN+1` badge, and nodes deprecated in the draft grey
and struck through, left in place until publish.

#### Scenario: Child added
- **WHEN** a draft adds a child under `Chaetoceros` at version 7
- **THEN** the child is green and `Chaetoceros` is yellow with `v7 -> v8`

### Requirement: Removing changes safely
Each change and each group SHALL be removable in edit mode. Removing a change
that later changes depend on SHALL keep those later changes, and validating SHALL
then show them as errors.

#### Scenario: Remove an add with dependants
- **WHEN** a user removes the `add` of `new:1` while a later `move` uses `new:1` as parent, and validates
- **THEN** the `move` stays in the list and shows an error

### Requirement: Saving, rebasing, publishing and discarding
Save Draft SHALL send the whole list and show the stored, reduced result. Saving
a draft with structural errors SHALL first ask for confirmation, saying the
draft will not be publishable as it is. A stale draft SHALL show a conflict with
a Rebase button that sets `base_rev` to the latest revision. Publish SHALL be
enabled for approvers on a saved, error-free, up-to-date draft, ask for notes,
and show the new revision. Discard SHALL keep the draft as read-only.

#### Scenario: Save with errors
- **WHEN** a drafter saves a validated draft that has a `cycle` error
- **THEN** a confirmation says the draft will not be publishable as it is, and confirming saves it

#### Scenario: Rebase then publish
- **WHEN** an approver opens a draft based on revision 2 while the latest is 3 and clicks Rebase
- **THEN** the draft's `base_rev` becomes 3, changes that no longer apply show errors, and Publish is enabled once they are fixed

### Requirement: Draft list and review
The draft list SHALL show each open draft of a tree with its `base_rev`, author
and change count, with discarded drafts in a separate read-only section.
Reviewing a draft SHALL show its net changes per node (`node_changes`) with old
and new versions and group tags, its ordered changes grouped by macro, and the
warnings that will change.

#### Scenario: Review a draft
- **WHEN** an approver opens draft #6 for review
- **THEN** they see each affected node's `from -> to` version and net changes, its grouped changes, and the warning changes

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
user pick a record, and propose an `add` with that AphiaID, under the nearest
node in the tree whose AphiaID is in the record's lineage, which the user may
change. The proposed label SHALL be the record's scientific name with spaces
replaced by underscores and characters that are not machine-safe dropped.

#### Scenario: Suggested parent
- **WHEN** a user picks `Chaetoceros debilis` and the tree has `Chaetoceros` anchored
- **THEN** the proposed `add` has parent `Chaetoceros` and label `Chaetoceros_debilis`

#### Scenario: Unsafe characters
- **WHEN** a user picks a record named `Chaetoceros (Hyalochaete) debilis`
- **THEN** the proposed label is `Chaetoceros_Hyalochaete_debilis`

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
Owners of an organization SHALL be able to clone the displayed revision as a
new tree in that organization by choosing the organization and entering the
new tree's id, title and description. This SHALL
create a new-tree draft that opens in edit mode for review before publishing.

#### Scenario: Clone flow
- **WHEN** an owner of `lab_a` clones revision 3 of `NES2022_taxonomy` as `lab_taxonomy` in `lab_a`
- **THEN** a new-tree draft for `lab_taxonomy` opens in edit mode with one collapsed `import#1` group
