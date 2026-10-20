# Web app

The tree-management web app lives in the same Django project as the API, using
server-rendered templates. It is where trees are browsed, edited, reviewed and
published. All edits go through the [write endpoints](api.md#write-endpoints).

> **TODO:** mockup of the tree browser and draft editor, as
> `diagrams/07-webapp-mockup.png`.

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
revision (latest + 1, which may be later than `base_rev + 1`). A changeset with
`base_rev: null` proposes the first revision of an empty tree
([New trees](#new-trees)).

- **Composing happens in the browser.** The user builds the change list
  locally, including merge and split presets. The browser calls `validate` as
  the list changes, so check results appear as the user works.
- **Saving a draft** sends the whole list to the server. Creating a draft
  records its `base_rev`; updating it replaces its changes, notes and
  `base_rev`. Drafts are visible to the tree's drafters, approvers and admins.
  Any drafter may update or discard any draft, not only their own.
- **Publishing** is done by an approver. All checks run again against the
  latest revision `r`. If they pass, publishing atomically creates revision
  `r+1`, closes the old node versions (`valid_to_rev = r+1`), opens the new
  ones, and records new `NODE_WARNINGS` for touched nodes whose warnings
  changed. A published changeset can no longer be edited.
- **Discarding** a draft keeps it for the record with its changes frozen. It
  can't be edited or published.

Publishing is blocked by a **conflict** or a **structural error**.
[WoRMS problems](worms.md#the-warnings) are warnings, never errors.

**Conflict:** a node touched by the changeset has a newer version than at
`base_rev`, or has been deprecated since. The drafter fetches the latest
revision, adjusts the changes and updates the draft with the new `base_rev`.
Touched nodes include parents whose children change, so two drafts adding
different children under the same parent will conflict; that's accepted. A
draft with `base_rev: null` conflicts as soon as the tree has any revision.

**Structural errors:**

- a cycle
- a target node that is not in the tree (deprecated)
- a parent that is not in the tree, or is in a different tree
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
with labels already in the tree. A node's `aliases` from the file are carried
on its `add` change and written as its initial aliases on publish.

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
  are read, and any of them except `label` may be left out.
- Everything else is **ignored**, including `id` and `tree`. New ids are
  assigned on publish. Any response in the content or detailed shape can
  therefore be imported again as is, e.g. the output of
  `/trees/{tree}/nodes_as_tree` or `/export`.

### New trees

1. An admin creates an empty tree (id, title, description) and assigns its
   roles. It has no revisions and is hidden from `GET /trees` until it has one.
2. A drafter creates a changeset with `base_rev: null`, by importing, building
   it by hand, or both.
3. An approver publishes it, creating revision 1.

So every revision, including revision 1, comes from a published changeset. The
[seed trees](backend.md#seed-trees) are created this way.
