# Design

## Context

See proposal.md for why. What exists after `webapp-and-write-api`:

- Organizations and users are created only in Django admin. The
  `ensure_superuser` command creates the first superuser on start. Migration
  `0006_tree_org` creates `amplify` only when trees already exist, so a fresh
  database has no organizations.
- The home view redirects to the first tree, or renders `empty.html` ("No
  trees yet") when there is none.
- New trees go through new-tree changesets: `POST /changesets/validate` and
  `POST /changesets` take `{new_tree: {id, title, description, org},
  changes}`. Validation reports `worms_missing`, and the draft editor's
  Validate step runs a `fetch` job for those (`kind: fetch, org`), polls it
  with `jobs.js`, and offers Try again / Proceed anyway. Publishing with
  uncached records is allowed; their checks are `unavailable`.
- `expanders.js` has `expandImport`, the browser-side twin of
  `core.importer.expand_import`; both share the fixtures in
  `core/tests/import_fixtures/`.
- Superusers hold `owner` in every organization, so they can publish
  new-tree changesets in any organization.

## Goals / Non-Goals

**Goals:**
- Everything the wizard does goes through the API, like the rest of the web
  app, so a script can do the same.
- The wizard keeps no state of its own: which step it opens at follows from
  the database, so leaving and coming back works.
- Imports in the wizard behave exactly like a new-tree draft created and
  published in the editor.

**Non-Goals:**
- Email invitations, password reset by email, or self-registration.
- Editing or deleting organizations and users outside Django admin.
- A wizard for instances that already have trees. Later organizations keep
  being created by site admins in Django admin or with `POST /orgs`.
- Importing into an existing tree, which is the draft editor's import.
- Creating API tokens. Site admins keep issuing them in Django admin.

## Decisions

### A server-rendered page with one Alpine component
`/setup/` is a Django view, superuser only, that renders `setup.html` with
page data: the organizations, the members of the one to pick, and whether
any tree exists. It redirects to `/` once a tree exists. A new
`static/app/setup.js` component, registered in `main.js`, runs the steps.
This follows the organization page (`org.html` with `members.js`).

The step to open at is computed from the page data: Users when there is
exactly one organization, with it picked, and Organization otherwise, where
the existing ones are listed to pick from. Organizations have no creation
time, so the wizard can't tell which one is "new"; with one organization, the
usual case on a new instance, it doesn't need to. Skip on the Trees step goes
to the organization's page, since the home page would send the site admin
back to the wizard while there are no trees.

*Alternative:* store wizard progress in the session or a table. Rejected:
the database already says what's done, and stored progress can drift from
it.

### Two small superuser endpoints
- `POST /orgs {id, name}` in `api/orgs.py`: `require_superuser`, slug check
  as for tree ids, `409 org_exists`. Returns `201 {id, name}`.
- `POST /users {username, password}` in a new `api/users.py`:
  `require_superuser`, Django's username validation, `validate_password`
  against an unsaved user with that username (so the similarity rule works),
  `409 user_exists`. Returns `201 {username}`. The password is never echoed
  or logged.

The superuser who creates an organization is not made a member: superusers
already act as owners everywhere, and an organization should get a real
owner in the Users step.

*Alternative:* plain Django form posts on `/setup/`. Rejected: it would be the
only write path outside the API, and scripts setting up an instance couldn't
use it.

### Users step: add first, create on demand
The form has username and role. Add calls `POST /orgs/{org}/members`. If it
answers `404` because the user doesn't exist, the form shows an initial
password field (twice, to catch typos) and the next Add calls `POST /users`
and then `POST /orgs/{org}/members`. Existing users are added without ever
seeing a password field. `409 already_member` is shown as on the
organization page.

The member list under the form reloads from `GET /orgs/{org}/members` after
each add, so it shows members added elsewhere too.

### Trees step: the editor's new-tree flow, end to end
For each import the component:
1. parses the text box (`JSON.parse`; errors show the parser's message) and
   expands it with `expandImport(data, {group: 'import#1'})`, which reports
   format errors by position;
2. calls `POST /changesets/validate {new_tree, changes}`. If `worms_missing`
   is non-empty, it runs a `fetch` job for them with progress and the
   failure choice, then validates again;
3. stops on structural errors or `tree_exists`, listing them, with nothing
   stored;
4. calls `POST /changesets` with notes `Imported in setup`, then
   `POST /changesets/{id}/publish`.

If publishing fails after the draft was saved, the component keeps the draft
id and its Import button becomes "Publish again", which retries the publish
of that draft instead of creating a second one. The error links to the draft
in the editor.

The file picker reads the file with `FileReader` into the text box, so a
pasted file and a picked one take the same path.

### Share the fetch step instead of copying it
The browser's fetch step (start job, poll, job/retry/pause bars, Try again /
Proceed anyway) moves out of `browser.js` into a `fetchStep()` mixin in
`jobs.js`, which returns the state and methods both components spread into
themselves. Its markup moves from `browser.html` into two includes:
`webapp/_job_progress.html` (the job, retry and pause bars, which the sync
progress uses too) and `webapp/_fetch_failed.html` (Try again / Proceed
anyway). `fetchMissing(org, ids)` returns the AphiaIDs left unfetched when the
user proceeds, and callers validate again either way. The editor keeps its behavior and its browser
tests keep passing unchanged.

*Alternative:* copy the step into `setup.js`. Rejected: two copies of the
retry and failure logic would drift, which is what the last review round
fixed for polling.

### Home page and account page
- `home`: no trees and a superuser goes to `/setup/`; no trees and anyone
  else gets `empty.html`, reworded to say a site admin sets the instance up
  (anonymous users also get a login link).
- `me.html`: a "Set up this instance" link for superusers while there are no
  trees, and a "Change password" link for everyone.
- Password change uses Django's `PasswordChangeView` and
  `PasswordChangeDoneView` at `/me/password/` and `/me/password/done/`, with
  templates extending `base.html`. The view keeps the session valid after
  the change.

## Risks / Trade-offs

- [A site admin types a password for someone else] → It is set once, over
  HTTPS, and the user is told to change it on the account page, which this
  change adds. Email invitations are out of scope.
- [Large imports post a large body] → Django's default
  `DATA_UPLOAD_MAX_MEMORY_SIZE` (2.5 MB) limits a changeset body. The
  largest current file is about 16 KB, so this is far off; the same limit
  already applies to the editor's import, and raising it is a settings
  change if needed.
- [Create succeeds, publish fails] → The draft stays as an ordinary new-tree
  draft, visible to the organization; "Publish again" or the editor can
  finish it.
- [Moving the fetch step out of `browser.js` breaks the editor] → The
  existing Validate and fetch browser tests cover it and must pass unchanged.

## Migration Plan

No migrations. Existing instances already have trees, so the home page and
wizard don't change for them; `/setup/` just redirects home. Rollback is
reverting the code.
