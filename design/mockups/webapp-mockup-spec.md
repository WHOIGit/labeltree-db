# Web app mockup spec

Spec for [`webapp-mockup.html`](webapp-mockup.html), an interactive mockup of
the tree browser and draft editor described in [webapp.md](../webapp.md).

The mockup is one static HTML file with no build step: Bootstrap 5 for layout
and widgets, Alpine.js for state, both from a CDN. The example trees from
`labeldata/` are embedded in the file, so it opens straight from disk. Nothing
is sent to a server; "saving" and "publishing" only change in-page state.

## Layout

```
┌──────────────────────────────────────────────────────────────────────────────┐
│ Tree: [NES2022_taxonomy ▾]  Revision: [3 ▾]  Status: Published (frozen)      │
│                                        [Edit ▾] [New tree ▾]                 │
├───────────────────────────────────────────┬──────────────────────────────────┤
│ Tree              [filter...] [+ New node]│ Changes                          │
│ ▾ Chromista  WoRMS 7                  ⋮   │  summary: errors / warnings      │
│   ▸ Acantharia  WoRMS 586732          ⋮   │  ▾ merge#1                       │
│   ▾ Bacillariophyceae  WoRMS ⚠1       ⋮   │     1 add  …                     │
│      …                                    │     2 move …                     │
│ ▸ other                               ⋮   │  3 edit …                        │
│                                           │  notes                           │
└───────────────────────────────────────────┴──────────────────────────────────┘
```

- **Top bar:** tree, revision, draft and status, plus the action buttons for
  the current mode.
- **Left panel:** the tree. The **New node** button sits at its top right,
  next to a label filter.
- **Right panel:** the list of atomic changes.

## Modes and status

There are two modes. **Static** mode browses published revisions. **Edit**
mode composes a changeset against a base revision.

| Mode | Tree selector | Revision | Draft | Status |
|---|---|---|---|---|
| Static | selectable | selectable, any published revision | hidden | `Published (frozen)`, or `None` if the tree has no revisions yet |
| Edit, nothing changed yet | fixed | fixed: `base_rev` | `new` | `None` |
| Edit, unsaved changes | fixed | fixed: `base_rev` | `new` or `#n` | `Draft (unsaved)` |
| Edit, saved | fixed | fixed: `base_rev` | `#n` | `Draft (saved)` |
| Viewing a discarded draft | fixed | fixed: its `base_rev` | `#n` | `Discarded (frozen)` |

Status names the changeset whose changes the right panel shows. In static mode
that is the changeset that produced the selected revision, so the right panel
answers "what changed in revision r". `None` means no changeset exists yet.

A tree can have several drafts, and any drafter may work on any of them
([webapp.md](../webapp.md#changesets-and-concurrency)). The **Edit** button is
a menu:

- **New draft from revision r** (the latest revision)
- **Open draft #n:** one entry per open draft, showing its `base_rev`, author
  and change count
- **Discarded drafts:** a separate section; these open read-only

In edit mode the top bar shows **Draft: #n**. Leaving edit mode with unsaved
changes asks for confirmation.

### Buttons per state

| State | Buttons |
|---|---|
| Static | **Edit ▾**, **WoRMS sync ▾**, **New tree ▾** (owner), **AMPLIfy members**; anonymous visitors see only **Log in to edit** |
| Edit (`None`, unsaved, saved) | **Validate**, **Save Draft** (enabled once the current list is validated), **Publish Revision** (approver; enabled when saved, validated and free of errors), **Discard Draft** (saved drafts), **Exit** |
| Discarded (frozen) | **Exit** |

The revision picker lists each revision with its publish date and author.

**Publish Revision** asks for notes, then creates revision `latest + 1` and
returns to static mode on that revision. **New tree ▾** offers **Empty
tree…**, **From an import file…** (pasted JSON; malformed files are reported)
and **From this revision…** (a clone), in one dialog with the kind as radio
buttons; each creates a new-tree draft and opens it. See
[webapp.md](../webapp.md#new-trees).

The mockup's top bar also has a **Role** selector (`anonymous`, `reader`,
`drafter`, `approver`, `owner`: the user's role in the tree's organization,
each including the ones below), so role-gated buttons can be tried out.
Disabled buttons show the reason as a tooltip.

**Validate** (edit mode) simulates the real flow: AphiaIDs the changes set that
aren't cached start a fetch job with a progress bar, including one retry bar,
then the results show in the changes panel tabs and **Save Draft** is enabled.
Any later edit marks the results out of date and disables Save again.

## The tree

- Nested list with expand and collapse per node, plus **Expand all** and
  **Collapse all**. Each node shows its label and child count. Double-clicking
  a node opens its details.
- **Filter box:** matches labels and aliases, and expands the matching nodes'
  ancestors.
- **Badges** after the label:
  - **AphiaID pill** (🪱) when the node has an `aphia_id`, linking to
    `https://www.marinespecies.org/aphia.php?p=taxdetails&id=<aphia_id>` in a
    new tab: green without warnings, orange with a `!` badge with any current
    [WoRMS warning](../worms.md#the-warnings), red with a `?` badge with
    `unknown_aphia`, grey when never fetched (here: added in the draft). Its
    tooltip shows the AphiaID and each warning.
- **Warnings panel** (Warnings / Hide warnings): the nodes with current WoRMS
  warnings; hovering highlights a node, clicking jumps to it.
- **WoRMS sync ▾**: Sync new AphiaIDs and Sync this tree (drafter); Full cache
  sync is shown disabled (site admins only). A started sync shows a progress
  bar in the changes panel, with a retry bar while an AphiaID is retried.
- **Draft markings** (edit mode only), using the colour key from
  [diagrams/README.md](../diagrams/README.md): **green** for added nodes,
  **yellow** for nodes whose version will increase (edited, moved, or a
  child added, moved or deprecated), with a `vN → vN+1` badge, and **grey,
  struck through** for nodes deprecated in the draft. Deprecated nodes stay visible in place until the
  draft is published. This is not a full diff view, which is out of scope for
  now.

### Node menu

Every node has a **⋮** menu in both modes. Items that only make sense in a
changeset are shown disabled in static mode, with the hint "Edit mode only".

| Item | Mode | Result |
|---|---|---|
| Details… | both | modal: id, label, version, parent, description, AphiaID, aliases, warnings |
| Edit aliases… | both (`drafter`) | saved at once via `POST /nodes/{id}/aliases` and `DELETE /nodes/{id}/aliases/{alias_id}`, one alias at a time, not part of any changeset. Disabled for nodes added in the draft, which have no id yet. |
| Edit description… | both (`drafter`) | saved at once via `PUT /nodes/{id}/description`, not part of any changeset; an empty description clears it. Disabled for nodes added in the draft, whose description is part of their `add`. |
| Edit… | edit | one `edit` change |
| New child… | edit | one `add` change under this node |
| Move to… | edit | one `move` change |
| Split… | edit | wizard, a `split#n` group |
| Merge… | edit | wizard, a `merge#n` group |
| Deprecate… | edit | one `deprecate` change |

Aliases and descriptions are not versioned and not part of changesets
([backend.md](../backend.md#labels-aliases-and-descriptions)), so editing them works in
static mode and from a frozen view, and the change is live immediately. Both
dialogs say so.

## Dialogs and wizards

Every dialog checks its input as the user types: labels must be machine-safe
(`^[A-Za-z0-9][A-Za-z0-9_.-]*$`) and not used by another node in the tree
after the changes before it. **Add** stays disabled until the input is valid.

- **New node** (left panel button): label, parent (a node, or top level),
  initial description, AphiaID, initial aliases. Gives one `add` with a
  placeholder id `new:k`. The initial description and aliases ride on the `add`
  change, as for imports.
- **New child:** the same form with the parent fixed.
- **Edit:** label and AphiaID, prefilled. Gives one `edit` holding only the
  changed fields. Clearing the AphiaID sets it to null. The description is
  edited separately (Edit description…), outside the changeset.
- **Move to:** closes the menu and enters pick mode. A banner reads "Click the
  new parent for X", with **Make top level** and **Cancel**. The node and its
  descendants can't be picked, so no cycle is possible. Esc cancels. Gives one
  `move` with `from_parent` and `to_parent`.
- **Deprecate:** blocked with an explanation if the node still has children
  (move, merge or split them first). Otherwise an optional successor picker.
  Gives one `deprecate`.
- **Merge** (from node A):
  1. Choose the nodes to merge with A. Siblings are listed first, but any node
     in the tree can be chosen.
  2. Choose **with replacement** (default) or **without replacement**, in which
     case one of the nodes survives and the others merge into it.
  3. With replacement: label, initial description and AphiaID of the new node, and its
     parent (by default the merged nodes' common parent).
  4. Review the expanded changes ([webapp.md](../webapp.md#merge-and-split)).
     **Add to draft** appends them as one `merge#n` group.
- **Split** (from node A):
  1. Choose **with replacement** (default) or **without replacement**.
  2. Name the new nodes: at least two with replacement (A1, A2, …), at least
     one without (A2).
  3. Assign A's children to the new nodes. With replacement, every child must
     be assigned; without, unassigned children stay with A.
  4. Review the expanded changes, then **Add to draft** as one `split#n` group.

After a merge is published, the deprecated nodes' labels and aliases are copied
into the surviving or new node's aliases
([webapp.md](../webapp.md#aliases-after-a-merge)). The merge review step says
so.

## Changes panel

In edit mode the panel has tabs: **As edited** (the editable list below),
**As reduced**, **By node** (the net change and version of each affected
node), **Summary**, **WoRMS warnings** and **Errors**, the last two with
counts. After Validate, tabs with new results show an unread dot until opened.
Before validating, the result tabs ask for Validate; after an edit, they are
greyed as out of date.

- **Summary line:** number of changes, errors and WoRMS warnings, then new
  nodes, version increases and deprecations.
- **Ordered list.** Each row shows its position, an op badge (`add`, `edit`,
  `move`, `deprecate`), and a one-line description, e.g.
  `move Licmophora: Bacillariophyceae → Fragilariophyceae`. Placeholders are
  shown by label, e.g. `new:1 (Chaetocerotaceae_sl)`.
- **Groups** (`merge#1`, `split#2`, `import#1`) collapse into a header with
  their change count. Large groups such as `import#1` start collapsed.
- **Inline checks** under the change that caused them, once validated:
  structural errors in red (they block publishing), WoRMS warnings in yellow
  (they don't). Saving a draft with errors asks for confirmation first.
- **Conflicts** appear under the summary line whenever the draft's `base_rev`
  is not the latest revision, naming the later revisions and the nodes the
  draft touches that they changed, with a **Rebase on revision r** button.
  Publishing stays disabled until the draft is rebased. Rebasing sets
  `base_rev` to the latest revision; changes that no longer apply then show as
  errors to fix.
- **Hovering** a change highlights the nodes it touches in the tree.
  **Clicking** it expands the tree to its node and scrolls there.
- **Removing** (edit mode): each change and each group has a ✕. Removing a
  change that later changes depend on, such as an `add` whose node a later
  `move` uses as a parent, marks those later changes as errors rather than
  removing them silently.
- **Notes** box at the bottom: the changeset notes, editable in edit mode.
- **Frozen views** (static mode, discarded drafts) show the same list without
  the ✕ buttons or notes editing.

## Mock data

- Both example trees from `labeldata/`, loaded as `import#1` (revision 1).
- Two made-up later revisions of `NES2022_taxonomy`, so the revision picker
  and frozen change list have something to show: revision 2 (a label fix and a
  new morphotype) and revision 3 (`merge#1` with replacement). `Mesodinium`'s
  description is set directly after revision 2, outside any changeset.
- One open draft, #6, based on revision 2. It edits a node that revision 3
  deprecated, so it shows a conflict.
- One discarded draft, #3: a `split#1` of `Eucampia`.
- Made-up current WoRMS warnings (`out_of_lineage`, `unaccepted_aphia`,
  `unknown_aphia`) on `Phaeocystis`, `Kryptoperidinium_triquetrum`,
  `Tintinnina` and `Nanoneis`.
- Made-up members of AMPLIfy, one per role.
- Node ids are made up. AphiaIDs are real, from the example files.

The mockup replays the published changesets to build each revision, including
node versions, and checks drafts with the same code. It checks the structural
rules it can check locally: machine-safe and unique labels, a target, parent or
successor that isn't in the tree, cycles, and deprecating a node with
children. Conflicts are computed for real: a draft whose `base_rev` is behind
the latest revision is in conflict, and the nodes it touches that a later
revision also touched are listed. It does not call WoRMS:
`duplicate_aphia` is computed locally for `add` and `edit`, and other changes
show the touched node's current warnings.

## Organization page

**AMPLIfy members** opens the organization's members with their roles. Owners
change roles there; demoting the last owner is refused with an explanation.

## Setup wizard

**New-instance setup** opens what a site admin sees on an instance with no
trees (see [Setting up a new instance](../webapp.md#setting-up-a-new-instance)),
as a dialog with the three steps marked at the top:

1. **Organization:** an id (a slug) and a name. `amplify` is refused as taken.
   Skip is disabled until there is an organization.
2. **Users:** a username and a role. A username that isn't a member of the
   mock's organization gets two password fields and **Create account and
   add**; a password under 8 characters or a mismatch is refused. The first
   user defaults to `owner`, later ones to `drafter`. Continue or Skip with a
   username typed but not added asks whether to discard it.
3. **Trees:** a tree id, a title and the import JSON in a text box. Malformed
   JSON, a node without a `label`, a label used twice and a taken tree id are
   reported; otherwise the tree is listed as published at revision 1. The
   mock doesn't fetch WoRMS records or add the tree to the tree picker.

**Done** and **Skip** on the last step close the dialog with a toast naming
where the web app goes: the first tree, or the organization's page. With a
tree id or JSON typed but not imported, they ask whether to discard it first.

## Out of scope for now

The web app itself (`src/webapp`, `src/static/app`) implements everything
below; the mockup leaves it out.

- A visual diff of draft against base revision, beyond the draft markings.
- Reordering changes by drag and drop.
- Import from file and **Add from WoRMS**.
- The node page, the draft list and review pages, and the user's own page.
- Real reduction in **As reduced**: the mockup lists the changes as edited.
