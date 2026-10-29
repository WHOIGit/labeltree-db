# Tasks

## 1. Organization and user endpoints

- [x] 1.1 Add `POST /orgs {id, name}` (superuser only, slug and name checks, `409 org_exists`, `201 {id, name}`) to `api/orgs.py`; verify API tests for the site-admin-creates, owner-refused, id-taken and bad-parameter scenarios, and add the route to the access matrix in `api/tests/test_access.py`
- [x] 1.2 Add `POST /users {username, password}` in a new `api/users.py` (superuser only, username validation, `validate_password` against the new username, `409 user_exists`, `201 {username}`, the password never echoed) and register its router; verify API tests for the creates, username-taken, weak-password and non-admin scenarios, that the new user can log in, and the access-matrix row
- [x] 1.3 Document both endpoints in `design/api.md` (endpoint list, `409` codes table) and update the "Users, organizations and tokens" section of README.md; verify the `openspec validate --strict` run and an API test replaying the README's curl sequence (organization, user, owner) with a site admin's token

## 2. Password change

- [x] 2.1 Add Django's password change and done views at `/me/password/` and `/me/password/done/` with templates extending `base.html`, and a "Change password" link on the account page; verify view tests for changing a password (old one no longer works, session stays logged in) and a wrong current password, and a CSP check that the pages load no inline script

## 3. Shared fetch step

- [x] 3.1 Move the editor's fetch step (start a `fetch` job, poll, job/retry/pause bars, Try again / Proceed anyway) from `browser.js` into a `fetchStep()` mixin in `jobs.js`, and its markup from `browser.html` into `webapp/_job_progress.html`; verify the existing Validate and job-progress browser tests pass unchanged, and `node --check` on every module

## 4. Setup wizard

- [x] 4.1 Add the `/setup/` view (superuser only, `403` page for other users, login redirect for anonymous, redirect home once a tree exists) with page data (organizations, the picked one's members, the opening step), the `setup.html` template and an empty `setup.js` component registered in `main.js`; route `/` to `/setup/` for superusers when there are no trees and reword `empty.html` for everyone else; verify page tests for the offered-on-empty-instance, other-user, setup-after-first-tree, anonymous and owner-refused scenarios
- [x] 4.2 Implement the step bar and the Organization step (create with id and name, or pick an existing one; errors stay in the step; Skip), opening at Users when an organization exists; verify browser tests for the first-organization, existing-id and resuming scenarios
- [x] 4.3 Implement the Users step (add by username and role, password fields shown after a `404` for an unknown user, `POST /users` then the member add, password rule errors shown, member list reloaded after each add, Skip and Continue); verify browser tests for the new-user, existing-user, weak-password and skipping-users scenarios, and that the new user can log in
- [x] 4.4 Implement the Trees step: tree id, title, description, a text box and a file picker that loads into it; parse and `expandImport`, validate, fetch missing WoRMS records with the shared fetch step, list errors with nothing stored, then create and publish; list published trees, allow another import, keep a saved draft for "Publish again" when publishing fails, and send Skip or Done to the home page; verify browser tests for importing a tree, loading a file, a second tree, malformed file, duplicate labels, taken tree id, an import with AphiaIDs (fixture-driven fetch job) and WoRMS unreachable with Proceed anyway
- [x] 4.5 Add "Set up this instance" to the account page for superusers while there are no trees; verify a page test that it shows only then
- [x] 4.6 Document the wizard in `design/webapp.md` (a "Setting up a new instance" section) and README.md (first start: log in as the superuser and follow the wizard, `import_tree` kept as the shell alternative), and add the three setup steps to `design/mockups/webapp-mockup.html` and its spec (the snapshot shows the editor, which doesn't change); verify the documents link correctly and a Playwright run through the mockup's setup dialog

## 5. Integration

- [x] 5.1 Run an end-to-end browser test from an empty database: the superuser logs in, is sent to the wizard, creates an organization, adds a new owner, imports `labeldata/NES2022_tags.json` from the file picker, and lands on the new tree; then the new owner logs in and sees the tree with their role. Verify it passes along with the full test suite, `ruff check src`, `node --test` and `openspec validate --strict`

## Workflow follow-up

- Archive `webapp-and-write-api` before archiving this change: this change's `access-control` delta modifies a requirement that change introduces.
