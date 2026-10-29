# Design

## Context

Builds on `core-tree-model` (engine, read API, `import_tree`) and
`worms-integration` (record cache, placement checks, warning history, and
drift runs, which this change renames syncs). The engine already reduces, validates and publishes changesets and is
called only from management commands. Saving and publishing currently fetch
missing or stale WoRMS records before their transaction, and drift runs stop at
the first AphiaID that keeps failing. The interactive mockup
`design/mockups/webapp-mockup.html` and its spec define the intended look and
interaction. See proposal.md for motivation.

## Goals / Non-Goals

**Goals:**

- One authorisation layer shared by API and web app.
- Keep the engine the only place that reduces, validates and publishes. The
  browser only composes change lists and renders server results.
- Plain call-and-response between browser and server: no live checking while
  composing, and every slow WoRMS operation is a job the browser polls.
- Reuse the mockup's layout and Alpine.js state model rather than redesign.

**Non-Goals:**

- A visual diff of a draft against its base revision beyond the draft markings
  and the By node tab.
- Reordering changes by drag and drop.
- Highlighting between changes-panel tabs (only tab entries to tree nodes).
- Keeping the as-composed list of a saved draft: only the reduced list is
  stored.
- Linking a clone to its source tree.
- Users creating their own tokens, or managing users outside Django admin.
- Roles that apply to a single tree within an organization.

## Decisions

### Authentication

- **Anonymous reads.** The read routers (`/trees` and `/nodes` GETs, alias and
  description history, `GET /worms/warnings`, `/health`) take no auth, so
  roi-db, datasetman and annotation tools keep reading as they do today.
- **Sessions** via Django auth for the web app, with standard login and CSRF.
  django-ninja's `SessionAuth` (CSRF-checked) covers API calls the browser
  makes.
- **Tokens:** an `ApiToken` model (hashed key, owning user, name, created,
  `last_used_at`, revoked) checked by a django-ninja `APIKeyHeader`
  (`Authorization: Token <key>`). The admin add form shows the key once. A
  token acts as its user, with that user's roles.
- **Default deny.** Token and session auth are the API's global `auth`; the
  read routes opt out explicitly with `auth=None`. A test walks every route of
  the API and checks it against the list of anonymous routes, so a new route
  is authenticated unless it is deliberately added there.

- **Login rate limiting** with django-axes: 5 failed logins for one username
  from one address lock that pair out for 15 minutes. Apache's stock modules
  only throttle bandwidth, and locking the pair rather than the username keeps
  others from locking a user out. The address is the `X-Forwarded-For` entry
  Apache sets; gunicorn listens on `127.0.0.1` only, so the header can't be
  sent around the proxy. Tokens are 256-bit random keys, so guessing them
  needs no limit.

Alternative: django-rest-knox, OAuth or WHOI single sign-on. Rejected or out
of scope: nothing here needs expiry flows or third-party login.

### Organizations and roles

```
 site      admin (Django superuser): users, tokens, organizations; owner of every organization; sync_all
 per org   owner > approver > drafter > reader      one row per (user, organization)
           every tree belongs to one organization; a role applies to all of its trees
```

- **Storage:** `Organization(id slug, name)` and `OrgMember(user, org, role)`
  in `accounts`, unique on `(user, org)`, with `role` an ordered choice.
  `Tree.org` is a required foreign key. One row holds the highest role; the
  lower ones are implied, which is how "setting approver also gives drafter"
  works without extra rows, and why the interface shows one role. Existing
  trees move into organization `amplify` (`AMPLIfy`) in the migration.
- **Checks:** one helper, `require(user, tree, minimum)`, looks up the user's
  role in the tree's organization (`owner` for superusers), compares it with
  the minimum and raises `401` or `403`. Every router and view calls it. It
  keeps the tree in its signature, so per-tree overrides could be added in one
  place later. The minimums, from the `access-control` spec, in one place:

  | Minimum | Actions |
  |---|---|
  | none | tree, node and organization reads, warnings report |
  | `reader` | drafts (list, get), job status, members list, WoRMS lookups |
  | `drafter` | validate, save, rebase and discard drafts, fetch jobs (per organization), `sync_new` and `sync_tree` jobs, aliases, descriptions |
  | `approver` | publish |
  | `owner` | change members; validate, create, change, publish and discard new-tree changesets in the organization |
  | superuser | `sync_all`; create organizations and move trees between them (Django admin) |

  WoRMS lookups and job status for `sync_all` aren't tree-scoped: any
  authenticated user may call them. A new-tree changeset has no tree yet; its
  checks use the organization in `new_tree.org`, stored as
  `Changeset.new_tree_org`.
- **Members:** `GET /orgs/{org}/members`, `PUT /orgs/{org}/members/{username}
  {role}` and `DELETE /orgs/{org}/members/{username}`. Changing or removing an
  owner locks the organization's member rows (`SELECT ... FOR UPDATE`) and
  refuses with `409 last_owner` if no owner would remain, unless a superuser
  makes the change.
- **Organization reads:** `GET /orgs` and `GET /orgs/{org}` (name and trees)
  are anonymous, like tree reads; `GET /trees` adds each tree's `org`. Tree
  ids stay globally unique and `/trees/{tree}` URLs are unchanged, so
  consumers don't need to know about organizations.
- **Django admin** is for site admins only: users, tokens, organizations,
  `OrgMember` rows for repairs such as an organization with no owner, and a
  tree's organization, the only editable field on a tree.

Alternatives:
- Roles per tree (`TreeMember`). Rejected: every new tree would need its
  members set up again, and the trees curators share are managed by the same
  people anyway.
- Organization roles with per-tree overrides. Deferred: it brings back a
  second membership table and rules for which role wins. A tree that needs
  different people can live in its own organization.
- Owners managing roles in Django admin. Rejected: Django admin permissions
  are per model, not per organization, so an owner could grant roles anywhere.

### WoRMS stays out of saves and publishes

`fetch_records` and `PUBLISH_MAX_AGE` go. `validate`, save and publish build
their records from the cache only (`newest_rows`, complete rows), and anything
missing makes the affected changes `unavailable`, exactly as an outage did
before. Keeping the cache current is the job of the fetch step behind the
Validate button and of sync runs, on demand or from cron.

Alternative: keep fetching on save and publish with a short budget. Rejected:
a request that may take 30 s on a bad WoRMS day, with no progress shown, is
what this change removes.

### WoRMS jobs

The drift runner in `worms/drift.py` generalises into one job runner in
`worms/sync.py`, for four kinds. "Drift" disappears from the API, code and docs:
the three re-fetching kinds are **syncs**.

| Kind | Fetches | Then | Lock |
|---|---|---|---|
| `fetch` | given AphiaIDs without a complete cached row; scoped to an organization, not a tree, so new-tree drafts can use it | nothing (cache only) | none |
| `sync_new` | the tree's AphiaIDs without a complete cached row | re-check tree, write warnings | `worms-sync:<tree>` |
| `sync_tree` | every AphiaID in the tree (today's drift run) | re-check tree, write warnings | `worms-sync:<tree>` |
| `sync_all` | every cached AphiaID and every tree's AphiaIDs | re-check every tree | `worms-sync:all`; refused while any `worms-sync:<tree>` is held, and tree syncs are refused while it is held |

- **Endpoints**, all under `/worms`, since jobs aren't tree content and
  `sync_all` has no tree:
  - `POST /worms/jobs {kind, tree?, org?, aphia_ids?}` (`org` for `fetch`,
    `tree` for `sync_new` and `sync_tree`, neither for `sync_all`) returns
    `202` with the job's status, or `409 sync_in_progress`;
  - `GET /worms/jobs/{job}`;
  - `GET /worms/jobs?tree=` returns the tree's active and last sync, or, without
    `tree`, the active and last `sync_all`;
  - `GET /worms/warnings?tree=` is the warnings report, feeding the warnings
    panel.

  They replace `POST /trees/{tree}/drift`, `.../drift/status` and `.../drift`.
- **Status** lives in the DatabaseCache as drift status does now, keyed by a
  job id (UUID), with `worms-sync:<tree>` (and `worms-sync:all`) pointing to the
  active and last sync. Each job holds a session advisory lock `worms-job:<id>` for its
  lifetime, so a status whose lock is free is reported `interrupted`; startup
  clears these through `clear_worms_jobs`, which replaces `clear_drift_status`.
- **Retry visibility:** `WormsClient` takes an `on_wait(aphia_id, attempt,
  retries, seconds)` hook next to `sleep`; the runner records it in the job's
  `retrying` map and clears it when the AphiaID finishes. The browser draws one
  bar per entry from `wait_until` and the schedule.
- **Schedules:** `JOB_BACKOFF = (1, 2, 5, 12)` for API-started jobs,
  `SCHEDULED_BACKOFF = (10, 30, 60, 120)` (today's `DRIFT_BACKOFF`) for the
  management command, `BACKOFF =
  (1, 2)` for lookup endpoints.
- **Failures skip:** `get_records` loses `stop_on_error`; each failing AphiaID
  goes to `failed` and the pool carries on. Sync kinds then re-check with the
  records they have and write rows only for nodes whose needed records are all
  present and were not in `failed` (`check_nodes` already returns `None` for a
  node missing a record; the run additionally treats failed AphiaIDs as
  missing).
- **429:** the client raises a distinct `RateLimited(retry_after)` instead of
  sleeping itself. The runner sets `paused`, stops handing out AphiaIDs, waits,
  and resumes. A second 429 after resuming ends an API-started job (remaining
  AphiaIDs to `failed`); management-command jobs allow 4 pauses. Lookups keep
  today's per-request handling.
- **Try again** in the web app starts the same kind with `aphia_ids` set to the
  failed ones. For sync kinds the whole tree is still re-checked.
- **Management command:** `worms_sync <tree>` (`sync_tree`), `worms_sync <tree>
  --new` (`sync_new`), `worms_sync --all` (`sync_all`), replacing `run_drift`.
  It exits non-zero if any
  AphiaID failed, so cron mail reports it, after writing what it could.

Alternative: stream progress over one long HTTP response. Rejected: it ties a
server worker for minutes, and drift runs already use polled status in the
cache.

### Validate flow

```
 [Validate] -> POST validate (cache only)
                 |
        worms_missing empty? --yes--> show result, enable Save
                 | no
                 v
          POST worms/jobs {kind: fetch, org, aphia_ids: worms_missing}
          poll GET /worms/jobs/{job} ~1 s: job bar, retry bars, pause bar
                 |
           failed empty? --no--> list failures: [Try again] | [Proceed anyway]
                 | yes                               |
                 v                                   v
          POST validate again ---------------> show result, enable Save
```

Save is gated only in the browser. The server always reduces and runs
structural checks on save; an API client that skips the fetch step gets
`unavailable` checks for uncached AphiaIDs, which the next sync fills in.
Structural errors don't block save (the web app asks for confirmation), only
publish.

### Changeset endpoints

Every changeset endpoint lives under `/changesets`: `POST /changesets/validate`
and `POST /changesets` take either `{tree, base_rev, ...}` or `{new_tree:
{id, title, description, org}, ...}`, and `GET /changesets?state=&tree=&org=`
lists what the user may see (changesets on their organizations' trees and
new-tree drafts for their organizations; everything for site admins). A
new-tree draft is thus validated, listed and saved like any other.

These are thin wrappers around the engine. The `ETag` of a draft is a hash of
`(id, updated_at, base_rev, changes)`. `PUT` and `publish` compare `If-Match`
inside a `SELECT ... FOR UPDATE` on the changeset row, so the `412` check and
the write are atomic. `validate` runs the same path as save, without the final
write, and `GET /changesets/{cs}` computes the same result for a stored draft.

### Change provenance (`sources`)

`ChangeSpec` gains `sources: tuple[int, ...]`, set to `(seq,)` by
`specs_from_dicts`. Every rewrite in reduction combines them: `_merged` takes
the union of both changes' sources, a successor collapse keeps the earlier
deprecate's sources plus the later one's, and drops discard theirs. `renumber`
keeps them. `validate` returns them on `reduced_changes`; they are not stored,
since a saved draft's reduced list becomes the new as-composed list when it is
reopened.

This answers the question left open by `core-tree-model` (groups are only labels
and reduction keeps the last change's group): group tags are taken from every
source, so a split's `add` that was later renamed by hand still shows under
`split#1` in By node, while `reduced_changes[].group` keeps today's rule.

### Net changes per node (`node_changes`)

Computed from the base state and the final state only, alongside
`version_changes`: for each node whose content, parent, child set or
deprecation differs, the changed fields as `[old, new]`, children gained and
lost, successors, the reduced `seq`s that touch it (as node, parent or
successor), and the union of those changes' source groups. Because it ignores
order, temporary labels and moves undone by hand never show. For a draft with
errors, the final state is what applied, so the review shows errors next to the
net changes.

Alternative: regroup the ordered changes under nodes. Rejected: a change
belongs to several nodes, interleaving (e.g. label swaps) is lost, and editing
from that view would act on a list the user can't see in order.

### Web app

- Server-rendered Django templates for the page frame, login, node page and
  draft list. The tree browser and draft editor are one page whose state is an
  Alpine.js store, ported from the mockup, that talks to `/api/v1` with the
  session.
- **No live checks.** The mockup's local JavaScript checks are dropped; the
  only check before Validate is what composing itself needs (Move to excludes
  descendants, Deprecate is blocked on nodes with children).
- **Changes panel tabs:** As edited (the editable list), As reduced, By node,
  Summary, WoRMS warnings and Errors. Each tab remembers the validation id it
  last showed; a newer result sets its unread dot. After an edit, the
  result tabs are greyed with "out of date, press Validate".
- **Jump to node:** a tab entry maps to node ids (for a move: the node, and the
  old and new parents for hover); click expands ancestors via the store,
  scrolls into view and flashes the row.
- **AphiaID pill:** colour from `worms_data` and current `worms_warnings` in
  the node payload: no `worms_data` and no `unknown_aphia` is grey (never
  fetched), `unknown_aphia` red with a `?` badge, any other warning orange with
  a `!` badge, else green. The badges keep the states apart without relying on
  colour. The link
  is `https://www.marinespecies.org/aphia.php?p=taxdetails&id=<id>`.
- **Sync menu and progress** share one progress component with Validate's
  fetch step; the menu polls `GET /worms/jobs?tree=` while open, so a
  cron run is visible.
- Merge, split, import, clone and Add from WoRMS are client-side expanders that
  produce grouped change lists, with no endpoints of their own. Import parsing
  runs in the browser using the same rules as the server format, and clone
  fetches `/trees/{tree}/nodes_as_tree?rev=` and runs it through the same
  client expander. The server re-validates everything on save.
- **Labels from WoRMS names:** spaces become `_`, then characters outside
  `[A-Za-z0-9_.-]` are dropped, as is leading punctuation.
- Aliases after a merge: after a successful publish response, the client issues
  `POST /nodes/{id}/aliases` for each missing label and alias. A failure is
  shown to the user with a retry. It is not transactional with the publish,
  which matches the spec, since aliases sit outside changesets.

Alternative: an HTMX-style fully server-rendered editor. Rejected, because the
mockup's interaction (markings, pick mode, wizards) is already built in
Alpine.js and maps directly onto the API.

### Bootstrap and Alpine from static files

Bootstrap 5 and Alpine.js are vendored into `static/`, not loaded from a CDN,
so the app works on isolated lab networks. In production Apache
serves `/static/` from `/opt/labeltree/static`, which the container's
`collectstatic` fills on start through a bind mount.

### Content Security Policy and Alpine's CSP build

Standard Alpine compiles the expressions in HTML attributes with
`new Function()`, which needs `script-src 'unsafe-eval'` and turns any
injected `x-init` or `@click` attribute into running script. So the app uses
Alpine's CSP build, under Django's built-in CSP middleware:

```
default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline';
img-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self';
frame-ancestors 'none'
```

- All logic lives in `Alpine.data` components in static ES modules
  (`static/app/`). The CSP build (3.17) parses attribute expressions itself,
  without `eval`: property reads, comparisons, ternaries and calls of the
  component's methods work, but not assignments to nested properties,
  template literals, arrow functions or globals (`JSON`, `Number`, …), so
  those live in the component as getters and methods.
- `img-src data:` is for Bootstrap's inline SVG icons (select arrows, close
  buttons). The API's `/docs` page, which loads Swagger UI from a CDN, is
  exempt (`csp_override`).
- No inline `<script>`; page data a script needs comes from `json_script` or
  the API.
- Inline styles stay allowed: injected styles are a much smaller risk than
  injected scripts, and Alpine's string `:style` bindings need them.
- Bootstrap 5 runs unchanged under this policy.

Alternative: standard Alpine with `'unsafe-eval'`. Rejected: injected markup
could still execute through Alpine attributes.

## Risks / Trade-offs

- [A new route is accidentally anonymous] → Auth is the default; the route
  test fails for any anonymous route not on the list.
- [Anonymous reads expose tree content to anyone on the network] → As today;
  trees hold label names and descriptions, nothing sensitive. Drafts, members
  and job details need a login.
- [An organization is left without an owner] → The last-owner rule; a site
  admin can repair it in Django admin.
- [A role covers trees its holder shouldn't edit] → Roles apply to the whole
  organization by design; trees maintained by different people belong in
  different organizations, which a site admin can move them to.
- [Warnings computed at publish may use an older cached record] → A record is
  as fresh as the last fetch or sync; nightly `sync_tree` runs and Sync this
  tree bound the age. Each warning-history row's `computed_at` is unchanged in
  meaning.
- [API clients that skip the fetch step publish `unavailable` checks] →
  Acceptable by design; `sync_new` (and cron) fills them in.
- [Client-side import parsing diverges from the server's] → The server is
  authoritative and returns errors per change. A shared JSON fixture set is
  tested against both parsers.
- [`sources` tracking makes reduction rewrites harder to get right] → The
  existing reduction tests gain `sources` assertions, plus the worked examples
  (split then rename, label swap, move undone by hand).
- [Polling many job statuses] → One poll per second per open progress view, on
  a cached value; stop polling when the job finishes or the view closes.
- [Alias copy after a merge can partially fail] → The UI lists any aliases it
  could not copy and offers a retry.

## Migration Plan

1. Deploy the migrations, which add tokens, organizations and members, and
   put the existing trees in organization `amplify`. Reads are unaffected, so
   consumers need no change.
2. In Django admin, create curator accounts and make at least one of them an
   owner of `amplify`. Owners then add the other members on the organization
   page.
3. Issue tokens to scripts that write.
4. Install the Apache site from `config/apache2/` (TLS, `/static/` from
   `/opt/labeltree/static`, which `collectstatic` fills on start) and set
   `DJANGO_BEHIND_TLS_PROXY=true`.
5. Replace `run_drift` with `worms_sync` in the cron entry. Its exit status
   now reports any failed AphiaID rather than a stopped run.

Rollback: revert to the previous release. Tokens and members stay in place,
unused.
