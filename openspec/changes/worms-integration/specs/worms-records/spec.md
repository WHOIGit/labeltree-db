# Spec Delta

## Purpose

Keeps the service's own snapshot of the WoRMS records it uses, and serves WoRMS
lookups to clients from that snapshot, so reads never depend on
marinespecies.org and past WoRMS states the tree was checked against stay
available.

## ADDED Requirements

### Requirement: WoRMS record cache
The system SHALL store each fetched WoRMS record, including name, rank, status,
`valid_AphiaID` and lineage, with `fetched_at` and WoRMS's `modified` time. A
new row SHALL be added whenever a fetched record's `modified` time differs from
the newest stored row for that AphiaID; otherwise only its `fetched_at` SHALL
be refreshed.

#### Scenario: Record changed in WoRMS
- **WHEN** AphiaID 149122 is re-fetched and its `modified` time is newer than the cached row
- **THEN** a second row is stored and the first is kept

#### Scenario: Record unchanged
- **WHEN** AphiaID 149122 is re-fetched with the same `modified` time
- **THEN** no new row is added and the newest row's `fetched_at` is updated

### Requirement: Cache is independent of node versions
Refreshing the WoRMS cache SHALL NOT create node versions or tree revisions.

#### Scenario: Refresh
- **WHEN** the cached record for a node's AphiaID is refreshed
- **THEN** the node's version is unchanged

### Requirement: Reads never call WoRMS
Tree and node read endpoints SHALL be served without calling WoRMS. Only WoRMS
lookup endpoints, changeset saves, publishes and drift runs SHALL call WoRMS,
and only from the service, never from the browser.

#### Scenario: WoRMS down during reads
- **WHEN** WoRMS is unreachable and a client requests `GET /nodes/{id}`
- **THEN** the node is returned with `worms_data` from the cache

### Requirement: WoRMS record lookup
`GET /worms/{aphia_id}` SHALL return the record from the cache, fetching it
from WoRMS if not cached. `GET /worms/search?name=` SHALL return candidate
records from WoRMS, `limit` default 20 and max 100, and SHALL cache the records
returned.

#### Scenario: Cache miss
- **WHEN** a client requests `GET /worms/148985` and it is not cached
- **THEN** the service fetches it from WoRMS, caches it and returns it

#### Scenario: Unreachable and not cached
- **WHEN** WoRMS is unreachable and the requested AphiaID is not cached
- **THEN** the API returns `503`

#### Scenario: Unknown AphiaID
- **WHEN** WoRMS reports no record for the requested AphiaID
- **THEN** the API returns `404`

### Requirement: WoRMS lineage lookups
`GET /worms/{aphia_id}/lineage` SHALL return the record's WoRMS ancestors, top
level first. `GET /worms/{a}/between/{b}` SHALL return the records on the
lineage path between `a` and `b` inclusive, or `400` unless one is an ancestor
of the other. `GET /worms/{a}/common_ancestor/{b}` SHALL return their nearest
common WoRMS ancestor, inclusive.

#### Scenario: Between a genus and its species
- **WHEN** a client requests `between` for `Chaetoceros` (148985) and `Chaetoceros didymus` (149122)
- **THEN** the response lists the records from 148985 down to 149122 inclusive

#### Scenario: Unrelated records
- **WHEN** neither record is an ancestor of the other
- **THEN** `between` returns `400`

#### Scenario: Ancestor is the common ancestor
- **WHEN** a client requests `common_ancestor` for 148985 and 149122
- **THEN** 148985 is returned

### Requirement: Citation
Every WoRMS-derived value returned to clients SHALL carry the `fetched_at` time
of the cached record it came from, so it can be cited as "WoRMS, accessed
<fetched_at>".

#### Scenario: Record response
- **WHEN** a client requests `GET /worms/149122`
- **THEN** the response includes `fetched_at`
