# Tasks

## 1. Authentication and roles

- [ ] 1.1 Add the `ApiToken` model (hashed key, revocation) and the token and session auth classes as the API's global auth; verify `401` for anonymous and revoked-token requests on every router
- [ ] 1.2 Add `TreeRole` and the `require()` helper, and apply the role rules to every read, write and drift endpoint; verify a test matrix of role × endpoint for the `access-control` scenarios
- [ ] 1.3 Filter `GET /trees` by the user's roles, gate new-tree changesets on `trees.add_tree`, and grant `admin` to the publisher of a new tree; verify the tree-list and first-admin scenarios
- [ ] 1.4 Record authenticated usernames in `author`, `published_by`, alias and drift fields; verify the publish-via-token scenario
- [ ] 1.5 Register tokens and roles in Django admin and document issuing a service token in README.md; verify the documented steps produce a working token

## 2. Changeset API

- [ ] 2.1 Implement `POST /trees/{tree}/validate` returning errors, conflicts (`stale_base` with changed touched nodes), warnings, warning changes, version changes, `reduced_changes` and `worms`; verify the validate scenarios and that nothing is stored
- [ ] 2.2 Implement create (tree and new-tree forms), list by state (paginated) and get with `ETag` and draft validation; verify the create and get scenarios
- [ ] 2.3 Implement `PUT` (replace and rebase) and `publish` with `If-Match` (`428`, `412`) under a row lock, `201` responses, approver notes, `409`/`422` with `validation`, and `DELETE` discard (`204`); verify every `changeset-api` scenario

## 3. Alias endpoints and cloning

- [ ] 3.1 Implement `POST /nodes/{id}/aliases` (`201`, `409` duplicate, refused on deprecated nodes), `DELETE .../aliases/{alias_id}` (`204`) and `GET .../aliases?history=`; verify the `node-aliases` scenarios
- [ ] 3.2 Implement the server-side clone expander (revision to new-tree changeset with `import#1`) for tests and management use, matching the client expander; verify the clone scenarios

## 4. Web app shell

- [ ] 4.1 Add login/logout, the base template, and vendored Bootstrap 5 and Alpine.js static files; verify an anonymous visit redirects to login
- [ ] 4.2 Port the mockup's tree browser to an Alpine store backed by `/api/v1`: tree and revision pickers, expand/collapse, filter, WoRMS and warning badges, and the frozen revision changes panel; verify with browser tests on the tags and taxonomy trees
- [ ] 4.3 Implement the node page (state, version history, WoRMS card, aliases, successors); verify against a deprecated node and an anchored node

## 5. Draft editor

- [ ] 5.1 Implement edit mode (new or open draft, status bar, leave confirmation) and the node menu with Edit, New child, New node, Move to (pick mode excluding descendants) and Deprecate (blocked with children); verify the edit-mode and composing scenarios in browser tests
- [ ] 5.2 Implement the changes panel with debounced `validate`, inline errors and warnings, summary, collapsible groups, hover/click highlighting and dependent-change error marking on removal; verify the live-check and safe-removal scenarios
- [ ] 5.3 Implement the draft markings (green, yellow with version badge, grey struck-through); verify the child-added scenario
- [ ] 5.4 Implement Save (showing the reduced list), Rebase, Publish with notes and Discard, with `412` handling that re-fetches; verify the rebase-then-publish scenario
- [ ] 5.5 Implement the draft list and review page; verify the review scenario

## 6. Wizards

- [ ] 6.1 Implement the merge wizard (with and without replacement) and copying aliases after a merge publishes, with retry on failure; verify both merge scenarios and the aliases-after-merge scenario
- [ ] 6.2 Implement the split wizard (with and without replacement, all children assigned when replacing); verify the split scenarios
- [ ] 6.3 Implement the import wizard (upload or paste, top level or under a node), sharing JSON fixtures with the server parser; verify the import-under-a-node scenario and that both parsers agree on the fixtures
- [ ] 6.4 Implement Add from WoRMS with the suggested parent from the lineage; verify the suggested-parent scenario against recorded WoRMS fixtures
- [ ] 6.5 Implement alias editing from the node menu and Clone as new tree; verify the alias-in-static-mode and clone-flow scenarios

## 7. Integration

- [ ] 7.1 End-to-end browser test: a drafter splits a node in `NES2022_taxonomy`, another drafter edits the same draft (`412` then re-fetch), an approver rebases after an intervening publish and publishes; verify the revision, version changes and successors via the read API
- [ ] 7.2 Verify that the roi-db and datasetman service tokens can read both NES2022 trees and are refused writes

## Workflow follow-up

- Archive after `core-tree-model` and `worms-integration`, since this change adds to their `node-aliases` and `tree-import` specs.
- Coordinate the auth cut-over date with roi-db and datasetman maintainers before deploying.
