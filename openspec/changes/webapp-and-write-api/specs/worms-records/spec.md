# Spec Delta

## MODIFIED Requirements

### Requirement: Reads never call WoRMS
Tree and node read endpoints SHALL be served without calling WoRMS. Only the
WoRMS lookup endpoints and WoRMS jobs SHALL call WoRMS, and only from the
service, never from the browser. `validate`, changeset saves and publishes
SHALL NOT call WoRMS; they use cached records only.

#### Scenario: WoRMS down during reads
- **WHEN** WoRMS is unreachable and a client requests `GET /nodes/{id}`
- **THEN** the node is returned with `worms_data` from the cache

#### Scenario: Publish without WoRMS
- **WHEN** WoRMS is unreachable and an approver publishes a draft whose AphiaIDs are all cached
- **THEN** the publish succeeds without contacting WoRMS, with warnings computed from the cached records

## ADDED Requirements

### Requirement: WoRMS fetch jobs
`POST /worms/jobs` with `{kind: "fetch", org, aphia_ids[]}` SHALL start a job
that fetches, record and lineage, each listed AphiaID that has no complete
cached record, and return `202` with the job's status. It SHALL need `drafter`
in the organization, whose members (`reader`) see its status. A fetch job SHALL
only fill the cache; it SHALL NOT write warnings. Fetch jobs SHALL NOT exclude
each other or sync jobs.

#### Scenario: Fetch before validating
- **WHEN** a drafter starts a fetch job for AphiaIDs 149122 and 148985, and only 149122 is cached
- **THEN** the API returns `202`, the job fetches 148985 only, and its total is 1

### Requirement: WoRMS job status
`GET /worms/jobs/{job}` SHALL return a job's `kind`, `tree` or `org`, `started_by`,
`started_at`, `finished_at`, `state` (`running`, `finished` or
`interrupted`), `total` and `done` AphiaIDs, and the `failed` AphiaIDs with
their `reason` and `detail`. Status SHALL be visible to every server process,
MAY be lost on restart, and a job whose process died SHALL be shown as
`interrupted`.

#### Scenario: Finished with a failure
- **WHEN** a job of 60 AphiaIDs finishes with one failed
- **THEN** its status is `finished` with `done` 59 of `total` 60 and one `failed` entry

### Requirement: Retry and pause status
A running job's status SHALL list the AphiaIDs currently `retrying`, each with
its attempt, the retries allowed and when its current wait ends, and SHALL
report `paused`, the reason and end of a job-wide pause, or null.

#### Scenario: Retry visible
- **WHEN** a fetch of AphiaID 149122 timed out and the job is waiting before retrying it
- **THEN** the job's status lists 149122 under `retrying` with attempt 1 and the time its wait ends

### Requirement: Failed AphiaIDs are skipped
An AphiaID that still fails after its retries SHALL be added to the job's
`failed` list with a `reason` of `worms_unreachable` (timeout or connection
error), `worms_rate_limited` (HTTP 429) or `worms_error` (any other error
response), its cached rows SHALL be left as they were, and the job SHALL go on
to the next AphiaID.

#### Scenario: One AphiaID unreachable
- **WHEN** a job's fetch of AphiaID 149122 keeps timing out and the rest succeed
- **THEN** the job finishes with 149122 in `failed` with reason `worms_unreachable`, and every other AphiaID is cached

### Requirement: Retry schedules
A WoRMS request that times out, cannot connect or gets a `5xx` response SHALL be
retried. Jobs started through the API SHALL retry 4 times, after 1, 2, 5 and 12
seconds. Jobs started by the management command, for scheduled runs, SHALL
retry 4 times, after 10, 30, 60 and 120 seconds. The WoRMS lookup endpoints
SHALL retry twice, after 1 and 2 seconds.

#### Scenario: Recovered on the third attempt
- **WHEN** an API-started job's fetch of an AphiaID fails twice and then succeeds
- **THEN** the job waited 1 and then 2 seconds, and the AphiaID is not in `failed`

### Requirement: Rate limiting pauses a job
When WoRMS answers HTTP 429 during a job, the whole job SHALL pause for the
response's `Retry-After` seconds, or 30 seconds if it has none, and report the
pause in its status. An API-started job that gets another 429 after resuming
SHALL stop and add every AphiaID it has not fetched to `failed` with reason
`worms_rate_limited`. A job started by the management command SHALL pause as
often as WoRMS asks, up to 4 times, before stopping the same way.

#### Scenario: Rate limited twice
- **WHEN** an API-started job of 60 AphiaIDs gets HTTP 429 after 20, pauses, and gets 429 again after resuming
- **THEN** the job finishes with the 40 AphiaIDs not yet fetched in `failed` with reason `worms_rate_limited`
