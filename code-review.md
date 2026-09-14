# Code structure review and server.py extraction plan

## Review scope

Reviewed local `develop` at `0a1dd00` (`chore(release): set application version to 1.11.0 (#622)`), on 2026-09-13. The review artifact lives on `docs/code-structure-review-20260913` in the dedicated `ai-coach-structure-review` worktree. The primary checkout had no tracked changes and an untracked `.worktrees/` directory; other worktrees were not reviewed or changed. This is a review of the recorded snapshot, not a claim about the latest remote branch.

The requested focus is **code structure, separation of concerns, and executable refactoring tasks**. Findings below are verified maintainability problems, not newly introduced PR regressions or claims of production corruption. No application fixes are implemented. Root, frontend, and test `AGENTS.md` instructions and the ai-coach-codebase-review checklist/report references were applied. The requested file creation is the sole source-tree edit.

Excluded: real `.env` files, athlete data, live databases, backups, Garmin tokens, authenticated browser state, production logs, connected provider accounts, and unrelated untracked files. Static inventory covers the tracked repository; detailed reading concentrates on backend boundaries and their test, frontend, and deployment consumers. The broader skill's exhaustive runtime audit is **not completed**; limitations are listed explicitly below.

## Findings

All findings are **P3, maintainability**, with high confidence in the cited structural evidence. No P0/P1/P2 production defect is asserted by this architecture review. File size alone is not a defect; the actionable issues are dependency direction, ownership, and the work required to change or test one responsibility.

### F1 — Make configuration loading explicit before extracting reusable code

**Evidence:** `server.py:495` reads both local and persistent settings; `server.py:506` calls it during import. `Config` field defaults read environment variables during class definition (`server.py:524`), and `CONFIG` is constructed at `server.py:551`. `IntervalsClient.__init__` captures that object in a default argument at `server.py:9047`. The test bootstrap intercepts `Path.read_text` before importing the server (`tests/test_server.py:41`).

**Trigger:** Import a parser, client, or service through `server` for a focused test or another entrypoint; alternatively, change the environment or replace `server.CONFIG` after import and construct `IntervalsClient()` without an explicit argument.

**Impact:** Importing business code also reads settings and changes process environment. Configuration defaults remain bound to import-time values; replacing the global configuration does not replace the constructor's captured default. Safe test setup consequently depends on ordering and application-wide patches. This does not establish a current credential leak.

**Concrete tasks:**

- [ ] **T1.1** Move `Config`, environment parsing, and settings persistence into `backend/config.py`. Use explicit `load_config(...)`; evaluate environment values when loading, not as dataclass field defaults.
- [ ] **T1.2** Call settings loading once from the entrypoint. Preserve process-environment precedence and the supported `/data/.env` settings behavior.
- [ ] **T1.3** Require explicit configuration in provider constructors. Pass only relevant settings where practical; never serialize or log the configuration object.
- [ ] **T1.4** Pass the original repository/public/data paths explicitly. Moving `__file__`-based root calculations into a nested package must not relocate `.env`, static assets, or the database.

**Acceptance check:** Import extracted domain/provider modules with filesystem and network access denied. Load two synthetic configurations in the same process and verify that clients use the supplied instance. Existing secure-startup tests must still reject missing/short passwords and unavailable SQLCipher.

### F2 — Give persistence and transaction scope one owner

**Evidence:** `backend/db/manager.py:80` already supplies a nested unit of work. `server.py:1156` and `server.py:1381` add a second connection `ContextVar`/reuse wrapper, while `server.py:1354` owns manager construction and replacement. Schema creation remains at `server.py:1394`; the current-schema manifest and restore validation remain at `server.py:21583` and `server.py:21640`. AST inspection finds **325 SQL execution call sites in server.py**. Existing repositories accept a caller-owned connection, but many domain writes bypass them.

The nesting is real: `_apply_training_patch` opens a transaction at `server.py:18824`, calls `_apply_structured_training_changes` at `server.py:18829`, and then creates new workouts at `server.py:18831`. The inner function opens `database()` again at `server.py:17548`.

**Trigger:** Extract plan edits, repositories, or backup handling independently and replace an inner `database()` call with a newly owned connection/transaction.

**Impact:** A seemingly mechanical extraction can split an operation that currently commits or rolls back together. Correctness depends on ambient connection reuse and an outer `DB_LOCK`, rather than on an explicit service transaction boundary. This is a demonstrated extraction hazard, not a claim that current nested commits are broken.

**Concrete tasks:**

- [ ] **T2.1** Move schema DDL, exact current-schema validation, cipher configuration, and database construction to `backend/db/schema.py` and the existing database package.
- [ ] **T2.2** Make `DatabaseManager.unit_of_work()` the sole transaction-context owner. Remove the duplicate server context only after equivalent nested-operation behavior is verified.
- [ ] **T2.3** Move SQL with its domain operation. Keep repository functions/methods connection-taking; they must not independently commit or acquire an unrelated connection.
- [ ] **T2.4** Make planning service entrypoints own the transaction for revision/hash validation, all row changes, plan bounds, and audit records. Internal helpers receive that connection.
- [ ] **T2.5** Preserve the existing lock order and restore drain while moving code. Review state-event publication relative to the outer commit; an inner helper returning does not imply that the transaction has committed.

**Acceptance check:** Inject failure after an existing workout is changed but before a new workout or its constraints are saved. Assert all related rows and the planning revision roll back. Preserve stale-revision/hash rejection, cross-plan authorization, same-build restart, and restore-drain coverage. Do not introduce migrations or a plaintext production fallback.

### F3 — Finish provider extraction at a usable client boundary

**Evidence:** `backend/providers/intervals.py:17` and `:47` contain transport classes, but the actual 299-line `IntervalsClient` remains at `server.py:9046`. Its transport callbacks resolve `server.http_json` (`server.py:9055`, `:9060`); writes use application-owned `intervals_operation` decorators (`server.py:9093`). Shared HTTP/error handling is at `server.py:7519` through `:8079`, and OpenAI/Gemini adapters are embedded in the server around `:15119` through `:16184`.

**Trigger:** Change or test a complete provider request, retry, streaming, or pagination path.

**Impact:** Importing the named provider module does not provide the complete client. Request construction, safe error handling, application gates, persistence, and coaching lifecycle still meet in `server.py`. Existing small modules reduce local complexity but do not isolate provider integration changes.

**Concrete tasks:**

- [ ] **T3.1** Move `IntervalsClient` into the existing Intervals module. Keep read and write operations visibly distinct and accept an explicit request function/configuration.
- [ ] **T3.2** Move bounded HTTP transport and redacted provider error conversion to `backend/providers/http.py`. Preserve cancellation, timeout/size limits, and existing error/retry semantics.
- [ ] **T3.3** Keep maintenance/resync gates, snapshot persistence, reconciliation, and durable job state in sync/application services. Inventory every current decorated client caller before moving a gate so no direct path loses protection.
- [ ] **T3.4** Move OpenAI and Gemini wire encoding/parsing into separate provider modules. Keep Coach command ownership, durable history, receipts, and tool rounds in `backend/coach/`.
- [ ] **T3.5** Preserve the special calendar DNS/address/redirect security path. Do not replace it with generic URL fetching during transport consolidation.

**Acceptance check:** Existing mocked provider tests exercise the extracted clients directly. Cover cancellation, malformed/oversized responses, pagination, partial success, and redacted errors; the service tests continue to prove that local workout creation makes no remote writes. Preserve existing token budgets and model policy; this task proposes no provider API changes.

### F4 — Put the Coach tool contract next to its execution policy

**Evidence:** Tool schemas are constructed at `server.py:16859`, the read-only set is at `server.py:17001`, dialogue schema transformation is at `server.py:17008`, dispatch is at `server.py:18520`, request/scope checks are around `server.py:18631`, and execution/receipt handling is around `server.py:19628`. `backend/coach/dialogue.py:233` transforms schemas but does not own this full contract. The public `apply_training_patch` schema is assembled from pieces of other schemas at `server.py:17012`.

**Trigger:** Add or modify a Coach operation, its required arguments, authorization scope, or read/write classification.

**Impact:** A coherent change requires coordinating several distant structures and the dialogue module. Schema presence alone does not demonstrate a valid, authorized dispatcher path. The reviewed evidence does **not** establish an already mismatched tool or authorization bypass; the finding is fragmented ownership of a security-sensitive contract.

**Concrete tasks:**

- [ ] **T4.1** Move the active schemas and shared argument fragments into `backend/coach/tools.py`, alongside the read/write classification and dispatch wiring.
- [ ] **T4.2** Move provenance, target/scope checks, and approval rules into `backend/coach/authorization.py`; the executor must call them before dispatch.
- [ ] **T4.3** Move turn/tool-round orchestration and receipts into `backend/coach/service.py`; use the existing `dialogue.py`, `context.py`, `attachments.py`, and `outcomes.py` directly.
- [ ] **T4.4** Use one explicit tool inventory and a small dispatch map where it removes repeated lists. Keep domain-specific guards explicit; do not build a plugin framework or treat a schema's `read_only` flag as sufficient authorization.
- [ ] **T4.5** Move planning SQL and application operations to planning services. Coach adapters should translate validated tool arguments into those operations rather than implement a second planner.

**Acceptance check:** Compare active schema names and dispatch coverage, and exercise each mutating tool with allowed and denied scope. Preserve user-message provenance, contextual follow-ups, duplicate-call replay, partial-failure receipts, explicit remote sync, and adaptive preview/apply. Do not add trigger words, keyword routing, or a generic confirmation step for ordinary authorized local actions.

### F5 — Separate reusable fixtures from the monolithic test module

**Evidence:** `tests/test_server.py` has **8,801 lines**, imports the application while rewriting synthetic environment settings, and owns the shared database setup. `tests/test_coach_dialogue.py:15` imports it as a fixture module and invokes `fixtures.CoachTests.setUp(self)` at `:32`. Similar coupling exists in Coach/provider review tests. Browser fixtures patch server internals directly (`e2e/fixture_runtime.py:28`, `:60`, `:101`).

**Trigger:** Move a production function out of `server`, rename/split `test_server.py`, or run a focused service test with a different fixture setup.

**Impact:** Tests depend on the monolith's namespace and another test case's lifecycle. Patches such as `patch.object(server, ...)` can stop intercepting dependencies after an extraction, even when a compatibility import still exists. This creates pressure to retain server wrappers solely for tests and obscures the actual dependency under test.

**Concrete tasks:**

- [ ] **T5.1** Extract non-discovered helpers into `tests/support.py`: synthetic configuration, temporary database lifecycle, provider fakes, sessions, and clocks. Helpers must not import a test case to initialize themselves.
- [ ] **T5.2** Split existing tests by domain as the corresponding production code moves. Keep `test_server.py` for entrypoint/HTTP integration contracts initially; do not rename every test before moving its production dependency.
- [ ] **T5.3** Patch where a dependency is looked up, or supply the existing fake through a constructor/function parameter. Remove moved server wrappers and update consumers in the same change.
- [ ] **T5.4** Update the fixture entrypoint to construct the same application services with blocked providers. Keep all fixture-only routes and canned model responses outside production wiring.
- [ ] **T5.5** Maintain test discovery/shard coverage. If nested test directories are introduced, add the required package files and verify the repository's discovery behavior rather than assuming recursion.

**Acceptance check:** Run each extracted domain suite in isolation and then complete discovery. All providers remain mocked, no real `.env` reads occur, and test IDs are distributed exactly once across CI shards. Preserve existing behavior assertions instead of replacing them with tests that merely mirror the new module layout.

## Current structure and extraction map

AST/line-count measurements on the recorded snapshot:

| Component | Measured size | Structural implication |
|---|---:|---|
| `server.py` | 22,906 lines; 1,239 top-level functions; 1,327 function definitions including methods/nested functions | Composition, business operations, transport, and persistence share a namespace |
| All `backend/**/*.py` | 2,774 lines combined | Useful existing extraction points; reuse them |
| `RequestHandler` | 678 lines, `server.py:22089` | Already has grouped route helpers; extract those groups rather than redesigning HTTP |
| `initialise_database` | 330 lines, `server.py:1394` | Schema belongs with database initialization/validation |
| `IntervalsClient` | 299 lines, `server.py:9046` | Move the complete client into the existing provider package |
| `public/app.js` | 5,267 lines | Related frontend follow-up; not required to begin backend extraction |
| `tests/test_server.py` | 8,801 lines | Fixture ownership and domain splits must accompany production moves |

Existing `backend` modules do not import `server`; preserve this useful direction. Their dependency-light parsers, repositories, and projections are assets, not code to replace with another architecture.

The following spans locate related source, not instructions to cut at line numbers. Definitions have non-contiguous callers and shared constants; move a cohesive operation and its dependency closure.

| Current responsibility / source anchors | Destination | What belongs elsewhere |
|---|---|---|
| Config, settings: `server.py:472`, `:524`, `:21138` | `backend/config.py` | UI-safe settings projection stays at application/HTTP boundary |
| `AppError:1081`, redaction/logging `:688`, `:835` | `backend/errors.py`, `backend/diagnostics.py` | Transport-specific parsing stays with providers |
| DB construction/schema `:1354`, `:1394`, `:21583` | Existing `backend/db/` plus `schema.py` | Domain authorization and remote calls |
| Profile/check-ins/feedback `:5053`–`:5297`; local competitions `:5312`, `:6638` | `backend/athlete.py`, `backend/competitions.py` | Competition remote reconciliation moves to sync |
| Garmin collection/normalization `:3710`–`:5030` | Existing `backend/providers/garmin.py`, `backend/performance.py`, sync services | Do not mix athlete metric derivation into the client |
| Calendar fetch/parse `:5422`–`:6162` | Existing `backend/providers/calendar.py` | Persisted calendar state and scheduled refresh |
| Weather fetch/state `:8082`–`:8728` | `backend/providers/weather.py` plus sync/projection consumers | Planning decisions and HTTP response composition |
| Intervals request/client `:8047`, `:9046` | Existing `backend/providers/intervals.py`, new `http.py` | Job state, reconciliation, gates, database writes |
| Workout validation/library/local plan `:9518`, `:9763`, `:10538`–`:12188`, `:12536`–`:12994` | `backend/planning/{workouts,library,plans,repository}.py` | Remote writes are explicit sync operations |
| Adaptive preview/apply `:9869`–`:10511` | `backend/planning/adaptive.py` | Provider transports; keep explicit approved sync calls visible |
| Plan patches/replacement `:17208`–`:17755`, `:18783`–`:18834` | `backend/planning/plans.py` | Coach-specific provenance translates to authorization before entry |
| Job queue/claim/retry `:1726`–`:2689`; sync/reconciliation `:12249`–`:13667`, `:7451` | Existing `backend/sync/`, add `service.py` and `reconcile.py` | HTTP serialization and provider wire parsing |
| Metrics/context `:13670`–`:15049`; recovery `:6288`–`:6601` | `backend/performance.py`, existing `backend/coach/context.py` | Raw source persistence remains unchanged |
| AI requests/streaming `:15119`–`:16184` | `backend/providers/{openai,gemini}.py` | Commands, tools, authoritative athlete state |
| Coach jobs/streams `:16549`–`:16792`, `:20376`–`:20636` | `backend/coach/jobs.py` | HTTP SSE framing belongs in HTTP package |
| Coach tools/dialogue/execution `:16800`–`:20373` | `backend/coach/{tools,authorization,service}.py` | Planning SQL/domain writes |
| Daily/morning scheduling `:20639`–`:20841`, `:22774`–`:22877` | Existing `backend/sync/daily.py`, `backend/coach/checkins.py` | Worker ownership/wiring belongs in application startup |
| Audit/undo `:2692`–`:3113`; export/delete `:21334`, `:21832` | `backend/history.py`, `backend/privacy.py` | Restore is separate, maintenance-protected workflow |
| Backup/restore `:21624`–`:21794` | Existing `backend/backup/` plus `restore.py` | HTTP stream adaptation stays in HTTP package |
| Sessions/rate/CSRF `:21896`–`:22086` | `backend/http_api/auth.py` | Domain authorization is a separate Coach/service responsibility |
| State projections `:20844`–`:21113`, routes `:22089` | `backend/http_api/state.py`, `handler.py`, `routes.py` | No SQL or provider requests in route adapters |
| Main, gates, shared runtime objects: `:234`, `:316`, `:400`, `:22880` | `backend/application.py`, owner modules for state | Keep `server.py` as entrypoint and literal release version |

## Proposed file structure

Use ordinary Python packages and the existing standard-library HTTP server. These are destinations for existing code, not a requirement to scaffold empty files in advance. Add a further split only when a moved module still contains independent responsibilities.

```text
server.py                         # APP_VERSION literal + guarded startup call
backend/
  application.py                  # construct config, DB, services, server, workers
  config.py
  errors.py                       # existing safe application error contract
  diagnostics.py                  # redaction, logging, diagnostic projection
  athlete.py                      # profile, check-ins, activity feedback
  competitions.py                 # local competition behavior
  performance.py                  # derived metrics and provenance
  history.py                      # audit records and guarded undo
  privacy.py                      # export/delete orchestration
  db/
    manager.py                    # connection/transaction/restore drain owner
    schema.py                     # current schema creation and validation
    repositories.py               # existing small persistence operations
  providers/
    http.py                       # bounded HTTP and safe transport errors
    intervals.py                  # complete Intervals client
    garmin.py                     # collection and provider normalization
    calendar.py                   # secure fetching and calendar parsing
    weather.py
    openai.py
    gemini.py
    workout_text.py               # existing parser/normalizer
  planning/
    workouts.py                   # normalization and calendar constraints
    library.py                    # local templates and library operations
    plans.py                      # plan metadata, atomic patches/replacement
    adaptive.py                   # preview and approved apply
    repository.py                 # planning SQL; takes caller connection
  sync/
    jobs.py                       # existing job rules plus durable queue owner
    service.py                    # execute named refresh/push workflows
    reconcile.py                  # remote/local identity and conflict handling
    daily.py                      # scheduling policy
    status.py                     # existing status projections
    windows.py                    # existing date-window helpers
  coach/
    service.py                    # turn lifecycle, tool rounds, receipts
    tools.py                      # schemas, classification, dispatch wiring
    authorization.py              # provenance, scope, approval checks
    jobs.py                       # durable Coach jobs and stream state
    checkins.py                   # morning workflow and current-sleep gate
    dialogue.py                   # existing request contract/instructions
    context.py                    # sanitized/bounded model context
    attachments.py                # existing attachment validation/parsing
    outcomes.py                   # existing truthful receipt wording
  backup/
    export.py                     # existing archive formatting
    restore.py                    # encrypted backup and restore workflow
  http_api/
    handler.py                    # BaseHTTPRequestHandler adapter/SSE/static
    routes.py                     # explicit grouped route adapters
    auth.py                       # session, CSRF, rate limits
    state.py                      # browser read models
    requests.py                   # existing bounded body readers
    responses.py                  # existing response encoders/headers
tests/
  support.py                      # fixture helpers, no discovered TestCase classes
  test_server.py                  # startup and HTTP integration
  test_planning.py                # expand/split only as actual tests move
  test_*.py                       # existing and extracted domain suites
```

**Dependency rules:** The entrypoint imports application wiring. HTTP and Coach adapters call application/domain services. Services call repositories and provider clients. Repositories receive a connection; provider clients receive explicit transport/configuration. Leaf modules never import `server`, `RequestHandler`, or the whole application to look up dependencies. Cross-domain orchestrators receive the few concrete collaborators they use.

Do not pass a giant `server`/`globals()` namespace into every module, create an all-purpose `utils.py`, wildcard-import extracted functions back into `server`, introduce one-method interface hierarchies, or move the whole file into `backend/service.py`. Those approaches relocate the coupling. A few explicit callables and concrete objects are sufficient; no dependency-injection framework, ORM, new web framework, or microservices are warranted by this review.

## Implementation sequence and acceptance gates

Each row is a separate reviewable change, not a single rewrite. Capture the baseline first. Move code and its tests together; keep behavioral changes separate unless required to establish the boundary safely.

| Order | Concrete change | Depends on | Completion gate |
|---|---|---|---|
| 0 | Record active routes/tools, test IDs, current schema, and critical transaction/lock paths | None | Reproducible baseline; all known validation failures documented |
| 1 | Extract test support and explicit configuration/errors (T1, T5 foundation) | 0 | Imports do not read settings; isolated tests use synthetic configuration |
| 2 | Move cohesive pure logic: calendar parsing, metric calculations, workout normalization, context helpers | 1 | Direct module tests pass; no server wrappers remain for moved leaf functions |
| 3 | Move DB initialization/schema and define one transaction owner (T2) | 1 | Nested rollback, exact schema, SQLCipher refusal, and restore drain tests pass |
| 4 | Move complete provider clients and wire safe transport (T3) | 1–2 | Mocked request/stream/error/cancellation contracts pass; provider paths remain bounded |
| 5 | Extract local athlete/competition/planning services and their SQL | 2–3 | HTTP and Coach use the same mutations; atomic patch/replacement and local-only behavior pass |
| 6 | Extract sync job execution/reconciliation and scheduling | 3–5 | Claim/retry/restart, partial failures, cursor advancement, explicit push and freshness tests pass |
| 7 | Extract Coach authorization/tools/service/jobs and morning check-in (T4) | 3–6 | Complete tool contracts, replay, cancellation, stream/background recovery, and fresh-sleep tests pass |
| 8 | Extract backup/privacy/history and HTTP adapters; finish application wiring | 3–7 | Authentication/CSRF, maintenance/restore, export, health, static assets, and fixture runtime pass |
| 9 | Remove obsolete forwarding aliases; update docs and validation scope | Each extraction | No reverse imports, no duplicate runtime objects, no missed tests/assets/release contracts |

The order is deliberately not “HTTP first”: moving the handler before its service dependencies exist tends to produce a huge injected namespace or reverse imports.

### Preserve these boundaries throughout

- **One runtime owner per resource.** Move each lock, queue, event, cancellation map, manager and its accesses together (`server.py:234`). Do not instantiate a second lock or manager in another module. Preserve singleton behavior within one running application; this remains a single-athlete service.
- **Explicit lifecycle.** `application.py` owns startup order and worker shutdown/join behavior. Current `main` starts workers and a daemon scheduler but its `finally` only closes the HTTP server (`server.py:22890`, `:22901`). Review stop events, drain order, and blocked provider calls before changing shutdown semantics; a move alone is not proof of safe shutdown.
- **One atomic planning boundary.** Revision/hash validation and all related writes stay in the same outer transaction. Preserve stable local identities, audit records and post-commit observation. Do not independently commit inside repositories.
- **Separate transport authentication from action authorization.** HTTP retains session/CSRF checks. Coach retains provenance, scope, idempotency and special approval boundaries. Moving one must not remove the other.
- **Keep HTTP exceptions intentional.** Restore and cancellation have special handling in `server.py:22297` and `:22315`; cancellation must remain reachable while streaming holds maintenance admission. Preserve GET/static/public route behavior rather than applying a new blanket wrapper.
- **Raw data stays authoritative.** Context extraction only changes ownership of projection code. It must not shrink stored Garmin/Intervals snapshots, lose provenance, or change current-sleep gating.
- **Current schema only.** Keep the exact current-schema and encrypted backup contract. No migration, upgrade, previous-install conversion, or old-client support is part of this refactor.
- **Keep release parsing working.** Retain `APP_VERSION = "1.11.0"` as a literal in `server.py` until the normal release process changes it. `.github/scripts/release_source.py:35`, release workflows, and review gates parse that file directly. Pass the version from the entrypoint into application wiring; do not import `server` from the backend to obtain it.
- **Keep deployment paths working.** `Dockerfile:9` already copies `backend/`; `Dockerfile` still executes `/app/server.py`. Update `garmin-login.py`, fixture startup, scoped instructions, and README when their imports/entrypoints actually change.

## Cross-cutting observations and follow-up tasks

These are not confirmed production defects.

1. **Frontend structure:** `public/state.js:12` exposes shared chat/sync/voice state, and `public/app.js:4257` onward owns streaming/recovery. A later frontend task should move complete chat orchestration, sync refresh, and voice controllers behind small explicit APIs, preserving generation/operation IDs. Keep plain JavaScript and existing globals initially if that makes the change smaller; converting to ES modules is a separate choice. Every added asset must be allowed by `STATIC_TARGETS`, referenced by `index.html`, and included consistently in service-worker caching.
2. **Do not “optimize” database reads during extraction.** Production `database()` currently uses the writer unit of work. A search found no production `.reader()` call. `DatabaseManager.reader()` bounds retained idle connections, not the number of simultaneously active readers (`backend/db/manager.py:107`). Do not claim a throughput gain or switch service reads to that API without separate concurrency/restore analysis and measurements.
3. **CI scope:** `.github/workflows/publish-container.yml:156`–`:160` runs Ruff/format/mypy only on `tests/run_tests.py`. Add focused lint/type validation for newly extracted modules once their baseline is established. This is a validation gap, not evidence that the modules contain type defects. Avoid an unrelated repository-wide formatting rewrite.
4. **Instruction/documentation drift:** Root `AGENTS.md` says there is no frontend test runner, but `package.json` and `playwright.config.cjs` define Playwright, and CI runs it. Update the development instructions to describe the actual fixture/browser workflow when undertaking remediation.
5. **Error contract follow-up:** `public/api.js:28` consumes `payload.reason`, while generic HTTP `AppError` responses at `server.py:22276` and `:22332` return only `error`; SSE error paths include a reason. Before centralizing response serialization, inventory existing consumers and tests and decide which safe reason codes belong in the shared public contract. Do not silently expand exported exception details as part of a file move.

## Coach-first and natural-language verdict

The existing dialogue module explicitly models provenance and contextual requests rather than validating wording (`backend/coach/dialogue.py:222`). Scoped execution, atomic planning and receipts are present in the paths inspected. The proposed architecture preserves this separation: dialogue resolves intent; authorization validates the permitted effect; a shared service performs it; receipts describe the durable result.

This review does **not** give a passing end-to-end natural-language verdict. Scripted provider outputs exercise execution, not model understanding; `tests/test_coach_dialogue.py:1` makes that limitation explicit. Every tool's allowed/denied/partial/replay path and actual language quality must be rechecked as the executor moves. No connected model evaluation was performed.

## Validation

Results are recorded below after command completion. Tests use temporary synthetic data; runtime uses the repository's disposable fixture entrypoint and a separate Docker image/container, never the existing athlete installation.

| Check | Result | Scope |
|---|---|---|
| Tracked-file inventory and Python AST inspection | Passed | `git ls-files`; backend import graph, definition/line counts and SQL call-site counts; no production imports used for these measurements |
| `python -m unittest discover -s tests -v` | Passed according to unittest's terminal summary: **747 tests, 12 skipped**, 225.748 seconds | Python 3.13.15, temporary data and mocked providers; skips require SQLCipher/container or Linux Bash. PowerShell's stderr-redirection wrapper returned a nonzero status despite the `OK` summary; a synthetic check confirmed Python stderr can produce this wrapper behavior. No failure/error summary was reported. |
| `python -m py_compile server.py tests/test_server.py` | Passed | Required entrypoint/test syntax checks; AST inspection also parsed all tracked Python files |
| `node --test tests/coach-receipts.test.cjs tests/codex-review-gate.test.cjs tests/release-promotion-gate.test.cjs` | Passed: **48 tests** | Existing receipt and release/review-gate contracts |
| `docker build -q -t ai-coach:structure-review .` | Passed, exit 0 | Dedicated image; normal Dockerfile and pinned dependencies. Initial verbose redirected build also produced the image but hit the same shell-wrapper status issue; cached quiet build confirmed success. |
| Fixture `/api/health` | Passed, HTTP 200 | Dedicated container `ai-coach-structure-review`; `127.0.0.1:18091`; read-only image, temporary `/data` and `/tmp`, repository fixture entrypoint, blocked providers |
| Chromium smoke through Playwright | Passed at **320×568, 390×844, 768×1024, 844×390, 1440×1000** | Separate fresh contexts, password login, initial bootstrap, reload and retained login; zero page errors. Mobile contexts enabled touch/mobile emulation. This is not the full configured project/device suite or an accessibility audit. |
| Full Playwright suite / manual usage matrix | Not run | Limited smoke only; complete interleaving, tool, provider, error, PWA and device-permission cases remain open |
| Full SQLCipher unit suite inside container | Not run | Real SQLCipher was exercised by fixture startup/login/bootstrap, not by every DB/restore regression |
| Ruff/mypy/Sonar/dependency vulnerability checks | Not run | Static architecture review and documentation-only change; no clean-analysis or dependency-security claim |

Runtime image: `sha256:5e7ae28eaa20e2f17f7bd78dfda7aff5bf270f9e381b0c492012b97f2f1bd7d9`; container ID prefix `a34a94de972d`; application version `1.11.0`. No production container was touched. The disposable fixture container is removed after validation. Browser auth storage and screenshots were not exported. Node dependencies were installed only in the task worktree with `npm.cmd ci --ignore-scripts` (the PowerShell `npm.ps1` launcher was blocked by local script-signing policy).

### HTTP extraction inventory

These existing route groups provide natural extraction seams. This is a route inventory, **not** a completed payload/error or frontend parity certification. Preserve public/protected distinctions and method-specific behavior inside each group.

| Method / source | Routes |
|---|---|
| GET, `server.py:22127` | `/api/health`, `/api/readiness`, `/api/auth/status`, `/api/bootstrap` |
| GET, `server.py:22147` | `/api/state/events`, `/api/sync/status`, `/api/activities`, `/api/sync/jobs/<id>` (regex) |
| GET, `server.py:22168` | `/api/chat/history`, `/api/chat/receipt`, `/api/chat/status` |
| GET, `server.py:22189` | `/api/profile`, `/api/feedback`, `/api/library`, `/api/performance`, `/api/plan`, `/api/weather`, `/api/context-preview` |
| GET, `server.py:22218` | `/api/change-history`, `/api/diagnostics`, `/api/diagnostics/capture`, `/api/logs`, `/api/privacy/backup`, `/api/privacy/delete/preview`, `/api/privacy/export` |
| POST, `server.py:22285` | `/api/login`, `/api/logout`, `/api/privacy/restore`, `/api/chat/cancel` |
| POST, `server.py:22474` | `/api/chat`, `/api/chat/stream`, `/api/chat/reset`, `/api/coach/actions/confirm`, `/api/coach/actions/execute`, `/api/feedback`, `/api/planning/commands`, `/api/transcribe` |
| POST, `server.py:22510` | `/api/sync`, `/api/sync/jobs`, `/api/sync/jobs/<id>/resolve` (regex), `/api/garmin/sync`, `/api/garmin/full-resync`, `/api/intervals/full-resync`, `/api/performance/refresh`, `/api/external-calendar/sync`, `/api/weather/sync` |
| POST, `server.py:22557` | `/api/change-history/undo`, `/api/change-history/undo/preview`, `/api/diagnostics/capture`, `/api/privacy/delete` |
| PUT, `server.py:22589` | `/api/athlete-context`, `/api/profile`, `/api/settings/ai-provider`, `/api/settings/calendar-display`, `/api/settings/model`, `/api/settings/thinking-level` |

## Coverage ledger

“Structural review” means ownership/dependency evidence was inspected, not a clean bill of health for runtime behavior. Inventory-only and unexecuted areas remain open for a full application audit.

| Checklist domain | Main evidence | Structural result / remaining gap |
|---|---|---|
| 1. Product invariants/architecture | `server.py`, `backend/`, AGENTS | Reviewed; F1–F4 and extraction map |
| 2. Authentication/HTTP | `RequestHandler`, auth/CSRF helpers, `public/api.js` | Boundary inspected; full route/error matrix not executed |
| 3. Secrets/privacy/untrusted content | config loading, redaction, export boundaries | Ownership inspected; no live secret/data handling exercised |
| 4. SQLCipher persistence | manager/repositories, schema, planning transaction | Reviewed structurally; F2; full container DB suite separate |
| 5. Backup/restore | restore validation/replacement/drain | Boundary inspected; failure injection/rollback runtime not exercised |
| 6. Providers/network | existing provider modules, Intervals client, HTTP/AI sections | Reviewed structurally; F3; full SSRF/network failure matrix open |
| 7. Sync/concurrency | job queue, globals, schedule, status | Ownership mapped; all interleavings not proven |
| 8. Coach context/provenance | context module, performance/context assembly | Ownership/projection boundaries inspected; no live coaching-quality assessment |
| 9. Responses/tools | schemas/dialogue/dispatch/receipts | Reviewed structurally; F4; complete per-tool runtime reconciliation open |
| 10. Planning/workouts/calendar | nested patch, revision guards, local/remote operations | Transaction/service boundaries inspected; all mutation paths not individually traced |
| 11. Dates/timezones/units | date windows, daily/morning functions, metric normalization inventory | Partial structural review; full DST/unit edge-case audit open |
| 12. Frontend state/API | API/state/app scripts, handler, browser tests | Ownership mapped; race/error state coverage incomplete |
| 13. PWA/offline | asset registry, script references, service worker | Refactor dependencies identified; fresh installation/offline/mixed-state tests open |
| 14. Reliability/performance | locks, manager, worker startup/shutdown | State ownership reviewed; no benchmark or throughput claim |
| 15. Tests | test bootstrap/shared harness, runner, fixture runtime | Reviewed structurally; F5; validation results below distinguish executed suites |
| 16. Dependencies/container | requirements inventory, Dockerfile, dockerignore | Packaging inspected and build attempted; no vulnerability/API compatibility audit |
| 17. CI/releases | workflow inventory, release parser, test/quality/e2e jobs | Version/import/discovery dependencies reviewed; not a full workflow security audit |
| 18. Documentation/maintainability | instructions, README/deployment references, docs inventory | Structure reviewed; historical handovers and all README claims not fully revalidated |

### Capability, lifecycle, provider and journey ledger

The rows below locate the behavioral checks required during extraction. “Open” is not “clean”; unit-suite success cannot stand in for the unexecuted full matrix.

| Capability group | Source ownership | Required extraction regression / current coverage limitation |
|---|---|---|
| Profile/check-ins/activity feedback | athlete operations + Coach adapters | Same effect through API/Coach; direct authorized execution; hypothetical/quoted text denied; complete language matrix open |
| Local workouts/templates/plans | planning services + Coach tools | Atomic moves/edits/additions; local identities; read/hash/revision checks; complete tool matrix open |
| Competitions | local domain + sync reconciliation | Local authority/tombstones, conflict resolution, explicit remote push; provider runtime open |
| Adaptive replanning | adaptive service + authorization | Explicit preview approval; stale/repeated apply; illness remote scope; runtime open |
| Named refresh/current performance | sync service | Selected provider and freshness, preserved last-good state, partial results; provider runtime open |
| Remote plan/library sync | sync jobs/reconciliation | Explicit scope, partial batches, retry/no duplicates, complete manifests; remote writes excluded |
| Inspect activities/context/weather/calendar | query/context/provider modules | Source labels, bounded projection, read-only advice; complete runtime open |
| Chat/question/follow-up/replay | Coach service/jobs + browser chat | Stable client turn IDs, request provenance, truthful receipts; scripted fixture does not establish language quality |
| Undo/privacy/backup/restore | history/privacy/backup + HTTP guards | Preview/ownership/maintenance/encryption; destructive runtime tests require disposable data and dedicated scenarios |
| Voice/notifications | HTTP transcription + browser controllers | Bounded audio, editable transcript, permission handling; device/permission matrix open |

The complete skill scenario list remains required for a separate usage audit or the relevant extraction phase:

| Matrix | Open scenarios and reason |
|---|---|
| Message lifecycle | Fast stream success; completion/history race; reversed bootstrap responses; state-event race; disconnect before/mid/after answer; background reload; conversation recovery; malformed/empty/oversized upstream; cancellation timing; rapid sends/steer/duplicate turn; navigation; close/reload timing; multi-tab ownership; offline reconciliation; reset with callbacks; long content. No complete controlled-interleaving run was performed for this structure review. |
| API errors | Every route's payload limits/types, stale IDs/hash/revisions and 400/401/403/404/409/413/422/429/500/502/503/504, invalid JSON, reset/timeout/abort. The full caller-to-route response/error parity matrix was not executed. |
| Provider states | For Intervals, Garmin, calendar, weather, OpenAI, Gemini and release checks: unconfigured, authentication failure, fresh/stale, partial, rate-limited, timeout, malformed/empty/duplicate/paginated data, recovery and mixed-provider failures. Fixture mode blocks providers; no connected external validation was requested. |
| Journeys/viewports | Cold login, read-only chat, every mutation/sync, queue/cancel/reset/recovery, edit/reload, empty/long/error/offline states, PWA install/offline, microphone and notifications across mobile-small, mobile, tablet, tablet-landscape and desktop. Any smoke result below is narrower than this full journey matrix. |

## Areas inspected without an actionable structural finding

- Existing backend modules avoid reverse imports into `server` and already offer useful pure functions and connection-taking repositories.
- Existing local plan patch code deliberately reuses an outer transaction; this is an invariant to retain, not something to replace with independent commits.
- Generic POST handling checks session and CSRF before protected routing; restore/cancel handling has explicit exceptions that must survive extraction.
- Secure startup refuses invalid password/SQLCipher configurations, and Docker already copies the backend package and runs as a non-root user.
- Tests and browser fixtures have explicit synthetic-data/provider isolation mechanisms. Their ownership should improve without weakening those protections.

## Completion and limitations

The requested **structural assessment and concrete refactoring plan are complete for the recorded snapshot**. The full codebase-review skill's exhaustive application/usage audit is incomplete: all-route/tool parity, all provider/failure/concurrency cases, destructive recovery cases, complete viewport journeys, full dependency security, and full workflow security still require review. No passing test result in this report proves those unexecuted areas correct.

Recommended first implementation change: **T1 plus the T5 fixture foundation**, followed by small leaf-module moves. The success criterion is explicit ownership and independently testable services, not an arbitrary line-count target for every file.
