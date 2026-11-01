## MODIFIED Requirements

### Requirement: Supported released-schema upgrades

The database SHALL recognize supported version-and-shape pairs from schema v16 through released v18 and the current schema v19, executing required versioned steps within one rollback-capable migration transaction.

#### Scenario: Skipped-release upgrade
- **WHEN** a populated released v16 database is opened by this build
- **THEN** all intermediate migrations run to the exact current schema while preserving existing rows.

#### Scenario: Later supported release
- **WHEN** a populated v17 or v18 database is opened
- **THEN** only remaining upgrade steps run and existing data remains intact.

Evidence: `backend/db/migrations.py`, `backend/db/schema_history.py`; `tests/test_db_planning_metrics_migration.py`, `tests/test_db_encrypted_upgrade_matrix.py`.

## ADDED Requirements

### Requirement: Retired schema rejection

The database SHALL reject schema versions older than v16 before changing their data or schema.

#### Scenario: Opening an older database
- **WHEN** a database from a release with schema v15 or older is opened
- **THEN** startup rejects it and leaves the database unchanged.

### Requirement: Planning metric upgrade preservation

The v18 to v19 upgrade SHALL rename stored local planning metrics and frozen target FTP without losing their values, identities or sync state. It SHALL preserve retired detail KV records and normalize their target basis on canonical backfill.

#### Scenario: Existing planning records
- **WHEN** a supported database contains local planning metrics under the former names
- **THEN** the upgraded records use the new names with the same values and sync baseline.

#### Scenario: Conflicting or unreadable values
- **WHEN** a relevant stored record has conflicting old and new values or cannot be parsed
- **THEN** the upgrade fails and rolls back without discarding either value.

#### Scenario: Retired detail record is backfilled
- **WHEN** a preserved legacy detail record has a former FTP basis
- **THEN** canonical analysis stores the equivalent neutral basis while the source record stays unchanged until safely retired.

Evidence: `backend/db/planning_metrics_migration.py`, `backend/sync/activity_detail_canonical.py`, `backend/sync/activity_detail_retirement.py`; `tests/test_db_planning_metrics_migration.py`, `tests/test_activity_detail_canonical.py`, `tests/test_activity_detail_retirement.py`, `tests/test_db_encrypted_upgrade_matrix.py`.

## MODIFIED Requirements

### Requirement: Canonical extension upgrade preservation
The extended schema SHALL preserve all athlete records, feedback, snapshots, tombstones, plans, sessions, settings, conversations, usage and sync state. Supported populated upgrades, injected-failure rollback, same-build restart and encrypted backup/restore SHALL be verified from v16 and every later released schema.

#### Scenario: Populated released schemas
- **WHEN** each frozen released schema from v16 onward is upgraded
- **THEN** existing identities, values, relationships and sync markers survive and new canonical structures satisfy their validation rules.

#### Scenario: Upgrade fails partway
- **WHEN** an injected failure interrupts a supported migration
- **THEN** schema and rows return to the unchanged released state and a later valid attempt remains possible.

#### Scenario: Encrypted restart and backup
- **WHEN** an upgraded temporary SQLCipher database is restarted and restored through the supported backup workflow
- **THEN** encryption stays enabled and old plus new canonical records and relationships remain available.

#### Scenario: Unknown or newer shape
- **WHEN** a database has an unsupported version, unrecognized shape or mismatched version/shape pair
- **THEN** initialization rejects it without deleting, resetting or partially modifying it.

### Requirement: Provider-neutral planning field upgrade
Databases at v16 or later SHALL retain local planning fields and allow changes recorded before v16 to be inspected and undone using current names and accepted historical hashes.

#### Scenario: Populated upgrade
- **WHEN** a populated v16 database with planning records is opened
- **THEN** the current start and duration names and their values remain intact.

#### Scenario: Rewritten records
- **WHEN** planned units, conflicts, artifacts, previews or undo proposals already use current field names
- **THEN** their start and duration values remain unchanged through the upgrade.

#### Scenario: Recorded remote baseline
- **WHEN** a synced planned unit recorded its remote baseline hash before v16
- **THEN** the same remote event still matches it after upgrade and reports no remote change.

#### Scenario: Undo of an earlier change
- **WHEN** a planned-unit or competition change recorded before v16, or its pending undo proposal, is undone after upgrade
- **THEN** the hash check accepts the recorded state and the restore writes the current field names.

#### Scenario: Upgrade fails partway
- **WHEN** a migration from v16 fails after changing planning data
- **THEN** the database returns to the unchanged v16 schema and rows.

Evidence: `backend/planning/planned_units.py`, `backend/change_history.py`, and `tests/test_db_planning_fields_migration.py`.

### Requirement: Canonical power curve upgrade
The v16 to v17 upgrade SHALL add the canonical `power_curve_points` and `power_curve_fetches` tables in one migration transaction and keep the Intervals.icu power curve of the newest stored snapshot as one unmapped `power_curve` raw record, so the canonical backfill projects it; other values SHALL stay intact.

#### Scenario: Populated upgrade
- **WHEN** a populated v16 database whose newest snapshot stores a power curve is opened
- **THEN** the empty tables are added, the curve is kept as one raw record with mapped version 0, and other values remain intact through subsequent upgrades.

#### Scenario: No stored curve
- **WHEN** no snapshot, a snapshot without a power curve, or one without any parseable fetch time is stored
- **THEN** the power-curve step adds only the empty tables.

#### Scenario: Completed backfill before the upgrade
- **WHEN** an installation whose backfill completed under v16 finishes its next backfill run
- **THEN** the chart shows the same power curve points as the former snapshot read.

#### Scenario: Upgrade fails partway
- **WHEN** an injected failure follows the table creation and the raw record copy
- **THEN** the database returns to the unchanged v16 schema and rows.

Evidence: `backend/db/power_curve_migration.py::copy_power_curve_to_raw_record`; `backend/db/migrations.py::_upgrade_v16_to_v17`. Tests: `tests/test_db_power_curve_migration.py::test_every_populated_release_keeps_its_rows_and_its_newest_curve`; `tests/test_db_power_curve_migration.py::test_a_release_without_a_stored_curve_only_adds_the_empty_table`; `tests/test_db_power_curve_migration.py::test_the_raw_record_takes_the_first_parseable_fetch_time`; `tests/test_db_power_curve_migration.py::test_failure_after_the_step_rolls_back_to_the_unchanged_release`; `tests/test_db_power_curve_migration.py::test_upgraded_database_restarts_with_the_same_build_unchanged`; `tests/test_db_power_curve_migration.py::test_restore_of_a_populated_v16_backup_upgrades_through_validation`; `tests/test_db_power_curve_migration.py::CompletedBackfillUpgradeTests`; `tests/test_db_encrypted_upgrade_matrix.py`.

### Requirement: Session RPE rating time upgrade
The v17 to v18 upgrade SHALL add the nullable `activity_feedback.session_rpe_rated_at` column in one migration transaction; every existing row SHALL keep its values with an unknown (NULL) rating time.

#### Scenario: Populated upgrade
- **WHEN** a populated v17 database with rated, unrated and session-linked feedback is opened
- **THEN** each feedback row keeps its existing values and gains a NULL rating time.

#### Scenario: Upgrade fails partway
- **WHEN** an injected failure follows the column addition
- **THEN** the database returns to the unchanged v17 or v16 schema and rows.

Evidence: `backend/db/migrations.py::_upgrade_v17_to_v18`; `tests/test_db_feedback_rating_time_migration.py`, `tests/test_db_encrypted_upgrade_matrix.py`.

## REMOVED Requirements

### Requirement: Data-preserving migration contents
**Reason**: Releases older than schema v16 are no longer supported.
**Migration**: Upgrade older databases using release 1.13.32 before opening them with this build.

### Requirement: Yazio source constraints migrate without data loss
**Reason**: Releases older than schema v16 are no longer supported.
**Migration**: Upgrade older databases using release 1.13.32 before opening them with this build.
