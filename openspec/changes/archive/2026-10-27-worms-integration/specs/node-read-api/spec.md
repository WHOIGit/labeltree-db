# Spec Delta

## ADDED Requirements

### Requirement: WoRMS fields on detailed nodes
Every detailed node SHALL return `worms_data` as `{scientificname, rank, status,
link, fetched_at}` from the newest cached record of its `aphia_id`, or `null`
when it has no `aphia_id` or the record is not cached. `worms_warnings` SHALL be
the node's current warnings, `[]` if none, whatever revision is requested.

#### Scenario: Anchored and cached
- **WHEN** a node with `aphia_id` 149122 is fetched and the record is cached
- **THEN** `worms_data.scientificname` is `Chaetoceros didymus` and `worms_data.link` points to its WoRMS page

#### Scenario: Warnings at a past revision
- **WHEN** a node is fetched at `?rev=3` and its current warnings include `out_of_lineage`
- **THEN** `worms_warnings` includes `out_of_lineage`

#### Scenario: Unanchored node
- **WHEN** a node without `aphia_id` is fetched
- **THEN** `worms_data` is `null`

### Requirement: Warning history endpoint
`GET /nodes/{id}/warning_history` SHALL return the node's warning-history rows,
newest first, each with `computed_at` and its warnings, paginated. It SHALL NOT
accept `?rev`.

#### Scenario: Warning raised then cleared
- **WHEN** a node got `out_of_lineage` and a later publish cleared it
- **THEN** the history lists the empty row first and the `out_of_lineage` row second

## REMOVED Requirements

### Requirement: WoRMS fields before WoRMS integration
**Reason**: WoRMS integration now provides real values.
**Migration**: Clients read `worms_data` and `worms_warnings` as described in "WoRMS fields on detailed nodes"; the field names and the `null`/`[]` empty values are unchanged.
