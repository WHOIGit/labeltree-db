# Spec Delta

## Purpose

Controls who can change each tree: published trees are readable by anyone,
while drafts, WoRMS jobs and every change need a logged-in user whose role in
the tree's organization allows it.

## ADDED Requirements

### Requirement: Anonymous reads
The tree, node and organization read endpoints, alias and description history,
the WoRMS warnings report and `/health` SHALL be available without
authentication. The
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
changesets, alias and description writes and organization members, SHALL require
authentication. Unauthenticated API requests SHALL get `401`, and web app pages
that need a login SHALL redirect to the login page.

#### Scenario: Anonymous validate
- **WHEN** a request without credentials calls `POST /api/v1/changesets/validate`
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
- **WHEN** a script sends a valid token of a user who is `drafter` in the tree's organization and saves a draft
- **THEN** the API returns `201`

#### Scenario: Revoked token
- **WHEN** a revoked token is used
- **THEN** the API returns `401`

### Requirement: Organizations
Every tree SHALL belong to exactly one organization. `GET /orgs` SHALL list the
organizations with their names and trees, and `GET /trees` SHALL include each
tree's `org`, both without authentication. Only site admins SHALL create
organizations and move a tree to another organization, in Django admin.

#### Scenario: Trees by organization
- **WHEN** a request without credentials calls `GET /api/v1/orgs`
- **THEN** the API lists organization `amplify` (`AMPLIfy`) with trees `NES2022_tags` and `NES2022_taxonomy`

### Requirement: Organization roles
A user SHALL hold at most one role in each organization: `reader`, `drafter`,
`approver` or `owner`, in increasing order. Each role SHALL include every
permission of the roles below it, and SHALL apply to every tree of the
organization. An authenticated request lacking the role an action needs in
the tree's organization SHALL get `403`.

#### Scenario: Approver drafts
- **WHEN** a user who is `approver` in a tree's organization saves a draft on it
- **THEN** the draft is saved

#### Scenario: Member of another organization
- **WHEN** a user who is `drafter` only in organization `lab_a` saves a draft on a tree of organization `amplify`
- **THEN** the API returns `403`

#### Scenario: New tree in the organization
- **WHEN** a user who is `drafter` in `amplify` saves a draft on a tree published in `amplify` after they joined
- **THEN** the draft is saved, without any change to their membership

### Requirement: Reader permissions
`reader` SHALL allow seeing the drafts of the organization's trees, the status
of their WoRMS jobs and the organization's members, and calling the WoRMS
lookup endpoints. Drafts SHALL be visible only to members of the tree's
organization.

#### Scenario: Reader lists drafts
- **WHEN** a user who is `reader` in a tree's organization requests its changesets in state `draft`
- **THEN** the drafts are listed

#### Scenario: Reader cannot edit
- **WHEN** a user who is `reader` in a tree's organization updates one of its drafts
- **THEN** the API returns `403`

#### Scenario: Non-member lists drafts
- **WHEN** an authenticated user with no role in a tree's organization requests its drafts
- **THEN** the API returns `403`

### Requirement: Drafter permissions
`drafter` SHALL allow creating, updating, rebasing and discarding any draft on
the organization's trees, not only one's own, validating changes to them,
starting fetch jobs for the organization and `sync_new` and `sync_tree` jobs
on its trees, adding and removing aliases, and setting descriptions.

#### Scenario: Editing another drafter's draft
- **WHEN** drafter B updates a draft created by drafter A in the same organization
- **THEN** the update succeeds

#### Scenario: Reader cannot sync
- **WHEN** a user who is `reader` in a tree's organization starts a `sync_new` job on it
- **THEN** the API returns `403`

### Requirement: Approver permissions
`approver` SHALL allow publishing drafts on the organization's trees,
including drafts the approver wrote.

#### Scenario: Drafter publishes
- **WHEN** a user who is `drafter` in a tree's organization publishes a draft
- **THEN** the API returns `403`

#### Scenario: Publishing one's own draft
- **WHEN** an approver publishes a draft they created
- **THEN** the API returns `201`

### Requirement: Owner manages members
`owner` SHALL allow managing the organization's members: `GET
/orgs/{org}/members` lists each member with their role, for any member; `PUT
/orgs/{org}/members/{username}` with `{role}` adds a user or changes their
role, any role including `owner`; `DELETE /orgs/{org}/members/{username}`
removes them, returning `204`.

#### Scenario: Owner raises a member
- **WHEN** an owner sets a drafter's role to `approver`
- **THEN** the member's role is `approver` and they can publish on every tree of the organization

#### Scenario: Co-owner
- **WHEN** an owner sets another member's role to `owner`
- **THEN** the organization has two owners

#### Scenario: Approver manages members
- **WHEN** an approver changes another member's role
- **THEN** the API returns `403`

### Requirement: Last owner
An organization with an owner SHALL keep at least one. Removing or demoting its
last owner SHALL return `409` with error `last_owner`, except for a site admin.

#### Scenario: Last owner steps down
- **WHEN** the only owner of an organization sets their own role to `approver`
- **THEN** the API returns `409` with error `last_owner`

### Requirement: Site admins
Django superusers SHALL be site admins: they SHALL hold `owner` in every
organization, manage users, tokens and organizations in Django admin, move
trees between organizations, and start full cache syncs (`sync_all`). Starting
`sync_all` as anyone else SHALL return `403`. Any authenticated user SHALL be
able to read a full cache sync's status.

#### Scenario: Owner starts a full sync
- **WHEN** a user who owns every organization but is not a superuser starts a `sync_all` job
- **THEN** the API returns `403`

### Requirement: Creating trees
Validating, creating, updating, publishing, discarding and seeing a new-tree
changeset (`base_rev: null`) SHALL require a role in the organization named in
its `new_tree.org`: `owner` to validate, change or publish it, `reader` to see
it. Publishing it SHALL create the tree in that organization.

#### Scenario: Drafter proposes a new tree
- **WHEN** a user who is `drafter` in `amplify` creates a changeset with `base_rev: null` and `new_tree.org` `amplify`
- **THEN** the API returns `403`

#### Scenario: Owner creates a tree
- **WHEN** an owner of `amplify` publishes a new-tree changeset for `NES2022_tags` in `amplify`
- **THEN** the tree exists in `amplify`, and every member of `amplify` has their role on it

### Requirement: Recorded identities
`author`, `published_by`, alias `added_by` and `removed_by`, description
`added_by`, and WoRMS job `started_by` SHALL record the authenticated user's
username, also for token requests.

#### Scenario: Publish via token
- **WHEN** an approver's token publishes a draft
- **THEN** the revision's `published_by` is that approver's username
