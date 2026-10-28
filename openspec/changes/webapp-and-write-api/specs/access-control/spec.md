# Spec Delta

## Purpose

Controls who can read and change each tree: every request is authenticated, and
per-tree roles decide which reads, drafts, publishes and administrative actions a
user or service may perform.

## ADDED Requirements

### Requirement: Authentication required everywhere
Every API endpoint and web app page SHALL require authentication; there SHALL
be no anonymous access. Unauthenticated API requests SHALL get `401`.

#### Scenario: Anonymous read
- **WHEN** a request without credentials calls `GET /api/v1/trees`
- **THEN** the API returns `401`

#### Scenario: Anonymous web access
- **WHEN** an unauthenticated browser opens the tree browser
- **THEN** it is redirected to the login page

### Requirement: Sessions and API tokens
The web app SHALL authenticate with Django sessions. Scripts and services SHALL
authenticate with per-user or per-service API tokens sent in a request header.
Tokens SHALL be revocable.

#### Scenario: Service token
- **WHEN** roi-db calls `GET /api/v1/nodes/431` with a valid token holding `reader` on that node's tree
- **THEN** the API returns the node

#### Scenario: Revoked token
- **WHEN** a revoked token is used
- **THEN** the API returns `401`

### Requirement: Per-tree roles
Roles `reader`, `drafter`, `approver` and `admin` SHALL be assigned per tree and
SHALL combine. A request that is authenticated but lacks the role an action
needs on that tree SHALL get `403`. Roles and tokens SHALL be managed in Django
admin, not through the API.

#### Scenario: Reader on another tree
- **WHEN** a user with `reader` only on `NES2022_tags` requests `GET /api/v1/trees/NES2022_taxonomy`
- **THEN** the API returns `403`

#### Scenario: Tree list
- **WHEN** a user with roles on one tree requests `GET /api/v1/trees`
- **THEN** only that tree is listed

### Requirement: Reader permissions
Any role on a tree SHALL allow reading that tree's published revisions, nodes
and WoRMS-derived data, reading the status of its WoRMS jobs, and calling the
WoRMS lookup endpoints.

#### Scenario: Drafter reads
- **WHEN** a user with only `drafter` on a tree reads one of its nodes
- **THEN** the node is returned

### Requirement: Drafter permissions
`drafter` SHALL allow creating, updating and discarding any draft on the tree,
not only one's own, running `validate`, starting WoRMS fetch jobs, adding and
removing aliases, setting descriptions, and starting tree sync jobs. Drafts SHALL be visible only to drafters, approvers and
admins of the tree.

#### Scenario: Editing another drafter's draft
- **WHEN** drafter B updates a draft created by drafter A on the same tree
- **THEN** the update succeeds

#### Scenario: Reader lists drafts
- **WHEN** a user with only `reader` requests the tree's changesets in state `draft`
- **THEN** the API returns `403`

### Requirement: Approver permissions
`approver` SHALL allow publishing drafts and starting tree sync jobs. A user SHALL
be able to publish their own draft only when holding both `drafter` and
`approver`.

#### Scenario: Drafter without approver
- **WHEN** a user holding only `drafter` publishes a draft
- **THEN** the API returns `403`

### Requirement: Admin permissions
`admin` SHALL allow managing the tree's settings and role assignments in Django
admin and starting tree sync jobs.

#### Scenario: Admin syncs a tree
- **WHEN** a tree admin starts a `sync_tree` job on the tree
- **THEN** the job starts

#### Scenario: Reader cannot sync
- **WHEN** a user with only `reader` starts a `sync_new` job on the tree
- **THEN** the API returns `403`

### Requirement: Full cache sync
Starting a full cache sync (`sync_all`), which spans every tree, SHALL require
a Django superuser. Any other user SHALL get `403`. Any authenticated user SHALL
be able to read a full cache sync's status.

#### Scenario: Tree admin starts a full sync
- **WHEN** a user who is `admin` on every tree but not a superuser starts a `sync_all` job
- **THEN** the API returns `403`

### Requirement: Creating new trees
Creating, updating, publishing and seeing new-tree changesets (`base_rev:
null`) SHALL require the global tree-creation permission. Publishing one SHALL
give the publishing user `admin` on the new tree.

#### Scenario: Drafter proposes a new tree
- **WHEN** a user without the tree-creation permission creates a changeset with `base_rev: null`
- **THEN** the API returns `403`

#### Scenario: First admin
- **WHEN** a user with the tree-creation permission publishes a new-tree changeset for `NES2022_tags`
- **THEN** the tree exists and that user holds `admin` on it

### Requirement: Recorded identities
`author`, `published_by`, alias `added_by` and `removed_by`, description
`added_by`, and WoRMS job
`started_by` SHALL record the authenticated username, or the service account's
name for token requests.

#### Scenario: Publish via token
- **WHEN** an approver's token publishes a draft
- **THEN** the revision's `published_by` is that approver's username
