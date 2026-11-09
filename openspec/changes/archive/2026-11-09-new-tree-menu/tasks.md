# Tasks

## 1. New tree menu

- [x] 1.1 Turn the clone dialog into the new-tree dialog (`f.kind` empty / import / clone, kind radios, import text box and file picker, per-kind notes) and replace **Clone as new tree…** with a **New tree ▾** menu; verify browser tests for the empty-tree, tree-from-import, clone, malformed-import and not-an-owner scenarios
- [x] 1.2 Add `/orgs/{org}/new-tree/` (owner or site admin; `403` page otherwise) rendering the browser with no tree and the dialog open for that organization, cancel returning to the organization page, and a **New tree…** button on the organization page for owners; verify page tests for access and the button, and a browser test for an owner of an organization with no trees starting an empty tree
- [x] 1.3 Update `design/webapp.md` (Pages, New trees, Cloning a tree), the web app mockup and its spec for the menu; verify the documents link correctly and a Playwright run through the mockup's menu

## Workflow follow-up

- Archive `webapp-and-write-api` before archiving this change: this change's `webapp` delta removes a requirement that change introduces.
