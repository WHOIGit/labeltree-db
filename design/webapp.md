# Web app

The tree-management web app lives in the same Django project as the API, using
server-rendered templates. It is where trees are browsed, edited, reviewed and
published. All edits go through the [write endpoints](api.md#write-endpoints).

An interactive mockup of the tree browser and draft editor is in
[`mockups/webapp-mockup.html`](mockups/webapp-mockup.html), specified in
[`mockups/webapp-mockup-spec.md`](mockups/webapp-mockup-spec.md).

![Web app mockup](mockups/webapp-mockup-snapshot.png)

## Pages

- **Tree browser:** search, warning badges, and a revision picker to view past
  revisions (including nodes deprecated since).
- **Node page:** current state, version history, WoRMS card, successors if
  deprecated.
- **Draft editor:** compose an ordered list of atomic changes, with check
  results shown inline. Merge, split and import are wizards that expand into
  atomic changes, which can be edited before saving.
- **Draft list and review:** the ordered change list grouped by macro, the
  affected nodes with their old → new versions, and a diff view. Approvers
  publish from here, with notes.
- **Add from WoRMS:** search by name, pick a record, and accept the suggested
  parent from its lineage.

Roles are described in [api.md](api.md#authentication-and-roles).

## Changesets and concurrency

![Changeset lifecycle](diagrams/03-changeset-lifecycle.png)

A changeset is a proposed tree revision: an ordered list of
[atomic changes](backend.md#atomic-changes) against `base_rev`. It has three
states: `draft`, `published` and `discarded`. Publishing creates the next
revision (latest + 1); since `base_rev` must be the latest revision at publish
time, this is always `base_rev + 1`. A changeset with `base_rev: null` proposes
a new tree: it carries the tree's id, title and description, and publishing it
creates the tree together with its revision 1 ([New trees](#new-trees)).

- **Composing happens in the browser.** The user builds the change list
  locally, including merge and split presets. The browser calls `validate` as
  the list changes, so check results appear as the user works.
- **Saving a draft** sends the whole list to the server. Creating a draft
  records its `base_rev`; updating it replaces its changes, notes and
  `base_rev`. Saving [reduces](backend.md#reduction-on-save) the change list.
  Drafts are visible to the tree's drafters, approvers and admins.
  Any drafter may update or discard any draft, not only their own.
- **Publishing** is done by an approver. `base_rev` must equal the latest
  revision `r`, and all checks run again. While one publish on a tree is in
  progress, any other publish on that tree is refused at once
  (`publish_in_progress`). If the checks pass, publishing atomically creates revision
  `r+1`, closes the old node versions (`valid_to_rev = r+1`), opens the new
  ones, and records new `NODE_WARNINGS` for touched nodes whose warnings
  changed. A published changeset can no longer be edited.
- **Discarding** a draft keeps it for the record with its changes frozen. It
  can't be edited or published.

Publishing is blocked by a **conflict** or a **structural error**.
[WoRMS problems](worms.md#the-warnings) are warnings, never errors.

**Conflict:** `base_rev` is not the tree's latest revision (`stale_base`).
A draft that has fallen behind must be **rebased** before it can be published:
its `base_rev` is set to the latest revision and its changes are rechecked;
changes that no longer apply show as errors to fix. To help, `validate` lists
the nodes the draft touches that later revisions changed. A new-tree changeset
is refused if a tree with its id already exists.

**Structural errors:**

- a cycle
- a target node that is not in the tree (deprecated)
- a parent that is not in the tree, or is in a different tree; no node left in
  the tree may reference a deprecated node
- a `move` whose `from_parent` isn't the node's current parent
- a successor that is deprecated, in another tree, or the node itself
- deprecating a node that still has children (decide what happens to them
  first)
- a label that isn't machine-safe
- a label already used by another node in the tree. Because each change is
  checked against the state left by the changes before it, swapping two labels
  needs a temporary label in between. If two drafts add the same label,
  whichever is published second is blocked.

The draft preview lists "warnings that will change" separately from "nodes
whose version will increase". The two don't always overlap: warnings aren't
versioned, and reflect the most recently fetched WoRMS data.

## Merge and split

Merge and split are presets that expand into ordered atomic changes sharing a
`group` id (e.g. `merge#1`). Reviewers see the expanded list and every node it
touches.

**With replacement** means the original node(s) are deprecated, with the new
node(s) as [successors](backend.md#deprecation-and-successors). **Without
replacement** means a node keeps its id while its meaning broadens (merge) or
narrows (split). Replacement is the default for both: without it, a surviving
node's meaning changes under the same id.

### Merge without replacement

A into B. B keeps its id and broadens.

```
1..n  move     each child of A → B
n+1   deprecate A  successors=[B]
```

![Merge without replacement](diagrams/04-node-merge-and-split-options/04a-merge-without-replacement.png)

Old ROIs labelled B stay correct, because B only got broader. But if A had no
children, B's set of children doesn't change, so B's version doesn't increase
and nothing records that B's meaning changed. Use this only when that's
acceptable to consumers, e.g. when A was a misspelt duplicate of B.

### Merge with replacement (default)

A and B are both deprecated, and a new C replaces them.

```
1     add      C (sibling of A and B)
2..n  move     each child of A and B → C
n+1   deprecate A  successors=[C]
n+2   deprecate B  successors=[C]
```

![Merge with replacement](diagrams/04-node-merge-and-split-options/04b-merge-with-replacement.png)

### Split without replacement

A keeps its id and narrows, and a new sibling takes some children.

```
1     add      A2 (sibling of A)
2..n  move     selected children of A → A2
```

![Split without replacement](diagrams/04-node-merge-and-split-options/04c-split-without-replacement.png)

Use this only when old ROIs labelled A are still correct as A.

### Split with replacement (default)

A is deprecated, and two new nodes replace it.

```
1     add      A1 (sibling of A)
2     add      A2 (sibling of A)
3..n  move     each child of A → A1 or A2   (UI requires every child to be assigned)
n+1   deprecate A  successors=[A1, A2]
```

![Split with replacement](diagrams/04-node-merge-and-split-options/04d-split-with-replacement.png)

Use the replacement form whenever existing ROIs labelled A might belong to
either new node. Otherwise those ROIs would silently keep a label whose meaning
has narrowed.

### Aliases after a merge

Aliases aren't part of changesets, so after a merge is published the UI copies
each deprecated node's label and aliases into the surviving or new node's
alias list.

## Import

There is no separate import mechanism. Importing is a feature of the draft
editor: the drafter uploads or pastes a file, and it expands into `add` changes
sharing one group (e.g. `import#4`), using
[placeholder ids](backend.md#change-records) for the new nodes. The imported
nodes go at top level or under a chosen node, and the changes can be edited
before saving. From there it is an ordinary draft. Its labels must not clash
with labels already in the tree. A node's `description` and `aliases` from the
file are carried on its `add` change and written as its initial description and
aliases on publish.

### Import format

The import format is the [content shape](api.md#content-shape), nested, with
only `label` required:

```
{tree: "NES2022_taxonomy",
 nodes: [
   {label: "Chromista", aphia_id: 7, children: [
     {label: "Acantharia", aphia_id: 586732},
     ...
   ]}
 ]}
```

- The structure comes from the nesting.
- Per node, only `label`, `aphia_id`, `description`, `aliases` and `children`
  are read, and any of them except `label` may be left out. `description` and
  `aliases` become the new node's initial description and aliases.
- Everything else is **ignored**, including `id` and `tree`. New ids are
  assigned on publish. Any response in the content or detailed shape can
  therefore be imported again as is, e.g. the output of
  `/trees/{tree}/nodes_as_tree` or `/export`.

### New trees

There are no empty trees: a tree exists only once it has a revision.

1. A user holding the global tree-creation permission creates a changeset with
   `base_rev: null` carrying the new tree's id, title and description, by
   importing, building it by hand, or both.
2. A user holding the tree-creation permission publishes it. This creates the
   tree and its revision 1 together, and gives the publisher `admin` on the
   new tree, from where they assign its roles.

So every revision, including revision 1, comes from a published changeset. The
[example trees](backend.md#example-trees) are loaded this way, through the
`import_tree` management command.

### Cloning a tree

Cloning converts a published revision of an existing tree into a stand-alone
new-tree changeset. It is the [new tree](#new-trees) flow with the import taken
from that revision:

1. A user with the tree-creation permission enters the new tree's id, title and
   description.
2. The source revision's nodes become an `import#1` draft with
   `base_rev: null`, as if its `/export` output had been imported. Labels and
   AphiaIDs at that revision, and the current descriptions and aliases, are
   copied.
3. Publishing it creates the new tree with revision 1.

The new tree's nodes get new ids, and nothing links them to the source nodes.
