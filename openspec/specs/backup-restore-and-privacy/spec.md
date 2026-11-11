# backup-restore-and-privacy Specification

## Purpose

Provide consistent athlete-controlled data exports, validated encrypted restore and explicit local erasure with truthful outcomes.

Owns export/restore/erasure workflows, not a fresh-database upgrade policy. Production backup contents and credential stores were not inspected. The specifications refer to synthetic existing regression fixtures.

## Requirements

### Requirement: Consistent encrypted database backup

The database backup service SHALL create a consistent snapshot containing committed WAL data, preserve configured encryption, stream without holding the application database lock for the download, and remove temporary snapshots afterward.

#### Scenario: Committed WAL data
- **WHEN** the athlete requests a database backup after a committed change remains in WAL
- **THEN** the snapshot includes the committed change

#### Scenario: Encrypted source
- **WHEN** a password-configured SQLCipher database is backed up
- **THEN** the target snapshot is configured with the same encryption before copying

#### Scenario: Download finishes or fails
- **WHEN** the snapshot streaming context exits
- **THEN** the temporary backup file is removed

Evidence: `backend/backup/database.py::DatabaseBackupService._create_snapshot`; `backend/backup/database.py::DatabaseBackupService._connect_target`; `backend/backup/database.py::DatabaseBackupService.stream_file`. Tests: `tests/test_database_backup.py::test_read_bytes_contains_wal_changes`; `tests/test_database_backup.py::test_stream_uses_complete_snapshot_without_holding_database_lock`; `tests/test_database_backup.py::test_sqlcipher_snapshot_keeps_encrypted_data_and_mapping_rows`.

### Requirement: Bounded export resource use

Database and privacy-archive exports SHALL enforce their configured size, free-space and time bounds and SHALL reject missing database storage rather than create an empty successful backup.

#### Scenario: Insufficient capacity
- **WHEN** the configured export limit or required free-space reserve cannot be met
- **THEN** the export returns a bounded size/storage error and discards temporary files

#### Scenario: Missing source database
- **WHEN** a backup is requested without its source database file
- **THEN** the service returns unavailable storage rather than an empty backup

#### Scenario: Interrupted file transfer
- **WHEN** the client disconnects or the stream deadline is exceeded
- **THEN** streaming stops and its temporary-file context is released

Evidence: `backend/backup/database.py::DatabaseBackupService._check_source_capacity`; `backend/backup/database.py::DatabaseBackupService._copy_snapshot`; `backend/backup/export.py::PrivacyArchiveExportService.create_file`; `backend/http_api/response_transport.py::HttpResponseTransport`. Tests: `tests/test_database_backup.py::test_size_and_free_space_limits_reject_backup`; `tests/test_database_backup.py::test_missing_database_does_not_create_an_empty_successful_backup`; `tests/test_server_database.py::test_privacy_archive_export_enforces_free_space_size_timeout_and_cleanup`; `tests/test_server_database.py::test_file_stream_uses_bounded_chunks_and_cleans_up_after_disconnect`.

### Requirement: Complete secret-filtered privacy exports

The authenticated privacy export SHALL be a bounded ZIP of JSON and JSON Lines members that holds every durable table except login sessions and the planning-state revision counter; approval proposals are exported without their session and action-token hashes, and every key/value row except the credential, token and OAuth-state keys and the transient running/status flags. The stored non-secret provider fields (Personal API key expiry date, Intervals.icu athlete id, Wahoo client id, OpenAI base URL) are exported in `provider_settings.json`. The format version is currently 17.

#### Scenario: Privacy archive requested
- **WHEN** the authenticated athlete requests the archive export
- **THEN** the archive includes its complete declared manifest and streams the durable collections

#### Scenario: Data kinds added since release 1.13.40
- **WHEN** the archive is exported
- **THEN** it holds the derived session-load and session-metric observations, the Garmin RPE, feel and minimum-heart-rate ratings, the Garmin and FIT detail sets with the executed strength sets and their source, the heart-rate histogram and zone times of each session analysis, the remote links of every provider and entity kind, the field names of nutrition-entry changes, the backfill cursors, the athlete's session purpose marking, the profile sex and the consent, purge and stage state

#### Scenario: Credential-bearing runtime state
- **WHEN** stored application state contains sessions, provider credentials, the Personal API key or Garmin or Wahoo tokens
- **THEN** those values are excluded from the archive, and the non-secret Personal API key expiry date appears only in `provider_settings.json`

#### Scenario: Unauthenticated download
- **WHEN** a privacy download is requested without a valid session
- **THEN** authentication fails before export streaming starts

Evidence: `backend/backup/export.py::PrivacyArchiveExportService`; `backend/backup/export.py::PRIVACY_EXPORT_JSONL_FILES`; `backend/http_api/privacy_get.py`. Only the archive is served. `backend/provider_credentials.py::stored_visible_settings` selects the exported provider fields. Tests: `tests/test_data_safety_coverage.py::DataKindExportTests`; `tests/test_privacy_provider_data.py::test_stored_non_secret_provider_fields_are_exported_without_secrets`; `tests/test_server_database.py::test_privacy_export_zip_streams_collections_and_contains_complete_manifest`; `tests/test_privacy_provider_data.py`; `tests/test_server_database.py::test_privacy_download_routes_require_auth_before_streaming`.

### Requirement: Coverage guards for stored data kinds

Every table in the current schema SHALL have a recorded export decision and a place in the erasure scope, every explicitly selected export column SHALL be exported or listed with its reason, and a schema change SHALL come with a decision on the export format version, so a new data kind cannot reach the database without a backup, export and erasure decision.

#### Scenario: New table without a decision
- **WHEN** a table is added to the schema without an export member, an exclusion reason or an erasure scope entry
- **THEN** the coverage tests fail

#### Scenario: New column of an exported table
- **WHEN** a column is added to a table whose export lists its columns
- **THEN** the coverage tests fail until the column is exported or listed as excluded

Evidence: `backend/backup/export.py::PRIVACY_EXPORT_FORMAT_VERSION`; `backend/privacy.py::PRIVACY_DELETE_SCOPE`. Tests: `tests/test_data_safety_coverage.py::CoverageGuardTests`; `tests/test_server_database.py::test_privacy_delete_preview_covers_every_durable_table_and_reports_counts`.

### Requirement: GPS positions stay in storage

Stored GPS position channels SHALL be part of the database backup, the privacy export and the local data purge, and SHALL NOT enter any read model, Coach context, diagnostics report, log line or structured log field. The athlete SHALL be able to turn off the storage of new tracks (default on); turning it off SHALL NOT delete stored tracks, which only a confirmed request with the exact phrase `GPS-SPUREN LÖSCHEN` removes.

#### Scenario: Positions in a stored stream set
- **WHEN** a stream set with latitude and longitude channels is merged, served as activity detail or summarized as coverage
- **THEN** no position channel and no coordinate value appears in the result

#### Scenario: Storage turned off
- **WHEN** the athlete turned "GPS-Spuren speichern" off and a file with positions is fetched
- **THEN** the stream set is stored without position channels and its content hash equals that of the stripped set

#### Scenario: Confirmed track deletion
- **WHEN** the athlete confirms `GPS-SPUREN LÖSCHEN`
- **THEN** every position channel is deleted, the other channels stay, the route index and its names are deleted and any other phrase is rejected

#### Scenario: Storage turned off with routes
- **WHEN** the athlete turns "GPS-Spuren speichern" off
- **THEN** stored tracks, the route index and the route names stay until the confirmed deletion

#### Scenario: Route read models
- **WHEN** a route is read for the activity view, the Coach, diagnostics or logs
- **THEN** only a label, a repeat count and an opaque route id appear

Evidence: `backend/canonical/vocabulary.py::POSITION_CHANNELS`; `backend/db/activity_detail_store.py::replace_detail_set`; `backend/privacy.py::PrivacyDeleteService`, `backend/activities/route_store.py::clear_routes`. Tests: `tests/test_gps_position_privacy.py`, `tests/test_activity_routes.py::PrivacyDeleteTests`, `tests/test_activity_routes.py::PrivacySweepTests`.

### Requirement: Secrets stay out of exports, reports and logs

The privacy export, the diagnostics report and the log output SHALL NOT contain the Personal API key, provider API keys, Garmin or Wahoo tokens, session hashes or APP_PASSWORD, and the database backup SHALL keep stored credentials only inside the encrypted database.

#### Scenario: Sentinel secrets in storage
- **WHEN** distinctive secrets are placed in temporary configuration and credential storage
- **THEN** none appears in the archive, the JSON projection, the diagnostics report, its log projection or a log line, and the only key/value rows holding one are the credential keys

#### Scenario: Encrypted backup
- **WHEN** the database is backed up with SQLCipher
- **THEN** the backup bytes show neither a plain SQLite header nor a stored secret

Evidence: `backend/provider_credentials.py::CREDENTIAL_KV_KEYS`; `backend/observability.py::Redactor`; `backend/diagnostics/report.py::DiagnosticReportService`. Tests: `tests/test_secret_exposure.py`; `tests/test_diagnostic_report.py::DiagnosticReportServiceTests::test_report_shape_counts_redaction_and_privacy`.

### Requirement: Stage and validate restore before promotion

Restore SHALL stage bounded input to a unique temporary file, migrate supported backup schemas, verify exact schema/integrity/foreign keys with the configured encryption, and leave the active database untouched on staging or validation failure.

#### Scenario: Supported older encrypted backup
- **WHEN** a staged backup has a supported released schema and decrypts under the configured key
- **THEN** it is migrated and validated in staging before promotion

#### Scenario: Malformed or invalid backup
- **WHEN** schema, integrity, foreign keys, encryption or body bounds fail validation
- **THEN** restore fails and the active database is not replaced

#### Scenario: Slow upload
- **WHEN** backup chunks are still arriving
- **THEN** staging proceeds before taking the maintenance gate

Evidence: `backend/backup/restore_validation.py::DatabaseRestoreValidationService.stage`; `backend/backup/restore_validation.py::DatabaseRestoreValidationService.validate`; `backend/backup/restore.py::DatabaseRestoreService.restore`. Tests: `tests/test_data_safety_coverage.py::BackupRestoreRoundTripTests`; `tests/test_database_restore_validation.py::test_stage_streams_chunks_and_enforces_the_limit_while_writing`; `tests/test_database_restore_validation.py::test_validate_accepts_a_populated_baseline_backup`; `tests/test_database_restore_validation.py::test_validate_rejects_foreign_key_violations`; `tests/test_database_restore_service.py::test_invalid_backup_never_changes_live_database_and_cleans_stage`.

### Requirement: Authenticated session-scrubbing restore

The restore endpoint SHALL require authentication and CSRF, delete sessions from a validated staged backup, preserve a unique pre-restore recovery copy when an active file exists, swap under maintenance/drain, and clear the response cookies on success.

#### Scenario: Successful restore
- **WHEN** an authorized backup passes validation and promotion succeeds
- **THEN** backup sessions are absent, the previous active file has a distinct recovery copy, and the athlete must authenticate again

#### Scenario: Repeated restores
- **WHEN** two valid backups are restored in quick succession
- **THEN** their pre-restore recovery-copy names remain distinct

#### Scenario: Gate refuses promotion
- **WHEN** another maintenance restore already owns the gate
- **THEN** the staged file is cleaned up without promoting it

Evidence: `backend/http_api/privacy_restore_post.py::PrivacyRestorePostRoutes.handle`; `backend/backup/restore_validation.py::DatabaseRestoreValidationService.validate`; `backend/backup/restore.py::DatabaseRestoreService._replace`. Tests: `tests/test_http_privacy_restore_post.py::test_success_authenticates_reads_body_restores_and_clears_cookies`; `tests/test_database_restore_validation.py::test_validate_commits_session_scrubbing_after_schema_integrity_and_fk_checks`; `tests/test_database_restore_service.py::test_two_restores_keep_distinct_recovery_copies`.

### Requirement: Truthful post-restore recovery

After replacing the database, restore SHALL refresh credential-derived configuration, resume interrupted sync and Coach jobs, restart canonical backfill and wake workers; resume failures SHALL be reported as restored_resume_failed rather than as an untouched invalid backup.

#### Scenario: Recovered durable work
- **WHEN** promotion completes and recovery dependencies succeed
- **THEN** restored jobs resume against restored provider configuration and both workers are signaled

#### Scenario: Resume fails after swap
- **WHEN** worker recovery raises after the active database has been replaced
- **THEN** the API reports restored_resume_failed and advises restart while worker wake signals still run

Evidence: `backend/backup/restore.py::DatabaseRestoreService._resume`; `backend/backup/restore.py::DatabaseRestoreService.restore`. Tests: `tests/test_database_restore_service.py::test_restore_restarts_the_canonical_backfill_worker_once_after_the_swap`; `tests/test_database_restore_service.py::test_resume_failure_after_replace_reports_restored_and_still_wakes_workers`; `tests/test_database_restore_service.py::test_coach_resume_failure_after_replace_still_wakes_both_workers`.

### Requirement: Explicit scoped local erasure

Local privacy deletion SHALL require the exact backend confirmation text before dependency access, expose a count preview covering durable deletion categories, and delete the declared local scope in one maintenance-gated transaction.

#### Scenario: Wrong deletion confirmation
- **WHEN** the request does not contain the exact required confirmation text
- **THEN** the service fails before touching deletion dependencies

#### Scenario: Confirmed erasure
- **WHEN** the exact confirmation is supplied
- **THEN** the declared durable tables and KV state, including the Personal API key, its expiry date, the consent and purge state and the profile sex, are cleared transactionally and the default profile/reset state is restored; a switched-off "GPS-Spuren speichern" setting stays off

#### Scenario: Remote links in the preview
- **WHEN** the preview counts the deletion scope
- **THEN** remote links are counted under the group owning their entity kind (library, competitions, or provider data for metric-export observations), so the counts add up to every row the deletion removes

#### Scenario: Files beside the database
- **WHEN** local erasure completes
- **THEN** the legacy Garmin token file and the `.env` file stay, and recovery copies and purge marker files are deleted (next scenario)

#### Scenario: Delete fails midway
- **WHEN** a table deletion fails within the local transaction
- **THEN** earlier table deletes roll back rather than reporting successful erasure

#### Scenario: Recovery copies beside the database
- **WHEN** restores or the Intervals.icu purge of release 2.0.0 saved database recovery copies and a purge marker file in the data directory
- **THEN** the preview counts them, the confirmed erasure deletes them after the transaction commits, and a copy that cannot be removed is reported without failing the erasure

Evidence: `backend/privacy.py::PrivacyDeleteService.preview`; `backend/privacy.py::PrivacyDeleteService.delete`; `backend/privacy.py::PRIVACY_DELETE_SCOPE`; `backend/backup/recovery_copies.py::RecoveryCopies`. Tests: `tests/test_data_safety_coverage.py::DataKindDeleteTests`; `tests/test_privacy_provider_data.py::test_preview_counts_remote_links_by_owning_group`; `tests/test_privacy_provider_data.py::test_delete_clears_every_garmin_capability_pause`; `tests/test_privacy_delete_confirmation.py::test_missing_or_wrong_confirmation_fails_before_any_dependency_access`; `tests/test_server_database.py::test_privacy_delete_preview_covers_every_durable_table_and_reports_counts`; `tests/test_server_database.py::test_privacy_delete_rolls_back_earlier_table_deletes_on_sql_failure`.

### Requirement: Remote-erasure and credential outcomes remain separate

Privacy deletion SHALL report local erasure separately from its best-effort OpenAI conversation deletion, preserve the declared untouched remote-provider scope, cancel pending Garmin login and mark legacy Garmin token state disconnected to prevent silent re-import.

#### Scenario: Remote conversation deletion fails
- **WHEN** an existing OpenAI conversation cannot be deleted remotely
- **THEN** local erasure continues and the result reports the remote attempt and failure separately

#### Scenario: Pending Garmin login exists
- **WHEN** local erasure runs while a Garmin login may still complete
- **THEN** the pending login is cancelled and the legacy token state is marked disconnected

#### Scenario: Diagnostic cache after erasure
- **WHEN** the erasure transaction clears diagnostic state
- **THEN** pre-erasure capture caches cannot repopulate the deleted entries

Evidence: `backend/privacy.py::PrivacyDeleteService.delete`; `backend/privacy.py::PRIVACY_REMOTE_SCOPE`; `backend/provider_credentials.py::GARMIN_TOKENSTORE_DISCONNECTED`. Tests: `tests/test_server_database.py::test_privacy_delete_reports_remote_attempt_and_failure`; `tests/test_privacy_delete_confirmation.py::test_deleted_diagnostic_entries_do_not_return_or_resurrect_after_delete`.

### Requirement: Retired backup schema rejection

Restore SHALL reject backups with schema versions older than the baseline v26 (releases before 2.0.5) without changing the backup or the active database, with a message that names release 2.0.5 for the upgrade.

#### Scenario: Older backup is selected
- **WHEN** a backup with schema v25 or older is staged for restore
- **THEN** validation fails with the release hint, the staged backup keeps its rows and version, and the active database remains unchanged.

Evidence: `backend/backup/restore_validation.py`; `tests/test_database_restore_validation.py::test_validate_rejects_a_pre_baseline_backup_by_release_without_modifying_it`.

