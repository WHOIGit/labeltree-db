# Spec Delta

## MODIFIED Requirements

### Requirement: Organizations
Every tree SHALL belong to exactly one organization. `GET /orgs` SHALL list the
organizations with their names and trees, and `GET /trees` SHALL include each
tree's `org`, both without authentication. Only site admins SHALL create
organizations, in Django admin or with `POST /orgs`, and only they SHALL move a
tree to another organization, in Django admin.

#### Scenario: Trees by organization
- **WHEN** a request without credentials calls `GET /api/v1/orgs`
- **THEN** the API lists organization `amplify` (`AMPLIfy`) with trees `NES2022_tags` and `NES2022_taxonomy`

## ADDED Requirements

### Requirement: Creating an organization
`POST /orgs` with `{id, name}` SHALL create an organization with no members and
return it with `201`. Only site admins SHALL call it; others SHALL get `403`.
An id that is not a slug or an empty name SHALL return `400` with error
`bad_parameter`, and an existing id SHALL return `409` with error `org_exists`.

#### Scenario: Site admin creates an organization
- **WHEN** a site admin posts `{"id": "lab_a", "name": "Lab A"}` to `/api/v1/orgs`
- **THEN** the API returns `201` with `{"id": "lab_a", "name": "Lab A"}` and `GET /api/v1/orgs` lists it

#### Scenario: Owner creates an organization
- **WHEN** an owner of `amplify` who is not a site admin posts a new organization
- **THEN** the API returns `403` and no organization is created

#### Scenario: Organization id taken
- **WHEN** a site admin posts `{"id": "amplify", "name": "Other"}`
- **THEN** the API returns `409` with error `org_exists` and `amplify` keeps its name

### Requirement: Creating a user account
`POST /users` with `{username, password}` SHALL create a user account, not a
site admin and in no organization, and return its username with `201`. Only
site admins SHALL call it; others SHALL get `403`. A taken username SHALL
return `409` with error `user_exists`. A password the site's password rules
refuse SHALL return `400` with error `bad_parameter` and the reasons.

#### Scenario: Site admin creates a user
- **WHEN** a site admin posts `{"username": "curator1", "password": "<a strong password>"}` to `/api/v1/users`
- **THEN** the API returns `201`, and `curator1` can log in with that password and has no role in any organization

#### Scenario: Username taken
- **WHEN** a site admin posts a username that already has an account
- **THEN** the API returns `409` with error `user_exists` and that account is unchanged

#### Scenario: Weak password
- **WHEN** a site admin posts `{"username": "curator1", "password": "1234"}`
- **THEN** the API returns `400` with error `bad_parameter` and the password rules it fails, and no account is created

#### Scenario: Drafter creates a user
- **WHEN** a user who is not a site admin posts to `/api/v1/users`
- **THEN** the API returns `403`

### Requirement: Changing one's own password
A logged-in user SHALL be able to change their own password from the account
page by giving their current password and a new one that the site's password
rules accept. Their session SHALL stay logged in afterwards.

#### Scenario: Changing a password
- **WHEN** `curator1` gives their current password and an accepted new password
- **THEN** they can log in with the new password and not with the old one, and they stay logged in

#### Scenario: Wrong current password
- **WHEN** a user gives a wrong current password
- **THEN** the page shows an error and the password is unchanged
