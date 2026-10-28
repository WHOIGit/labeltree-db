# Spec Delta

## Purpose

Controls who can change each tree: published trees are readable by anyone,
while drafts, WoRMS jobs and every change need a logged-in user whose role on
the tree allows it.

## ADDED Requirements

### Requirement: Anonymous reads
The tree and node read endpoints, alias and description history, the WoRMS
warnings report and `/health` SHALL be available without authentication. The
web app SHALL let anonymous users browse trees, revisions and node pages, read
only, with a way to log in.

#### Scenario: Anonymous read
- **WHEN** a request without credentials calls `GET /api/v1/trees`
- **THEN** the API returns every tree

#### Scenario: Anonymous browsing
- **WHEN** an unauthenticated browser opens the tree browser
- **THEN** the tree is shown in static mode with a "Log in to edit" button and no edit or sync controls

### Requirement: Authentication for everything else
Every other endpoint, including the WoRMS lookups, WoRMS jobs, `validate`,
changesets, alias and description writes and tree members, SHALL require
authentication. Unauthenticated API requests SHALL get `401`, and web app pages
that need a login SHALL redirect to the login page.

#### Scenario: Anonymous validate
- **WHEN** a request without credentials calls `POST /api/v1/trees/{tree}/validate`
- **THEN** the API returns `401`

#### Scenario: Anonymous WoRMS search
- **WHEN** a request without credentials calls `GET /api/v1/worms/search?name=Chaetoceros`
- **THEN** the API returns `401` and WoRMS is not called

#### Scenario: Anonymous draft list
- **WHEN** an unauthenticated browser opens a tree's draft list
- **THEN** it is redirected to the login page

### Requirement: Sessions and API tokens
The web app SHALL authenticate with Django sessions, checked against CSRF.
Scripts SHALL authenticate with per-user API tokens sent in a request header,
which are not CSRF-checked. A token's key SHALL be shown once when it is
created and stored only as a hash. Tokens SHALL be revocable.

#### Scenario: Script token
- **WHEN** a script sends a valid token of a user who is `drafter` on the tree and saves a draft
- **THEN** the API returns `201`

#### Scenario: Revoked token
- **WHEN** a revoked token is used
- **THEN** the API returns `401`

### Requirement: Tree roles
A user SHALL hold at most one role on each tree: `reader`, `drafter`,
`approver` or `owner`, in increasing order. Each role SHALL include every
permission of the roles below it. An authenticated request lacking the role an
action needs on that tree SHALL get `403`.

#### Scenario: Approver drafts
- **WHEN** a user who is `approver` on a tree saves a draft on it
- **THEN** the draft is saved

#### Scenario: Member of another tree
- **WHEN** a user who is `drafter` only on `NES2022_tags` saves a draft on `NES2022_taxonomy`
- **THEN** the API returns `403`

### Requirement: Reader permissions
`reader` SHALL allow seeing the tree's drafts, the status of its WoRMS jobs and
its members, and calling the WoRMS lookup endpoints. Drafts SHALL be visible
only to members of the tree.

#### Scenario: Reader lists drafts
- **WHEN** a user who is `reader` on a tree requests its changesets in state `draft`
- **THEN** the drafts are listed

#### Scenario: Reader cannot edit
- **WHEN** a user who is `reader` on a tree updates one of its drafts
- **THEN** the API returns `403`

#### Scenario: Non-member lists drafts
- **WHEN** an authenticated user with no role on a tree requests its drafts
- **THEN** the API returns `403`

### Requirement: Drafter permissions
`drafter` SHALL allow creating, updating, rebasing and discarding any draft on
the tree, not only one's own, running `validate`, starting fetch, `sync_new`
and `sync_tree` jobs, adding and removing aliases, and setting descriptions.

#### Scenario: Editing another drafter's draft
- **WHEN** drafter B updates a draft created by drafter A on the same tree
- **THEN** the update succeeds

#### Scenario: Reader cannot sync
- **WHEN** a user who is `reader` on a tree starts a `sync_new` job on it
- **THEN** the API returns `403`

### Requirement: Approver permissions
`approver` SHALL allow publishing the tree's drafts, including drafts the
approver wrote.

#### Scenario: Drafter publishes
- **WHEN** a user who is `drafter` on a tree publishes a draft
- **THEN** the API returns `403`

#### Scenario: Publishing one's own draft
- **WHEN** an approver publishes a draft they created
- **THEN** the API returns `201`

### Requirement: Owner manages members
`owner` SHALL allow managing the tree's members: `GET /trees/{tree}/members`
lists each member with their role, for any member; `PUT
/trees/{tree}/members/{username}` with `{role}` adds a user or changes their
role, any role including `owner`; `DELETE /trees/{tree}/members/{username}`
removes them, returning `204`.

#### Scenario: Owner raises a member
- **WHEN** an owner sets a drafter's role to `approver`
- **THEN** the member's role is `approver` and they can publish

#### Scenario: Co-owner
- **WHEN** an owner sets another member's role to `owner`
- **THEN** the tree has two owners

#### Scenario: Approver manages members
- **WHEN** an approver changes another member's role
- **THEN** the API returns `403`

### Requirement: Last owner
A tree with an owner SHALL keep at least one. Removing or demoting its last
owner SHALL return `409` with error `last_owner`, except for a site admin.

#### Scenario: Last owner steps down
- **WHEN** the only owner of a tree sets their own role to `approver`
- **THEN** the API returns `409` with error `last_owner`

### Requirement: Site admins
Django superusers SHALL be site admins: they SHALL hold `owner` on every tree,
manage users, tokens and the tree-creator role in Django admin, and start full
cache syncs (`sync_all`). Starting `sync_all` as anyone else SHALL return
`403`. Any authenticated user SHALL be able to read a full cache sync's status.

#### Scenario: Owner starts a full sync
- **WHEN** a user who owns every tree but is not a superuser starts a `sync_all` job
- **THEN** the API returns `403`

### Requirement: Tree creators
Creating, updating, publishing and seeing new-tree changesets (`base_rev:
null`) SHALL require the tree-creator role, which site admins assign in Django
admin. Publishing one SHALL make the publishing user `owner` of the new tree.

#### Scenario: Drafter proposes a new tree
- **WHEN** a user who is not a tree creator creates a changeset with `base_rev: null`
- **THEN** the API returns `403`

#### Scenario: First owner
- **WHEN** a tree creator publishes a new-tree changeset for `NES2022_tags`
- **THEN** the tree exists and that user is its `owner`

### Requirement: Recorded identities
`author`, `published_by`, alias `added_by` and `removed_by`, description
`added_by`, and WoRMS job `started_by` SHALL record the authenticated user's
username, also for token requests.

#### Scenario: Publish via token
- **WHEN** an approver's token publishes a draft
- **THEN** the revision's `published_by` is that approver's username
