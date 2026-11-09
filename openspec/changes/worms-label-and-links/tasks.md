# Tasks

## 1. Label rule

- [x] 1.1 Add the lowercase option to `worms_label` and `wormsLabel`, add a lowercase column to every row of `label_cases.json`, and check both columns in the pytest and Node label tests; verify both pass

## 2. Quick add API

- [x] 2.1 Add `worms_url(aphia_id)` beside the WoRMS client and return it as `plan.worms_url` and `node.worms_url` (`null` without an AphiaID); verify API tests for a preview with an AphiaID, a label-only preview, and a published response
- [x] 2.2 Add `lowercase_label` (default `true`) to the request and apply it to derived labels only; update tests that expect `Chaetoceros_debilis` as a derived label; verify API tests for the default, `false`, a given label, and that changing `lowercase_label` before confirming gives `body_changed`
- [x] 2.3 Update `design/api.md` (request field, `worms_url`, example labels), the README curl example, and the derived label in `design/diagrams/07-quick-add.mmd`, re-rendering the PNG; verify the README sequence test still passes

## 3. Web app

- [x] 3.1 Add from WoRMS: a Lowercase label toggle (on when opened) that recomputes the label until the user types one, and the picked record's full WoRMS link opening in a new tab; verify browser tests for the default, toggling off, a typed label kept, and the link
- [x] 3.2 Quick add page: the Lowercase label toggle sent as `lowercase_label`, the picked record's link, and `worms_url` as a full link in the preview and the published message; update existing Quick add browser tests for lowercase labels; verify browser tests for the toggle off and the links
- [x] 3.3 Describe the toggle and links in `design/webapp.md`; verify its links resolve

## 4. Integration

- [x] 4.1 Run the full test suite (including Playwright), `ruff check`, `ruff format --check` and `openspec validate worms-label-and-links --strict`; verify all pass

## Workflow follow-up

- Archive `webapp-and-write-api`, then `quick-add`, before archiving this change: its deltas modify requirements those changes introduce.
- Future investigation: a per-tree `labelcase_policy` (strict or recommended, case-sensitive or case-insensitive labels, how WoRMS-derived labels follow it), which would replace the fixed toggle default.
