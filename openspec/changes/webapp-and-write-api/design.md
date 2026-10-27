# Design

## Context

Builds on `core-tree-model` (engine, read API, `import_tree`) and
`worms-integration` (checks, lookups, drift). The engine already reduces,
validates and publishes changesets and is called only from management commands.
The interactive mockup `design/mockups/webapp-mockup.html` and its spec define
the intended look and interaction, and already re-implement the structural
checks in JavaScript. See proposal.md for motivation.

## Goals / Non-Goals

**Goals:**

- One authorisation layer shared by API and web app.
- Keep the engine the only place that reduces, validates and publishes. The
  browser only composes change lists and renders server results.
- Reuse the mockup's layout and Alpine.js state model rather than redesign.

**Non-Goals:**

- A visual diff of a draft against its base revision beyond the draft markings.
- Reordering changes by drag and drop.
- Linking a clone to its source tree.
- Managing roles or tokens outside Django admin.

## Decisions

### Authentication

- **Sessions** via Django auth for the web app, with standard login and CSRF.
  django-ninja's `SessionAuth` (CSRF-checked) covers API calls the browser
  makes.
- **Tokens:** an `ApiToken` model (hashed key, owning user, name, created,
  revoked) checked by a django-ninja `APIKeyHeader` (`Authorization: Token
  <key>`). Service accounts are ordinary Django users with no password.
- Both auth classes are set as the API's global `auth`, so a route can't be
  left unauthenticated by forgetting it.

Alternative: django-rest-knox or OAuth. Rejected, since nothing here needs
expiry flows or third-party login.

### Roles

A `TreeRole(user, tree, role)` table with a unique `(user, tree, role)`. The
global tree-creation permission is the Django model permission
`trees.add_tree`, assignable to users or groups in Django admin. A single helper
`require(user, tree, *roles)` raises `403`, and every router and view calls it.
The rules come from the `access-control` spec in one place:

- reads: any role
- draft, validate, aliases: `drafter`
- publish: `approver`
- drift: `drafter`, `approver` or `admin`

Publishing a new tree inserts `TreeRole(publisher, tree, admin)` in the publish
transaction. `GET /trees` filters to trees the user has a role on.

### Changeset endpoints

These are thin wrappers around the engine. The `ETag` of a draft is a hash of
`(id, updated_at, base_rev, changes)`. `PUT` and `publish` compare `If-Match`
inside a `SELECT ... FOR UPDATE` on the changeset row, so the `412` check and
the write are atomic. `validate` runs the same engine path as save, without the
final write, and returns the reduced list as `reduced_changes`, so the browser
shows what save would store. New-tree changesets live at `POST /changesets`
because they have no tree in the path.

### Web app

- Server-rendered Django templates for the page frame, login, node page and
  draft list. The tree browser and draft editor are one page whose state is an
  Alpine.js store, ported from the mockup, that talks to `/api/v1` with the
  session.
- The mockup's local JavaScript checks are dropped in favour of calling
  `validate`, debounced at about 300 ms, so the server stays the single source
  of truth. The instant per-keystroke label regex check stays client-side,
  because it is trivial and helps typing.
- Merge, split, import, clone and Add from WoRMS are client-side expanders that
  produce grouped change lists, with no endpoints of their own. Import parsing
  runs in the browser using the same rules as the server format, and clone
  fetches `/trees/{tree}/nodes_as_tree?rev=` and runs it
  through the same client expander. The server re-validates everything on save.
- Aliases after a merge: after a successful publish response, the client issues
  `POST /nodes/{id}/aliases` for each missing label and alias. A failure is
  shown to the user with a retry. It is not transactional with the publish,
  which matches the spec, since aliases sit outside changesets.

Alternative: an HTMX-style fully server-rendered editor. Rejected, because the
mockup's interaction (live markings, pick mode, wizards) is already built in
Alpine.js and maps directly onto the API.

### Bootstrap and Alpine from static files

Bootstrap 5 and Alpine.js are vendored into `static/`, not loaded from a CDN,
so the app works on isolated lab networks.

## Risks / Trade-offs

- [BREAKING auth on reads cuts off existing consumers] → Issue `reader` tokens
  to roi-db and datasetman before deploy, and announce the cut-over date.
- [Client-side import parsing diverges from the server's] → The server is
  authoritative and returns errors per change. A shared JSON fixture set is
  tested against both parsers.
- [Debounced `validate` load with large imports] → `validate` on a ~250-change
  import is a single in-memory pass. Measure it and raise the debounce for
  `import#` groups if needed.
- [Alias copy after a merge can partially fail] → The UI lists any aliases it
  could not copy and offers a retry.

## Migration Plan

1. Deploy the `ApiToken` and `TreeRole` migrations.
2. In Django admin, create service accounts and tokens for roi-db and
   datasetman with `reader` on both NES2022 trees, and create curator accounts
   with their roles. Grant `trees.add_tree` to tree administrators. Assign
   `admin` on existing trees to the operator who loaded them.
3. Switch consumers to send tokens, then deploy the auth-enforcing release.

Rollback: revert to the previous release. Tokens and roles stay in place,
unused.
