# Server composition root slimming progress

Implementation baseline: `develop` at `0ffefbe`, plan from
`docs/composition-root-slimming` at `5e77fe3`.

## S0: baseline and dependency map

- Composition graph and test/fixture references: see
  [server-composition-root-s0-map.md](server-composition-root-s0-map.md).
- `server.py`: 2,756 physical / 2,378 nonblank lines, 218 AST import
  statements, 171 top-level functions.
- `python scripts/server_extraction_inventory.py --check`: passed.
- `python -m unittest discover -s tests -v`: 2,820 tests passed, 12 skipped
  in 499.521 seconds. SQLCipher-dependent cases require the application
  container and are skipped in this Windows run.
- `python -m compileall -q server.py backend tests`: passed.
- `git diff --check`: passed.

All tests ran on the isolated task worktree with repository fixtures and
mocked providers; no live account or runtime data was used.

## S1 boundary before implementation

- `backend/db/manager.py` will own one `DATABASE_MANAGER_CACHE` and the
  application `DATABASE_LOCK`; `server.py` will import those same objects and
  pass them to its consumers. No second cache or lock is created.
- Keep `database_manager()` in the root as the explicit edge that supplies the
  current `CONFIG`, `DATA_DIR`, `DB_PATH`, SQLCipher backend, and cipher
  configuration. Its lookup remains lazy and its fail-closed SQLCipher check
  precedes cache construction. Keep `initialise_database()` with the startup
  lifecycle because it owns the root's lock/transaction boundary and passes
  current retention and provider-resync configuration to the DB bootstrap.
- `backend/http_api/auth.py` remains owner of its existing auth cache and rate
  limiter through `get_session_auth_service(manager, lock, config,
  sqlcipher_available)`. Provider state cache remains owned by
  `backend/providers/state.py`; its `get_provider_state_service` interface
  takes the manager, repository, lock, clocks, and logger explicitly.
- `DATABASE_MANAGER_CACHE` currently has nine test reset call sites in five
  test modules plus `tests/support.py` and `tests/server_test_support.py`;
  move those resets to the backend owner. Retain `server.DB_LOCK` patching only
  where a test specifically verifies the root passes a substituted lock.
- `database_manager()` is called from root factories and used directly by
  temporary-storage fixtures; tests also patch it in the manager-switch and
  login cases. Manager creation is never eager. Cache reset must still drain
  and close the same manager before a replacement is opened.

## S1: shared resources and database boundary

- Completed: `backend/db/manager.py` now owns the single application lock and
  database-manager cache. The root imports the lock under its composition
  name and uses the backend cache module directly. `backend/runtime/clock.py`
  owns UTC timestamps; root factories and tests use that owner directly. Auth
  and provider-state caches remain with their existing backend owners and are
  accessed through narrow backend functions.
- `database_manager()` remains the explicit root adapter because it combines
  mutable root configuration and paths with SQLCipher startup policy. It
  continues to create the directory and manager only when called. Database
  bootstrap remains on the visible `main()` startup path.
- Updated reset and clock lookups in `tests/support.py`,
  `tests/server_test_support.py`, and affected database, provider, runtime,
  planning, Coach, performance, diagnostics, and weather tests. Added a
  resource identity regression in `tests/test_server_database.py`.
- Changed files: `server.py`, `backend/db/manager.py`, new
  `backend/runtime/clock.py`, generated `docs/server-extraction-inventory.md`,
  this progress record, and 14 test/support modules.
- Measured `server.py`: 2,756 physical / 2,381 nonblank lines, 220 import
  statements, 170 top-level functions.
- Focused checks passed: database (45 run, 3 skipped), architecture (48),
  providers (48), support fixtures (2), runtime (13), and weather/calendar
  (44). Inventory check, compileall, and diff check passed.
- Docker image build could not run because the local Docker engine pipe is
  unavailable. SQLCipher-dependent checks remain limited to the existing
  skips; no application or provider data was used.

## S2a1 boundary before implementation: provider transports

- `provider_http_client()` currently composes the owner cache in
  `backend/providers/http.py` with provider state, diagnostics, redaction,
  clock, and sync-operation context. The active provider state and client must
  continue to be bound to the current manager. `intervals_client(config)` is
  stateless and uses the active config only when called.
- About 136 test references call these root factories to access the concrete
  clients; they patch the returned HTTP client's request/opener. No fixture
  patches either root factory, and `e2e/fixture_runtime.py` has no transport
  lookup. `provider_http.urlopen` and `server.CONFIG` are patched by provider
  tests, so the new owner must resolve those at client construction time.
- Proposed interface: one provider-only `ProviderTransportAssembly` in
  `backend/providers/` with `json_http_client()` and
  `intervals_client(config=None)`. `server.py` creates the object with named
  dependencies and replaces route/service/test lookups with those methods.
  Its constructor performs no provider, DB, file, or thread I/O; the existing
  JSON client cache remains the only client cache owner. The getter for
  provider state and the manager will stay lazy until `json_http_client()` is
  called.

## S2a1: provider transport assembly

- Completed in `backend/providers/transport_assembly.py`. The root now creates
  one provider-only assembly with explicit dependencies. Its constructor only
  stores those dependencies; client creation remains lazy. The JSON HTTP cache
  stays in `backend/providers/http.py`, and its active provider state still
  follows the current manager. Intervals config and the provider opener are
  resolved when their methods run, preserving the test patch points.
- Removed the root `provider_http_client()` and `intervals_client()`
  forwarding factories. Service factories, tests, and fixture setup use the
  assembly methods directly. Updated auth rate-limiter references to
  `backend/http_api/auth.py` where earlier fixture/test lookups still targeted
  a removed root binding.
- Focused checks passed: architecture (48), providers (49), Intervals client
  (2), HTTP (67), sync (80), weather/calendar (44), planning (88), performance
  (38), and database (45 run, 3 skipped). Inventory, compileall (including
  `e2e/fixture_runtime.py`), and diff checks passed.
- Measured `server.py`: 2,753 physical / 2,381 nonblank lines, 220 import
  statements, 168 top-level functions.
- Docker image build remains unavailable because the local Docker engine pipe
  is absent. No live provider was contacted.

## S2a2a boundary before implementation: provider refresh state

- The refresh tracker cache already lives in `backend/sync/refresh.py` and is
  keyed by the active manager, shared event buffer, and retry/retention
  settings. Its root callers are the provider observer and weather refresh
  journal; tests also read it for persistence assertions.
- The operation observer is intentionally a fresh lightweight adapter per
  call, but every instance must receive that exact cached tracker, the shared
  maintenance gate, and the same logger. Provider freshness is an uncached
  service whose manager/config are resolved at each call.
- Proposed interface: `ProviderSyncAssembly` in `backend/sync/assembly.py`,
  with `refresh_tracker()`, `operation_observer()`, and
  `freshness_service()`. Its constructor stores late manager/config providers
  and the existing shared resources only; methods call backend-owned caches
  and service constructors. Root and test callers will use this single,
  domain-specific assembly lookup.
- External patch targets: no tests patch these root factories; tests consume
  the returned instances. No e2e fixture directly references these factories.

## S2a2b boundary before implementation: weather services

- `weather_service()` composes the existing `WEATHER_SERVICE_CACHE`, a
  `WeatherCacheStore` for the active manager, a deferred WeatherClient factory,
  and a refresh journal using the shared provider refresh tracker and sync
  operation context. The cache store is bound to `profile_service()` and the
  maintenance gate. `WeatherServiceCache.get` stores the client factory; it
  does not invoke it during composition.
- `weather_sync_service()` composes profile reads, the cached weather service,
  adaptive preview generation, and a fresh observer. These are weather
  application services; `public_weather_state_service()` stays for the later
  HTTP/public-state slice.
- Tests directly obtain the service to exercise refresh and cache behavior or
  patch its `state` method; no tests patch either root factory. No e2e fixture
  uses these factories.
- Proposed interface: `WeatherAssembly` in `backend/weather/assembly.py`,
  exposing only `service()` and `sync_service()`. Manager/profile/planning
  providers and the HTTP client factory are explicit lazy inputs; the existing
  weather cache remains the sole owner of the shared service instance.

## S2a2b: weather service assembly

- Completed in `backend/weather/assembly.py`. The root now supplies a focused
  `WeatherAssembly`; weather cache lookup and sync-service construction live
  with weather ownership. The existing manager-keyed cache remains the sole
  owner, and its deferred WeatherClient factory remains uncalled until a
  refresh actually needs it. The public weather projection stays for S5.
- Removed the root weather and weather-sync factories. Root and test callers
  now use the assembly methods; the architecture test checks the backend cache
  boundary. Added a regression that the assembly constructor does not resolve
  the database, profile, preview, or provider-client callbacks.
- Focused checks passed: architecture (48), weather/calendar (44), database
  (45 run, 3 skipped), sync-executor (13), planning (88), audit remediation
  (17 run, 1 skipped), weather service (6), and workout repair (27). Inventory,
  compileall, and diff checks passed.
- Measured `server.py`: 2,713 physical / 2,349 nonblank lines, 217 import
  statements, 163 top-level functions.
- Docker image build is still blocked by the absent local Docker engine. No
  live provider was contacted.

## S2a2a: provider refresh state assembly

- Completed in `backend/sync/assembly.py` as `ProviderSyncAssembly`. It owns
  the retrieval of the cached refresh tracker, construction of operation
  observers over the shared tracker/gate, and construction of provider
  freshness projections. Manager/config resolution is late; the existing
  tracker cache, event buffer, maintenance gate, and logger identities are
  passed through unchanged.
- Removed the three root factories and migrated their root/test consumers to
  `server.PROVIDER_SYNC`. Updated the architecture test to enforce the
  assembly boundary and retained tracker-cache ownership in
  `backend/sync/refresh.py`.
- Focused checks passed: architecture (48), providers (49), database (45 run,
  3 skipped), runtime (13), and sync (80). Inventory, compileall, and diff
  checks passed.
- Measured `server.py`: 2,732 physical / 2,364 nonblank lines, 218 import
  statements, 165 top-level functions.
- Docker image build remains unavailable because the local Docker engine pipe
  is absent. No live provider was contacted.

## S2a2c boundary before implementation: Garmin services

- `garmin_fixture_loader`, `garmin_client_factory`, `garmin_payload_service`,
  `garmin_sync_state_service`, `garmin_remote_reader`, `garmin_sync_service`,
  and `garmin_projection_service` are the Garmin-owned composition group in
  `server.py`. Their callers span the sync/Coach/HTTP setup plus provider,
  performance, diagnostics, HTTP, Coach, and fixture tests. Tests directly call
  these factories but do not patch the factory names; they patch the concrete
  Garmin service/provider methods at their owning modules. `tests/server_test_support.py`
  also reads payload snapshots through the root factory.
- Preserve the active manager on every manager-backed service; pass through the
  existing key-value repository, sync-state repository, daily marker service,
  provider operation observer, event buffer, Garmin sync lock, and resync gate.
  The Garmin projection receives the performance-owned morning body-battery
  service as a specific lazy dependency. The existing morning battery cache,
  source, and orchestration remain performance-owned and are not folded into
  this assembly.
- Proposed interface: `GarminAssembly` in `backend/sync/garmin_assembly.py`,
  with the seven corresponding named methods. It owns Garmin-specific factory
  composition only. Config and manager are supplied as late providers because
  tests/runtime can replace them; date/clock, diagnostic, and marker callbacks
  retain current evaluation timing. Constructors stay lazy: assembly creation
  and service construction do not invoke Garmin SDK/network operations.

## S2a2c: Garmin service assembly

- Completed in `backend/sync/garmin_assembly.py`. The root now creates one
  `GarminAssembly` with seven Garmin-owned factory methods. Manager and config
  stay late-resolved; the manager-backed services retain the active manager,
  key-value repository, state repository, marker service, shared Garmin lock,
  resync gate, operation observer, and event buffer. The existing morning
  body-battery cache and construction remain performance-owned; the projection
  receives its specific factory as a lazy dependency.
- Moved all root/test callers to `GARMIN_ASSEMBLY`. The complete patch-target
  search found tests patching `GarminClientFactory` and `GarminSyncService`
  through old root imports; those patches now target their provider and sync
  owner modules, and Garmin assembly resolves the classes through those same
  modules. No fixture factory aliases remain.
- Focused checks passed: architecture, providers, sync, performance, provider
  review, diagnostics, Coach, HTTP, and sync executor (372 tests, 1 SQLCipher
  skip, 110.756 seconds). Inventory check, compileall, and diff check passed.
  The required Docker build was attempted but the local Docker engine pipe is
  unavailable. No live provider or application data was used.
- Measured `server.py`: 2,625 physical / 2,274 nonblank lines, 215 import
  statements, 156 top-level functions.
- Changed files: `backend/sync/garmin_assembly.py`, `server.py`, regenerated
  `docs/server-extraction-inventory.md`, this progress record, and Garmin
  factory consumers/patch targets in `tests/server_test_support.py`,
  `tests/test_diagnostic_followups.py`, `tests/test_provider_review.py`,
  `tests/test_server_architecture.py`, `tests/test_server_coach.py`,
  `tests/test_server_http.py`, `tests/test_server_performance.py`,
  `tests/test_server_providers.py`, and `tests/test_server_sync.py`.
- Remaining risk: SQLCipher integration and image build still require the
  application Docker runtime, unavailable on this host.

## S2b1 boundary before implementation: sync-job queue control plane

- The root factories `sync_job_store`, `sync_job_queue_service`, and
  `sync_job_outcome_service` form the persistent job control-plane seam. Their
  callers are shared by manual HTTP sync, Coach refresh/planning commands,
  performance follow-ups, public state, sync execution, scheduling, startup
  recovery, and temporary-storage tests. Tests directly call the factories
  throughout the suite; no fixture patches these root functions. Several tests
  patch `server.SyncJobQueueService` methods, so those patches must move to
  `backend.sync.queue.SyncJobQueueService` and the assembly must resolve the
  class through its owning module.
- `SyncJobStore` wrappers are fresh per factory call and must use the current
  manager with the existing UTC clock and UUID factory. Queue and outcome
  wrappers are also fresh. Preserve the same state-event buffer, maintenance
  gate, and `shared_sync_job_wake_event()` owner identity across queue service,
  outcome service, and the later worker assembly. Resolve the manager and wake
  event when the corresponding method is called; do not make assembly creation
  touch storage or start work. Daily marker service construction remains a
  callable edge from queue construction.
- Proposed interface: `SyncJobQueueAssembly` in
  `backend/sync/queue_assembly.py`, exposing `store()`, `service()`, and
  `outcome_service()`. Worker singleton creation, executor wiring, schedulers,
  command endpoints, and provider/domain sync services remain outside this
  slice.

## S2b1: sync-job queue control plane assembly

- Completed in `backend/sync/queue_assembly.py` as `SyncJobQueueAssembly`, with
  `store()`, `service()`, and `outcome_service()`. The root supplies manager,
  clock, UUID, event-buffer, maintenance-gate, shared wake-event, marker,
  redaction, logging, and retry dependencies. Store and service wrappers remain
  fresh per call; database and wake-event lookup remains lazy.
- Removed the three root factories and migrated root, Coach, HTTP, scheduler,
  fixture, and test consumers to `SYNC_JOB_QUEUE`. Tests now patch
  `SyncJobQueueService` through `backend.sync.queue`; no queue factory alias
  remains in the root.
- Focused queue/job/sync/lifecycle/Coach/architecture run exercised 273 tests.
  The first combined run found one stale architecture expectation for the
  removed root factory; after updating it, that route ownership test passed and
  the full architecture module passed (48 tests). Queue, job outcome, job
  contract, sync, runtime, Coach dialogue/recovery, and response-failure tests
  passed. Inventory check, compileall, and diff check passed.
- Measured `server.py`: 2,606 physical / 2,260 nonblank lines, 213 import
  statements, 153 top-level functions.
- Docker build was attempted again and remains blocked by the missing local
  Docker engine pipe. No live provider or application data was used.
- Remaining risk: image and SQLCipher integration checks need the application
  Docker runtime.

## S2b2 boundary before implementation: sync-job executor

- `sync_job_executor` is the only root constructor for the provider job
  dispatcher, and sync worker plus provider/diagnostic/sync tests invoke it
  directly. No fixture patches this factory. Tests patch `server.SyncJobExecutor`
  for execution result/failure scenarios; move that patch to
  `backend.sync.executor.SyncJobExecutor`, and resolve the class through that
  owner module. No e2e fixture references this factory.
- Preserve one `HistoricalSyncJobOwner` instance shared by the Intervals and
  Garmin owner groups; preserve the current active sync-state repository,
  queue/outcome services, provider observer, gates, and the weather/Garmin
  service owners. Executor construction remains uncached and occurs only when
  explicitly requested by the lazy worker factory or a test. Creating the
  assembly itself must only store callbacks and not touch the DB or providers.
- Proposed interface: `SyncJobExecutionAssembly` in
  `backend/sync/execution_assembly.py`, exposing only `executor()`. Its
  named inputs are the concrete factories for the historical, Intervals,
  Garmin, calendar/weather owners and queue outcomes plus the current window
  settings. The worker singleton and daily/startup schedulers remain for the
  following lifecycle slice.

## S2b2: sync-job executor assembly

- Completed in `backend/sync/execution_assembly.py` as
  `SyncJobExecutionAssembly.executor()`. It keeps executor creation uncached,
  constructs one shared `HistoricalSyncJobOwner` for the Intervals and Garmin
  owner groups, and resolves all provider, queue, outcome, and state factories
  only when an executor is requested. Worker singleton and scheduler
  construction remain for the next slice.
- Removed the root executor factory and migrated worker/test callers to
  `SYNC_JOB_EXECUTION.executor()`. Tests patch `SyncJobExecutor` through
  `backend.sync.executor`; service factory tests patch the server class names
  that the retained root factory functions actually look up. Added a focused
  regression that assembly construction does not invoke any supplied factory.
- Focused sync, provider, diagnostics, and architecture checks passed: 207
  tests, 1 SQLCipher skip, 79.369 seconds. Three dispatch regressions initially
  exposed tests patching factories after their callbacks had been captured;
  patches were moved to the constructors at the actual lookup sites, and the
  full focused rerun passed. Inventory check, compileall, and diff check passed.
- Measured `server.py`: 2,580 physical / 2,235 nonblank lines, 213 import
  statements, 152 top-level functions.
- Docker build was attempted; the local Docker engine pipe is still unavailable.
  No live provider or application data was used.
- Remaining risk: image and SQLCipher integration checks need the application
  Docker runtime.

## S2b3 boundary before implementation: sync worker construction

- `sync_job_worker` is called only from `main()` after database initialization
  and interrupted-job recovery. `server.SYNC_JOB_WORKER` is the sole
  restartable instance and one runtime test resets that root-owned cache. Keep
  that process-level owner and call timing in the root; move only constructor
  wiring. Tests patch `server.SyncJobWorker.start/stop/join`; move the class
  patches to `backend.sync.worker.SyncJobWorker`, where the assembly will
  resolve it.
- Worker construction must use the queue assembly's active store, the fresh
  execution assembly's executor, the shared maintenance gate, configured poll
  interval, and the same `shared_sync_job_wake_event()` owner used by queue and
  outcome services. Keep creation lazy until the root requests its cached
  worker; do not start its thread from assembly construction.
- Proposed interface: `SyncJobWorkerAssembly` in
  `backend/sync/worker_assembly.py`, exposing only `create()`. The root retains
  `SYNC_JOB_WORKER` and its small get-or-create operation so startup/shutdown
  ownership remains visible.

## S2b3: sync worker assembly

- Completed in `backend/sync/worker_assembly.py` as `SyncJobWorkerAssembly`
  with one `create()` operation. Worker construction now receives the queue
  store, executor, maintenance gate, poll interval, and shared wake-event
  provider explicitly. `server.py` retains only the process-level
  `SYNC_JOB_WORKER` cache and its get-or-create operation, so startup and
  shutdown ownership remain visible and the worker still starts only after
  storage initialization and interrupted-job recovery.
- Migrated lifecycle test patches from `server.SyncJobWorker` to
  `backend.sync.worker.SyncJobWorker`. The root's cached worker identity and
  direct test reset target remain unchanged.
- Focused checks passed: runtime plus startup ordering (14 tests) and
  architecture (48 tests). Inventory check, compileall, and diff check passed.
- Measured `server.py`: 2,585 physical / 2,238 nonblank lines, 215 import
  statements, 152 top-level functions.
- Docker build was attempted; the local Docker engine pipe remains unavailable.
  No live provider or application data was used.
- Remaining risk: image and SQLCipher integration checks need the application
  Docker runtime.

## S2b4 boundary before implementation: daily and startup schedulers

- `daily_sync_loop_service`, `daily_sync_scheduler`, and
  `startup_sync_scheduler` are the remaining sync-scheduling factories. The
  daily loop constructs a fresh daily scheduler, morning battery service, and
  stop event; the daily scheduler is also called directly by the audit test.
  `main()` constructs the startup scheduler, schedules it after workers start,
  creates the daily loop, and then starts its thread. No e2e fixture references
  these factories.
- Preserve late config reads at each scheduler construction, the active
  manager, profile, queue and marker services, Garmin sync service, sync-state
  repository, DB lock, provider gate, and maintenance gate. Tests patch the
  root marker factory and the startup/loop factory names in `main()`; move the
  marker patch to its constructor lookup and the lifecycle patches to the
  scheduler assembly methods. Keep `main()`'s startup and shutdown order in the
  root.
- Proposed interface: `SyncSchedulerAssembly` in
  `backend/sync/scheduler_assembly.py`, exposing only `daily_scheduler()`,
  `startup_scheduler()`, and `daily_loop()`. It stores the explicit domain
  factories and a late config provider; construction starts no loop or worker.

## S2b4: scheduler assembly

- Completed in `backend/sync/scheduler_assembly.py` as `SyncSchedulerAssembly`
  with the planned three operations. Scheduler construction reads current
  config on each request; all existing scheduler dependencies remain explicit.
  The assembly starts no worker or thread. `main()` retains startup ordering,
  starts the daily loop thread, and owns shutdown.
- Moved the audit test's marker-constructor patch to `DailySyncMarkerService`
  and lifecycle factory patches to `SYNC_SCHEDULERS`. Added no global lookup,
  locator, or compatibility wrapper.
- Focused sync, architecture, and audit checks passed: 145 tests, 1
  SQLCipher-dependent skip. Inventory check, compileall, and diff check passed.
- Measured `server.py`: 2,552 physical / 2,209 nonblank lines, 216 AST import
  statements, 149 top-level functions.
- Docker build was attempted but the local Docker engine pipe is unavailable.
  No live provider or application data was used.
- Remaining risk: image and SQLCipher integration checks need the application
  Docker runtime.

## S2c boundary before implementation: synchronization persistence factories

- `sync_state_repository()` and `daily_sync_marker_service()` each construct a
  fresh repository/service per call. Their manager dependency must remain late
  through `database_manager()` so manager replacement is respected; both retain
  the process-shared key/value repository, with sync state also retaining the
  shared snapshot repository and UTC clock, and daily markers retaining the
  athlete-local clock callback. Do not cache either returned object.
- The methods feed Intervals and Garmin services, provider refresh and queue
  services, weather/calendar workflows, public state, Coach context, HTTP, and
  temporary-database tests. Test helpers and ten test modules call the root
  factories directly; migrate those calls to the assembly methods rather than
  retaining forwarding functions. No e2e fixture references these factories.
- Direct constructor patch targets are `tests/test_server_weather_calendar.py`
  for `server.DailySyncMarkerService` and `server.SyncStateRepository`; move
  each patch to `backend.sync.daily.DailySyncMarkerService` and
  `backend.sync.state.SyncStateRepository`, respectively. No test depends on
  repository object identity across calls; durable state identity is carried by
  the shared manager/repositories and database.
- Proposed owner/interface: `SyncPersistenceAssembly` in
  `backend/sync/persistence_assembly.py`, exposing only
  `state_repository()` and `daily_markers()`. Construction is inert and stores
  explicit late manager and clock dependencies.

## S2c: sync persistence assembly

- Completed in `backend/sync/persistence_assembly.py` as
  `SyncPersistenceAssembly.state_repository()` and `.daily_markers()`. Both
  return fresh objects and resolve the current database manager on every call;
  shared key/value and snapshot repositories remain the same instances.
- Preserved late athlete-clock lookup for daily markers. The first broad run
  exposed a patch-target timing regression when the clock method was captured
  during root assembly. The assembly now resolves the clock owner when creating
  each marker service, and the regression plus the full focused rerun passed.
- Migrated server, test-helper, and ten test-module callers to the explicit
  assembly methods. Constructor patches now target their backend owners. Added a
  focused composition test for inert assembly construction and current-manager
  lookup.
- Focused sync, weather/calendar, HTTP, Coach, provider, performance, database,
  diagnostic, Coach-tool, architecture, and assembly checks passed: 428 tests,
  4 SQLCipher-dependent skips. Inventory check, compileall, and diff check
  passed.
- Measured `server.py`: 2,546 physical / 2,205 nonblank lines, 215 AST import
  statements, 147 top-level functions.
- No live provider or application data was used. Remaining environment risk is
  SQLCipher/container-only validation, since the Docker engine is unavailable.

## S2d boundary before implementation: Intervals refresh and sync pipeline

- The cohesive group is `performance_refresh_service`,
  `intervals_snapshot_reader`, `performance_refresh_followup_service`,
  `intervals_snapshot_service`, and `intervals_sync_service`. Callers include
  manual refresh and conflict commands, the sync-job execution assembly,
  provider refresh, Coach/planning, HTTP/public context, and direct tests in the
  Coach review, provider review, performance, sync, planning, weather/calendar,
  and workout-repair modules. No e2e fixture directly names these factories.
- Preserve fresh-per-call service objects; late CONFIG and database-manager
  reads; fresh state-repository, marker, observer, and provider-client lookups;
  the shared event buffer, provider gate, and `INTERVALS_SYNC_LOCK`; the current
  provider transport; the athlete clock lookup at service creation; the same
  queue service for follow-up work; and exact work-window constants. Snapshot
  persistence continues to use the existing reconciliation and library service
  factories. `full_provider_resync_service()` remains in the root for its next
  cross-provider boundary and delegates to the new Intervals sync method.
- The only direct root-constructor test patches are two
  `server.PerformanceRefreshService` patches in `tests/test_server_sync.py`;
  move them to the constructor lookup in
  `backend.sync.intervals_assembly.PerformanceRefreshService`. Other
  constructor patches already target the owning backend classes. Update all
  direct root-factory callers to the assembly rather than retaining forwarding
  names. Tests use temporary managers and mocked provider requests.
- Proposed owner/interface: `IntervalsSyncAssembly` in
  `backend/sync/intervals_assembly.py`, exposing only
  `performance_service()`, `snapshot_reader()`, `performance_followup()`,
  `snapshot_service()`, and `sync_service()`. It stores explicit callbacks for
  cross-domain providers, reads CONFIG and the active manager on each method,
  and starts no I/O during construction. `SyncJobExecutionAssembly` receives
  `INTERVALS_SYNC.performance_service` and `.sync_service` directly.

## S2d: Intervals sync assembly

- Completed in `backend/sync/intervals_assembly.py` as `IntervalsSyncAssembly`
  with five domain operations. The root no longer defines per-service
  Intervals refresh and sync factories. `SyncJobExecutionAssembly` receives
  the performance and sync methods directly; full-provider resync remains
  separate because it crosses Garmin and competition ownership.
- Preserved fresh service creation, late CONFIG/manager/provider/clock lookup,
  shared sync lock, event buffer, provider gate, queue service, repositories,
  and sync-window settings. The assembly constructor resolves no callback or
  provider I/O.
- Migrated direct callers and constructor patches to the actual assembly
  lookup. Focused sync, performance, weather/calendar, planning, Coach review,
  workout repair, architecture, and assembly checks passed: 342 tests.
  Inventory check, compileall, and diff check passed.
- Measured `server.py`: 2,461 physical / 2,128 nonblank lines, 214 AST import
  statements, 142 top-level functions.
- Tests used isolated temporary managers and mocked provider requests. No
  live provider or application data was used. Docker/SQLCipher integration
  remains unavailable on this host.

## S2e boundary before implementation: external-calendar synchronization

- `external_calendar_reader()` and `external_calendar_sync_service()` are
  external-calendar sync composition owned by `backend/sync/external_calendar.py`.
  Reader consumers include planning conflict/adaptive context, Coach, HTTP,
  diagnostics, backup/exports, and tests; the sync service also feeds the sync
  executor and startup/public-calendar projections. Test callers are in
  provider and weather/calendar tests. No e2e fixture references either
  factory. The calendar sync regression patches the still-root-owned adaptive
  preview factory, so keep that explicit callback late-bound at service
  creation.
- Preserve fresh readers/services, active manager lookup, shared key/value
  repository, shared daily-marker factory, observer and state-event buffer,
  redactor/logger, adaptive-preview callback, release version, and the singleton
  `EXTERNAL_CALENDAR_SYNC_LOCK`. Resolve CONFIG and `ATHLETE_CLOCK.now` when
  constructing each sync service, and preserve the reader's local-date callback.
- Proposed owner/interface: `ExternalCalendarAssembly` in
  `backend/sync/external_calendar_assembly.py`, exposing only `reader()` and
  `sync_service()`. It stores explicit callbacks and resolves manager/config/
  clock state only when a method is requested; construction performs no I/O.

## S2e: external-calendar assembly

- Completed in `backend/sync/external_calendar_assembly.py` as
  `ExternalCalendarAssembly.reader()` and `.sync_service()`. The two root
  factories were removed and all server and test callers use the assembly.
- Preserved late manager, CONFIG, date, and athlete-clock lookup, the shared
  marker/observer/event dependencies, the still-root-owned adaptive-preview
  callback, release version, and singleton calendar lock. Construction remains
  inert. Added an assembly regression for lazy dependency resolution.
- The first focused pass found that the adaptive-preview factory callback was
  captured too early, breaking the existing test patch. It is now late-bound at
  service creation. The inventory also needed an explicit composition-root owner
  for the new `EXTERNAL_CALENDAR` instance; that mapping is accurate and the
  inventory architecture check passes.
- Provider, weather/calendar, sync external-calendar, executor, Coach context,
  architecture, and assembly checks passed: 168 tests. Inventory check,
  compileall, and diff check passed.
- Measured `server.py`: 2,450 physical / 2,119 nonblank lines, 214 AST import
  statements, 140 top-level functions.
- Tests used temporary data and mocked providers only. Docker/SQLCipher
  integration remains unavailable on this host.

## S2f boundary before implementation: competition and full-provider resync

- `competition_sync_reconciler()`, `competition_sync_service()`, and
  `full_provider_resync_service()` form one provider-resync group. The
  competition sync service is also an executor operation; full resync composes
  fresh Intervals, Garmin, and competition services with one observer, state
  store, and operation journal. Callers include manual sync commands, queued
  execution, public/Coach sync state, and provider, audit-remediation, sync,
  planning, and Coach tests. No e2e fixture names these root factories.
- Preserve fresh-per-call services, current CONFIG/database manager, key/value
  repo and event buffer, provider transport callback, redactor/logger/UTC clock,
  fresh operation observer, shared Intervals/Garmin gates, all-days setting,
  operation journal ID/time sources, and the same Intervals/Garmin service
  owners. Local `competition_service()` stays in planning ownership and is
  passed as a callback. No process cache is introduced.
- The direct constructor patch in `tests/test_server_sync.py` targets
  `server.CompetitionSyncService` for executor dispatch; move it to the class
  lookup in the new assembly. Existing tests otherwise call the root factories
  directly; migrate those calls to the assembly. No test patches the full-resync
  classes.
- Proposed owner/interface: `ProviderResyncAssembly` in
  `backend/sync/provider_resync_assembly.py`, exposing only
  `competition_reconciler()`, `competition_sync_service()`, and
  `full_resync_service()`. It stores late config/manager/service providers and
  starts no provider I/O during construction.

## S2f: competition and full-provider resync assembly

- Completed in `backend/sync/provider_resync_assembly.py` as
  `ProviderResyncAssembly`, exposing only competition reconciliation,
  competition synchronization, and full-provider resync construction. Removed
  the three root factories and migrated server, test, and executor lookup sites.
- Preserved fresh use cases, the current config and database manager, shared
  key/value repository and event buffer, current transport callback, the same
  Intervals/Garmin service owners and gates, the operation observer, journal
  clocks/IDs, and all-days setting. Transport lookup remains late so tests and
  runtime transport replacement observe the current method.
- Updated bootstrap to use the assembly directly and moved the daily-marker
  constructor patch to `backend.sync.scheduler_assembly`. Added a callback
  laziness regression. Focused assembly/domain tests passed: 44 tests. The wider
  focused run found these two stale references; their isolated rerun passed: 2
  tests. The daily competition case also passed under an external network-deny
  guard. Inventory check, compileall, and diff check passed.
- The first unguarded integration attempt revealed a provider callback patch
  point regression and reached `intervals.icu`; it was interrupted. The callback
  now resolves the current transport, and all later server integration checks
  were run with external networking blocked and loopback allowed. No provider
  credentials or real application data were used.
- Measured `server.py`: 2,419 physical / 2,092 nonblank lines, 214 AST import
  statements, 137 top-level functions. Docker/SQLCipher integration remains
  unavailable on this host.

## S2g boundary before implementation: planned-calendar sync and repair

- `planned_calendar_sync_service()` and
  `planned_calendar_repair_service()` form the planned-calendar push/repair
  boundary. The only production factory consumer is
  `selected_workout_sync_service()`; direct service callers are in
  `tests/test_server_weather_calendar.py` and `tests/test_workout_repair.py`.
  Domain behavior tests construct the services directly in
  `tests/test_sync_planned_calendar.py`. No e2e fixture references these root
  factories, and no test directly patches either constructor.
- Preserve fresh service/writer creation; active CONFIG and database manager;
  the shared planning revision service and redactor; current provider transport
  lookup; UTC clock; late athlete-local date; and configured future repair
  window. Keep the existing per-unit synchronization guard owned by
  `backend/sync/planned_calendar.py`. The selected-workout factory continues to
  receive the library-sync service from its existing owner.
- Proposed owner/interface: `PlannedCalendarSyncAssembly` in
  `backend/sync/planned_calendar_assembly.py`, exposing only
  `sync_service()` and `repair_service()`. It will accept explicit providers for
  config, manager, transport, state writer, UTC time, and athlete date, plus the
  future-day setting. The provider-client callback must resolve the active
  transport method when invoked, preserving current test patch and lazy provider
  lookup behavior.

## S2g: planned-calendar sync and repair assembly

- Completed in `backend/sync/planned_calendar_assembly.py` as
  `PlannedCalendarSyncAssembly`, exposing only `sync_service()` and
  `repair_service()`. Removed both root factories; selected-workout sync now
  composes these operations from the assembly. Migrated direct server test
  callers and removed the old architecture allowlist entries.
- Preserved fresh services and sync-state writers, active config/database
  manager/provider transport, the shared planned-unit revision service and
  redactor through the existing writer, UTC clock, late athlete-local date,
  repair future-day setting, and the per-unit guard owned by the service module.
  Provider transport lookup stays deferred until the sync use case asks for a
  client.
- Added lazy-dependency and fresh-writer assembly tests. Planned-calendar and
  selected-sync unit tests passed: 39 tests. The affected guarded integration
  run exposed four stale test patches to the removed `server.calendar_external`
  name; moved them to `backend.calendar.external` and reran all workout-repair
  tests: 27 passed. The other affected server sync, weather/calendar, and
  architecture tests passed in that guarded run. Inventory check, compileall,
  and diff check passed.
- Measured `server.py`: 2,400 physical / 2,077 nonblank lines, 214 AST import
  statements, 135 top-level functions. No Docker or SQLCipher dependency change.

## S2h boundary before implementation: workout-library provider sync

- `workout_library_sync_state_service()`,
  `workout_library_remote_reconciler()`, `workout_library_refresh_service()`,
  and `workout_library_sync_service()` form the provider-facing workout-library
  sync group. Consumers include Intervals snapshot sync, selected-workout sync,
  planning authority, public state and diagnostics, plus provider, planning,
  Coach, database, HTTP, and sync tests. No e2e fixture or `tests/support.py`
  patches these root factories. No tests patch their constructors through
  `server`; class patches already target `backend.sync.library`.
- Preserve fresh services, current CONFIG/database manager and Intervals
  transport callback; fresh local remote reconciler and state service per old
  factory call; shared key/value repository and state-event buffer; the local
  `workout_library_service()` owner; redactor; UTC clock; and UUID source. The
  process-wide `workout_library_sync_running()` state remains owned by
  `backend/sync/library.py`. `planning_authority_service()` keeps its existing
  call path through the sync-state operation.
- Proposed owner/interface: `WorkoutLibrarySyncAssembly` in
  `backend/sync/library_assembly.py`, exposing only `sync_state_service()`,
  `remote_reconciler()`, `refresh_service()`, and `sync_service()`. It receives
  explicit providers for config, manager, transport, local library service,
  key/value repository, event buffer, redactor, UTC clock, and UUID generation.
  Provider-client resolution remains deferred until the operation requests a
  client; no cache or process state is added.

## S2h: workout-library provider sync assembly

- Completed in `backend/sync/library_assembly.py` as
  `WorkoutLibrarySyncAssembly`, exposing sync-state service, remote reconciler,
  read-only refresh service, and explicit sync service factories. Removed all
  four root factories and migrated Intervals sync, planning authority, selected
  sync, public state, diagnostics, and tests to the assembly. Local
  `workout_library_service()` remains owned by planning.
- Preserved fresh services and state services, active config/database manager and
  provider transport, the same repository/event buffer/redactor/local library
  owner/UTC clock/UUID source, and the shared library sync lock owned by
  `backend/sync/library.py`. Intervals snapshot sync retains lazy lookup of the
  assembly through its existing callback.
- Assembly and sync-domain tests passed: 61 tests. The first guarded integration
  pass found a stale bootstrap callback left after the root factory removal; it
  now points to the assembly operation. The complete affected guarded matrix then
  passed: 467 tests, 4 SQLCipher-dependent skips. Inventory check, compileall,
  diff check, and root factory reference search passed.
- Measured `server.py`: 2,372 physical / 2,057 nonblank lines, 215 AST import
  statements, 131 top-level functions.

## S2i boundary before implementation: planned-unit sync reconciliation

- `planned_unit_sync_state_writer()` and
  `remote_planned_unit_reconciler()` form one planned-unit sync persistence
  boundary. The writer is used by planned-calendar sync/repair; the reconciler
  is the lazy callback used by Intervals snapshot sync. Direct test callers are
  in planning, weather/calendar, and workout-repair tests. No e2e fixture
  references these factories, and constructor patches target the owning backend
  classes directly.
- Preserve a fresh writer and reconciler per call; the singleton planning
  revision service; redactor; current manager and planned-unit service; UTC
  clock; and athlete-local date callback. Intervals sync currently constructs
  the reconciler only when needed through its callback, so its assembly input
  must remain a deferred `PLANNED_UNIT_SYNC.remote_reconciler` lookup.
- Proposed owner/interface: `PlannedUnitSyncAssembly` in
  `backend/sync/planned_unit_assembly.py`, exposing only `state_writer()` and
  `remote_reconciler()`. It receives explicit revision/redactor and manager/
  planned-unit-service/clock/date dependencies and introduces no cache or I/O.

## S2i: planned-unit sync persistence and reconciliation assembly

- Completed in `backend/sync/planned_unit_assembly.py` as
  `PlannedUnitSyncAssembly`, exposing only `state_writer()` and
  `remote_reconciler()`. Removed both root factories, migrated direct server
  test callers, and updated the Intervals sync assembly input.
- Preserved the shared planning revision service and redactor; fresh state
  writers/reconcilers; current database manager and planned-unit service; UTC
  clock; and athlete-local date. Intervals sync resolves the reconciliation
  operation lazily on demand. No storage or provider I/O was added.
- Focused planned-unit, planned-calendar, and writer domain tests passed: 48
  tests. The affected guarded server planning, weather/calendar, sync, repair,
  and architecture matrix passed: 287 tests. Inventory check, compileall, diff
  check, and old-factory reference search passed.
- Measured `server.py`: 2,363 physical / 2,052 nonblank lines, 214 AST import
  statements, 129 top-level functions.

## S2j boundary before implementation: selected workout synchronization

- `selected_workout_sync_service()` composes the one selected-workout use case
  across the workout-library, planned-calendar, and library-repair owners. It is
  consumed lazily by `SyncJobExecutionAssembly`; direct callers are sync and
  workout-repair tests. No e2e fixture references the root factory, and class
  patches target `backend.sync.selected.SelectedWorkoutSyncService` directly.
- Preserve a fresh use case, current CONFIG/database manager, current library
  sync service, fresh planned-calendar sync and repair services, redactor,
  singleton `INTERVALS_SYNC_LOCK`, repair wait duration, and shared provider
  resync gate. All subordinate service callbacks remain lazy until the selected
  use case is requested.
- Proposed owner/interface: `SelectedWorkoutSyncAssembly` in
  `backend/sync/selected_assembly.py`, exposing only `service()`. It accepts
  explicit config/manager and subordinate service providers plus redactor, the
  shared lock, wait duration, and gate.
- `sync_job_worker()` still protects a single unstarted worker instance used by
  `main()`; `tests/test_server_runtime.py` patches the root cache to isolate its
  startup test. Keep this lifecycle resource and its root cache for the worker
  slice/S6 review unless an explicit owner can preserve that same instance and
  the current test seam.

## S2j: selected-workout synchronization assembly

- Completed in `backend/sync/selected_assembly.py` as
  `SelectedWorkoutSyncAssembly.service()`. Removed the root factory and
  migrated the sync executor and direct test callers.
- Preserved fresh use-case construction, current config/database manager, lazy
  subordinate library/calendar services, redactor, singleton Intervals lock,
  repair wait duration, and provider-resync gate.
- Selected assembly and executor tests passed: 25 tests. The guarded server
  sync, workout-repair, and architecture checks passed: 155 tests. Inventory
  check, compileall, diff check, and factory reference search passed.
- S2 provider/sync factories are now owned by the sync/provider assemblies.
  `sync_job_worker()` and its root singleton remain as an explicit lazy lifecycle
  resource used by `main()`; S6 will review this retained process identity.
- Measured `server.py`: 2,359 physical / 2,050 nonblank lines, 214 AST import
  statements, 128 top-level functions.

## S3 boundary before implementation: athlete and planning persistence

- Current root factories are traced from `server.py` and the S0 AST map. The
  athlete-owned group is activity feedback/read/duplicate, check-ins, and
  profile. The planning-owned group is competitions, training-plan metadata,
  planned-unit persistence, workout-library persistence, and adaptive preview
  application. Cross-domain callers include Coach, HTTP/public state, sync,
  history undo, privacy export, and test setup. `tests/support.py` and
  `tests/server_test_support.py` directly call profile service; many tests
  directly call all persistence factories. No `e2e/fixture_runtime.py` factory
  patch was found for this group. Constructor patch targets are inspected per
  factory before caller migration.
- Preserve the active manager per call; existing repositories, revision
  service, event buffer, clock and UUID identities; fresh service wrappers;
  athlete-local date as a late callback; and local-only library/planned-unit
  writes. Preview apply continues through its existing domain service and does
  not bypass the explicit approval path. Keep transactional behavior inside
  the existing service classes. The athlete clock retains its single eager
  profile-service identity for clock configuration; service factory calls
  remain fresh and manager-aware.
- Proposed narrow owners: `AthleteDataAssembly` in `backend/athlete/assembly.py`
  for activity, check-in, and profile services; `PlanningDataAssembly` in
  `backend/planning/assembly.py` for competition, training-plan, planned-unit, workout
  library, and adaptive-apply services. Each stores explicit late manager,
  date, clock/event, conflict-reader and revision dependencies. No assembly
  performs storage/provider I/O in its constructor. Privacy and backup remain a
  separately traced S3 slice because restore additionally owns maintenance,
  worker cancellation, queue generation reset and database-manager rebinding.

## S3a: athlete and local planning persistence assemblies

- Completed `AthleteDataAssembly` for activity feedback/read/duplicate,
  check-in, and profile service creation; `PlanningDataAssembly` owns
  competition service creation alongside its planning repository. The athlete clock still
  receives one eagerly bound profile service over the same manager-cache owner;
  ordinary services still resolve the active manager per factory call.
- Completed `PlanningDataAssembly` for training-plan metadata, planned-unit,
  workout-library, and approved adaptive-preview application services. Shared
  revision, repository, event, clock, redaction, local-date, UUID, and calendar
  conflict dependencies are explicit. Conflict lookup stays lazy until a
  planned-unit service is requested. Existing use cases retain transaction,
  revision/hash validation, preview approval, and local-only write behavior.
- Removed ten root factories and updated Coach, HTTP, public state, sync,
  history, support fixtures, and direct test lookups to call the assemblies.
  Updated route-boundary expectations, added assembly identity/laziness tests,
  and assigned the two assembly globals in the generated inventory owner map.
- Focused checks: architecture + assembly (50 passed); athlete/planning/database
  server checks (186 passed, 3 SQLCipher skips). Compileall, generated inventory
  `--check`, and diff check passed. Docker remains unavailable on this host.
- Changed files include `server.py`, new
  `backend/athlete/assembly.py` and `backend/planning/assembly.py`, inventory
  generator/output, architecture tests, new
  `tests/test_athlete_planning_assemblies.py`, and direct service callers in
  support, Coach, athlete, database, HTTP, planning, provider, sync, weather,
  and repair tests.
- Measured `server.py`: 2,271 physical / 1,991 nonblank lines, 210 AST imports,
  118 top-level functions. Risk remaining for S3 is the separately traced
  privacy/backup/restore assembly and its SQLCipher integration check.

## S3b boundary before implementation: privacy and backup/restore

- The remaining `privacy_data_export_service()`, `privacy_delete_service()`,
  `privacy_archive_export_service()`, `database_backup_service()`,
  `database_restore_validation_service()`, and `database_restore_service()`
  callers are the Coach attachment export, privacy GET/DELETE/restore HTTP
  routes, export stream transport, and audit/database/provider review tests.
  No fixture references or tests patch these root factory names or their
  constructors. Tests directly call the root factories and one architecture
  assertion checks the old archive factory body; all will move to owner
  assembly methods.
- Preserve fresh service wrappers; current manager/path/config at each
  operation; the same `DB_LOCK`, key-value and planning revision owners,
  maintenance gate, sync queue, sync wake event, and Coach worker wake event.
  `PrivacyDataExportService` keeps its bounded projection and exact exclusion
  rules. Backup continues holding the shared DB lock through streaming. Restore
  validation remains staged and exact-schema/SQLCipher guarded; restore keeps
  maintenance, generation reset, interrupted Coach job recovery, worker
  cancellation/restart, and current manager rebinding. The route continues to
  defer restore service construction until request execution.
- Proposed interfaces: `PrivacyAssembly` in `backend/privacy.py` exposes only
  `data_export_service()`, `delete_service()`, and `archive_export_service()`;
  `BackupAssembly` in `backend/backup/assembly.py` exposes only
  `backup_service()`, `restore_validation_service()`, and
  `restore_service()`. Both receive named, explicit late callbacks for active
  manager and subordinate services; their constructors perform no storage,
  file, worker, or provider operations. `export_stream_transport()` stays in
  the HTTP/root boundary until S5 because it is an HTTP download adapter.

## S3b: privacy and backup/restore assemblies

- Completed `PrivacyAssembly` in `backend/privacy.py` and `BackupAssembly` in
  `backend/backup/assembly.py`. Removed six root factories; Coach attachment
  export, HTTP privacy routes, export streaming, fixtures/tests now call the
  owning assembly directly. The export stream adapter remains at the root for
  S5.
- Preserved fresh use cases and active manager/path/config resolution. Database
  lock and maintenance gate are late-resolved so temporary fixture patches
  participate in the same coordination as worker decorators. Privacy exports
  retain existing projections and limits. Restore retains the exact shared
  queue, sync wake event, Coach worker wake event, maintenance gate, and the
  validation, generation reset, cancellation, recovery, and manager-drain
  behavior. Added direct identity/laziness regressions.
- Focused guarded checks passed: privacy/backup assembly and architecture
  (54 passed); database, audit, provider review, privacy export, HTTP export,
  privacy GET/DELETE/restore and confirmation checks (95 passed, 5 SQLCipher
  skips). Compile/inventory/diff checks pass. The earlier first pass exposed a
  real late-binding defect (patched maintenance gate and athlete clock); both
  dependencies now resolve at service creation, and the focused regressions
  pass. Docker/SQLCipher execution is still unavailable.
- Changed files: `server.py`, `backend/privacy.py`, new
  `backend/backup/assembly.py` and `tests/test_privacy_backup_assemblies.py`,
  progress/inventory owner map, and direct Coach attachment, database, privacy,
  provider, route and architecture test callers.
- Measured `server.py`: 2,210 physical / 1,930 nonblank lines, 207 AST imports,
  112 top-level functions. S3 still has no dedicated privacy or backup factory
  chain in the root; Coach and HTTP slices remain.
