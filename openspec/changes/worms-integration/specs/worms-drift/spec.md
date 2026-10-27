# Spec Delta

## Purpose

Re-checks a whole tree against the current state of WoRMS on demand or on a
schedule, so that WoRMS changes made since nodes were published surface as
warnings, without the run ever editing the tree.

## ADDED Requirements

### Requirement: Drift run
A drift run SHALL collect every AphiaID in the tree's latest revision, re-fetch
each record and its lineage from WoRMS, re-run placement checks for the whole
tree, and add a warning-history row for each node whose warnings changed.

#### Scenario: WoRMS reclassified a family
- **WHEN** WoRMS moved a family the tree does not hold, changing the lineage of anchored genera below it
- **THEN** a drift run re-fetches those genera's lineages and updates their warnings

#### Scenario: Quiet run
- **WHEN** nothing changed in WoRMS since the last run
- **THEN** the run adds no warning-history rows

### Requirement: Drift never edits the tree
A drift run SHALL NOT create changesets, revisions or node versions.

#### Scenario: Drift with new warnings
- **WHEN** a drift run finds a newly unaccepted AphiaID
- **THEN** only warnings change, and the tree's latest revision is the same before and after

### Requirement: Starting a run
`POST /trees/{tree}/drift` SHALL start a run asynchronously and return `202
Accepted`. At most one run per tree SHALL be active; starting another SHALL
return `409`. A management command SHALL start a run as well, so runs can be
scheduled.

#### Scenario: Run already active
- **WHEN** a run is active on a tree and another is requested
- **THEN** the API returns `409`

#### Scenario: Interrupted run
- **WHEN** the process running a drift run dies and the service restarts
- **THEN** no run is shown as active and a new run can start at once

### Requirement: Run status
`GET /trees/{tree}/drift/status` SHALL return the active run's progress, if any,
and the last finished run (who started it, when, and whether it succeeded),
visible to every server process. Run status SHALL be kept in a cache shared by
the server processes, not in the tree's tables, and MAY be lost on restart. On
startup, status left by a run that was interrupted SHALL be cleared.

#### Scenario: Progress
- **WHEN** a run has re-fetched 120 of 175 AphiaIDs
- **THEN** status reports the run as active with progress 120 of 175

### Requirement: Drift against the latest revision
A drift run SHALL compute and write its warnings against the tree's latest
revision at the moment it writes them, while holding the tree's publish lock, so
that a revision published during the run is never overwritten with warnings
computed from an older revision.

#### Scenario: Publish during a run
- **WHEN** revision 43 moves an anchored node while a drift run that started at revision 42 is still fetching from WoRMS
- **THEN** the run's warnings for that node are computed against revision 43

### Requirement: Drift report
`GET /trees/{tree}/drift` SHALL list the nodes in the latest revision that
currently have warnings, with their warnings, paginated.

#### Scenario: Nodes with warnings
- **WHEN** three nodes currently have warnings
- **THEN** the report lists exactly those three with `count: 3`

### Requirement: WoRMS failure during a run
If WoRMS keeps failing during a run after retries, the run SHALL stop, keep the
warning rows it already wrote, and record in its status a failure `reason`
and `detail`. `reason` SHALL be `worms_unreachable` (timeout or connection
error), `worms_rate_limited` (HTTP 429) or `worms_error` (any other error
response).

#### Scenario: Outage mid-run
- **WHEN** WoRMS stops responding halfway through a run
- **THEN** status shows the last run as failed with reason `worms_unreachable`, and no further rows are written

#### Scenario: Rate limited
- **WHEN** WoRMS keeps answering HTTP 429 after the run's retries
- **THEN** status shows the last run as failed with reason `worms_rate_limited` and the number of AphiaIDs fetched so far
