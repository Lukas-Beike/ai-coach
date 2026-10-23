# Runtime and configuration Specification Delta

## Purpose

Start and operate the private single-athlete application with explicit configuration, coordinated maintenance and bounded local event state.

Owns composition/lifecycle, configuration and shared infrastructure. Provider-specific scheduling and durable Coach jobs have their own capability contracts. Network exposure is an operational LAN/VPN deployment constraint, not an IP allowlist implemented by the HTTP listener.

## ADDED Requirements

### Requirement: Explicit configuration precedence

Configuration loading SHALL use explicit root/data paths and a supplied environment snapshot, retain non-empty process values ahead of root and data-directory .env values, and avoid filesystem side effects merely from importing the configuration module.


#### Scenario: Process value already set
- **WHEN** a non-empty process setting and a persisted setting exist for the same name
- **THEN** the process value remains authoritative during environment loading

#### Scenario: Independent snapshots
- **WHEN** two loads use distinct supplied environments and directories
- **THEN** each result uses its own inputs rather than a previous configuration singleton

Evidence: `backend/config.py::load_local_env`; `backend/config.py::load_config`. Tests: `tests/test_config.py::test_two_loads_use_their_supplied_environment_and_paths`; `tests/test_config.py::test_process_values_win_over_persisted_values`; `tests/test_config.py::test_import_has_no_filesystem_side_effect`.

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

Evidence: `backend/config.py::validated_openai_base_url`; `backend/provider_credentials.py::ProviderCredentialService.status`; `backend/provider_credentials.py::credential_status`. Tests: `tests/test_config.py::test_openai_base_url_requires_https_or_loopback_http`; `tests/test_provider_credentials.py::test_status_never_contains_secret_values`; `tests/test_provider_credentials.py::test_stored_value_overrides_env_and_clearing_restores_env`.

### Requirement: Ordered startup and durable-work recovery

Startup SHALL validate secure configuration, initialize the database, recover interrupted sync/Coach work, start workers/canonical backfill, enqueue configured startup refreshes and start daily scheduling before serving the main loop.


#### Scenario: Normal start
- **WHEN** secure initialization succeeds
- **THEN** job recovery is performed by the startup owner, workers start, and configured startup refreshes are scheduled

#### Scenario: Database initialization alone
- **WHEN** the schema/bootstrap service initializes persistent state
- **THEN** it does not independently repeat job recovery that belongs to runtime startup

Evidence: `server.py::main`; `backend/db/bootstrap.py::initialize_application_database`. Tests: `tests/test_server_runtime.py::test_worker_start_functions_do_not_repeat_recovery`; `tests/test_server_database.py::test_database_initialization_does_not_recover_jobs`; `tests/test_provider_runtime_assembly.py`.

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

Evidence: `backend/http_api/public_get.py::PublicGetRoutes.handle`; `backend/http_api/readiness.py::ReadinessService.state`. Tests: `tests/test_http_public_get_routes.py::test_health_returns_live_maintenance_state`; `tests/test_http_public_get_routes.py::test_readiness_uses_ready_boolean_for_http_status_and_preserves_json`; `tests/test_http_public_get_routes.py::test_bootstrap_authenticates_before_read_and_returns_json`.

### Requirement: Bounded event stream with explicit gaps

The local state-event buffer SHALL admit only supported event types, assign monotonic event IDs, retain a bounded window, validate cursors and signal a retention gap instead of silently presenting incomplete incremental history.


#### Scenario: Retained cursor
- **WHEN** a client requests state events after an ID still covered by retention
- **THEN** it receives later retained events and the latest event ID

#### Scenario: Cursor older than retention
- **WHEN** the requested cursor precedes the retained window
- **THEN** the result reports gap=true rather than a misleading partial event list

#### Scenario: Invalid cursor or event type
- **WHEN** a cursor is not parseable or a publication uses an unsupported type
- **THEN** the buffer rejects the invalid input

Evidence: `backend/runtime/events.py::StateEventBuffer`; `backend/http_api/state_events_get.py`. Tests: `tests/test_runtime_events.py::test_parallel_publish_assigns_unique_monotonic_ids`; `tests/test_runtime_events.py::test_retention_reports_gap_and_cursor_is_clamped`; `tests/test_runtime_events.py::test_invalid_cursor_is_app_error`.

### Requirement: Explicit bounded retention

Database startup SHALL retain messages and snapshots indefinitely when DATA_RETENTION_DAYS is nonpositive; a positive value SHALL be clamped to 30 through 3650 days and SHALL preserve the newest snapshot even when old.


#### Scenario: Default/unlimited retention
- **WHEN** retention_days is zero or negative
- **THEN** bootstrap does not purge old messages or provider snapshots

#### Scenario: Positive retention
- **WHEN** a positive configured retention period is applied
- **THEN** old messages and non-latest snapshots are purged using the bounded period while the latest snapshot remains

Evidence: `backend/db/bootstrap.py::initialize_application_database`; `backend/config.py::load_config`. Tests: `tests/test_server_runtime.py::test_unlimited_retention_does_not_delete_history`; `tests/test_server_database.py::test_snapshot_repository_preserves_latest_payload_and_retention_contract`.

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
