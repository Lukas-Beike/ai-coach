# runtime-and-configuration Specification

## Purpose

Start and operate the private single-athlete application with explicit configuration, coordinated maintenance and bounded local event state.

Owns composition/lifecycle, configuration and shared infrastructure. Provider-specific scheduling and durable Coach jobs have their own capability contracts. Network exposure is an operational LAN/VPN deployment constraint, not an IP allowlist implemented by the HTTP listener.

## Requirements

### Requirement: Explicit configuration precedence

Configuration loading SHALL use explicit root/data paths and a supplied environment snapshot, retain non-empty process values ahead of root and data-directory .env values, and avoid filesystem side effects merely from importing the configuration module.


#### Scenario: Process value already set
- **WHEN** a non-empty process setting and a persisted setting exist for the same name
- **THEN** the process value remains authoritative during environment loading

#### Scenario: Independent snapshots
- **WHEN** two loads use distinct supplied environments and directories
- **THEN** each result uses its own inputs rather than a previous configuration singleton

#### Scenario: Blank value
- **WHEN** `OPENAI_BASE_URL`, `OPENAI_MODEL`, `INTERVALS_ATHLETE_ID` or `GARMINTOKENS` is set to an empty or blank value
- **THEN** it counts as unset and the documented default applies, so a blank model id is never offered or selected

Evidence: `backend/config.py::load_local_env`; `backend/config.py::load_config`. Tests: `tests/test_config.py::test_two_loads_use_their_supplied_environment_and_paths`; `tests/test_config.py::test_blank_values_use_their_documented_defaults`; `tests/test_config.py::test_process_values_win_over_persisted_values`; `tests/test_config.py::test_import_has_no_filesystem_side_effect`.

### Requirement: Validated endpoints and server-side credentials

Configuration SHALL accept HTTPS OpenAI base URLs and HTTP only on loopback, reject embedded credentials/query/fragment/traversal components, and expose provider credential status without returning secret values.


#### Scenario: Compatible local endpoint
- **WHEN** an HTTP OpenAI endpoint targets localhost or a loopback address
- **THEN** it is accepted and normalized for the Responses client

#### Scenario: Unsafe endpoint
- **WHEN** the submitted endpoint uses non-loopback HTTP, URL credentials, a query, fragment or traversal path
- **THEN** configuration rejects it rather than silently changing transport policy

#### Scenario: Credential status read
- **WHEN** the browser requests provider connection/configuration status
- **THEN** it receives source/configured metadata without stored credential values

#### Scenario: Garmin Personal API key and expiry
- **WHEN** the Garmin Personal API key is stored in the app or read from `GARMIN_PERSONAL_API_KEY` with its `GARMIN_PERSONAL_API_KEY_EXPIRES` date
- **THEN** the key is never returned, the ISO expiry date is the only visible value, and a stored key never takes the environment's expiry, so saving or removing the key clears its expiry

Evidence: `backend/config.py::validated_base_url`; `backend/provider_credentials.py::ProviderCredentialService.status`; `backend/provider_credentials.py::credential_status`; `backend/provider_credentials.py::_unpaired_expiry`. Tests: `tests/test_config.py::test_openai_base_url_requires_https_or_loopback_http`; `tests/test_provider_credentials.py::test_status_never_contains_secret_values`; `tests/test_provider_credentials.py::test_stored_value_overrides_env_and_clearing_restores_env`; `tests/test_garmin_personal_key_status.py::test_a_stored_key_never_takes_the_environment_expiry`; `tests/test_garmin_personal_key_status.py::test_saving_or_removing_the_key_clears_its_expiry`.

### Requirement: Environment variable defaults and tolerance

Configuration SHALL read the variables of `docs/configuration.md` with the defaults stated there (including `PORT` 8090, `OPENAI_MODEL` `gpt-6-luna`, `OPENAI_BASE_URL` `https://api.openai.com/v1`, `ANTHROPIC_BASE_URL` `https://api.anthropic.com`, `DATA_RETENTION_DAYS` -1, `SYNC_HISTORY_EARLIEST_DATE` 2000-01-01); any other variable defaults to empty. A malformed number, boolean or date SHALL fall back to its default and SHALL NOT stop startup.

#### Scenario: Unparsable number
- **WHEN** `PORT` or `DATA_RETENTION_DAYS` is not an integer
- **THEN** 8090 or -1 is used

#### Scenario: Boolean
- **WHEN** `COOKIE_SECURE` is `1`, `true`, `yes` or `on` in any letter case
- **THEN** secure cookies are on; any other value or an empty value means off

#### Scenario: Invalid history floor
- **WHEN** `SYNC_HISTORY_EARLIEST_DATE` is not an ISO date
- **THEN** 2000-01-01 is used and a warning with event `config_invalid_date` names the setting, not the value

#### Scenario: Trusted proxies
- **WHEN** `TRUSTED_PROXY_IPS` lists addresses or networks separated by commas or whitespace
- **THEN** each entry must be an address or a network without host bits; an IPv4-mapped IPv6 entry is treated as its IPv4 form; invalid entries are ignored and counted

#### Scenario: Provider completeness
- **WHEN** only some of `WAHOO_CLIENT_ID`, `WAHOO_CLIENT_SECRET`, `WAHOO_REDIRECT_URI` are set, or only one of `YAZIO_EMAIL`, `YAZIO_PASSWORD`
- **THEN** that provider counts as not configured

#### Scenario: Trimmed and derived values
- **WHEN** a Wahoo, Yazio, Anthropic or Garmin Personal API value has surrounding whitespace
- **THEN** it is stripped; `YAZIO_COUNTRY` is effective only as two letters (else `DE`) and `YAZIO_USER_AGENT` falls back to the built-in client string when empty

#### Scenario: Process-only variables
- **WHEN** `DATA_DIR` or `TZ` appears only in a local environment file
- **THEN** it has no effect: `DATA_DIR` (default `<application directory>/data`, `/data` in the image) is read from the process environment before any file is loaded, and the default profile time zone (`TZ`, default `Europe/Berlin`) is fixed at import

Evidence: `backend/config.py::load_config`; `server.py` (`DATA_DIR`); `backend/athlete/profile.py` (`DEFAULT_PROFILE`, `DEFAULT_TIMEZONE`); `backend/providers/yazio.py`. Tests: `tests/test_config.py::test_sync_history_floor_defaults_parses_and_rejects_invalid_values`; `tests/test_config.py::test_trusted_proxies_parse_addresses_and_networks`; `tests/test_config.py::test_blank_values_use_their_documented_defaults`. No test pins number and boolean parsing, provider completeness or the process-only variables. A blank value is specified under "Explicit configuration precedence".

### Requirement: Local environment files, secure-start refusal and startup warnings

The loader SHALL read `KEY=VALUE` lines from `<application directory>/.env` and then `<DATA_DIR>/.env`, the first non-empty value of a name winning. Startup SHALL stop before any database access when the password or SQLCipher requirement is not met, and SHALL warn, without repeating any configured value, about a password stored beside the database and about ignored proxy entries.

#### Scenario: Line syntax
- **WHEN** a file is read
- **THEN** blank lines and lines starting with `#` are skipped, a leading `export ` is removed, the key must be an ASCII identifier, the value is trimmed and one pair of matching single or double quotes is removed; other lines and unreadable files are ignored

#### Scenario: Refusal order and messages
- **WHEN** the password is missing, shorter than 12 characters, or SQLCipher cannot be imported (checked in this order)
- **THEN** a CRITICAL log with event `secure_startup_refused` is written and the process exits with the message "APP_PASSWORD ist nicht konfiguriert. Lege ein langes, zufälliges Passwort als Container-Umgebungsvariable fest.", "APP_PASSWORD muss mindestens 12 Zeichen lang sein." or "SQLCipher ist nicht verfügbar; die verschlüsselte Datenbank kann nicht geöffnet werden."

#### Scenario: Password in the data directory
- **WHEN** `<DATA_DIR>/.env` assigns a non-empty `APP_PASSWORD`
- **THEN** startup continues and logs a warning with event `app_password_in_data_dir`

#### Scenario: Ignored proxy entries
- **WHEN** at least one `TRUSTED_PROXY_IPS` entry was invalid
- **THEN** startup logs a warning with event `config_invalid_trusted_proxy` whose text is fixed

#### Scenario: Unsafe base URL in the environment
- **WHEN** `OPENAI_BASE_URL` or `ANTHROPIC_BASE_URL` fails validation
- **THEN** the process does not start (error "OPENAI_BASE_URL muss HTTPS oder HTTP auf Loopback verwenden." or the same text for `ANTHROPIC_BASE_URL`)

Evidence: `backend/config.py` (`load_local_env`, `_parse_local_env_line`, `security_configuration_error`, `data_dir_env_warning`, `proxy_list_warning`, `validated_base_url`); `server.py::main`. Tests: `tests/test_config.py::test_security_error_order_and_success`; `tests/test_config.py::test_local_env_defines_reports_only_assigned_names`; `tests/test_config.py::test_data_dir_env_warning_never_contains_the_value`; `tests/test_config.py::test_process_values_win_over_persisted_values`; `tests/test_config.py::test_openai_base_url_requires_https_or_loopback_http`. No test pins the quote handling, the `secure_startup_refused` and warning log events, or the startup failure for an unsafe `ANTHROPIC_BASE_URL`.

### Requirement: Ordered startup and durable-work recovery

Startup SHALL validate secure configuration, initialize the database, recover interrupted sync/Coach work, enqueue configured startup refreshes, then start the workers, the canonical backfill and daily scheduling before serving the main loop. The canonical re-projection and the stream-decoding follow-up stages SHALL start no new record or session after a short batch time; those stages SHALL compute before taking the writer, so logins, Coach turns and syncs keep working during a recompute.


#### Scenario: Normal start
- **WHEN** secure initialization succeeds
- **THEN** job recovery is performed by the startup owner, workers start, and configured startup refreshes (calendar, Garmin, Wahoo, weather) are scheduled; Intervals.icu, an output target, is not read

#### Scenario: Long recompute after an upgrade
- **WHEN** a method version bump makes the canonical backfill recompute every stored session
- **THEN** startup finishes, and a login, a Coach turn or a provider sync waiting for the writer gets it within its normal timeout because each batch stops at the batch time

#### Scenario: Recompute outside the writer
- **WHEN** a follow-up stage recomputes changed sessions
- **THEN** the writer stays free while their streams are decoded and computed; the writer transaction re-checks each session's fingerprint and writes only results whose inputs are unchanged

#### Scenario: Database initialization alone
- **WHEN** the schema/bootstrap service initializes persistent state
- **THEN** it does not independently repeat job recovery that belongs to runtime startup

Evidence: `server.py::main`; `backend/db/bootstrap.py::initialize_application_database`; `backend/sync/canonical_backfill.py::timed_batch`; `backend/sync/canonical_backfill.py::precomputed_batch`. Tests: `tests/test_server_runtime.py::test_worker_start_functions_do_not_repeat_recovery`; `tests/test_server_sync.py::test_startup_explicitly_recovers_jobs_before_starting_workers`; `tests/test_session_analysis_stage.py::test_a_long_recompute_leaves_the_writer_to_a_waiting_login`; `tests/test_session_analysis_stage.py::test_sessions_are_analysed_before_the_writer_is_taken`; `tests/test_session_metrics.py::test_metrics_are_computed_before_the_writer_is_taken`; `tests/test_activity_routes.py::test_tracks_are_decoded_before_the_writer_is_taken`; `tests/test_server_database.py::test_database_initialization_does_not_recover_jobs`; `tests/test_startup_sync_scheduler.py::test_enqueues_all_provider_jobs_in_contract_order_with_exact_payloads`.

### Requirement: Startup preparation before workers

After the security check, startup SHALL initialize the database and apply the stored provider credentials over the environment values, delete orphaned staging files, bind the listener, recover interrupted work and enqueue the startup refreshes, in this order, before any worker or the periodic loop starts. A failure before serving SHALL end the process.

#### Scenario: Orphaned staging files
- **WHEN** the data directory holds regular files named `.intervals-coach-export-*.zip`, `.intervals-coach-restore-*.db` or `.database-backup-*.tmp` (the latter two also with `-journal`, `-wal`, `-shm`)
- **THEN** they are deleted before any worker starts and one INFO log `backup_staging_removed` reports the count; the live database, its sidecars, pre-restore copies, the token file and symbolic links are never matched; a failed deletion is a warning and does not stop startup

#### Scenario: Port in use
- **WHEN** `0.0.0.0:<PORT>` cannot be bound
- **THEN** the process ends before any worker or scheduler starts

#### Scenario: Recovery before workers
- **WHEN** the listener is bound
- **THEN** the interrupted workout-library sync state is reset, interrupted sync jobs and interrupted Coach jobs are resumed, the startup refreshes are enqueued, and only then the sync worker, the Coach worker, the canonical backfill worker and the daily loop start

#### Scenario: Startup refresh order
- **WHEN** startup refreshes are enqueued
- **THEN** configured providers are visited in the order calendar, Garmin, weather, Wahoo, and a provider with an active refresh job gets no second one

#### Scenario: Lifecycle log
- **WHEN** startup begins and when the listener is ready
- **THEN** INFO logs `server_start` (version, port) and `server_ready` (port) are written

Evidence: `server.py::main`; `server.py::initialise_database`; `backend/backup/staging_sweep.py::remove_orphaned_staging_files`; `backend/sync/scheduler.py::StartupSyncScheduler.schedule`; `backend/sync/provider_registry.py` (`startup_order`). Tests: `tests/test_backup_sweep.py::OrphanedStagingSweepTests.test_removes_only_orphans_directly_in_the_data_directory`; `tests/test_backup_sweep.py::OrphanedStagingSweepTests.test_symlinked_match_is_kept_with_its_target`; `tests/test_server_composition_architecture.py::test_startup_sweeps_orphaned_staging_files_once_before_workers`; `tests/test_server_sync.py::test_startup_explicitly_recovers_jobs_before_starting_workers`; `tests/test_provider_registry.py::test_startup_order_matches_scheduler_ranks`; `tests/test_startup_sync_scheduler.py::test_enqueues_all_provider_jobs_in_contract_order_with_exact_payloads`. No test pins the port-in-use order or the lifecycle log events.

### Requirement: Coordinated maintenance and generation invalidation

The maintenance gate SHALL drain active operations before restore/erasure, reject new ordinary operations during maintenance, reject concurrent restores and invalidate claimed work from an older generation.


#### Scenario: Maintenance starts
- **WHEN** a restore begins while other operations are active
- **THEN** it waits for active work, blocks new ordinary operations and advances the generation

#### Scenario: Claimed work is stale
- **WHEN** a job claimed before maintenance tries to run with its old generation
- **THEN** the operation is rejected as invalidated rather than writing into replacement state

#### Scenario: Maintenance raises
- **WHEN** the maintenance body exits with an exception
- **THEN** the gate clears its restoring state and admission can resume

Evidence: `backend/runtime/maintenance.py::MaintenanceGate`; `backend/runtime/maintenance.py::claimed_maintenance_operation`. Tests: `tests/test_runtime_maintenance.py::test_operation_rejects_stale_generation`; `tests/test_runtime_maintenance.py::test_restore_drains_other_operations_when_called_from_operation`; `tests/test_runtime_maintenance.py::test_second_restore_is_rejected_and_restore_finally_cleans_up`.

### Requirement: Maintenance gate error contract and bounded drain

The gate SHALL answer a new ordinary operation during maintenance with HTTP 503 (reason `maintenance`), a job from an older generation with HTTP 409 (reason `operation_invalidated`) and a second maintenance request with HTTP 409. Draining SHALL be bounded at 20 seconds; on expiry nothing is changed, the gate reopens and the caller gets HTTP 409 (reason `maintenance_drain_timeout`).

#### Scenario: Running work is asked to stop first
- **WHEN** maintenance starts
- **THEN** new operations are refused at once, then the cancel hook (running Coach turns) runs outside the gate lock, then the drain waits

#### Scenario: Drain timeout
- **WHEN** an operation is still active after 20 seconds
- **THEN** the generation is not advanced and the error text is "Laufende Aufgaben, etwa eine Coach-Antwort, werden noch beendet. Es wurde nichts geändert. Bitte gleich erneut versuchen."

#### Scenario: Maintenance from inside an operation
- **WHEN** the thread that starts maintenance already holds an operation
- **THEN** its own operation is not waited for and is counted again when maintenance ends, also after a timeout

#### Scenario: Nested operations
- **WHEN** one thread enters operations recursively
- **THEN** they count as one active operation

#### Scenario: Claimed job meets maintenance
- **WHEN** a claimed job runs during maintenance or with an old generation
- **THEN** it ends without running and without raising; other errors propagate

Detailed contract: messages are "Die Anwendung befindet sich gerade im Wartungsmodus. Bitte später erneut versuchen." (503), "Der Auftrag wurde durch eine Datenlöschung verworfen." (409) and "Eine Datenbankwiederherstellung läuft bereits." (409, no reason). The gate state is `{"active": <maintenance running>, "running_operations": <count>}`. Which routes enter the gate is listed in `docs/api-routes.md`.

Evidence: `backend/runtime/maintenance.py` (`MaintenanceGate.operation`, `MaintenanceGate.restore`, `RESTORE_DRAIN_TIMEOUT_SECONDS`, `claimed_maintenance_operation`). Tests: `tests/test_runtime_maintenance.py::test_restore_times_out_with_retryable_409_and_leaves_gate_open`; `tests/test_runtime_maintenance.py::test_restore_cancels_running_work_before_it_waits`; `tests/test_runtime_maintenance.py::test_restore_timeout_keeps_a_nested_caller_operation`; `tests/test_runtime_maintenance.py::test_recursive_operations_count_once_per_thread`; `tests/test_runtime_maintenance.py::test_operation_rejects_during_restore`; `tests/test_runtime_maintenance.py::test_claimed_decorator_swallowing_and_propagation`; `tests/test_runtime_maintenance.py::test_failing_cancel_hook_clears_restoring`.

### Requirement: Health is distinct from readiness

The public health endpoint SHALL report live process/maintenance state, while readiness SHALL require available database reads, exact current schema, writable data storage and no active maintenance; bootstrap SHALL remain authenticated.


#### Scenario: Alive but not ready
- **WHEN** the process responds but a database/storage/maintenance readiness check fails
- **THEN** health can respond while readiness returns HTTP 503 with the bounded failed checks

#### Scenario: All checks ready
- **WHEN** database, schema and writable-directory checks pass outside maintenance
- **THEN** readiness returns ready=true and HTTP 200

#### Scenario: Bootstrap without a session
- **WHEN** the initial state API is requested by an unauthenticated client
- **THEN** authentication is required before reading athlete bootstrap state

#### Scenario: Public probes and their bodies
- **WHEN** `GET /api/health`, `GET /api/readiness` or `GET /api/auth/status` is requested without a session
- **THEN** each answers; health never touches the database, and the response bodies are the contracts in `docs/api-routes.md`

#### Scenario: Probe fails closed
- **WHEN** the database or schema check raises, or the data directory cannot be written
- **THEN** that check counts as false and readiness answers HTTP 503; no path, athlete data or password appears in the body

#### Scenario: Long writer
- **WHEN** a write transaction is running
- **THEN** the database and schema checks still pass, because they read through a read snapshot

#### Scenario: Storage check
- **WHEN** readiness runs
- **THEN** it creates and removes a file `.readiness-<random>.probe` in the data directory, also after a failed write; failure to create it sets `data_directory` to false

Evidence: `backend/http_api/public_get.py::PublicGetRoutes.routes`; `backend/http_api/readiness.py::ReadinessService.state`. Tests: `tests/test_http_public_get_routes.py::test_health_returns_live_maintenance_state`; `tests/test_http_public_get_routes.py::test_readiness_uses_ready_boolean_for_http_status_and_preserves_json`; `tests/test_http_public_get_routes.py::test_auth_status_uses_optional_authenticated_session_and_live_gate`; `tests/test_http_public_get_routes.py::test_bootstrap_returns_json`; `tests/test_http_readiness.py::test_a_ready_state_is_safe_and_leaves_no_probe_behind`; `tests/test_server_http.py::test_readiness_handler_returns_503_when_manager_composition_fails`; `tests/test_http_readiness.py::test_a_read_only_data_directory_is_not_ready`; `tests/test_http_readiness.py::test_the_probe_is_removed_after_a_write_failure`. No test pins the read-snapshot behavior under a running writer.

### Requirement: Bounded event stream with explicit gaps

The local state-event buffer SHALL admit only the event types `provider`, `job`, `planning`, `coach` and `sync`, number events from 1, keep the newest 500 in process memory, validate cursors and signal a gap instead of silently presenting incomplete incremental history.


#### Scenario: Retained cursor
- **WHEN** a client requests state events after an ID still covered by retention
- **THEN** it receives later retained events and the latest event ID

#### Scenario: Cursor older than retention
- **WHEN** the requested cursor precedes the retained window
- **THEN** the result reports gap=true rather than a misleading partial event list

#### Scenario: Invalid cursor or event type
- **WHEN** a cursor is not parseable or a publication uses an unsupported type
- **THEN** the buffer rejects the invalid input; an invalid cursor is HTTP 400 with reason `invalid_event_cursor` and message "Die Event-ID ist ungültig.", and a negative cursor counts as 0

#### Scenario: Event shape
- **WHEN** an event is published
- **THEN** it is stored as `{"event_id": <int>, "event": <type>, "data": <shallow copy of the payload object>}`; a payload that is not an object is stored as `{}`

#### Scenario: Cursor ahead of the stream
- **WHEN** the cursor is greater than the latest id, as after a process restart
- **THEN** `gap` is true and `events` is empty; a read answers `{"events", "latest_event_id", "gap"}` and a gap always carries the current latest id

#### Scenario: Empty buffer and reset
- **WHEN** nothing was published yet, or the buffer was cleared
- **THEN** cursor 0 returns no gap and a positive cursor returns a gap; clearing restarts events and the id sequence together, so the next event has id 1

The stream route that serves the buffer (`GET /api/state/events`, SSE `reset` and `heartbeat`) is specified in `docs/api-routes.md`.

Evidence: `backend/runtime/events.py::StateEventBuffer`; `backend/http_api/state_events_get.py`. Tests: `tests/test_runtime_events.py::test_parallel_publish_assigns_unique_monotonic_ids`; `tests/test_runtime_events.py::test_retention_reports_gap_and_cursor_is_clamped`; `tests/test_runtime_events.py::test_invalid_cursor_is_app_error`; `tests/test_runtime_events.py::test_publish_validates_events_and_copies_payload`; `tests/test_runtime_events.py::test_cursor_ahead_of_latest_reports_gap`; `tests/test_runtime_events.py::test_empty_buffer_reports_gap_only_for_a_positive_cursor`; `tests/test_runtime_events.py::test_clear_resets_events_and_ids_atomically`.

### Requirement: Explicit bounded retention

With DATA_RETENTION_DAYS at 0 or below (default -1) startup SHALL delete nothing. A positive value SHALL be clamped to 30 through 3650 days; startup SHALL then delete old chat messages, old snapshots except the newest, old finished Coach receipts whose changes can no longer be undone, old unreferenced non-draft Coach plan drafts and expired Coach action proposals.

#### Scenario: Default/unlimited retention
- **WHEN** retention_days is zero or negative
- **THEN** bootstrap deletes no message, snapshot, Coach receipt, plan draft or proposal

#### Scenario: Positive retention
- **WHEN** a positive configured retention period is applied
- **THEN** older messages, non-latest snapshots, completed `coach_commands` and non-draft `coach_plan_artifacts` that no command references are purged using the bounded period; the latest snapshot remains, a receipt whose changes can still be undone is kept only while every change-history row it names is still stored, and expired `coach_action_proposals` are removed

#### Scenario: Coach receipts, drafts and proposals
- **WHEN** a completed Coach command is older than the cutoff
- **THEN** it is deleted unless its receipt lists undoable changes that are not yet undone; a non-draft Coach plan artifact older than the cutoff and referenced by no command is deleted, and every action proposal past its expiry is deleted

#### Scenario: Untouched data
- **WHEN** retention runs
- **THEN** athlete records, plans, settings, canonical provider data, change history and diagnostics stay, and one log event `data_retention_purged` carries the clamped days and the deletion counts

Evidence: `backend/db/bootstrap.py::initialize_application_database`; `backend/config.py::load_config`. Tests: `tests/test_server_runtime.py::test_unlimited_retention_does_not_delete_history`; `tests/test_db_bootstrap.py::test_retention_purges_old_receipts_artifacts_and_expired_proposals`; `tests/test_db_bootstrap.py::test_unlimited_retention_keeps_old_receipts_and_expired_proposals`; `tests/test_db_bootstrap.py::test_retention_keeps_the_newest_snapshot_after_a_long_sync_gap`.

### Requirement: Bounded request concurrency and graceful stop

The HTTP runtime SHALL bound concurrent request handlers and release slots after completion/failure; SIGTERM/interrupt shutdown SHALL stop workers and scheduling and flush diagnostic capture.


#### Scenario: Handler budget saturated
- **WHEN** the configured 32 active handler slots are already occupied
- **THEN** another request is closed without creating an unbounded extra handler

#### Scenario: Handler exits or cannot start
- **WHEN** a request thread finishes or thread startup raises
- **THEN** its request slot is released

#### Scenario: Process stop
- **WHEN** SIGTERM or keyboard interrupt leaves the serving loop
- **THEN** the shutdown path stops scheduling/workers, closes the server and flushes pending diagnostics

Evidence: `backend/http_api/server.py::CoachHTTPServer`; `backend/runtime/socket_deadline.py::SocketDeadline`; `server.py::main`. Tests: `tests/test_security_resource_limits.py::test_handler_slots_recover_when_thread_start_fails`; `tests/test_security_resource_limits.py::test_saturated_handler_budget_rejects_and_recovers`; `tests/test_observability.py::test_diagnostic_capture_close_writes_now_and_stops_delaying`.

### Requirement: Shutdown order and stalled-server diagnosis

On SIGTERM or Ctrl+C the process SHALL signal the daily loop, the sync worker, the Coach worker, the canonical backfill worker and the metric export runner to stop, close the listener, close diagnostic capture, wait at most 5 seconds for each of them, write pending diagnostics and end normally. Except on Windows, SIGUSR1 SHALL write every thread's stack to standard error without stopping the process.

#### Scenario: Slow worker
- **WHEN** a worker does not finish within 5 seconds
- **THEN** shutdown continues with the next one and the process still ends

#### Scenario: Failure while serving
- **WHEN** an exception occurs after the listener was bound and the signal handlers were installed
- **THEN** the same stop sequence runs before the exception ends the process

#### Scenario: Stack dump
- **WHEN** the operator sends `docker kill -s USR1 <container>`
- **THEN** the container log shows file names, line numbers and function names of all threads and no variable values

Evidence: `server.py::main`; `docs/operations.md` (Stalled Server Stack Dump). Tests: `tests/test_server_sync.py::test_startup_explicitly_recovers_jobs_before_starting_workers` (stop and join order); `tests/test_observability.py::test_diagnostic_capture_close_writes_now_and_stops_delaying`. No test pins the join bound or the stack dump.

### Requirement: Stored credentials overlay the environment at run time

The running configuration SHALL be the environment snapshot overlaid with the credentials stored in the database. It SHALL be recomputed after database initialization, after a restore and after a local data purge, and a change SHALL take effect without a restart.

#### Scenario: Stored value changes
- **WHEN** the overlay yields a different configuration
- **THEN** the running configuration is replaced and a generation counter increases so that cached services are rebuilt with the new values

#### Scenario: Cleared or purged value
- **WHEN** a stored credential is removed, or a restore or purge leaves none
- **THEN** the credential field returns to its environment value and every other runtime setting is kept

#### Scenario: Overridden environment secret
- **WHEN** a stored credential overrides an environment secret
- **THEN** the environment secret is still redacted from logs

Evidence: `server.py` (`CONFIG_HOLDER`, `initialise_database`, `REDACTOR`); `backend/config.py::ConfigHolder.apply`; `backend/provider_credentials.py::ProviderCredentialService.refresh`; `backend/backup/assembly.py` and `backend/privacy.py` (`refresh_credentials` hooks). Tests: `tests/test_provider_credentials.py::test_stored_value_overrides_env_and_clearing_restores_env`; `tests/test_provider_credentials.py::test_refresh_keeps_runtime_settings_outside_the_credentials`; `tests/test_provider_credentials.py::test_hot_swap_is_visible_to_lambda_readers_without_restart`; `tests/test_provider_credentials.py::test_wipe_then_refresh_returns_to_environment`; `tests/test_provider_credentials.py::test_environment_secret_stays_redacted_while_a_stored_value_overrides_it`; `tests/test_database_restore_service.py` (restore calls the credential refresh). The purge call site has no dedicated test.

### Requirement: Composition limits and file locations

The composition root SHALL wire these fixed limits and locations; the capabilities that enforce them refer to these values.

#### Scenario: Request and transfer limits
- **WHEN** the application is assembled
- **THEN** JSON request bodies are limited to 1,000,000 bytes, audio uploads to 8,000,000 bytes, database backups and restore uploads to 1,000,000,000 bytes, the privacy export to 100,000,000 bytes, and exports and backups need 10,000,000 free bytes and may take 120 seconds

#### Scenario: Model call limits
- **WHEN** the application is assembled
- **THEN** the longest silence allowed between two parts of a streamed model response is 600 seconds, a plain model request may take 180 seconds, and a chat history page holds at most 100 messages

#### Scenario: Retry and polling
- **WHEN** the application is assembled
- **THEN** provider refresh and sync job retries start at 15 minutes and are capped at 6 hours, and the sync worker polls every second

#### Scenario: Listener
- **WHEN** the listener starts
- **THEN** it accepts at most 32 queued connections besides the 32 active handlers

#### Scenario: Storage
- **WHEN** the application opens its storage
- **THEN** the database is `<DATA_DIR>/intervals-coach.db`, the log is `<DATA_DIR>/intervals-coach.log`, and the pool has four readers with a 20-second database timeout

Evidence: `server.py` (constants above `ENV_CONFIG`, `database_manager`, `CHAT_PAGE_MAX`); `backend/http_api/server.py::CoachHTTPServer`. Tests: `tests/test_server_coach.py::test_coach_http_server_retains_threading_contract`; `tests/test_server_providers.py::test_openai_client_composition_keeps_runtime_hooks`. Not verified: how each consuming module applies its value; only the wiring was read, and the limits other than the two tests above have no test that pins them.
