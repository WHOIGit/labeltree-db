# Proposal

## Why

Other applications that find a taxon with `GET /worms/search` and need it as a
label have to build a change list, save a draft, fetch its ETag and publish it:
four calls and knowledge of the change format to add one node. Quick add makes
this a single, safe step for approvers: the server works out the label and the
parent from WoRMS, shows the result first, and publishes only what was shown.

## What Changes

- New endpoint `POST /trees/{tree}/quick_add` for approvers of the tree's
  organization. The body is `{aphia_id?, label?, parent?, description?,
  aliases?, notes?, confirm?}`.
  - With an `aphia_id`, the record is read from the WoRMS cache, fetched on a
    miss. A missing `label` is derived from its scientific name, and a missing
    `parent` is the deepest live node anchored to its lineage. Two or more
    nodes tying for that place leave the parent at the top level, with an
    `ambiguous_parent` issue.
  - Without an `aphia_id`, `label` is required, and a missing `parent` means
    the top level.
- **Preview, then confirm.** A call without a valid `confirm` publishes
  nothing. It returns `200` with the resolved plan, its issues (WoRMS
  warnings and `ambiguous_parent`, each with suggested request edits) and a
  signed `confirm` key that binds this request to this plan. Sending the same
  request with its key re-plans on the latest revision and, if the plan is
  unchanged, creates and publishes a one-change changeset (`201`). Otherwise it
  returns a fresh preview and key, with `confirm_status` saying why. Errors
  (invalid or taken label, unknown parent, no WoRMS record, WoRMS unreachable,
  not an approver) return no key.
- Published quick adds are ordinary changesets and revisions, with the caller
  as author and publisher, so history, diffs and revision changes need nothing
  new.
- **Web app:** a **Quick add** page for a tree, linked from the tree browser
  for its approvers. It has a WoRMS search, optional label and parent, and
  Preview. The preview shows the plan, its issues and their suggested edits,
  and then Confirm. It uses the endpoint above, as any other client would.
- Docs: the "Quick add (planned)" section of `design/api.md` and
  `design/diagrams/07-quick-add` become the endpoint's documentation, and
  `design/webapp.md` gets the page.

## Capabilities

### New Capabilities
- `quick-add`: the preview-then-confirm endpoint for adding and publishing a
  single node, including how the label and parent are resolved, the issues it
  reports, the confirm key and its error responses.

### Modified Capabilities
- `webapp`: adds a Quick add page requirement. The `webapp` capability is
  introduced by the `webapp-and-write-api` change, which must be archived
  first.

## Impact

- **API:** a new module `src/api/quick_add.py` on the trees router, which reuses
  `core.validation.validate`, `core.changesets.create_changeset` /
  `publish_changeset` and `api.worms.cached`. There is no model or migration
  change. The confirm key uses `django.core.signing` with the site's
  `SECRET_KEY`.
- **Shared rules:** the label and parent rules move into Python
  (`core`/`worms`), with the same behaviour as `wormsLabel` and
  `suggestParent` in `static/app/expanders.js`.
- **Web app:** a new view, URL and template, a small Alpine component, and a
  link in the tree browser.
- **Docs:** `design/api.md`, `design/webapp.md`, `design/diagrams/07-quick-add`
  (error code wording), README API section.
- **Tests:** API tests for resolution, issues, the key's life cycle, retries
  and roles, plus browser tests for the page.
