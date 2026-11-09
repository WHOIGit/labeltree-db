# Proposal

## Why

A new instance starts with one superuser and nothing else: no organizations,
no other users and no trees. Getting to a usable tree today means three trips
through Django admin and a `manage.py import_tree` run on the host, and the
web app only says "No trees yet". A guided setup in the web app gets a new
instance from first login to a browsable tree without shell access.

## What Changes

- A **setup wizard** at `/setup/` for site admins (superusers), in three
  steps:
  1. **Organization:** create the first organization (slug id and name).
  2. **Users:** add members to it with a role. A user who doesn't exist yet
     is created with a username and an initial password the admin chooses.
  3. **Trees:** import one or more trees into it. Each import takes a tree
     id, title and optional description, and the import JSON pasted into a
     text box or loaded from a file into that box. The wizard checks it,
     fetches its WoRMS records with the usual job progress, and publishes it
     as revision 1.
- The home page sends a logged-in site admin to the wizard while the
  instance has no trees. Others keep seeing "No trees yet", now saying that a
  site admin sets the instance up. Each step can be skipped, and the wizard
  can be reopened from the account page while there are no trees.
- New write endpoints the wizard uses, superuser only: `POST /orgs` creates
  an organization, and `POST /users` creates a user account.
- Users change their own password from the account page, so an initial
  password chosen by the admin doesn't have to stay.
- Imports reuse the existing new-tree changeset flow (`POST
  /changesets/validate`, WoRMS fetch jobs, `POST /changesets`, publish), so
  the wizard adds no import endpoint.

## Capabilities

### New Capabilities
- `instance-setup`: the site admin's setup wizard for a new instance: when it
  is offered, its organization, users and trees steps, skipping and
  resuming.

### Modified Capabilities
- `access-control`: adds creating organizations and user accounts through the
  API (site admins only), and users changing their own password. This
  capability is introduced by the `webapp-and-write-api` change, which should
  be archived first.

## Impact

- **API:** `api/orgs.py` gains `POST /orgs`; a new `api/users.py` holds
  `POST /users`. Both use the existing error conventions (`409
  org_exists` / `user_exists`, `400 bad_parameter`).
- **Web app:** new `setup` view and template, a `setup.js` module reusing
  `expanders.js` (`expandImport`), `jobs.js` and `api.js`. The home view and
  the `empty.html` and `me.html` templates change. Password change uses
  Django's `PasswordChangeView`.
- **Docs:** README (setting up a new instance), `design/webapp.md`,
  `design/api.md`, and the web app mockup gain the setup wizard.
- **Tests:** API tests for the new endpoints and browser tests for the wizard
  steps, skipping and the home-page redirect.
- No migrations and no new dependencies.
