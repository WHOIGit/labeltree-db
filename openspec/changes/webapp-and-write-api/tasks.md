# Tasks

## 1. Authentication and roles

- [x] 1.1 Add the `ApiToken` model (hashed key shown once, `last_used_at`, revocation) and token and session auth as the API's global default, with the read routes and `/health` opting out; verify a test that walks every API route against the anonymous list (`401` for the rest), plus the revoked-token and script-token scenarios
- [ ] 1.2 Add `Organization`, `OrgMember` (one ordered role per user and organization, superusers as owner) and `Tree.org` (existing trees into `amplify`), and `require(user, tree, minimum)` through the tree's organization, applied to every changeset, job, lookup, alias, description and member endpoint; verify a role × endpoint matrix covering the `access-control` scenarios, including approvers drafting and publishing their own drafts, members of another organization, and trees added to an organization after a member joined
- [x] 1.3 Implement `GET /orgs`, `GET /orgs/{org}`, `org` in `GET /trees`, and `GET/PUT/DELETE /orgs/{org}/members[/{username}]` with the last-owner rule under a row lock (superusers exempt); verify the trees-by-organization, owner, co-owner, approver-refused and last-owner scenarios
- [ ] 1.4 Store a new-tree changeset's organization (`new_tree.org`, `--org` for `import_tree`), require `owner` there to create, change, publish or discard it and `reader` to see it, and create the tree in it on publish; verify the drafter-proposes and owner-creates-a-tree scenarios
- [ ] 1.5 Record authenticated usernames in `author`, `published_by`, alias, description and WoRMS job `started_by` fields; verify the publish-via-token scenario
- [x] 1.6 Register users, tokens, organizations, `OrgMember` and a tree's organization (its only editable field) in Django admin for site admins, and document issuing a token, creating an organization and making an owner in README.md; verify the documented steps produce a working token and owner
- [x] 1.7 Rate-limit logins (django-axes, per username and address behind the proxy) and add the Apache site config with TLS-aware Django settings; verify lockout, reset and spoofed `X-Forwarded-For` tests

## 2. WoRMS jobs

- [x] 2.1 Remove WoRMS fetching from save and publish (`fetch_records`, `PUBLISH_MAX_AGE`): checks use complete cached rows only, missing ones make checks `unavailable`; verify the `worms-records` "Publish without WoRMS" and `worms-placement-checks` scenarios with the HTTP fixture asserting no calls
- [x] 2.2 Add the client's `on_wait` hook, `JOB_BACKOFF` (1, 2, 5, 12 s) and a distinct rate-limit error carrying `Retry-After`, keeping lookups on (1, 2 s) and renaming `DRIFT_BACKOFF` to `SCHEDULED_BACKOFF` for the command; verify the retry-schedule scenarios in `worms/tests/test_client.py`
- [x] 2.3 Generalise the drift runner into a job runner in `worms/sync.py` (replacing `worms/drift.py`, locks `worms-sync:<tree>` and `worms-sync:all`): job ids, status in the cache (`retrying`, `paused`, `failed`), per-job advisory lock and `interrupted` cleanup on startup (`clear_worms_jobs` replacing `clear_drift_status`), skip-and-continue on failure, job-wide pause on 429 (stop after a second 429 for API jobs, up to 4 pauses for command jobs); verify the job-status, failed-AphiaID and rate-limit scenarios with fixture transports
- [x] 2.4 Implement the `fetch`, `sync_new`, `sync_tree` and `sync_all` kinds, their locks and `409 sync_in_progress`, optional `aphia_ids`, and no warning-history rows for nodes needing a failed record; verify every `worms-sync` scenario
- [x] 2.5 Add `POST /worms/jobs`, `GET /worms/jobs/{job}`, `GET /worms/jobs?tree=` and `GET /worms/warnings?tree=`, remove the `/trees/{tree}/drift` endpoints, and replace `run_drift` with `worms_sync <tree> [--new]` and `worms_sync --all` (non-zero exit on failed AphiaIDs); rename drift to sync in README (cron section included) and the start script; verify with API tests, a command test, and `grep -ril drift src README.md` and `find src -iname '*drift*'` finding nothing

## 3. Changeset API

- [ ] 3.1 Track `sources` through reduction (union on merge and collapse, kept by renumber); verify the existing reduction tests plus the split-then-rename, label-swap and move-undone examples
- [ ] 3.2 Compute `node_changes` from base and final states with touching `seq`s and source groups; verify the split and temporary-label scenarios
- [ ] 3.3 Implement `POST /trees/{tree}/validate` (cache only) returning errors, conflicts (`stale_base` with changed touched nodes), `reduced_changes` with `sources`, `version_changes`, `node_changes`, `warnings`, `warning_changes`, `unchecked`, `worms_missing` and `worms`; verify the validate scenarios and that nothing is stored and WoRMS is not called
- [ ] 3.4 Implement create (tree and new-tree forms, saved even with structural errors), list by state (paginated) and get with `ETag` and validation; verify the create, draft-with-errors and get scenarios
- [ ] 3.5 Implement `PUT` (replace and rebase) and `publish` with `If-Match` (`428`, `412`) under a row lock, `201` responses, approver notes, `409`/`422` with `validation`, and `DELETE` discard (`204`); verify every remaining `changeset-api` scenario

## 4. Alias and description endpoints, and cloning

- [ ] 4.1 Implement `POST /nodes/{id}/aliases` (`201`, `409` duplicate, refused on deprecated nodes), `DELETE .../aliases/{alias_id}` (`204`) and `GET .../aliases?history=`; verify the `node-aliases` scenarios
- [ ] 4.2 Implement `PUT /nodes/{id}/description` (`200`, `409` on deprecated nodes) and `GET .../description?history=`; verify the `node-descriptions` scenarios
- [ ] 4.3 Implement the server-side clone expander (revision to new-tree changeset with `import#1`) for tests and management use, matching the client expander; verify the clone scenarios

## 5. Web app shell

- [ ] 5.1 Add login/logout, the base template, vendored Bootstrap 5 and Alpine.js (CSP build) static files, Django's CSP middleware with the policy from design.md, and anonymous read-only browsing with "Log in to edit"; verify that an anonymous visit shows the tree without edit or sync controls, that login-only pages redirect, and that pages load with no CSP violations in the browser console
- [ ] 5.2 Port the mockup's tree browser to an Alpine store backed by `/api/v1`: tree and revision pickers, expand/collapse, filter, AphiaID pills and the frozen revision changes panel; verify the pill colours and badges (none, grey, green, orange `!`, red `?`) and tooltips with browser tests on the tags and taxonomy trees
- [ ] 5.3 Add the hideable warnings panel (from `GET /worms/warnings?tree=`) with jump-to-node; verify on `NES2022_taxonomy`'s 13 `unaccepted_aphia` nodes
- [ ] 5.4 Implement the node page (state, version history, WoRMS card, warning history, aliases, successors); verify against a deprecated node and a node with warning history
- [ ] 5.5 Build the shared job-progress component (job bar, one bar per retrying AphiaID, pause bar, failure list with Try again / Proceed anyway) and the sync menu (`sync_new`, `sync_tree`, superuser-only `sync_all`) that also shows runs started elsewhere; verify with browser tests against fixture-driven jobs, including a retry and a failure

- [ ] 5.6 Implement the organization page (its trees; members with their role; owner controls to add, change and remove; last-owner refusal), the tree picker grouped by organization, and the user's own page listing their organizations and roles; verify the organization-page scenarios in browser tests

## 6. Draft editor

- [ ] 6.1 Implement edit mode (new or open draft from its stored changes, status bar, leave confirmation) and the node menu with Edit, New child, New node, Move to (pick mode excluding descendants) and Deprecate (blocked with children), with no server calls while composing; verify the edit-mode and composing scenarios in browser tests
- [ ] 6.2 Implement Validate (validate, fetch job for `worms_missing` with progress, validate again) and the Save gate (disabled until the current list is validated, re-enabled Validate after any edit); verify the validate-before-save scenarios
- [ ] 6.3 Implement the changes panel tabs (As edited with errors placed through `sources`, As reduced, By node, Summary, WoRMS warnings, Errors), out-of-date greying, unread markers and counts, removal of changes and groups, and hover/click jump-to-node; verify the tab, notification, jump and safe-removal scenarios
- [ ] 6.4 Implement the draft markings (green, yellow with version badge, grey struck-through); verify the child-added scenario
- [ ] 6.5 Implement Save (showing the reduced list, confirmation when it has errors), Rebase, Publish with notes and Discard, with `412` handling that re-fetches; verify the save-with-errors and rebase-then-publish scenarios
- [ ] 6.6 Implement the draft list and review page (By node first, then grouped changes and warning changes); verify the review scenario

## 7. Wizards

- [ ] 7.1 Implement the merge wizard (with and without replacement) and copying aliases after a merge publishes, with retry on failure; verify both merge scenarios and the aliases-after-merge scenario
- [ ] 7.2 Implement the split wizard (with and without replacement, all children assigned when replacing); verify the split scenarios
- [ ] 7.3 Implement the import wizard (upload or paste, top level or under a node), sharing JSON fixtures with the server parser; verify the import-under-a-node scenario and that both parsers agree on the fixtures
- [ ] 7.4 Implement Add from WoRMS with the suggested parent from the lineage and the label rule; verify the suggested-parent and unsafe-characters scenarios against recorded WoRMS fixtures
- [ ] 7.5 Implement alias and description editing from the node menu and Clone as new tree; verify the alias-in-static-mode, description-in-static-mode and clone-flow scenarios

## 8. Integration and docs

- [ ] 8.1 End-to-end browser test: a drafter splits a node in `NES2022_taxonomy` and validates (fetch job runs), another drafter edits the same draft (`412` then re-fetch), an approver rebases after an intervening publish and publishes; verify the revision, version changes, successors and warning history via the read API
- [ ] 8.2 Verify that roi-db's and datasetman's read calls work without credentials against both NES2022 trees, and that the same calls to write, validate or start jobs get `401`
- [ ] 8.3 Update `design/mockups/webapp-mockup.html` and its spec to the Validate flow, changes panel tabs, AphiaID pills with `!` and `?` badges, warnings panel, sync menu, progress bars, organization page and a role selector of anonymous, `reader`, `drafter`, `approver` and `owner`, and refresh the snapshot; verify by opening the mockup

## Workflow follow-up

- The archive syncs this change's deltas into the `worms-records` and `worms-placement-checks` main specs, creates `worms-sync`, and deletes `worms-drift` (`retire_capabilities: true`).
