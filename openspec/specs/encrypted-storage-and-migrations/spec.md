# encrypted-storage-and-migrations Specification

## Purpose

Preserve durable athlete state through encrypted creation, bounded transactions, supported schema upgrades and restarts.

Owns database lifecycle and upgrade contracts. The only supported baseline is the schema production runs, v26 (release 2.0.5); the current schema is v27; canonical/domain records are described in their capability specs. SQLCipher conformance requires encrypted fixtures, separate from SQLite test doubles.

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

### Requirement: Baseline schema upgrades

The database SHALL recognize the version-and-shape pair of the baseline, the schema production runs (v26, release 2.0.5, frozen as one fixture and one digest), and of the current schema, executing the versioned steps from the baseline within one rollback-capable migration transaction. A schema that never reached production SHALL get no frozen shape of its own.

#### Scenario: Baseline database
- **WHEN** a populated baseline database is opened by this build
- **THEN** the steps from the baseline run to the exact current schema while preserving existing rows.

#### Scenario: One step from the previous shape
- **WHEN** a previous shape with one registered step is opened
- **THEN** the step runs in one transaction to the exact current schema and keeps every row.

#### Scenario: Baseline food mirror becomes canonical products
- **WHEN** a v26 database with own products and mirrored foods is upgraded
- **THEN** every own product keeps its row as origin `own`, every mirrored food becomes a product of its database's origin with its fetch time and all fields, an own product with the EAN or id of mirrored foods wins and only its empty fields are filled, and the mirror table is gone. The step uses its own frozen copy of the v27 table and row move, so changes to the live product DDL or repositories never change its result.

#### Scenario: Failing baseline upgrade
- **WHEN** the baseline upgrade fails after moving some rows
- **THEN** the database, its rows and its version stay exactly as before, and a later attempt succeeds.

#### Scenario: Normative schema reference
- **WHEN** a reader needs the exact current schema or the acceptance rule
- **THEN** `docs/schema-reference.md` states the signature and digest rule, how a new database is created and the startup state, and carries the current version, shape digest and DDL generated from `backend/db/schema.py`; the baseline shape is the frozen fixture `tests/fixtures/schema_v26.sql.txt`, and a test fails when the generated reference is out of date

Evidence: `backend/db/migrations.py`, `backend/db/schema_history.py`; `tests/test_db_migrations.py::test_populated_baseline_reaches_the_live_schema_with_its_rows`, `tests/test_db_migrations.py::test_schema_reference_is_current`, `tests/test_db_migrations.py::test_baseline_mirror_rows_become_canonical_products_without_loss`, `tests/test_db_migrations.py::test_v27_product_step_is_frozen_against_live_repository_changes`, `tests/test_db_migrations.py::test_failing_baseline_upgrade_rolls_back_and_a_retry_succeeds`, `tests/test_db_migrations.py::test_upgraded_database_restarts_with_the_same_build_unchanged`, `tests/test_db_migrations.py::test_frozen_baseline_fixture_is_the_recorded_production_shape`, `tests/test_db_migrations.py::test_a_previous_shape_upgrades_in_one_step_with_its_rows`, `tests/test_db_encrypted_upgrade_matrix.py`.

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

A failing migration SHALL roll back its schema and data changes, preserve the original upgrade error even when a savepoint was lost, and leave the database available for a later valid attempt.

#### Scenario: Upgrade step fails
- **WHEN** a schema/data upgrade raises before current-schema validation succeeds
- **THEN** the enclosing migration changes are rolled back rather than committed partially

#### Scenario: Storage engine loses savepoint
- **WHEN** a storage failure rolls back the outer transaction and removes the savepoint
- **THEN** cleanup does not replace the original migration exception with a savepoint error

Evidence: `backend/db/migrations.py::migrate_schema`; `backend/db/migrations.py::_abandon_migration_savepoint`; `backend/db/schema.py::execute_ddl`. Tests: `tests/test_db_encrypted_upgrade_matrix.py::test_a_failing_upgrade_leaves_the_encrypted_database_unchanged`; `tests/test_db_migrations.py::test_lost_savepoint_does_not_mask_the_original_upgrade_error`.

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
The extended schema SHALL preserve all athlete records, feedback, snapshots, tombstones, plans, sessions, settings, conversations, usage and sync state. Supported populated upgrades, injected-failure rollback, same-build restart and encrypted backup/restore SHALL be verified from the baseline, the schema production runs (v26, release 2.0.5, the only production instance).

#### Scenario: Populated baseline
- **WHEN** the frozen baseline schema is populated and opened
- **THEN** existing identities, values, relationships and sync markers survive and new canonical structures satisfy their validation rules.

#### Scenario: Upgrade fails partway
- **WHEN** an injected failure interrupts a supported migration
- **THEN** schema and rows return to the unchanged prior state and a later valid attempt remains possible.

#### Scenario: Encrypted restart and backup
- **WHEN** an opened temporary SQLCipher baseline database is restarted and restored through the supported backup workflow
- **THEN** encryption stays enabled and old plus new canonical records and relationships remain available.

#### Scenario: Unknown or newer shape
- **WHEN** a database has an unsupported version, unrecognized shape or mismatched version/shape pair
- **THEN** initialization rejects it without deleting, resetting or partially modifying it.

Evidence: `backend/db/migrations.py`; `tests/test_db_encrypted_upgrade_matrix.py::test_the_encrypted_baseline_reaches_the_live_schema_like_the_plain_one`, `tests/test_db_encrypted_upgrade_matrix.py::test_a_failing_upgrade_leaves_the_encrypted_database_unchanged`, `tests/test_db_encrypted_upgrade_matrix.py::test_the_baseline_restarts_unchanged_and_needs_its_key`, `tests/test_db_encrypted_upgrade_matrix.py::test_an_encrypted_backup_at_the_baseline_restores_the_same_rows`, `tests/test_database_restore_validation.py::test_validate_accepts_a_populated_baseline_backup`.

### Requirement: Retired schema rejection

The database SHALL reject schema versions older than the baseline v26 (releases before 2.0.5) before changing their data or schema, with a message that names release 2.0.5 for the upgrade. Change-history entries written before v16 under the former planning field names are not translated and cannot be undone.

#### Scenario: Opening an older database
- **WHEN** a database from a release with schema v25 or older is opened
- **THEN** startup rejects it with the release 2.0.5 hint and leaves its rows and version unchanged.

Evidence: `backend/db/migrations.py::migrate_schema`, `backend/db/schema_history.py::OLDEST_SUPPORTED_SCHEMA_VERSION`; `tests/test_db_migrations.py::test_older_database_file_is_refused_at_startup_without_changes`, `tests/test_db_migrations.py::test_older_or_newer_schema_version_is_rejected_without_modification`, `tests/test_change_history.py::test_planning_field_names_before_schema_v16_are_not_translated`.

### Requirement: Closed value columns of the current schema

The current schema SHALL check each closed value column to its vocabulary or JSON shape (each nullable), SHALL require the parent detail set of a strength set row, and SHALL serve the backfill-continuation lookup from the partial index `idx_sync_jobs_backfill_end`. Release 2.0.5 upgrades older schemas to these columns with NULL values.

#### Scenario: Value outside the vocabulary
- **WHEN** `activity_feedback.purpose` is written outside training, race, commute, warmup and cooldown, `activity_detail_sets.hr_source` outside chest_strap, optical and unknown, `power_source` outside power_meter, trainer, estimated and unknown, `sensors` as anything but a JSON array, or `dfa_alpha1` as anything but a JSON object
- **THEN** the database rejects the write.

#### Scenario: Orphan strength set and continuation lookup
- **WHEN** a strength set row names no detail set, or the backfill-continuation lookup runs
- **THEN** the insert is rejected, and the lookup's query plan reads `idx_sync_jobs_backfill_end`.

Evidence: `backend/db/schema.py`; `tests/test_db_provider_schema.py::test_closed_value_columns_accept_only_their_values`, `tests/test_strength_sets.py::test_the_schema_requires_the_set_source_and_a_parent_set`, `tests/test_sync_jobs.py::test_backfill_continuation_lookup_reads_its_index_on_the_live_schema`.
