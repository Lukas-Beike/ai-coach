# encrypted-storage-and-migrations Specification

## Purpose

Preserve durable athlete state through encrypted creation, bounded transactions, supported schema upgrades and restarts.

Owns database lifecycle and upgrade contracts. The baseline records current schema v23 and supports upgrades from v21 (releases 1.13.41 to 1.13.44) and v22 (the 2.0.0 candidate); canonical/domain records are described in their capability specs. SQLCipher conformance requires encrypted fixtures, separate from SQLite test doubles.

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

The database SHALL recognize supported version-and-shape pairs from released schemas v21 and v22 and the current schema v23, executing required versioned steps within one rollback-capable migration transaction.

#### Scenario: Released baseline upgrade
- **WHEN** a populated released v21 database is opened by this build
- **THEN** the remaining migrations run to the exact current schema while preserving existing rows.

Evidence: `backend/db/migrations.py`, `backend/db/schema_history.py`; `tests/test_db_migrations.py::test_oldest_supported_release_schema_upgrades_to_current`, `tests/test_db_strength_sets_migration.py`, `tests/test_db_encrypted_upgrade_matrix.py`.

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

### Requirement: Rollback on failed upgrades

A failing migration SHALL roll back its schema and data changes, preserve the original upgrade error even when a savepoint was lost, and leave the released database available for a later valid attempt.

#### Scenario: Upgrade step fails
- **WHEN** a schema/data upgrade raises before current-schema validation succeeds
- **THEN** the enclosing migration changes are rolled back rather than committed partially

#### Scenario: Storage engine loses savepoint
- **WHEN** a storage failure rolls back the outer transaction and removes the savepoint
- **THEN** cleanup does not replace the original migration exception with a savepoint error

Evidence: `backend/db/migrations.py::migrate_schema`; `backend/db/migrations.py::_abandon_migration_savepoint`; `backend/db/schema.py::execute_ddl`. Tests: `tests/test_db_strength_sets_migration.py::test_failed_upgrade_leaves_the_release_unchanged`; `tests/test_db_encrypted_upgrade_matrix.py::test_a_failing_upgrade_leaves_every_released_schema_unchanged`; `tests/test_db_migrations.py::test_lost_savepoint_does_not_mask_the_original_upgrade_error`.

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

### Requirement: Canonical extension upgrade preservation
The extended schema SHALL preserve all athlete records, feedback, snapshots, tombstones, plans, sessions, settings, conversations, usage and sync state. Supported populated upgrades, injected-failure rollback, same-build restart and encrypted backup/restore SHALL be verified from v21 (release 1.13.44, the only production instance) and every later released schema.

#### Scenario: Populated released schemas
- **WHEN** each frozen released schema covered by the requirement is upgraded
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

Evidence: `backend/db/migrations.py`; `tests/test_db_encrypted_upgrade_matrix.py::test_every_released_schema_upgrades_encrypted_like_the_plain_upgrade`, `tests/test_db_encrypted_upgrade_matrix.py::test_a_failing_upgrade_leaves_every_released_schema_unchanged`, `tests/test_db_encrypted_upgrade_matrix.py::test_an_encrypted_backup_of_an_upgrade_restores_the_same_rows`, `tests/test_database_restore_validation.py::test_validate_upgrades_a_populated_release_v21_backup`.

### Requirement: Retired schema rejection

The database SHALL reject schema versions older than v21 (releases before 1.13.41) before changing their data or schema, with a message that names release 1.13.44 for the upgrade. Change-history entries written before v16 under the former planning field names are not translated and cannot be undone.

#### Scenario: Opening an older database
- **WHEN** a database from a release with schema v20 or older is opened
- **THEN** startup rejects it with the release 1.13.44 hint and leaves its rows and version unchanged.

Evidence: `backend/db/migrations.py::migrate_schema`, `backend/db/schema_history.py::OLDEST_SUPPORTED_SCHEMA_VERSION`; `tests/test_db_migrations.py::test_older_database_file_is_refused_at_startup_without_changes`, `tests/test_db_migrations.py::test_older_or_newer_schema_version_is_rejected_without_modification`, `tests/test_change_history.py::test_planning_field_names_before_schema_v16_are_not_translated`.

### Requirement: Legacy detail target basis

Canonical backfill SHALL normalize the former FTP target basis of a preserved legacy detail record without changing the source record until it is safely retired.

#### Scenario: Retired detail record is backfilled
- **WHEN** a preserved legacy detail record has a former FTP basis
- **THEN** canonical analysis stores the equivalent neutral basis while the source record stays unchanged until safely retired.

Evidence: `backend/canonical/legacy_planning_fields.py`, `backend/sync/activity_detail_canonical.py`, `backend/sync/activity_detail_retirement.py`; `tests/test_activity_detail_canonical.py`, `tests/test_activity_detail_retirement.py`.

### Requirement: Strength set storage upgrade

The v21 to v22 step SHALL rebuild the detail set tables so the kind CHECK accepts `strength_sets`, add `activity_detail_sets.set_source` (NULL for every released set) and an empty `activity_strength_sets` table, keep every stream, lap, zone and analysis row unchanged with foreign keys enforced, and fail without changes when a detail row has no parent.

#### Scenario: Populated release upgrade
- **WHEN** a populated v21 database is opened by this build
- **THEN** every detail row and its cascade survive, strength sets can be stored afterwards, and a failure rolls back to the unchanged release.

Evidence: `backend/db/migrations.py:_upgrade_v21_to_v22`; `tests/test_db_strength_sets_migration.py`, `tests/test_db_encrypted_upgrade_matrix.py`.

### Requirement: Session purpose marking upgrade

The v22 to v23 step SHALL add `activity_feedback.purpose` (NULL for every existing row, checked to the five purposes training, race, commute, warmup and cooldown) and keep every other row unchanged. A v21 database SHALL reach v23 through the v22 shape in the same transaction.

#### Scenario: Populated release upgrade
- **WHEN** a populated v21 or v22 database is opened by this build
- **THEN** every feedback row and every other table survive with no marking, a marking can be stored afterwards, a failure rolls back to the unchanged release, and a restart with the same build changes nothing.

Evidence: `backend/db/migrations.py:_upgrade_v22_to_v23`; `tests/test_db_feedback_purpose_migration.py`, `tests/test_db_encrypted_upgrade_matrix.py`.

### Requirement: Versioned data maintenance after an upgrade

A data maintenance step that deletes stored records without a schema change, such as the Intervals.icu ingest purge, SHALL run once per version behind a completion marker, after an encrypted recovery copy, inside one writer transaction, and SHALL be provable on a populated released v21 database upgraded to the current schema.

#### Scenario: Populated v21 database
- **WHEN** a populated v21 database is upgraded and the purge runs, fails midway or the application restarts
- **THEN** athlete data is re-keyed, a failure rolls back to the upgraded state without the marker, and a restart repeats nothing.

#### Scenario: Dry run on a copy
- **WHEN** the dry-run script runs on a copy of the database
- **THEN** it upgrades and purges inside one transaction, prints counts only, rolls back, and the file's hash is unchanged.

Evidence: `backend/sync/intervals_purge.py`, `scripts/intervals_purge_dry_run.py`; `tests/test_intervals_purge.py`.
