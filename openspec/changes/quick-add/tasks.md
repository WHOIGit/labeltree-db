# Tasks

## 1. Resolution rules

- [ ] 1.1 Add `worms_label(name)` and `lineage_parent(state, lineage)` (deepest anchored lineage AphiaID, skipping the record itself; returns the node, or none plus the tied candidates), with unit tests for: derived label, unsafe characters, nearest anchored ancestor, nothing anchored, a tie, and deprecated nodes ignored; verify `pytest` passes
- [ ] 1.2 Add a shared label fixture table (name → label) used by a pytest test of `worms_label` and a Playwright test that evaluates `X.wormsLabel` on the same rows; verify both pass

## 2. Quick add endpoint

- [ ] 2.1 Add `POST /trees/{tree}/quick_add` (approver role, request schema, record via the cached fetch with `404`/`503`, label and parent resolution, one `add` change validated against the latest revision, `422` with the errors and no key on structural errors) returning the preview with plan, `rev`, issues with options, `confirm_status: "none"` and a signed key; verify API tests for access (anonymous `401`, drafter `403`, approver token `200`), the request rules, the label/parent scenarios, `unaccepted_aphia` / `ambiguous_parent` / `duplicate_aphia` issues and options, `label_in_use`, `parent_not_in_tree`, WoRMS `404` and `503`, and that a preview stores no changeset
- [ ] 2.2 Implement confirming: key checks (signature and age 15 min, user and tree, request hash without `confirm`/`notes`, plan hash), publishing one changeset in one transaction with the caller as author and publisher and `notes` or `Quick add`, one re-plan on `stale_base`, `409 publish_in_progress` passed through, and `201` with node, rev, changeset and warnings; verify API tests for every scenario of "Confirm key binds request and plan", "Confirming a quick add", "Retried confirm adds nothing twice" and "Published quick adds", including an unrelated publish between preview and confirm
- [ ] 2.3 Confirm that the route needs auth (the anonymous-routes test still passes) and appears in the OpenAPI schema with its body fields; verify the schema test and a CSRF test that a session POST without the token gets `403`
- [ ] 2.4 Document the endpoint: change "Quick add (planned)" in `design/api.md` to the endpoint's reference (body, preview and published shapes, issues and options, `confirm_status` values, errors, key lifetime), fix the error code in `design/diagrams/07-quick-add.mmd` to `label_in_use` and re-render it, and add a curl example to the README API section; verify the README example's sequence in an API test like the existing README sequence test

## 3. Quick add page

- [ ] 3.1 Add `/trees/{tree}/quick-add/` (approver, else the 403 page) with the WoRMS search, label field, parent picker (tree label search, top level, work it out) and Preview, plus a **Quick add…** button in the tree browser for approvers; verify page tests for access and the button's visibility per role
- [ ] 3.2 Show the preview (plan with the parent's label, issues, option buttons that patch the form and preview again), Confirm with the stored request and key, the success panel with links to the node and the tree, a re-preview with its reason when confirm doesn't publish, and errors next to their fields without Confirm; verify browser tests for choosing the accepted name, confirming, plan changed before confirming, and label in use
- [ ] 3.3 Describe the page in `design/webapp.md` (Pages and a Quick add section); verify the document links resolve

## 4. Integration

- [ ] 4.1 Run the full test suite (`pytest`, including Playwright tests) and `ruff check`, and run `openspec validate quick-add --strict`; verify all pass

## Workflow follow-up

- Archive `webapp-and-write-api` before archiving this change: this change's `webapp` delta adds to the capability that change introduces.
