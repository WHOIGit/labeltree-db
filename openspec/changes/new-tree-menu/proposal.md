# Proposal

## Why

Owners can start a new tree only by cloning the revision they are viewing.
There is no way to start an empty tree or one from an import file outside the
one-time setup wizard, and an owner whose organization has no trees yet has to
browse another organization's tree to find even the clone button.

## What Changes

- The tree browser's **Clone as new tree…** button becomes a **New tree ▾**
  menu: **Empty tree…**, **From an import file…** and **From this
  revision…** (the existing clone).
- One dialog serves all three: organization (those the user owns), tree id,
  title, description, and for an import, a text box with a file picker. Each
  creates a saved new-tree draft and opens it in the editor for review,
  validation and publishing, as clone does today. An empty draft has no nodes;
  it can be saved but not published until it has some.
- The organization page gets a **New tree…** button for its owners, opening
  the same dialog (empty or from an import file) for that organization on a
  page of its own, `/orgs/{org}/new-tree/`.
- No API changes: drafts are created with the existing `POST /changesets
  {new_tree, changes}`.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `webapp`: the "Clone as new tree" requirement is replaced by a "New tree
  menu" requirement covering empty, import and clone, plus a requirement for
  starting a new tree from the organization page. The `webapp` capability is
  introduced by the `webapp-and-write-api` change, which must be archived
  first.

## Impact

- **Web app:** `browser.js` (the dialog and menu, replacing the clone code),
  `browser.html` and `browser_dialogs.html`, a new `new_tree_page` view and URL,
  `org.html`.
- **Docs:** `design/webapp.md` (Cloning a tree, New trees, Pages), the web app
  mockup and its spec.
- **Tests:** browser tests for each menu entry and the organization page entry;
  the existing clone test moves to the menu.
