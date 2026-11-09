# Proposal

## Why

When adding a node from WoRMS (Quick add, or Add from WoRMS in the tree editor),
the user can't easily check the record they picked: neither page links to its
WoRMS page, and the Quick add response carries only the AphiaID. And labels
derived from WoRMS names keep WoRMS's capitalisation (`Chaetoceros_debilis`),
while the trees we curate use lowercase labels, so almost every derived label
gets retyped.

## What Changes

- The Quick add response gives the record's WoRMS page as `worms_url`: in the
  preview's `plan` and in the published `node` (`null` without an AphiaID).
- The Quick add page shows that URL as a plain, full link in the preview and
  after publishing. The tree editor's Add from WoRMS dialog shows the picked
  record's WoRMS URL the same way.
- A **Lowercase label** toggle in Quick add and in Add from WoRMS, on by default:
  the label derived from the WoRMS name is lowercased (`chaetoceros_debilis`).
  A label the user types is used as is.
- The Quick add request gets `lowercase_label` (boolean, default `true`), which
  applies only to a derived label. **BREAKING** for Quick add clients relying on
  the derived label's case: the default derived label is now lowercase. Quick
  add isn't released yet, so nothing outside this repository depends on it.

Not in this change: a per-tree label case policy (`labelcase_policy`: strict or
recommended, case-sensitive or case-insensitive labels, and how WoRMS-derived
labels follow it). It is noted as a future investigation; until then the
toggle's default is fixed.

## Capabilities

### New Capabilities

None.

### Modified Capabilities
- `quick-add`: "Quick add request" gains `lowercase_label`; "Label from WoRMS"
  lowercases a derived label by default; "Quick add preview" and "Published
  quick adds" include `worms_url`. (Introduced by the `quick-add` change, not
  yet archived.)
- `webapp`: "Add from WoRMS" gets the lowercase toggle and the record link;
  "Quick add preview and confirm" shows the WoRMS link and the toggle.
  (Introduced by `webapp-and-write-api` and `quick-add`, not yet archived.)

## Impact

- `src/worms/placement.py` (`worms_label`) and `src/static/app/expanders.js`
  (`wormsLabel`) get a lowercase option; the shared `label_cases.json` gains
  lowercase rows.
- `src/api/quick_add.py`: request field and `worms_url`.
- `src/static/app/quick_add.js`, `browser.js`, `quick_add.html`,
  `browser_dialogs.html`.
- Tests asserting `Chaetoceros_debilis` as a derived Quick add label.
- Docs: `design/api.md`, `design/webapp.md`, the README curl example,
  `design/diagrams/07-quick-add.mmd` (derived label in the example).
- Archive order: `webapp-and-write-api`, then `quick-add`, then this change.
