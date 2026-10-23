# Encrypted storage and migrations Specification Delta

## Purpose

Preserve durable athlete state through encrypted creation, bounded transactions, supported schema upgrades and restarts.

Owns database lifecycle and upgrade contracts. The baseline records current schema v13; canonical/domain records are described in their capability specs. SQLCipher conformance requires encrypted fixtures, separate from SQLite test doubles.

## ADDED Requirements

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

The database SHALL recognize supported version-and-shape pairs from schema v9 through the current v13 and execute the required versioned steps within one rollback-capable migration transaction.


#### Scenario: Skipped-release upgrade
- **WHEN** a populated released v9 database is opened by this build
- **THEN** all intermediate migrations run to the exact current schema while preserving existing rows

#### Scenario: Later supported release
- **WHEN** a populated v10, v11 or v12 database is opened
- **THEN** only remaining upgrade steps run and existing data remains intact

Evidence: `backend/db/migrations.py::migrate_schema`; `backend/db/migrations.py::UPGRADE_STEPS`; `backend/db/schema_history.py::ACCEPTED_SHAPES_BY_VERSION`. Tests: `tests/test_db_migrations.py::test_oldest_supported_release_schema_upgrades_to_current`; `tests/test_db_migrations.py::test_populated_v9_upgrade_keeps_every_row_and_adds_empty_detail_tables`; `tests/test_db_migrations.py::test_populated_v10_upgrade_keeps_every_row_and_adds_the_empty_mirror`.

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
