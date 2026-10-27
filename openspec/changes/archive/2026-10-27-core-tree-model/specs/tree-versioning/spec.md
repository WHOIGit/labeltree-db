# Spec Delta

## Purpose

Defines the versioned label-tree model: trees, tree revisions, nodes and node
versions, the rules for labels, when a node's version increases, and how
deprecation and successors work, so that a node id plus a tree revision always
resolves to exactly one node state.

## ADDED Requirements

### Requirement: Multiple disjoint trees
The system SHALL hold any number of disjoint trees, each identified by a slug id
and carrying a title and description. Each tree SHALL have its own nodes and its
own revisions. A tree SHALL NOT exist without at least one revision.

#### Scenario: Two trees side by side
- **WHEN** trees `NES2022_tags` and `NES2022_taxonomy` are both loaded
- **THEN** each has its own revision numbering starting at 1 and its own set of nodes

#### Scenario: No empty trees
- **WHEN** the set of trees is listed
- **THEN** every tree in it has a latest revision of at least 1

### Requirement: Tree is the implicit root
A node whose parent is null SHALL be a top-level node of its tree. A tree SHALL
allow any number of top-level nodes.

#### Scenario: Several top-level nodes
- **WHEN** a tree is imported with top-level nodes `Chromista`, `Protozoa` and `other`
- **THEN** all three are nodes with parent null and tree depth 0

### Requirement: Globally unique, permanent node ids
Every node SHALL have an integer id that is unique across all trees and never
reused. A node id alone SHALL identify the node and its tree. Node ids SHALL be
assigned only when a changeset is published.

#### Scenario: Id resolves the tree
- **WHEN** a node id is looked up without naming a tree
- **THEN** the node and the tree it belongs to are found

#### Scenario: Ids are never reused
- **WHEN** a node is deprecated and a new node is later added with the same label
- **THEN** the new node receives a different id from the deprecated node

### Requirement: Tree revisions
Each tree SHALL have revisions numbered with consecutive integers starting at 1.
Each revision SHALL be produced by exactly one published changeset and SHALL
record `published_at`, `published_by`, the changeset's author, notes and the
changeset id. A published revision SHALL never change.

#### Scenario: One revision per publish
- **WHEN** a changeset is published on a tree whose latest revision is 7
- **THEN** revision 8 is created and records who published it, when, and from which changeset

### Requirement: Node versions with revision ranges
A node's versioned data (label, parent, `aphia_id`) SHALL be held
in node versions numbered from 1 per node. Each node version SHALL be valid for
the tree revisions `[valid_from_rev, valid_to_rev)`, where a null
`valid_to_rev` means it is current. A node's versions SHALL NOT overlap.

#### Scenario: Version ranges are contiguous runs
- **WHEN** node `Chaetoceros` is v1 at revision 1, v2 at revisions 2-3, v3 at revision 4 and v4 from revision 5
- **THEN** it has four versions with ranges `[1,2)`, `[2,4)`, `[4,5)` and `[5,null)`

### Requirement: Node lifetime fields
Every node SHALL record `created_in_rev`, the revision that added it, and
`deprecated_in_rev`, null while it is in the tree and otherwise the first
revision from which it is no longer in the tree.

#### Scenario: Node added then deprecated
- **WHEN** a node is added in revision 2 and deprecated in revision 5
- **THEN** it records `created_in_rev = 2` and `deprecated_in_rev = 5`

### Requirement: Reading a revision
The state of a tree at revision `r` SHALL be exactly the set of node versions of
that tree with `valid_from_rev <= r < valid_to_rev`, treating a null
`valid_to_rev` as unbounded. A node id plus a revision SHALL give at most one
node version.

#### Scenario: Historic state is preserved
- **WHEN** node L is moved from parent K to parent J in revision 3
- **THEN** reading revision 2 shows L under K, and reading revision 3 shows L under J

### Requirement: Children derived from parent pointers
A node's children at revision `r` SHALL be the nodes whose node version valid at
`r` has that node as parent. Children SHALL NOT be stored separately.

#### Scenario: Children follow the revision
- **WHEN** a child is moved out of node P in revision 4
- **THEN** P's children at revision 3 include the child and at revision 4 do not

### Requirement: Labels are unique per tree revision
Within one tree, no two nodes SHALL hold the same label at the same revision.
Label comparison SHALL be case-sensitive. A label freed by a rename or
deprecation MAY be used by another node in a later revision.

#### Scenario: Case-sensitive uniqueness
- **WHEN** a tree holds label `Chain`
- **THEN** another node in the same revision may hold `chain` but not `Chain`

#### Scenario: Label reused after deprecation
- **WHEN** node A with label `bleb` is deprecated in revision 5 and node B is added with label `bleb` in revision 6
- **THEN** label `bleb` names A at revision 4 and B at revision 6

### Requirement: Machine-safe labels
Every label SHALL match `^[A-Za-z0-9][A-Za-z0-9_.-]*$`.

#### Scenario: Label with a space
- **WHEN** a label `Chaetoceros didymus` is proposed
- **THEN** it is rejected as not machine-safe

### Requirement: What increases a node's version
A node's version SHALL increase in a revision if, comparing its state at the
previous revision with its state at the new one, its label, `aphia_id`,
parent, or set of immediate children differs. Nothing else SHALL increase it,
including descriptions, aliases, WoRMS warnings, a child's own edits and
changes to ancestors.

#### Scenario: Child added
- **WHEN** a node is added under `Chaetoceros`
- **THEN** `Chaetoceros`'s version increases

#### Scenario: Child renamed
- **WHEN** a child of `Chaetoceros` is renamed
- **THEN** `Chaetoceros`'s version does not increase

#### Scenario: Grandparent moved
- **WHEN** a node's grandparent is moved under a different parent
- **THEN** the node's version does not increase

#### Scenario: Alias added
- **WHEN** an alias is added to a node between two revisions
- **THEN** no node version and no revision is created

#### Scenario: Description changed
- **WHEN** a node's description is changed between two revisions
- **THEN** no node version and no revision is created

### Requirement: At most one version increase per revision
A node's version SHALL increase at most once per revision, however many changes
in the revision affect it.

#### Scenario: Moved and renamed together
- **WHEN** one revision both moves and renames a node
- **THEN** the node's version increases by exactly one

#### Scenario: Child deprecated and parent edited together
- **WHEN** one revision deprecates a child of P and renames P
- **THEN** P's version increases by exactly one

### Requirement: Deprecation removes a node from the tree
Deprecating a node in revision `r` SHALL close its current version
(`valid_to_rev = r`), set `deprecated_in_rev = r`, and create no new version.
From `r` on, the node SHALL be absent from children, descendants, label
lookups, search and exports, and its label SHALL be free. Before `r` it SHALL
appear normally. Nothing SHALL ever be deleted.

#### Scenario: Deprecated node at earlier and later revisions
- **WHEN** node `C_didymus_sl` is deprecated in revision 5
- **THEN** it appears among its parent's children at revision 4, is absent at revision 5, and its last version's range ends at 5

### Requirement: Successors of deprecated nodes
A deprecated node SHALL carry a possibly empty list of successor node ids from
the same tree. Successors SHALL be informational pointers, unversioned, and
SHALL be the only record that a merge or split happened. A successor MAY itself
be deprecated later.

#### Scenario: Successor chain
- **WHEN** A is deprecated with successor B, and B is later deprecated with successor C
- **THEN** A's successors are `[B]` and B's successors are `[C]`

#### Scenario: Plain removal
- **WHEN** a node is deprecated without successors
- **THEN** its successor list is empty
