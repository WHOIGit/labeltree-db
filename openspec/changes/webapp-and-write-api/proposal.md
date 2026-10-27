# Proposal

## Why

After `core-tree-model` and `worms-integration`, trees can only be created or
changed from the command line, and the API is open to anyone on the network.
Curators need to draft, review and publish edits in a browser, consumers need
authenticated access, and edits must go through role-checked endpoints.

Depends on `core-tree-model` and `worms-integration`.

## What Changes

- **BREAKING**: every endpoint, including reads, requires authentication
  (session for the web app, API token for services). Unauthenticated requests
  get `401`.
- Per-tree roles `reader`, `drafter`, `approver` and `admin`, plus a global
  tree-creation permission for new-tree changesets, managed in Django admin.
- Write API: `validate`, changeset create/list/get/update/publish/discard with
  `ETag`/`If-Match`, and direct alias add/remove/history.
- Server-rendered web app: tree browser with revision picker, node page, draft
  editor with inline checks, draft list and review, merge and split wizards,
  import wizard, Add from WoRMS, alias editing, and clone as new tree.
- Cloning turns a published revision into a stand-alone new-tree changeset,
  which an approved publish turns into revision 1 of a new tree.

## Capabilities

### New Capabilities

- `access-control`: authentication (sessions, API tokens), per-tree roles, the
  global tree-creation permission, and what each role may do.
- `changeset-api`: the `validate` endpoint and the changeset endpoints,
  including concurrency control (`ETag`/`If-Match`), rebasing, publishing and
  their status codes.
- `webapp`: the tree-management web app: pages, edit mode, draft markings, the
  merge/split/import wizards, Add from WoRMS, alias editing and cloning.

### Modified Capabilities

- `node-aliases`: adds the alias write and history endpoints.
- `tree-import`: adds cloning a published revision into a new-tree changeset.

## Impact

- All API consumers (roi-db, datasetman, annotation tools) need a `reader`
  token before this is deployed.
- New tables for API tokens and per-tree role assignments.
- New Django templates, static assets (Bootstrap 5, Alpine.js, as in the
  mockup), and session/CSRF configuration.
