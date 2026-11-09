# Spec Delta

## REMOVED Requirements

### Requirement: Drift run
**Reason**: Drift runs are renamed WoRMS syncs and move to the `worms-sync` capability.

**Migration**: See `worms-sync`: Sync kinds, and Sync re-checks warnings.

### Requirement: Drift never edits the tree
**Reason**: Drift runs are renamed WoRMS syncs and move to the `worms-sync` capability.

**Migration**: See `worms-sync`: Sync never edits the tree.

### Requirement: Starting a run
**Reason**: Drift runs are renamed WoRMS syncs and move to the `worms-sync` capability.

**Migration**: Start syncs with `POST /worms/jobs`; see `worms-sync`: Starting a sync, and One sync at a time. `drift_in_progress` becomes `sync_in_progress`.

### Requirement: Run status
**Reason**: Drift runs are renamed WoRMS syncs and move to the `worms-sync` capability.

**Migration**: Use `GET /worms/jobs?tree=` and `GET /worms/jobs/{job}`; see `worms-sync`: Sync status.

### Requirement: Drift against the latest revision
**Reason**: Drift runs are renamed WoRMS syncs and move to the `worms-sync` capability.

**Migration**: See `worms-sync`: Sync against the latest revision.

### Requirement: Drift report
**Reason**: Drift runs are renamed WoRMS syncs and move to the `worms-sync` capability.

**Migration**: Use `GET /worms/warnings?tree=`; see `worms-sync`: Warnings report.

### Requirement: WoRMS failure during a run
**Reason**: Drift runs are renamed WoRMS syncs and move to the `worms-sync` capability.

**Migration**: See `worms-sync`: WoRMS failure during a sync. Failed AphiaIDs are now skipped instead of stopping the sync.
