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
- **Sync:** re-fetch our AphiaIDs and re-check our anchored nodes against the
  current WoRMS hierarchy.

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
- **No runtime dependency.** Reads, saves and publishes never touch
  marinespecies.org. WoRMS is needed only by the lookup endpoints and by
  [WoRMS jobs](#worms-jobs-and-syncs) that refresh the cache.
- **Simpler versioning.** We version our own data. WoRMS has no releases, so a
  portal would have to snapshot WoRMS and the overlay together.

The cost is maintaining the tree ourselves. Import from WoRMS, placement checks
and syncs keep that cost low.

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
| `unaccepted_aphia` | WoRMS points this AphiaID to a different accepted AphiaID, whatever its status (`unaccepted`, `superseded combination`, a synonym, or `unassessed` with an accepted name given). The accepted AphiaID is suggested. | A species renamed in WoRMS since it was added. |
| `unknown_aphia` | WoRMS has no record for this AphiaID. | A mistyped AphiaID. |
| `duplicate_aphia` | Another node in the same tree has the same AphiaID. | The same species added twice under different labels. |

"WoRMS ancestors" means the node's lineage from WoRMS
(`AphiaClassificationByAphiaID`). WoRMS lineages contain accepted names only, so
if the nearest anchored ancestor has an unaccepted AphiaID, its `valid_AphiaID`
is compared instead; otherwise every descendant of a synonym would get an
`out_of_lineage` warning. A node with no anchored ancestor gets no
`out_of_lineage` check.

### When checks run

Checks run on `validate`, when saving a draft, and again on publish
([webapp.md](webapp.md#changesets-and-concurrency)), always against cached
records: none of them calls WoRMS. The web app's Validate button first runs a
fetch job for the AphiaIDs the draft needs that aren't cached
([webapp.md](webapp.md#validating-a-draft)). A
[sync](#worms-jobs-and-syncs) reruns the checks for the whole tree.

Moving or re-anchoring one node can change warnings on nearby nodes, so an edit
rechecks:

- the node itself
- **looking down:** the first anchored node on each path below it, since its
  nearest anchored ancestor may have changed. Nodes further down keep the same
  nearest anchored ancestor.
- any other node in the tree with the same AphiaID

Ancestors don't need rechecking.

If a record the checks need isn't cached (never fetched, or every fetch
failed), the affected changes record "checks unavailable" and publishing is
still allowed. The next fetch or sync fills the warnings in.

### How warnings are stored and shown

- `NODE_WARNINGS` keeps each node's warnings over time. Publishing and syncs
  add a row only when a node's warnings differ from its newest row,
  including an empty list when its warnings clear. The newest row is the
  node's **current** set, which is all the API shows by default
  (history: `GET /nodes/{id}/warning_history`).
- Each row records when it was computed (`computed_at`).
- A node whose warnings can't be computed, because a record they need isn't
  cached or failed to refresh in that sync, gets no row.
- Warnings never bump node versions and never block publishing.
- The API returns them on every detailed node as `worms_warnings`, a list that
  is empty when there are none:

  ```
  worms_warnings: [
    {warning: "out_of_lineage",
     detail: "Nearest anchored ancestor Dinophyceae is not in the WoRMS lineage of Chaetoceros."}
  ]
  ```

## WoRMS jobs and syncs

![WoRMS sync](diagrams/06-worms-sync.png)

Everything that fetches from WoRMS in bulk is a **job** that runs in the
background, because fetching hundreds of AphiaIDs takes minutes. Starting one
returns `202 Accepted`, and its status, with progress, is polled
([api.md](api.md#worms-jobs-and-warnings)).

| Kind | Started by | Fetches | Then |
|---|---|---|---|
| `fetch` | the web app's Validate button (drafter) | the given AphiaIDs that aren't cached | nothing: it only fills the cache |
| `sync_new` | drafter, approver, admin | the tree's AphiaIDs that aren't cached | re-checks the tree |
| `sync_tree` | drafter, approver, admin, or cron | every AphiaID in the tree | re-checks the tree |
| `sync_all` | superuser, or cron | every cached AphiaID and every tree's AphiaIDs | re-checks every tree |

The three sync kinds re-check warnings after fetching:

1. Collect the AphiaIDs to fetch from the latest revision.
2. Fetch each record and its lineage from WoRMS. `AphiaRecordsByDate` isn't
   enough on its own: if WoRMS moves a family our tree doesn't hold, only the
   family's record changes, not those of our genera below it. A tree uses a few
   hundred AphiaIDs, so a full sync takes minutes.
3. Re-run the placement checks for the whole tree, and add a `NODE_WARNINGS`
   row for each node whose warnings changed. A quiet sync writes almost nothing.
4. `GET /worms/warnings?tree=` reports the nodes that currently have
   warnings; the web app shows it as the warnings panel.

Jobs themselves aren't stored in the tree's tables. One sync per tree can be
active at a time, and a `sync_all` sync excludes every other sync,
enforced by PostgreSQL advisory locks that are released when the sync ends or
its process dies. Fetch jobs exclude nothing. Job status (progress, AphiaIDs
being retried, a rate-limit pause, failures, and who started it when) is held
in Django's database cache, so that every server process sees it without an
extra service such as Redis. It is lost on restart, and startup clears status
left by an interrupted job.

WoRMS is fetched without locking the tree. A sync then re-checks and writes
its warnings in one short transaction under the tree's publish lock, against
the latest revision at that moment, so a revision published mid-run is never
overwritten with warnings from an older one.

### Failures and retries

- A timeout, connection error or `5xx` is retried: after 1, 2, 5 and 12 s for
  jobs started through the API, and after 10 s, 30 s, 1 min and 2 min for
  scheduled syncs, which have nobody waiting. Lookups retry after 1 and 2 s.
- An AphiaID that still fails is recorded with its reason
  (`worms_unreachable`, `worms_rate_limited` or `worms_error`), its cache rows
  are left alone, and the job carries on with the next one. A sync writes
  no warning row for nodes needing a failed record. The web app offers to try
  the failed AphiaIDs again; a scheduled sync leaves them to the next one.
- `429 Too Many Requests` limits all our requests, not one AphiaID, so it
  pauses the whole job for the response's `Retry-After` (30 s if absent). A job
  started through the API stops if it is rate limited again after resuming,
  listing the AphiaIDs it didn't fetch as failed; a scheduled sync pauses up
  to 4 times.

Syncs never propose or make changes to the tree, and never modify
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
WoRMS's `modified` time. A new row is added whenever the record or its lineage
changes, so the record seen when a node version was published can always be
looked up. The lineage is compared too because when WoRMS moves a family, the
genera below it get a new lineage while their own records, and `modified`
times, stay the same. Search results arrive without lineages; they are cached
without one, and the lineage is filled in on the first full fetch. The
cache is not a node field, so refreshing it never changes node versions. The
browser never calls WoRMS directly; it uses the
[WoRMS lookup endpoints](api.md#write-endpoints).

Citation and provenance: "WoRMS, accessed <fetched_at>", per AphiaID.
