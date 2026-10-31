# encrypted-storage-and-migrations Specification

## Purpose

Preserve durable athlete state through encrypted creation, bounded transactions, supported schema upgrades and restarts.

Owns database lifecycle and upgrade contracts. The baseline records current schema v17 (v16 is the released planning-field schema); canonical/domain records are described in their capability specs. SQLCipher conformance requires encrypted fixtures, separate from SQLite test doubles.

## Requirements

### Requirement: Encrypted application database

A configured application database SHALL be opened/created through SQLCipher with APP_PASSWORD and cipher compatibility 4; encrypted startup SHALL not fall back to an unencrypted database when SQLCipher is unavailable.

#### Scenario: New encrypted database
- **WHEN** a valid secure configuration opens new temporary application storage
- **THEN** the database is created with the configured SQLCipher key

#### Scenario: Same-key restart
- **WHEN** a current encrypted database is reopened with the same application key
- **THEN** the existing records and schema remain available

#### Scenario: Missing encryption backend
- **WHEN** a secure database is requested while SQLCipher is unavailable
- **THEN** startup/database access fails without creating a plaintext replacement

Evidence: `backend/db/schema.py::configure_cipher`; `backend/db/manager.py::DatabaseManager`; `server.py::database_manager`; `backend/config.py::security_configuration_error`. Tests: `tests/test_server_database.py::test_unavailable_sqlcipher_closes_manager_for_changed_secure_configuration`; `tests/test_db_migrations.py::test_encrypted_current_database_reopens_with_same_key`.

### Requirement: Supported released-schema upgrades

The database SHALL recognize supported version-and-shape pairs from schema v9 through released v16 and the current schema v17, executing required versioned steps within one rollback-capable migration transaction.

#### Scenario: Skipped-release upgrade
- **WHEN** a populated released v9 database is opened by this build
- **THEN** all intermediate migrations run to the exact current schema while preserving existing rows.

#### Scenario: Later supported release
- **WHEN** a populated v10, v11, v12, v13, v14, v15 or v16 database is opened
- **THEN** only remaining upgrade steps run and existing data remains intact.

Evidence baseline: `backend/db/migrations.py`, `backend/db/schema_history.py`; `tests/test_db_migrations.py`. The outgoing v16 fixture is frozen (`tests/test_db_migrations.py::test_frozen_v16_fixture_is_the_recorded_released_shape`); freeze v17 before changing the live shape again.

### Requirement: Unknown schema preservation

The database SHALL reject unsupported versions, unknown shapes and mismatched version/shape pairs before modifying the database; a current exact schema SHALL be restart-idempotent.

#### Scenario: Newer or unsupported schema
- **WHEN** a database version is outside the supported released set
- **THEN** opening fails and no reset, deletion or partial upgrade is performed

#### Scenario: Shape does not match version
- **WHEN** the stored version is supported but tables/indexes/shape do not match an accepted release
- **THEN** migration refuses the database unchanged

#### Scenario: Current restart
- **WHEN** the exact current schema is initialized repeatedly
- **THEN** the current version and durable rows remain unchanged by migration

Evidence: `backend/db/migrations.py::migrate_schema`; `backend/db/schema.py::database_schema_is_current`. Tests: `tests/test_db_migrations.py::test_older_or_newer_schema_version_is_rejected_without_modification`; `tests/test_db_migrations.py::test_unknown_schema_shape_is_rejected_without_modification`; `tests/test_db_migrations.py::test_version_and_shape_must_belong_together`; `tests/test_db_migrations.py::test_current_schema_is_accepted_repeatedly_without_changes`.

### Requirement: Data-preserving migration contents

The implemented migrations SHALL add canonical detail and food-mirror structures, split the legacy Garmin snapshot into dated records, and add nullable lap maximum speed without inventing values for previously stored laps.

#### Scenario: Garmin snapshot migration
- **WHEN** a supported v11 database contains a populated legacy Garmin snapshot
- **THEN** the migration stores its items as canonical provider records with observed days without dropping elements

#### Scenario: Existing laps gain a column
- **WHEN** the v12 lap table lacks max_speed_mps
- **THEN** the column is added and existing laps retain NULL until actual provider data supplies a value

#### Scenario: Earlier path already has the column
- **WHEN** an upgrade from v9 created current detail DDL including maximum speed
- **THEN** the later step does not attempt a duplicate column addition

Evidence: `backend/db/migrations.py::_upgrade_v9_to_v10`; `backend/db/migrations.py::_upgrade_v10_to_v11`; `backend/db/migrations.py::_upgrade_v11_to_v12`; `backend/db/migrations.py::_upgrade_v12_to_v13`; `backend/db/garmin_items_migration.py::split_garmin_snapshot`. Tests: `tests/test_db_migrations.py::test_populated_v11_upgrade_splits_the_garmin_snapshot_into_rows`; `tests/test_db_migrations.py::test_populated_v12_upgrade_keeps_every_row_and_adds_an_empty_lap_max_speed`; `tests/test_db_migrations.py::test_v12_upgrade_works_with_the_application_row_factory`.

### Requirement: Rollback on failed upgrades

A failing migration SHALL roll back its schema and data changes, preserve the original upgrade error even when a savepoint was lost, and leave the released database available for a later valid attempt.

#### Scenario: Upgrade step fails
- **WHEN** a schema/data upgrade raises before current-schema validation succeeds
- **THEN** the enclosing migration changes are rolled back rather than committed partially

#### Scenario: Storage engine loses savepoint
- **WHEN** a storage failure rolls back the outer transaction and removes the savepoint
- **THEN** cleanup does not replace the original migration exception with a savepoint error

Evidence: `backend/db/migrations.py::migrate_schema`; `backend/db/migrations.py::_abandon_migration_savepoint`; `backend/db/schema.py::execute_ddl`. Tests: `tests/test_db_migrations.py::test_failed_upgrade_step_rolls_back_to_the_unchanged_v9_database`; `tests/test_db_migrations.py::test_failed_v11_upgrade_rolls_back_to_the_unchanged_v11_database`; `tests/test_db_migrations.py::test_lost_savepoint_does_not_mask_the_original_upgrade_error`.

### Requirement: Owned atomic transactions and consistent reads

The database manager SHALL serialize writers, commit/roll back an owned unit of work atomically, bound reader leases, and offer query-only read snapshots whose reads share one committed WAL state.

#### Scenario: Write fails inside a unit of work
- **WHEN** a domain operation raises before leaving its owned transaction
- **THEN** its partial writes are rolled back before the connection is reused

#### Scenario: Read snapshot composition
- **WHEN** a response composes several queries in one read_snapshot block
- **THEN** the queries observe one committed state and writes through that snapshot are rejected

#### Scenario: Resource contention
- **WHEN** a reader/writer lease cannot be acquired within its configured bound
- **THEN** the manager raises classified contention instead of waiting indefinitely

Evidence: `backend/db/manager.py::DatabaseManager.unit_of_work`; `backend/db/manager.py::DatabaseManager.read_snapshot`; `backend/db/manager.py::WriterGate`. Tests: `tests/test_db_manager.py::test_unit_of_work_rolls_back_and_reader_pool_reuses_connections`; `tests/test_db_manager.py::test_unit_of_work_rolls_back_on_base_exceptions_before_reuse`; `tests/test_db_manager.py::test_writer_wait_is_bounded`; `tests/test_diagnostic_report.py::test_database_counts_and_kv_reads_share_one_read_snapshot`.

### Requirement: Restore drains active connections

The database manager SHALL block new leases, wait for active operations and close existing connections while a restore swaps the database; later leases SHALL use the resulting active database.

#### Scenario: Restore begins with leased work
- **WHEN** a validated restore requests a drain while database work remains active
- **THEN** the swap waits for active leases and no new lease enters the drained manager

#### Scenario: Restore leaves the drain
- **WHEN** the swap completes or fails and the drain context exits
- **THEN** lease admission resumes without retaining a connection to the replaced file

Evidence: `backend/db/manager.py::DatabaseManager.restore_drain`; `backend/db/manager.py::DatabaseManagerCache`. Tests: `tests/test_db_manager.py`; `tests/test_database_restore_service.py::test_restores_after_checkpoint_and_drain_then_resumes_both_job_owners`.

### Requirement: Yazio source constraints migrate without data loss
The v13 to v14 upgrade SHALL allow `yazio:` ids in the food mirror and the `yazio` source in saved products by rebuilding their constraints in the same migration transaction, preserving every row, identifier, timestamp and index, and failing atomically.

#### Scenario: Populated upgrade
- **WHEN** a populated v9 through v13 database is opened
- **THEN** all mirror entries and products are unchanged afterwards, and a `yazio:` mirror entry and a `yazio` product can be stored.

#### Scenario: Failed upgrade
- **WHEN** the rebuild fails partway
- **THEN** the database remains at its prior version with unchanged rows.

### Requirement: Canonical extension upgrade preservation
The extended schema SHALL preserve all athlete records, feedback, snapshots, tombstones, plans, sessions, settings, conversations, usage and sync state. Supported populated upgrades, injected-failure rollback, same-build restart and encrypted backup/restore SHALL be verified from v9 and every later released schema.

#### Scenario: Populated released schemas
- **WHEN** each frozen released schema from v9 through v14 is upgraded
- **THEN** existing identities, values, relationships and sync markers survive and new canonical structures satisfy their validation rules.

#### Scenario: Upgrade fails partway
- **WHEN** an injected failure interrupts extension migration
- **THEN** schema and rows return to the unchanged released state and a later valid attempt remains possible.

#### Scenario: Encrypted restart and backup
- **WHEN** an upgraded temporary SQLCipher database is restarted and restored through the supported backup workflow
- **THEN** encryption stays enabled and old plus new canonical records and relationships remain available.

#### Scenario: Unknown or newer shape
- **WHEN** a database has an unsupported version, unrecognized shape or mismatched version/shape pair
- **THEN** initialization rejects it without deleting, resetting or partially modifying it.

### Requirement: Provider-neutral planning field upgrade
The v15 to v16 upgrade SHALL rename the stored start and planned duration of local planning records from `start_date_local` and `moving_time` to `starts_at_local` and `planned_duration_s` in one migration transaction, in competition columns and in every stored planning JSON record, preserving ids, values, key order, row counts, sync markers and remote baselines. Change history SHALL NOT be rewritten; recorded field names SHALL be translated on read.

#### Scenario: Populated upgrade
- **WHEN** a populated v15 or v9 database with planning records under the former names is opened
- **THEN** every planning record names `starts_at_local` and `planned_duration_s` with unchanged values, and every other table keeps its exact rows.

#### Scenario: Rewritten records
- **WHEN** planned-unit or workout-library payloads, planned-unit or competition sync conflicts, staged Coach plan artifacts, adaptive preview changes or pending undo proposals name the former keys
- **THEN** only those keys are renamed; rows without them, non-object JSON, used proposals and activity proposals keep their exact bytes.

#### Scenario: Recorded remote baseline
- **WHEN** a synced planned unit recorded its remote baseline hash before the upgrade
- **THEN** the same remote event still matches it afterwards and reports no remote change.

#### Scenario: Undo of an earlier change
- **WHEN** a planned-unit or competition change recorded before the upgrade, or its pending undo proposal, is undone afterwards
- **THEN** the hash check accepts the recorded state and the restore writes the current field names.

#### Scenario: Upgrade fails partway
- **WHEN** an injected failure follows the column rename and JSON rewrite
- **THEN** the database returns to the unchanged v15 or v9 schema and rows.

Evidence: `backend/db/planning_fields_migration.py::rename_planning_fields_in_database`; `backend/db/migrations.py::_upgrade_v15_to_v16`; `backend/planning/planned_units.py::planned_unit_payload_hash`; `backend/change_history.py::accepted_audit_hashes`, `backend/change_history.py::current_audit_fields`. Tests: `tests/test_db_planning_fields_migration.py::test_populated_releases_upgrade_every_planning_record_to_the_neutral_names`; `tests/test_db_planning_fields_migration.py::test_recorded_remote_baseline_still_matches_after_the_upgrade`; `tests/test_db_planning_fields_migration.py::test_failure_after_the_rewrite_rolls_back_to_the_unchanged_release`; `tests/test_db_planning_fields_migration.py::test_upgraded_database_restarts_with_the_same_build_unchanged`; `tests/test_db_planning_fields_migration.py::test_restore_of_a_populated_v15_backup_upgrades_through_validation`; `tests/test_db_planning_fields_migration.py::PreUpgradeUndoTests`; `tests/test_db_encrypted_upgrade_matrix.py`.

### Requirement: Canonical power curve upgrade
The v16 to v17 upgrade SHALL add the canonical `power_curve_points` and `power_curve_fetches` tables in one migration transaction and keep the Intervals.icu power curve of the newest stored snapshot as one unmapped `power_curve` raw record, so the canonical backfill projects it; every other row SHALL stay unchanged.

#### Scenario: Populated upgrade
- **WHEN** a populated v9 to v16 database whose newest snapshot stores a power curve is opened
- **THEN** the empty tables are added, the curve is kept as one raw record with mapped version 0, and every other table keeps its exact rows.

#### Scenario: No stored curve
- **WHEN** no snapshot, a snapshot without a power curve, or one without any parseable fetch time is stored
- **THEN** only the empty tables are added.

#### Scenario: Completed backfill before the upgrade
- **WHEN** an installation whose backfill completed under v16 finishes its next backfill run
- **THEN** the chart shows the same power curve points as the former snapshot read.

#### Scenario: Upgrade fails partway
- **WHEN** an injected failure follows the table creation and the raw record copy
- **THEN** the database returns to the unchanged v16 or v9 schema and rows.

Evidence: `backend/db/power_curve_migration.py::copy_power_curve_to_raw_record`; `backend/db/migrations.py::_upgrade_v16_to_v17`. Tests: `tests/test_db_power_curve_migration.py::test_every_populated_release_keeps_its_rows_and_its_newest_curve`; `tests/test_db_power_curve_migration.py::test_a_release_without_a_stored_curve_only_adds_the_empty_table`; `tests/test_db_power_curve_migration.py::test_the_raw_record_takes_the_first_parseable_fetch_time`; `tests/test_db_power_curve_migration.py::test_failure_after_the_step_rolls_back_to_the_unchanged_release`; `tests/test_db_power_curve_migration.py::test_upgraded_database_restarts_with_the_same_build_unchanged`; `tests/test_db_power_curve_migration.py::test_restore_of_a_populated_v16_backup_upgrades_through_validation`; `tests/test_db_power_curve_migration.py::CompletedBackfillUpgradeTests`; `tests/test_db_encrypted_upgrade_matrix.py`.
