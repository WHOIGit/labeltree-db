# Design

## Context

See proposal.md for why. Clone already builds an `import#1` change list in the
browser (`expandImport(cloneData(BASE))`), posts it with `POST /changesets
{new_tree, changes}` and redirects to `/changesets/{id}/edit/`. A new-tree draft
with no changes can be saved; publishing it is refused with `empty_changeset`.
The browser page (`_browser`) assumes either a tree or a draft.

## Goals / Non-Goals

**Goals:** one dialog and one code path for all three ways to start a tree;
reachable from an organization with no trees.

**Non-Goals:** publishing straight from the dialog (the setup wizard does that,
once); importing into an existing tree (the editor's Import); any API change.

## Decisions

### One dialog, three kinds
The clone dialog becomes the new-tree dialog, with `f.kind` of `empty`,
`import` or `clone`. The menu opens it at the chosen kind, and radio buttons in
the dialog switch between them (`clone` only when a revision is shown). The
changes come from:
- `empty`: none;
- `import`: `JSON.parse` and `expandImport(data, {group: 'import#1'})`, errors
  shown in the dialog with the parser's message or the format error's position;
- `clone`: as today.

Notes: `New tree.`, `Import of <file name or "pasted JSON">.`, and the clone's
`Clone of <tree> revision <n>.`. The dialog's id check, title check and
organization picker stay as they are.

*Alternative:* three dialogs. Rejected: they would share every field.

### The organization page opens a tree-less browser
`/orgs/{org}/new-tree/` (owner of `org`, or site admin; others get the `403`
page) renders the browser with no tree and no draft, with page data
`start_new_tree: org`. On load the browser opens the dialog at `empty` with that
organization picked; cancelling goes back to the organization page. `_browser`
takes the organization from the tree, the draft or this argument.

*Alternative:* a separate small page and component for the form. Rejected: it
would duplicate the dialog, its checks and the import parsing.

## Risks / Trade-offs

- [A tree-less browser shows an empty top bar behind the dialog] → Acceptable
  for a page whose only purpose is the dialog; cancelling leaves it.
- [Empty drafts accumulate if owners start trees and abandon them] → They are
  ordinary drafts, listed and discardable like any other.
