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
