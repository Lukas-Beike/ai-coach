# Proposal

## Why

Local planning records retain Intervals.icu field names for planned load, intensity and target FTP. This couples local planning to the provider and leaves the earlier planning-field normalization incomplete.

## What Changes

- Store and expose provider-neutral planning load, intensity and frozen target FTP fields, mapping the provider names at the Intervals.icu boundary.
- Migrate existing records transactionally, preserving values, sync identities, history and undo compatibility.
- **BREAKING** Support upgrades and restores from schema v16 onward; reject older schemas unchanged and remove their migration paths.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `training-library`: Provider-neutral planned load and intensity fields and unchanged Intervals.icu wire values.
- `encrypted-storage-and-migrations`: Transactional upgrade of planning fields and v16 minimum supported schema.
- `backup-restore-and-privacy`: Reject backups older than v16 without modifying the active database.
- `activity-ingestion-and-storage`: Preserve legacy detail backfill and retirement for supported schemas with neutral target bases.

## Impact

Planning, provider adapters, consumers, schema migration and restore validation, tests and documentation are affected. Existing local and remote identities and athlete data must remain intact. No implicit provider writes are introduced. Inspected baseline: develop at 8a6b7eea; relevant sources include `backend/db/migrations.py`, `backend/db/planning_fields_migration.py`, `backend/planning/library.py`, `backend/planning/target_snapshot.py`, `backend/providers/intervals_workouts.py`, and `tests/test_db_migrations.py`. End-to-end upgrade and restore evidence remains to be gathered.
