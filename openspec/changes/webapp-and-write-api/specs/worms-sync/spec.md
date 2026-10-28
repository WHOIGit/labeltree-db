# Spec Delta

## Purpose

Keeps cached WoRMS records and the warnings computed from them current, on
demand or on a schedule, so that WoRMS changes made since nodes were published
surface as warnings, without a sync ever editing the tree.

## ADDED Requirements

### Requirement: Sync kinds
A sync SHALL be a WoRMS job of one of three kinds. `sync_tree` SHALL re-fetch
the record and lineage of every AphiaID in the tree's latest revision.
`sync_new` SHALL fetch only those AphiaIDs in the tree's latest revision that
have no complete cached record. `sync_all` SHALL re-fetch every cached AphiaID
and every AphiaID in any tree's latest revision.

#### Scenario: Only new AphiaIDs
- **WHEN** a tree has 175 AphiaIDs and 3 of them have never been fetched
- **THEN** a `sync_new` sync fetches those 3

#### Scenario: Full cache sync
- **WHEN** two trees share 40 AphiaIDs and the cache also holds 10 AphiaIDs no tree uses
- **THEN** a `sync_all` sync re-fetches each of those AphiaIDs once

### Requirement: Sync re-checks warnings
After fetching, a sync SHALL re-run placement checks for the whole tree, or
every tree for `sync_all`, and add a warning-history row for each node whose
warnings changed.

#### Scenario: WoRMS reclassified a family
- **WHEN** WoRMS moved a family the tree does not hold, changing the lineage of anchored genera below it
- **THEN** a `sync_tree` sync re-fetches those genera's lineages and updates their warnings

#### Scenario: Quiet sync
- **WHEN** nothing changed in WoRMS since the last sync
- **THEN** the sync adds no warning-history rows

### Requirement: Sync never edits the tree
A sync SHALL NOT create changesets, revisions or node versions.

#### Scenario: Sync with new warnings
- **WHEN** a sync finds a newly unaccepted AphiaID
- **THEN** only warnings change, and the tree's latest revision is the same before and after

### Requirement: Starting a sync
`POST /worms/jobs` with `{kind, tree}` for `sync_new` and `sync_tree`, or
`{kind: "sync_all"}`, SHALL start a sync asynchronously and return `202
Accepted` with the job's status. An optional `aphia_ids` list SHALL restrict
the fetching to those AphiaIDs, so failed ones can be tried again; the sync
SHALL still re-check the whole tree. A management command SHALL start each kind
as well, so syncs can be scheduled.

#### Scenario: Try again
- **WHEN** a `sync_tree` sync is started with `aphia_ids` holding the 2 AphiaIDs that failed last time
- **THEN** it fetches those 2 and re-checks the whole tree

### Requirement: One sync at a time
At most one sync per tree SHALL be active, and a `sync_all` sync SHALL count as
active on every tree. Starting a sync that would overlap an active one SHALL
return `409` with error `sync_in_progress`.

#### Scenario: Sync already active
- **WHEN** a sync is active on a tree and another is requested
- **THEN** the API returns `409` with error `sync_in_progress`

#### Scenario: Tree sync during a full sync
- **WHEN** a `sync_all` sync is active and a drafter starts a `sync_tree` sync on any tree
- **THEN** the API returns `409` with error `sync_in_progress`

#### Scenario: Interrupted sync
- **WHEN** the process running a sync dies and the service restarts
- **THEN** no sync is shown as active and a new sync can start at once

### Requirement: Sync status
`GET /worms/jobs?tree={tree}` SHALL return the sync active on the tree, if any,
including an active `sync_all` sync, and the last finished sync on the tree,
each in the shape of `GET /worms/jobs/{job}`. Without `tree`, it SHALL return the
active and last `sync_all` sync. Status SHALL be kept in a cache shared by the
server processes, not in the tree's tables, and MAY be lost on restart.

#### Scenario: Progress
- **WHEN** a sync has re-fetched 120 of 175 AphiaIDs
- **THEN** `GET /worms/jobs?tree=` reports it as active with progress 120 of 175

### Requirement: Sync against the latest revision
A sync SHALL compute and write its warnings against the tree's latest revision
at the moment it writes them, while holding the tree's publish lock, so that a
revision published during the sync is never overwritten with warnings computed
from an older revision.

#### Scenario: Publish during a sync
- **WHEN** revision 43 moves an anchored node while a sync that started at revision 42 is still fetching from WoRMS
- **THEN** the sync's warnings for that node are computed against revision 43

### Requirement: Warnings report
`GET /worms/warnings?tree={tree}` SHALL list the nodes in the tree's latest
revision that currently have warnings, with their warnings, paginated.

#### Scenario: Nodes with warnings
- **WHEN** three nodes currently have warnings
- **THEN** the report lists exactly those three with `count: 3`

### Requirement: WoRMS failure during a sync
An AphiaID that still fails after its retries, or is left unfetched because the
sync stopped on rate limiting, SHALL be listed in the sync's `failed` list as for
any WoRMS job. The sync SHALL still re-check the tree and write warning-history
rows for every node whose warnings could be computed, and SHALL write none for
nodes needing a record that failed.

#### Scenario: Outage mid-sync
- **WHEN** WoRMS stops responding halfway through a sync
- **THEN** the sync finishes with the AphiaIDs it could not fetch in `failed` with reason `worms_unreachable`, and warnings are written for the nodes whose records were fetched

#### Scenario: Outage for one AphiaID
- **WHEN** WoRMS keeps timing out for one AphiaID during a sync and answers for the rest
- **THEN** the sync finishes with that AphiaID in `failed` with reason `worms_unreachable`, and the other nodes' warnings are updated

#### Scenario: Rate limited
- **WHEN** a sync stops because WoRMS keeps answering HTTP 429
- **THEN** its status lists the unfetched AphiaIDs in `failed` with reason `worms_rate_limited`, and warnings are written for the nodes whose records were fetched
