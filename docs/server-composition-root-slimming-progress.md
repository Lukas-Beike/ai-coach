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
