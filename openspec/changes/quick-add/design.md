# Design

## Context

Writes go through changesets. `core.validation.validate` checks a change list
against the latest revision and reports structural errors and WoRMS warnings
from cached records. `core.changesets.create_changeset` and `publish_changeset`
save a draft and publish it under the tree's advisory publish lock.
`api.worms.cached` reads a record and fetches it on a miss, with `404` and
`503` already mapped. The label and parent rules exist only in the browser
(`wormsLabel`, `suggestParent` in `static/app/expanders.js`). `suggestParent`
takes the first node it finds and doesn't detect ties.

The behaviour is in `specs/quick-add/spec.md`, and the call sequence is in
`design/diagrams/07-quick-add`.

## Goals / Non-Goals

**Goals:**
- No server-side state between preview and confirm, and nothing to clean up.
- Reuse the existing validate, create and publish path, so a quick add can't
  disagree with what a draft would do.

**Non-Goals:**
- Adding more than one node, or editing, moving or deprecating nodes.
- Adding the accepted name's ancestors that are missing from the tree. Only
  the deepest anchored ancestor is used.
- Changing the editor's Add from WoRMS, which keeps its first-match
  `suggestParent`.

## Decisions

### Stateless signed key (over draft-backed or dry_run)
The key is `django.core.signing.dumps({tree, user, req, plan}, salt="quick-add")`,
compressed, and read with `loads(max_age=900)`.
- `req` is a SHA-256 of the canonical JSON of the parsed request with `confirm`
  and `notes` removed. Parsing through the Schema first means key order,
  whitespace and `1` versus `1.0` don't matter.
- `plan` is a SHA-256 of the canonical JSON of `{label, parent, aphia_id,
  description, aliases, issues}`.

Alternatives considered:
- A draft changeset per preview leaves abandoned drafts and needs an ETag
  round trip.
- A bare `dry_run` lets a client commit something it never previewed.

The key is a capability for the caller only. Binding `user` stops a key being
replayed by someone else. The key's own timestamp is the only freshness check;
there is no nonce store. Replay is harmless because a re-plan after the publish
always differs (see Risks).

### One handler, with confirm deciding
`quick_add(request, tree, body)`:

1. Check the role.
2. Resolve the record, label and parent.
3. Build the change `[{op: add, node: "n1", label, parent, aphia_id,
   description, aliases}]`.
4. Run `validate()` against the latest revision. Structural errors give a
   `422` (the shape of the existing `structural` refusal: `errors` list), with
   no key.
5. Build the issues.
6. If a `confirm` was given:
   - check its signature and age, then its user and tree, then `req`, then
     `plan`;
   - on a full match, publish;
   - otherwise fall through, with `confirm_status` set to `expired`,
     `invalid`, `body_changed` or `plan_changed`.
7. Return the preview with a new key.

The check order means a modified body reports `body_changed` even if the plan
also changed.

### Publishing
After the key matches:
- `create_changeset(author=user, changes, tree, base_rev=latest, notes=notes
  or "Quick add")`, then `publish_changeset(changeset, published_by=user,
  notes=...)`.
- Both run in one `transaction.atomic()`, so a failed publish leaves no stray
  draft.
- `publish_changeset` takes the lock, then rechecks `base_rev == latest`. A
  publish between our re-plan and the lock gives `stale_base`, and the handler
  retries the whole plan once before answering `plan_changed` or publishing.
- `publish_in_progress` is passed through as `409`.

The published revision's WoRMS checks use the record fetched in step 2, which
is now cached.

### Resolution rules in Python
`core/quick_add.py`, or `worms/placement.py` for the WoRMS-specific parts,
holds the rules:
- `worms_label(name)` mirrors `wormsLabel`.
- `lineage_parent(state, lineage)` walks the lineage from deepest to top,
  skipping the record itself, and finds the live nodes anchored to each
  AphiaID using `worms.checks.aphia_index`. It returns `(node, [])` for one
  match, `(None, candidates)` for a tie, and `(None, [])` when there is none.

A shared fixture table (name → label) is checked by both the pytest tests and
a Playwright `evaluate` test against `X.wormsLabel`, so the two can't drift.

### Issues
Issues come from `validate()`'s `warnings` for change `n1`, with WoRMS codes
passed through, plus `ambiguous_parent` from resolution. Options:

| Issue | Options |
|---|---|
| `unaccepted_aphia` | `{aphia_id: valid_AphiaID}` ("Use the accepted name …") |
| `ambiguous_parent` | `{parent: id}` per candidate, plus `{parent: null}` |
| `out_of_lineage` | `{parent: <lineage parent>}` when there is one |
| `duplicate_aphia` | none (cancelling means not confirming) |

The options are part of the plan hash only through the issue codes and their
details. They are derived deterministically, so hashing the whole issue list
is fine.

### Response shapes
- **Preview `200`:** `{status: "preview", confirm_status, tree, rev, plan:
  {label, parent: {id, label} | null, aphia_id, description, aliases},
  issues: [{code, message, options: [{label, set}]}], confirm}`.
- **Published `201`:** `{status: "published", confirm_status: "accepted",
  node: {id, label, parent, aphia_id}, rev, changeset, warnings}`.
- **Errors:** the existing error envelope, `{error, detail, errors?}`.

### Route and auth
- The route lives in `api/quick_add.py` with its own router mounted at
  `/trees`, or on `trees.router`. It needs auth (not in `ANONYMOUS_ROUTES`),
  and session calls are CSRF-checked like other writes.
- The role check is `require(user, tree, Role.APPROVER)`.

### Web app page
- **View:** `quick_add_page(tree_id)` checks `approver` (else the 403 page),
  then renders `quick_add.html` with the tree and a page-data blob.
- **Component:** `static/app/quick_add.js` reuses:
  - `api.js` (`post`, CSRF meta);
  - the WoRMS search markup pattern from the Add from WoRMS dialog;
  - a parent picker: a label search box using `GET /trees/{tree}/search`, plus
    "top level" and "work it out".
- The page keeps the last request and key in memory. Option buttons patch the
  form and preview again. Confirm posts the last request plus the key. A `201`
  shows a success panel with links.
- **Link:** a **Quick add…** button in the tree browser's static-mode toolbar
  for approvers (`can_approve` is already in the page data, or add it).

## Risks / Trade-offs

- **[Replayed key after publish]** → After a publish, the same request
  re-plans to a label collision (`422`) or a `duplicate_aphia` issue (plan hash
  differs). So a replay can't publish twice. A test covers both cases.
- **[A synchronous WoRMS fetch makes the request slow]** → Only on a cache miss,
  and bounded by the client's timeouts and retries. Clients that care can
  `GET /worms/{id}` first.
- **[`SECRET_KEY` rotation invalidates keys]** → The client gets
  `confirm_status: "invalid"` and a fresh preview. That's harmless.
- **[Python and JS label rules drift]** → The shared fixture test.
- **[A tie silently defaults to the top level on confirm]** → It is always
  reported as an issue with options, and the default is in the spec.

## Migration Plan

Additive only: no models, migrations or settings. Rolling back removes the
route and page.
