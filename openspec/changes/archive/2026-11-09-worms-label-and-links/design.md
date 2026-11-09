# Design

## Context

The label rule exists twice: `worms_label` (Python, Quick add) and `wormsLabel`
(browser, Add from WoRMS). A shared table, `src/worms/tests/label_cases.json`,
keeps them in step. The browser already builds WoRMS URLs (`wormsUrl` in
`static/app/model.js`), and the node page has the same URL in its template.
Quick add signs the request (without `confirm` and `notes`) into its confirm key,
so any new request field takes part in "body changed".

## Goals / Non-Goals

**Goals:**
- One lowercase rule in both implementations, tested by the same rows.
- The server owns the URL it returns; the page just displays it.

**Non-Goals:**
- A configurable default (env or per tree). The toggle starts on, fixed in code;
  `labelcase_policy` is the later place for it.
- Case-insensitive label uniqueness. `Chaetoceros` and `chaetoceros` remain
  different labels.
- Links on every search result row. Only the picked record and the plan get one.

## Decisions

- **Lowercase as a parameter of the label rule.** `worms_label(name, lower=False)`
  and `wormsLabel(name, lower = false)` lowercase after the other steps. The
  default `False` keeps the function a pure "clean the name" rule; callers pass
  the toggle. `label_cases.json` rows (`[name, label]`) gain a third column, the
  lowercase result, and both tests check both columns.
  *Alternative:* lowercase at each call site. Rejected: the two implementations
  could drift again, which is what the shared table exists to stop.
- **`lowercase_label` defaults to `true` in the API too.** The API and the page
  derive the same label for the same record. A client that wants WoRMS's case
  sends `false` or a `label`.
- **One server-side URL helper.** `worms_url(aphia_id)` next to the WoRMS
  client returns the `aphia.php?p=taxdetails&id=` URL; Quick add uses it for
  `plan.worms_url` and `node.worms_url`. The format matches the browser's
  `wormsUrl` and the node page, so all links look the same.
- **"Typed label" tracking in Add from WoRMS.** The dialog keeps a flag set when
  the user edits the label field. While it's unset, picking a record or
  switching the toggle recomputes the label. On the Quick add page an empty
  label field already means "derive it", so the toggle is simply sent as
  `lowercase_label` and the preview shows the result.

## Risks / Trade-offs

- [Derived labels change case for existing Quick add callers] → Quick add is
  unreleased; tests and docs are updated in this change.
- [Lowercase labels next to existing capitalised ones, e.g. `chaetoceros_debilis`
  beside `Chaetoceros`] → Accepted for now; deciding a tree's convention is the
  `labelcase_policy` investigation.
