# WoRMS

How labeltree-db uses the [World Register of Marine Species](https://www.marinespecies.org):
why the tree is ours rather than WoRMS's, how placements are checked, and what
we store.

## Why an owned tree

We own every node in the tree. A node may carry a WoRMS AphiaID, and its
placement is *checked* against WoRMS rather than *derived* from it. WoRMS is
also used to:

- **Import from WoRMS:** create a node or subtree from an AphiaID, pulling in
  name and lineage.
- **Report drift:** compare our anchored nodes with the current WoRMS hierarchy.

We chose this over a WoRMS portal with an overlay of our own labels because:

- **Stable ROI labels.** Node ids are ours and never change meaning. Changes in
  WoRMS (reclassifications, new synonyms) reach the tree only as reviewed edits,
  so existing annotations never shift silently.
- **Curated label sets.** Annotators need tens to hundreds of usable classes,
  not WoRMS's ~500k taxa. Our tree *is* that curated set.
- **Non-biological and informal labels.** Detritus, bubbles, "flagellate",
  morphotypes and "X_or_Y" mixes are ordinary nodes, not exceptions to WoRMS.
- **Multiple trees.** The same machinery serves taxonomy, parasites, morphology
  and lab-specific trees, including flat ones.
- **No runtime dependency.** Reads never touch marinespecies.org. WoRMS is
  needed only while editing, publishing and running drift reports.
- **Simpler versioning.** We version our own data. WoRMS has no releases, so a
  portal would have to snapshot WoRMS and the overlay together.

The cost is maintaining the tree ourselves. Import from WoRMS, placement checks
and drift reports keep that cost low.

## Placement checks

When a node has an AphiaID, the service compares where we put it with where
WoRMS puts it. Any disagreement becomes a **warning**: our tree may differ from
WoRMS, but the difference should be visible.

### The warnings

A node is *anchored* if it has an `aphia_id`. Checks walk past unanchored nodes,
such as `morphotype1` or `artifact`, as if they weren't there.

| Warning | Meaning | Example |
|---|---|---|
| `out_of_lineage` | The node's nearest anchored ancestor isn't one of its WoRMS ancestors. | *Chaetoceros* placed under *Dinophyceae*. Also catches rank inversions, e.g. a genus under a species. |
| `unaccepted_aphia` | WoRMS marks this AphiaID as unaccepted (e.g. now a synonym). The accepted AphiaID is suggested. | A species renamed in WoRMS since it was added. |
| `duplicate_aphia` | Another node in the same tree has the same AphiaID. | The same species added twice under different labels. |

"WoRMS ancestors" means the node's lineage from WoRMS
(`AphiaClassificationByAphiaID`). WoRMS lineages contain accepted names only, so
if the nearest anchored ancestor has an unaccepted AphiaID, its `valid_AphiaID`
is compared instead; otherwise every descendant of a synonym would get an
`out_of_lineage` warning. A node with no anchored ancestor gets no
`out_of_lineage` check.

### When checks run

Checks run on `validate`, when saving a draft, and again on publish
([webapp.md](webapp.md#changesets-and-concurrency)). A
[drift report](#drift-reports) reruns them for the whole tree.

Moving or re-anchoring one node can change warnings on nearby nodes, so an edit
rechecks:

- the node itself
- **looking down:** the first anchored node on each path below it, since its
  nearest anchored ancestor may have changed. Nodes further down keep the same
  nearest anchored ancestor.
- any other node in the tree with the same AphiaID

Ancestors don't need rechecking.

If WoRMS can't be reached, the affected changes record "checks unavailable" and
publishing is still allowed. The next drift report fills the warnings in.

### How warnings are stored and shown

- `NODE_WARNINGS` keeps each node's warnings over time. Publishing and drift
  reports add a row only when a node's warnings differ from its newest row,
  including an empty list when its warnings clear. The newest row is the
  node's **current** set, which is all the API shows by default
  (history: `GET /nodes/{id}/warning_history`).
- Each row records when it was computed (`computed_at`).
- Warnings never bump node versions and never block publishing.
- The API returns them on every detailed node as `worms_warnings`, a list that
  is empty when there are none:

  ```
  worms_warnings: [
    {warning: "out_of_lineage",
     detail: "Nearest anchored ancestor Dinophyceae is not in the WoRMS lineage of Chaetoceros."}
  ]
  ```

## Drift reports

![WoRMS drift report](diagrams/06-worms-drift-report.png)

Run by a drafter, approver or admin, or on a schedule. `POST
/trees/{tree}/drift` starts the run and returns `202 Accepted`, because
fetching every AphiaID from WoRMS takes minutes:

1. Collect every AphiaID used in the latest revision.
2. Re-fetch each record and its lineage from WoRMS. `AphiaRecordsByDate` isn't
   enough on its own: if WoRMS moves a family our tree doesn't hold, only the
   family's record changes, not those of our genera below it. A tree uses a few
   hundred AphiaIDs, so a full run takes minutes.
3. Re-run the placement checks for the whole tree, and add a `NODE_WARNINGS`
   row for each node whose warnings changed. A quiet run writes almost nothing.
   Runs themselves aren't recorded.
4. `GET /trees/{tree}/drift` reports the nodes that currently have warnings.

Drift reports never propose or make changes to the tree, and never modify
published node versions. Any fix is made by a drafter in an ordinary draft.

## What we store

WoRMS has no releases or version numbers; it is edited continuously.

- **AphiaIDs are permanent.** When a name becomes a synonym, its record stays
  and gets `status: unaccepted`, with `valid_AphiaID` pointing to the accepted
  name.
- Each record has a `modified` timestamp. `AphiaRecordsByDate` lists the
  records changed in a date range.
- The API has no per-record history. The website shows some edit history.

So the service keeps its own snapshot of the parts of WoRMS it uses. The
`WORMS_RECORD` cache stores each record as fetched, with `fetched_at` and
WoRMS's `modified` time. A new row is added whenever `modified` changes, so the
record seen when a node version was published can always be looked up. The
cache is not a node field, so refreshing it never changes node versions. The
browser never calls WoRMS directly; it uses the
[WoRMS lookup endpoints](api.md#write-endpoints).

Citation and provenance: "WoRMS, accessed <fetched_at>", per AphiaID.
