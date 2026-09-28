# Full codebase architecture review — GPT-6 Luna handoff

Date: 2026-09-28

Commit: `a01eab4f57bf331dc712344587421708ea1a3cad`

Branch: `t3code/full-codebase-architecture-review`

Scope: complete repository review, including backend, frontend/PWA, persistence, providers, Coach tools, HTTP routes, tests, Docker, CI/CD, and documentation.

## Review scope and method

The review followed the repository `AGENTS.md`, the scoped `public/AGENTS.md` and `tests/AGENTS.md`, and the `ai-coach-codebase-review`, `ai-coach-navigator`, `ai-coach-validation`, and Ponytail skills. Source files were scanned with `sonar analyze secrets` before they were read. Real `.env`, `/data`, databases, backups, Garmin tokens, browser credentials, provider accounts, and logs containing athlete data were excluded. No application code, database, provider state, commit, or deployment was changed.

The source snapshot was `a01eab4f57bf331dc712344587421708ea1a3cad` on `t3code/full-codebase-architecture-review`. At review start, the tracked tree was clean; this report was the sole untracked path. It is the review deliverable, not a source change included in the reviewed snapshot.

The review traced the application from `server.py` composition through `backend/`, the browser client, SQLCipher repositories, workers, provider adapters, OpenAI/Gemini Responses flows, route contracts, tests, Docker, workflows, and README claims. A disposable SQLCipher fixture container was used for the unit and browser checks. The complete local source snapshot is covered below; runtime and real-provider limitations are recorded explicitly.

## Findings

### F1 [P1] Keep background workers alive after transient claim or run failures — `backend/sync/worker.py:79-98`, `backend/coach/job_worker.py:49-60`, `backend/sync/scheduler.py:168-183`

**Evidence:** `SyncJobWorker.run_loop` and `CoachJobWorker.run_forever` catch only `AppError`. An unexpected exception from `claim()`, the runner, a database connection, or a provider-independent job path escapes the daemon thread. `DailySyncLoop.run` has the same outer-loop shape and only logs an `AppError` branch. The process starts these workers from `server.py:1802-1809`, and no supervisor restarts a dead thread.

**Trigger:** A deterministic test injected `sqlite3.OperationalError("synthetic transient database failure")` from a queue claim. Both worker loops exited immediately with the exception. The same termination path is available for an unexpected runner error or scheduler dependency error.

**Impact:** A transient SQLite/connection/restore-adjacent error silently stops all queued synchronization or Coach background work until the process is restarted. Durable jobs can remain queued or running while no worker consumes them; scheduled refreshes also stop. This is a core Coach and sync reliability failure under a realistic transient condition.

**Remediation task F1 for GPT-6 Luna:** Add an outer-loop recovery boundary for sync, Coach, and daily scheduling workers. Catch recoverable unexpected exceptions, log only safe exception class/reason metadata, apply bounded interruptible backoff, and continue polling. Preserve maintenance, stop, and fatal process-exit semantics. Distinguish a claim failure from an already-claimed job failure: retain durable failed/unknown status and existing idempotency/recovery rules rather than blindly replaying a remote effect. Use existing event waits and a testable delay; do not add a worker framework or orchestration to `server.py`.

**Regression-test task:** Add deterministic tests for transient claim failure, runner failure, scheduler failure, recovery on the next iteration, bounded backoff, stop during backoff, and no duplicate claim after recovery. Assert that maintenance errors still wait and that a restart/requeue path remains intact. Run the worker tests against temporary storage and mocked runners only.

**Confidence:** high.

### F2 [P2] Make authoritative action status override contradictory Coach prose — `backend/coach/turn_outcome.py:38-49`

**Evidence:** `_queued_message` replaces the model text only when every effect is queued. When a turn has a local effect plus a queued provider refresh, it appends a queue receipt to the model answer. A model answer such as “the refresh has completed” therefore remains beside `Synchronisationsauftrag …: queued. Remote-Abschluss ist noch nicht bestätigt.`

**Trigger:** A structured turn containing a successful local `save_checkin` receipt and a queued `refresh_current_performance` receipt was finalized with model text claiming completion. The result retained the claim and appended the queued status.

**Impact:** The athlete receives mutually contradictory state about current data and remote completion. The durable receipt is correct, but the final Coach message can cause the athlete to act on a false completion claim. This is distinct from the earlier all-queued wording fix because mixed local/queued effects still take the contradictory path.

**Remediation task F2 for GPT-6 Luna:** Generate action-result wording from authoritative receipts and job observations when effects exist, including mixed local and queued outcomes. Do not attempt to detect completion claims with language-specific regexes or a phrase list. Preserve useful explanation only where it cannot claim an unsupported action result. Retain proposal/approval boundaries and follow-up questions without letting a question suppress authoritative status. Keep this projection in the existing outcome service shared by provider flows.

**Regression-test task:** Add mixed local/queued, local/failed, queued/completed-observation, partial, and deliberately false model-text cases. Assert that no final answer says a queued or failed provider action completed, that local success remains visible, and that read-only prose is preserved when no authoritative effect exists. Cover both providers’ finalization paths.

**Confidence:** high.

### F3 [P2] Filter archived library rows before applying the Coach limit — `backend/planning/library_service.py:255-273`

**Evidence:** `_list_in_db` selects and limits all date-less library rows, then parses JSON and removes archived rows in Python. `WorkoutLibraryService.list(..., include_archived=False)` is used by Coach reads. The HTTP path in `backend/http_api/library_page.py:20-47` filters `archived=0` in SQL before pagination, so the two read models disagree.

**Trigger:** A temporary database with 100 archived templates followed by one active template returned an empty Coach list for the default limit, while the HTTP library page returned the active template.

**Impact:** Coach can report that no reusable template exists or fail to resolve a valid active template even though the browser library displays it. This breaks Coach-first capability parity and can lead to unnecessary new-template creation.

**Remediation task F3 for GPT-6 Luna:** Move the archived predicate into the domain query before `LIMIT`; this is sufficient for the demonstrated defect. If consolidating both projections is a small cohesive follow-up, keep the canonical query in planning and the cursor envelope in HTTP. Preserve explicit `include_archived=True`, valid JSON handling, and the HTTP path's existing ordering/cursor continuation. Do not add an unused pagination API to the Coach service just to fix filtering.

**Regression-test task:** Add a service test with archived rows filling the requested limit and active rows after them; test `include_archived=True`, malformed payloads, stable tie ordering, and cursor/page continuation. Add a parity test comparing the Coach projection with the HTTP library projection for the same temporary database.

**Confidence:** high.

### F4 [P2, test infrastructure] Isolate SQLCipher plan fixtures between viewport projects — `e2e/fixture_runtime.py:97`, `e2e/coach.spec.js:638`

**Evidence:** `stage_fixture_artifact()` always stages four sessions from the athlete's current date. After a successful commit, `/api/fixture/plan` stages another draft without removing the earlier committed fixture sessions. The test generates a different client-turn ID for each project, so subsequent commits correctly hit the application's occupied-date guard. One Playwright worker serializes execution but does not reset database state.

**Trigger:** Run the five projects against one disposable fixture container. The first plan-commit case passed; later mobile, tablet, and landscape cases failed because today already contained a local calendar unit.

**Impact:** The prescribed browser matrix becomes order-dependent and cannot validate plan persistence/sport rendering in later viewports. This is a confirmed testing defect; the production conflict guard is behaving correctly.

**Remediation task F4 for GPT-6 Luna:** Isolate this fixture per test/project, or add explicit fixture-only setup/teardown that owns and cleans its exact synthetic records. Keep resets outside production routes and never point cleanup at a real data directory. Preserve the replay check within each test and the application's date-conflict validation. Prefer fixture isolation over weakening an assertion or accepting an expected conflict.

**Regression-test task:** Run this plan test in all five projects, repeat it twice, and reverse project order. Each case must independently create exactly four expected sports and confirm idempotent replay. Re-run the full browser suite after isolation.

**Confidence:** high.

### F5 [P2] Do not hold the global write lock while compressing a full privacy archive — `backend/backup/export.py:108-145` (and the JSONL writers below it)

**Evidence:** `PrivacyArchiveExportService.create_file` enters `with self._db_lock, self._database_manager.unit_of_work() as db, zipfile.ZipFile(...)` before writing every archive member. The configured export bounds are 100 MB and 120 seconds. It iterates snapshots and other durable records while the application-wide lock and database unit of work remain held. The lock duration is source-proven; no production-sized timing benchmark was run.

**Trigger:** A realistic archive containing large snapshots or histories keeps the lock for the entire database read plus JSON serialization and DEFLATE compression. The source and bounds make this a deterministic long critical section even when no exception occurs.

**Impact:** Privacy export can block profile/check-in/planning writes, Coach commands, sync queue claims, and other lock users for the full export duration. A large export therefore creates visible stalls and can make background jobs appear dead. The issue is transaction/technology placement rather than an export-content leak.

**Remediation task for GPT-6 Luna:** Capture a consistent bounded read snapshot using a SQLite read transaction/backup or bounded extraction, then release the application write lock before compression. Preserve current-schema consistency, size/time limits, cleanup on failure, sensitive-field handling, and restore/maintenance coordination. If serialization is intentionally required, expose bounded progress and document the maintenance behavior instead of silently blocking all writes.

**Regression-test task:** Run an export against temporary populated storage while a chat/check-in write and a sync claim execute. Assert the write either proceeds outside the export lock or returns a documented bounded maintenance response; assert archive consistency, cleanup, limits, and no sensitive logging. Add a failure test for disk-full/timeout that releases the lock.

**Confidence:** high.

## Architecture improvement tasks (not confirmed production defects)

### A1 — Incrementally expand static-quality coverage — `.github/workflows/publish-container.yml:155-172`

**Evidence:** The quality job runs Ruff, format, and mypy only on `tests/run_tests.py` and a small set of Coach, database, error, and HTTP files. The repository contains hundreds of backend modules, including the worker, planning, backup, provider, and server composition paths. Full tests and compile checks do not enforce repository-wide lint or type quality.

**Assessment:** Most modules are outside the deliberate static-analysis baseline. This is a prevention gap and a useful incremental improvement; an omitted lint/type check by itself is not proof of a production defect. Broad `Any`/dict boundaries make targeted expansion valuable.

**Remediation task for GPT-6 Luna:** Define an incremental repository-wide Ruff, format, and mypy policy with explicit configuration and exclusions. Start with package-level checks or changed-file enforcement, then expand ownership boundaries without requiring a risky all-at-once rewrite. Keep tests, coverage, and static checks separately visible in CI and fail closed for newly changed backend files.

**Acceptance:** Verify representative provider, planning, backup, worker, HTTP, and composition modules; document intentional exclusions and staged expansion. Validate the workflow selection on an unchecked changed file, a checked file, and a documentation-only diff. Do not add implementation-mirroring tests solely to prove a static file list.

**Confidence:** high.

## Cross-cutting architecture observations

### Technology and placement assessment

The Python 3.14 `http.server` application, SQLCipher persistence, native JavaScript PWA, and durable in-process job queues remain proportionate to a private single-athlete service. This review does not justify a framework rewrite, ORM, message broker, hosted service, or frontend framework. The failures are at ownership and lifecycle boundaries, and the current technologies can address them.

Keep request parsing/authentication/response handling in `backend/http_api`; planning rules and canonical queries in `backend/planning`; provider wire formats in `backend/providers`; job lifetime/recovery in `backend/sync` and `backend/coach`; archive consistency/compression in `backend/backup`. `server.py` should supply dependencies and lifecycle wiring. Fix F3 in the domain owner before considering moving the HTTP adapter; do not make planning import an HTTP read service. F5 should reuse the database manager's existing read/maintenance facilities, preserving snapshot consistency and avoiding an unbounded in-memory copy or plaintext database staging file.

### A2 — Type one cross-domain contract at a time

Start with `backend/coach/turn_outcome.py` and its receipt producers during F2: represent only the status/job fields consumed at that boundary with a `TypedDict`, dataclass, or existing protocol, validate external data in its provider adapter, and keep arbitrary provider payloads at the edge. Prove the real producer-to-consumer path with the existing outcome/tool tests. Do not build a parallel DTO layer for every dictionary. This is optional maintainability work, not a finding requiring broad rewrites.

### A3 — Consolidate frontend reconciliation ownership after identifying the duplicate caller

`public/coach.js` owns the Coach lifecycle, but `public/app.js` still owns history loading, route restoration, and shared state. Keep one authoritative reconciliation owner with explicit generation/version inputs. U1 below must establish the two actual request stacks before deciding whether a small coalescing change or fixture correction is needed. Do not introduce a state-management dependency or split files solely by length.

- `server.py` remains approximately 1,833 lines, but the reviewed current paths keep new domain workflows in `backend/` and use `server.py` primarily as composition root. Size alone is therefore not reported as a defect.
- A static dependency pass showed a provider-state/openai/http/gemini cycle-shaped relationship caused partly by type-checking and dynamic imports. No import failure or runtime break was reproduced. Treat this as a refactoring candidate: make provider protocols and transport dependencies unidirectional before adding more adapters.
- `Any` and untyped dictionary boundaries are concentrated in provider payloads, Coach proposals/context, and sync jobs. Type those boundaries incrementally alongside the CI task; no standalone correctness defect was proven from the inventory alone.
- The HTTP and Coach library projections duplicate pagination/filtering rules. Finding 3 is the confirmed failure; consolidate the read model while fixing it.
- The Playwright fixture uses one worker and mutable shared SQLCipher state. Tests that create “today” records can contaminate later projects. The observed plan-commit failure at `e2e/coach.spec.js:638-652` was classified as fixture isolation, not as a product defect. Reset or namespace fixture state per test/project in a follow-up.

## Browser investigations to hand over separately

### U1 — Identify both callers in the duplicate history-request test

`e2e/contracts.spec.js:195` observed two pending `/api/chat/history` requests instead of one on multiple viewports. Relevant owners are `public/coach.js:30` (proposal refresh), `public/coach.js:372` (completion), and `public/app.js:4006` (area loads). The persisted-receipt branch returns without calling `loadChatHistoryFresh`, so the evidence does **not** establish that completion itself always calls both paths. A bootstrap/navigation/state-event load or a fixture timer may be the second caller. No disappearing message or stale proposal overwrite was reproduced.

**Task U1:** Capture sanitized caller stacks and generation/content versions in this synthetic test, isolate pending initial loads/events, and reproduce both request orderings. If production requests duplicate unnecessarily, reuse one in-flight history result while retaining generation guards; if the harness counts an unrelated load, fix its setup/barrier and keep the proposal assertion meaningful. Acceptance: the test passes on all five viewports and in repeat runs, proposals reconcile correctly after reload, and a new-session response cannot be overwritten. Do not blindly change the expected count to two or add sleeps.

### U2 — Stabilize the synthetic measurement test

`e2e/diagnostic-followups.spec.js:3` appends synthetic metrics directly to the DOM after a real fixture load. A later render removes them; the tablet failure explicitly showed the normal empty-performance placeholder replacing the injected DOM. This supports a fixture/render-order problem, not a proven failure to retain stored measurements.

**Task U2:** Serve the synthetic values through the normal performance response/state path (use the existing read-fixture helpers), then verify date, age, fetch tooltip, and unknown measurement date through refresh/navigation. Scope timer/event isolation to the test. Acceptance: repeated runs of this test and the complete matrix pass without disabling production polling or loosening source/freshness assertions.

### U3 — Explain the desktop library-pagination failure

`e2e/audit-remediation.spec.js:164` passed in earlier projects but failed on desktop: after clicking the synthetic library cursor, the test expected `['older-template']` and observed an empty library. The test directly replaces `state.data.library`/cursor and intercepts only the synthetic cursor URL. `public/app.js:1937` owns the append operation; ordinary area loads can also replace library state. The evidence does not yet identify whether the append was skipped or a later refresh replaced it.

**Task U3:** Capture the cursor request, response, generation checks, and subsequent library load/render order with synthetic data. Reproduce before/after refresh timing and keep legitimate new-session invalidation. Correct the fixture if its initial state is unstable; otherwise fix the specific production ordering. Acceptance: history and library pages append exactly once, remain visible through the intended UI flow, and repeat runs pass at all viewports. Do not relax the expected result or disable production updates to hide the race.

### U4 — Diagnose the desktop initial-load unauthorized timeout

`e2e/coach.spec.js:400` timed out at 60 seconds while awaiting `loadInitialState()` after intercepting bootstrap with HTTP 401. The same scenario passed in earlier projects. Source paths are `public/coach.js:185` and the shared load promise/session invalidation in `public/app.js`. A timeout alone does not establish that the session was retained or that authentication was bypassed.

Subsequent desktop tests at `coach.spec.js:417`, `:448`, `:638`, and `:660` failed before their main action because `#appShell` remained hidden. The disposable container was still running, was not OOM-killed, and returned HTTP 200 from `/api/health`. This localizes neither the browser nor backend cause; health success is not proof of authenticated readiness.

**Task U4:** Reproduce the test in isolation and after the preceding browser scenarios; capture pending request/load ownership, sanitized browser exceptions, and fixture health without logging authentication values. Resolve whether an old load, intercepted request, or fixture/browser lifecycle prevented settlement. Verify fresh-page bootstrap and the four subsequent hidden-shell cases as part of the same investigation. Acceptance: the initial load settles after 401, login is visible, `initialStateLoaded` stays false, and an old request cannot affect a new session. Keep the timeout assertion meaningful rather than only increasing it.

## Copyable GPT-6 Luna implementation handoff

> Read this report and the current root/scoped AGENTS.md instructions. Implement **[insert F1, F2, F3, F4, F5, U1, U2, U3, U4, A1, A2, or A3]** only, in a dedicated task worktree. First recheck the cited code against the current branch and reproduce the recorded behavior using temporary data and mocked services. Preserve the fresh-install SQLCipher contract, sessions/CSRF, local-first plans, explicit remote approval, and adaptive preview/apply. Never read or modify real .env, data, databases, backups, or Garmin tokens. Follow the mandatory secrets scan before file reads. Implement the smallest fix in its domain owner, add the behavioral regression coverage specified by the task, and run the focused checks below. If a frontend asset changes, update index asset versions and the service-worker cache/assets together. Report changed files, cause, observed before/after result, exact test results, and remaining limits. Do not commit, create a PR, deploy, or call a real provider unless separately requested. Do not treat observations as proven bugs.

| Task | Start with these files/tests | Required acceptance |
|---|---|---|
| F1 | `backend/sync/worker.py`, `backend/coach/job_worker.py`, `backend/sync/scheduler.py`; `tests/test_sync_worker.py`, `tests/test_coach_job_worker.py`, scheduler tests | One transient failure does not kill the worker; the next eligible job executes once; stop/maintenance and unknown-effect handling remain safe |
| F2 | `backend/coach/turn_outcome.py`; `tests/test_coach_turn_outcome.py`, `tests/test_coach_repair_outcomes.py` | Mixed local/queued/failed statuses cannot leave a false completion claim; local success and follow-up question remain useful |
| F3 | `backend/planning/library_service.py`, `backend/coach/read_tools.py`, `backend/http_api/library_page.py`; `tests/test_library_service.py`, `tests/test_library_page_service.py` | Archived rows cannot consume the active limit; Coach and browser agree; preserve existing pagination contract without adding a new one unnecessarily |
| F4 | `e2e/fixture_runtime.py`, `e2e/coach.spec.js`, `playwright.config.cjs` | All five project commits succeed independently; duplicate turn in one test stays idempotent; no production cleanup endpoint |
| F5 | `backend/backup/export.py`, `backend/db/manager.py`; `tests/test_privacy_data_export.py`, export-stream tests | Pause compression at a deterministic barrier and prove an independent write progresses; consistent snapshot, limits, cleanup, and restore coordination remain intact |
| U1 | `e2e/contracts.spec.js`, `public/coach.js`, history/route/state load helpers in `public/app.js` | Explain both request stacks; correct proposal refresh and stale-response handling in repeat runs |
| U2 | `e2e/diagnostic-followups.spec.js`, `e2e/read-fixture.js` | Values survive normal refresh because the fixture supplies them through state/API, with source/date assertions retained |
| U3 | `e2e/audit-remediation.spec.js`, `public/app.js` pagination and scoped-load functions | Explain the empty desktop library; append once and preserve the correct generation through refresh |
| U4 | `e2e/coach.spec.js:400`, `public/coach.js:185`, `public/app.js` load/session helpers | Explain and fix the stalled unauthorized initial-load test; preserve new-session ownership |
| A1 | `.github/workflows/publish-container.yml`, existing quality configuration and locks | Expand static coverage in a bounded step and document the remaining baseline; no mass formatting mixed with fixes |
| A2 | Receipt producers and `backend/coach/turn_outcome.py` | Type the consumed cross-domain fields, check actual producers, preserve serialized contracts and focused behavior tests |
| A3 | `public/coach.js` and history/route helpers in `public/app.js` | After U1, assign one reconciliation owner and verify ordering with existing controlled-response tests; no framework replacement |

Recommended sequence: F1, F2, F3, F4, U1–U4, F5; then A1–A3 if still useful. Each task can be a separate thread using the prompt above. F4 is needed before treating a complete shared-container browser run as clean. F5 has the greatest transaction/privacy design risk; do not remove locking without proving a consistent snapshot.

Run focused tests with `python -m unittest discover -s tests -p 'test_<area>.py' -v`; then the required full `python -m unittest discover -s tests -v` and `python -m compileall -q server.py backend tests`. Backend/frontend/runtime changes also require the repository's Docker build. Browser fixes require `npm run test:e2e -- --project=<affected-project>` against a disposable fixture, followed by the complete five-project matrix. Use the existing CI static checks for touched covered files. If checks are unavailable, state the exact blocker rather than bypassing SQLCipher or using live credentials.

## Coach-first and natural-language verdict

The Coach is not yet demonstrably reliable as the sole primary interface. The current capability catalog binds active schemas to owners, effect classes, authorization rules, receipts, and canonical dispatchers; local-first planning, explicit remote approval, named provider refreshes, adaptive preview/apply, and nutrition paths are represented. The reviewed tests show contextual follow-up and reference resolution mechanics, and no fixed keyword gate was found in the active dispatcher.

The verdict remains non-passing because mixed-effect wording can contradict durable status, Coach library pagination can hide active templates, and the browser proposal-refresh test has an unexplained duplicate request (U1). Scripted model outputs prove execution mechanics only; no real-model semantic certification was performed for German paraphrases, typos, negation, quotation, hypothetical prompts, multi-action wording, or provider text containing instructions. Remote writes remain protected by explicit approval, while local actions retain their current direct-execution contract.

## Validation

| Check | Result | Evidence / limitation |
|---|---|---|
| `python -m unittest discover -s tests -v` | Passed | Native run: 2,919 tests, 12 skipped, 930.463 seconds. |
| Container Python suite (`tests/run_tests.py`, shard 1/1) | Passed | Python 3.14/SQLCipher image: 2,919 tests, 13 skipped, 79.955 seconds. Skipped paths are not counted as exercised; the differing platform skips remain a coverage limit. |
| `python -m compileall -q server.py backend tests` | Passed | No syntax errors. |
| Docker build | Passed | `ai-coach:architecture-review-a01eab4`; disposable container on `127.0.0.1:18091`. |
| Focused Ruff checks | Passed | CI-listed files. Repository-wide policy remains improvement A1. |
| Focused Ruff format check | Passed | CI-listed files. |
| Focused mypy | Passed | CI-listed files. |
| Node receipt/review/release tests | Passed | 61 tests. |
| Playwright browser matrix | Failed; stopped | 270 tests scheduled, one worker, five Chromium projects. Reached test 244/270; 17 completed failures observed before interruption. The first four projects completed; desktop stalled on bootstrap/hidden-shell scenarios. Stopped with Ctrl+C after repeated failures; no aggregate pass count is claimed. See exact failure table below. |
| Secret scans | Passed | Scanned reviewed source and the report after writing; no issues reported. |
| `git diff --check` | Passed | Report-only worktree change; also checked report whitespace explicitly because it is untracked. |
| Live providers / real model semantic evaluation | Not run | Prohibited by the repository privacy and review boundary. |
| Destructive remote sync, privacy delete, restore against persistent data | Not run | Intentionally blocked; only isolated fixtures and source/tests were used. |

Runtime identity: image `ai-coach:architecture-review-a01eab4`, container `ai-coach-architecture-review`, app `1.11.15`, service-worker cache `intervals-coach-v229`, fixture host `127.0.0.1:18091`, Chromium via the repository Playwright configuration. Synthetic data and scripted model responses only. The fixture used container-local disposable storage, with only `e2e/fixture_runtime.py` bind-mounted read-only. It was stopped and removed after validation without `-v`; real data and containers were preserved.

| Failed scenario | Projects / observed symptom | Classification |
|---|---|---|
| `contracts.spec.js:195` proposal refresh | mobile-small, mobile, tablet, tablet-landscape: 2 history requests instead of 1 | U1, 4 failures |
| `diagnostic-followups.spec.js:3` measurement age | Same four projects: injected synthetic metric disappears or expected undated label is replaced | U2, 4 failures |
| `coach.spec.js:638` plan commit | mobile, tablet, tablet-landscape: today's fixture sessions already exist | F4, 3 failures |
| `audit-remediation.spec.js:164` cursor append | desktop: expected older template, received empty library | U3, 1 failure |
| `coach.spec.js:400` unauthorized initial load | desktop: `loadInitialState()` did not settle before 60-second timeout | U4, 1 failure |
| `coach.spec.js:417`, `:448`, `:638`, `:660` | desktop: shell stayed hidden before the intended scenario | U4 follow-on, 4 failures |

Desktop `contracts.spec.js:45` was active at interruption. The remaining desktop contract, diagnostic-followup, and state-events cases were not executed in that project. The same cases in earlier projects supply evidence only for those viewports. No retry was used to erase the failures.

## Coverage ledger: 18 review domains

| Domain | Main evidence inspected | Validation | Result | Remaining gap |
|---|---|---|---|---|
| 1. Product invariants and architecture | `AGENTS.md`, `server.py`, `backend/`, README, dependency scan | Architecture tests, source trace | Reviewed; observations above | Provider cycle refactor not required for this handoff |
| 2. Authentication, sessions, CSRF, HTTP | auth/session services, route dispatchers, request validation, tests | Native/container tests; browser auth flows started | Reviewed | Full injected route/error matrix not completed |
| 3. Secrets, privacy, untrusted content | logging/redaction, Markdown, voice, export/delete, token boundaries | Secret scans and tests | Reviewed; export lock finding | No real credential/provider run |
| 4. SQLCipher and durable data | DB manager, schema/repositories, UOW/reader ownership | Container unit suite | Reviewed | Load under real SQLCipher concurrency not measured |
| 5. Backup/restore/recovery | export, restore, maintenance gate, recovery copy | Unit tests and source trace | Reviewed | Full fault-injection restart journey blocked |
| 6. Provider/network security | Intervals, Garmin, calendar, weather, OpenAI, Gemini HTTP adapters | Mocked provider tests | Reviewed | Live API/version and DNS edge cases unverified |
| 7. Synchronization/concurrency | queues, workers, scheduler, cursors, reconciliation | Worker reproduction; unit suite | Finding 1 | Cross-process restart/load tests remain follow-up |
| 8. Coach context/training correctness | context projection, provenance, local authority, budgets | Unit/source checks | Reviewed | Real-model advice quality not certified |
| 9. Responses lifecycle/Coach tools | schemas, catalog, dispatcher, receipts, stream/background state | Container tests; browser matrix | F2/F3; investigation U1 | Full semantic and every race scenario not observed |
| 10. Planning/workouts/competitions/calendars | planning services, library, adaptive actions, sync protection | Unit tests; fixture browser | Finding 3; fixture conflict | No connected remote mutation |
| 11. Dates/timezones/units | athlete clock, date helpers, validation, UI rendering | Unit and fixture checks | Reviewed | DST and all viewport/timezone combinations not run |
| 12. Frontend/API contracts | `public/*.js`, route modules, validators, Playwright contracts | Node tests; browser failures recorded | U1–U4 | Exhaustive per-route boundary injection remains unexecuted |
| 13. PWA/service worker/offline | `index.html`, service worker, manifest, asset versions | Offline-shell contract passed in first four projects; source check | Reviewed | Desktop case interrupted; installed-client update race not manually observed |
| 14. Reliability/performance/observability | locks, bounds, logs, worker lifecycle, export | Unit suite; source trace | Findings 1 and 5 | Production-size timing unavailable |
| 15. Tests/verification quality | Python, Node, Playwright, fixture setup, CI | Results above | F4; A1; U1–U4 | Repeat/order-variation browser runs need fixture fixes |
| 16. Dependencies/container/runtime | Dockerfile, lock files, non-root/read-only runtime | Docker build and fixture health | Reviewed | Advisory/license scan not run |
| 17. CI/CD/releases | workflows, version/tag checks, permissions, SBOM | YAML/source review | Improvement A1 | Workflows not dispatched and repository settings not inspected |
| 18. Documentation/maintainability | README, `.env.example`, architecture docs, source placement | Source/doc comparison | Reviewed | Update docs after remediation |

## Coach capability and tool parity ledger

| User goal / natural-language examples | Canonical tool(s) and scope | Authorization / durable effect | Receipt, refresh, UI | Evidence / runtime result |
|---|---|---|---|---|
| Read profile, training state, activities, details, feedback, plans, competitions, weather/provider status | `read_profile`, `read_training_state`, `list_recent_activities`, `get_activity_details`, `list_change_history`, `list_competitions`, `list_training_plans`, `get_sync_job` | Read-only; local confirmed profile/competition records authoritative | Read response; no mutation | Schemas, catalog, dispatcher, unit tests; real semantic wording unverified |
| Inspect reusable templates and planned workouts | `list_workout_library`, `list_planned_workouts` | Read-only | Coach projection and library UI | Finding 3: archived rows can hide active templates |
| Save/update/delete check-ins, feedback, competitions, nutrition | `save_checkin`, `save_activity_feedback`, `delete_activity_feedback`, `save_competition`, `delete_competition`, `save_nutrition_entry`, `update_nutrition_entry`, `delete_nutrition_entry` | Explicit local request; durable local transaction | Receipt, change history, state refresh | Container tests passed; mixed wording still relevant to provider jobs |
| Create/replace/change local plans and templates | `stage_training_plan`, `commit_training_plan`, `replace_training_plan`, `apply_training_patch`, `apply_training_changes`, `manage_training_templates`, `apply_workout_library_plan`, `update_training_plan` | Local writes direct under current contract; adaptive apply has preview boundary | Receipt, plan/library refresh | Unit tests and catalog checks passed; browser plan fixture contaminated by shared state |
| Adaptive replanning, undo, duplicate repair | `preview_adaptive_replan`, `apply_adaptive_replan`, `undo_training_change`, `delete_duplicate_intervals_activity` | Remote/conditional actions require athlete approval and selected scope | Proposal/approval or receipt; refresh | Approval and manifest tests passed; no live remote write |
| Explicit provider refresh/current performance | `start_provider_refresh`, `refresh_current_performance` | Named request queues durable provider-read job | Job receipt, sync status/state events | Finding 2 can misstate queued completion; worker recovery Finding 1 |
| Explicit Intervals plan sync, competitions, nutrition sync, conflict resolution | `start_intervals_plan_sync`, `sync_competitions`, `sync_nutrition`, `resolve_training_sync_conflict` | Remote writes require approval where applicable; local-first records preserved | Remote job receipt and status | Unit tests passed; live provider blocked |
| Dialogue clarification/cancellation and follow-up | `clarify_coach_request`, `cancel_coach_request` | Request-state control; session/generation bound | Pending state/history refresh | Scripted follow-up/reload test; U1 concerns a separate proposal refresh |
| Change athlete profile; inspect nutrition and duplicate activities | `update_profile`, `read_nutrition`, `inspect_activity_duplicates` | Explicit local write for profile; other two read-only | Profile receipt/state refresh or read result | Catalog and focused tool/service tests reviewed; semantic selection not evaluated |

The active catalog was checked for schema-to-owner coverage, read/write sets, canonical names, receipts, and missing dispatcher branches. Scripted tool calls do not establish natural-language understanding. Required paraphrase, pronoun, correction, typo, negation, quotation, hypothetical, ambiguity, and provider-instruction cases remain a semantic follow-up.

## Message lifecycle and race/interleaving ledger

The intended ordering is: current session/turn accepted -> durable effect and receipt -> terminal response -> generation-checked browser reconciliation. Provider jobs extend that sequence through durable claim -> execution -> persisted terminal status; a queued receipt is not the terminal status (F2). Restore must quiesce active operations before replacing the database and invalidate old session/generation state. F1 breaks progress at the claim loop; F5 extends the writer critical section across compression. U1/U3/U4 require actual caller-order capture before attributing a missing guard.

| State / interleaving | Source and test evidence | Result / next task |
|---|---|---|
| Fast send, stream, completion, persisted history | `public/coach.js`, stream/receipt tests, Playwright contracts | Covered mechanically; proposal refresh anomaly U1 remains |
| Completion/history/proposal race | `applyCompletedChatStreamEvent`, `refreshCompletedChatStream`, proposal refresh | U1; identify both callers before selecting a fix |
| Bootstrap/scoped load reverse order | `public/app.js` generation/load sequence | Source and unit coverage reviewed; full browser delay matrix incomplete |
| Stream disconnect before delta/midstream/after completion | stream parser, recovery, cancellation tests | Source/unit covered; browser injection incomplete |
| Background fallback, reload, polling, recovery | job store/worker/status paths | Source/unit covered; worker lifetime Finding 1 |
| Cancel before operation ID, midstream, polling, simultaneous completion | cancellation/generation tests | Reviewed; full browser timing run incomplete |
| Rapid sends, queue, steer, duplicate turn | queue and client-turn tests | Reviewed; all viewport runtime combinations incomplete |
| Navigation, visibility, keyboard, reset | route/state handlers and Playwright scenarios | Started across projects; later browser results incomplete |
| Multi-tab and state events | Broadcast/session generation source and tests | Reviewed; controlled two-tab run not fully completed |
| Offline submit/reconnect and service worker | API error handling, service worker, contract test | Source/test reviewed; fresh-install race incomplete |
| Long receipts/Markdown/history | renderer and Node tests | Sanitization/unit coverage; visual overflow matrix incomplete |
| Restart after effect before receipt / worker reclaim | durable jobs and recovery tests | Unit coverage; disposable process restart follow-up remains |
| Export versus write/sync lock overlap | export lock scope and UOW | Finding 5; add concurrency regression test |

## API and error contract ledger

The following route inventory reconciles the concrete route modules with frontend callers. Authenticated routes use the session and CSRF checks owned by the HTTP boundary; streaming and state-event paths additionally bind generation/operation state. Exact payload validation and safe `{error, reason}` envelopes were inspected in each owner.

| Method / route family | Concrete paths | Success and user state | Error classes / validation | Result |
|---|---|---|---|---|
| GET public/authenticated bootstrap | `/api/health`, `/api/readiness`, `/api/auth/status`, `/api/bootstrap` | Public health/readiness/auth status; bootstrap requires authentication and projects athlete state | 401/503 as applicable | Reviewed |
| POST auth | `/api/login`, `/api/logout` | Session creation/invalidation | 400/401/rate limit; cookie/session cleanup | Reviewed |
| GET athlete | `/api/performance`, `/api/profile`, `/api/feedback`, `/api/context-preview` | Source-labelled local projection | 401/404/5xx; stale/partial state retained | Reviewed |
| PUT athlete/settings | `/api/athlete-context`, `/api/profile`, `/api/settings/model`, `/api/settings/ai-provider`, `/api/settings/thinking-level`, `/api/settings/calendar-display` | Validated local update and refresh | 400/403/409/5xx; CSRF | Reviewed |
| GET Coach | `/api/chat/history`, `/api/chat/receipt`, `/api/chat/status` | History, receipt, job status | 400 cursor, 401, 404/5xx | Duplicate history request investigation U1 |
| POST Coach/chat | `/api/chat`, `/api/chat/reset`, `/api/chat/cancel`, `/api/chat/stream` | Stream/background result, durable messages/receipts | 400/401/403/409/413/422/429/5xx, abort/retry | Reviewed; browser matrix incomplete |
| POST Coach actions | `/api/coach/actions/confirm`, `/api/coach/actions/cancel`, `/api/coach/actions/execute` | Proposal state/approved effect | 400/403/404/409/5xx, session/turn binding | Reviewed |
| GET/POST planning | `/api/plan`, `/api/weather`, `/api/library`, `/api/planning/commands` | Local plan/library and explicit commands | 400/404/409/422/5xx | Library parity Finding 3 |
| GET/POST sync | GET `/api/sync/status`, `/api/sync/jobs/{id}`, `/api/activities`; POST `/api/sync/jobs`, `/api/sync/jobs/{id}/resolve`, `/api/sync`, `/api/intervals/full-resync`, `/api/garmin/sync`, `/api/garmin/full-resync`, `/api/performance/refresh`, `/api/external-calendar/sync`, `/api/weather/sync`, `/api/nutrition/sync` | Job enqueue/status/activity projection; full-resync confirmation | 400/401/404/409/429/5xx | Worker recovery F1 |
| GET/POST/PUT feedback/nutrition | GET/POST `/api/feedback`; GET `/api/nutrition/day`, `/api/nutrition/range`; POST/PUT `/api/nutrition/entry`; POST `/api/nutrition/entry/delete` | Validated records | 400/404/409/422/5xx | Reviewed |
| GET/POST history | GET `/api/change-history`; POST `/api/change-history/undo/preview`, `/api/change-history/undo` | Local history and scoped undo | Session/CSRF, stale preview/unknown target | Reviewed |
| GET/POST privacy | `/api/privacy/export`, `/api/privacy/delete/preview`, `/api/privacy/backup`, `/api/privacy/delete`, `/api/privacy/restore` | Bounded archive/preview/delete/restore | 400/403/409/413/507/5xx; maintenance | Export lock Finding 5; destructive runtime blocked |
| GET diagnostics/events | `/api/logs`, `/api/logs/download`, `/api/diagnostics`, `/api/state/events` | Redacted diagnostics/SSE | 401/403/404/5xx, reconnect | Reviewed; full SSE race matrix incomplete |
| POST media | `/api/transcribe` | Short-lived editable transcript | 400/413/415/429/5xx | Reviewed; real microphone matrix incomplete |

Required 400, 401, 403, 404, 409, 413, 422, 429, 500, 502, 503, 504, malformed-response, timeout, reset, and abort cases were inspected in validators/tests and partially injected in Playwright. The full per-route browser injection matrix remains a follow-up and is not represented as a pass.

## Provider and recovery ledger

| Provider | Paths, freshness, persistence, recovery, Coach/UI visibility | Runtime result / gap |
|---|---|---|
| Intervals.icu | Incremental/full snapshots, activities, calendar/planned sync, competitions, library push, cursors, tombstones, local authority, explicit remote actions | Mocked/container tests passed; no live provider or remote write |
| Garmin Connect | Token-store boundary, windowed metrics/activity sync, snapshots, Body Battery, freshness labels, fixture path | Fixture and unit tests passed; MFA/live partial failure not run |
| Public iCalendar | HTTPS/SSRF/pinned-address fetch, bounded recurrence, timezone/event text as data, last-good state | Source/tests reviewed; DNS rebinding and live feed not run |
| Weather | Location-derived forecast, cache/backoff, stale/error state, plan visibility | Unit/source reviewed; no live weather |
| OpenAI Responses | Conversation create/resume/reset, streaming/background, cancellation, tools, usage, redaction, model setting | Mocked tests passed; no real model semantic evaluation; Finding 2 applies to status projection |
| Gemini | Equivalent stream/tool/history/media path and provider selection | Mocked tests passed; no live model |
| GitHub release status | Optional status/version/release validation | Source/workflow reviewed; no live GitHub request |

Cross-provider success/failure combinations, startup/daily/manual/named refresh overlap, pagination boundaries, duplicate/out-of-order records, rate limits, malformed schemas, and recovery were covered by mocks/source where available but not certified against live services.

For **each** provider above, the live scenarios blocked by unavailable disposable provider accounts are: never configured/loaded, authentication, fresh/stale/partial data, invalid credentials, rate limit, timeout, malformed/schema-drift response, empty success, pagination boundary, duplicate/out-of-order records, transient/persistent failure, and recovery. Startup, daily, manual, named Coach refresh, concurrent refresh, and safe full-resync routes were traced; their full UI-observed cross-product was not executed. In particular, Intervals-success/Garmin-failure, the inverse, calendar-only failure, weather-only failure, and provider recovery during a Coach turn need deterministic integration fixtures. Use mock endpoints first; do not connect a real athlete account to fill this gap.

## Journey and viewport ledger

| Project | Viewport | Runtime result |
|---|---:|---|
| `mobile-small` | 320×568 | All 54 scheduled cases reached completion; 2 failures (U1/U2). |
| `mobile` | 390×844 | All 54 scheduled cases reached completion; 3 failures (F4/U1/U2). |
| `tablet` | 768×1024 | All 54 scheduled cases reached completion; 3 failures (F4/U1/U2). |
| `tablet-landscape` | 844×390 | All 54 scheduled cases reached completion; 3 failures (F4/U1/U2). |
| `desktop` | 1440×1000 | 27 cases completed, 6 failures (U3/U4); interrupted during its 28th case after repeated hidden-shell failures. Last 26 cases not started. |

The viewport run exercises the existing automated suite, not every possible combination of screens and failures. It does not replace the following explicit gaps.

| Journey | Observed/test evidence | Remaining prerequisite |
|---|---|---|
| Login, navigation, profile dirty/save, core layout | `coach.spec.js`, audit-remediation tests, WCAG AA assertions | Manual physical touch/keyboard review remains unperformed |
| Stream, long Markdown, scroll, navigation, reload, clarification | Coach and contract suites with synthetic responses | Real model semantics and every disconnect point need separate fixtures/evaluation |
| Queue/cancel/reset, rejected drafts, cross-tab generation changes | Audit-remediation and contract scenarios | Every background restart/remote-effect interleaving still requires process fault injection |
| Planning commit/replay/sport rendering | SQLCipher fixture test | F4 blocks later viewports |
| History/library pagination | Synthetic cursor test | Desktop anomaly U3 needs explanation |
| Performance date/source/freshness | Contract source-label tests; diagnostic test | U2 blocks a reliable synthetic age assertion |
| Every Coach mutation/named sync and reload | Tool catalog and backend tests | Full browser execution for every tool not implemented in the fixture |
| Nutrition, competitions, adaptive apply, conflict resolution | Backend tests and source trace | Dedicated browser fixture journeys required; no live remote mutation |
| Privacy export/delete/backup/restore | Source and temporary-storage tests | Full destructive browser journey and process-failure recovery require disposable integration fixtures |
| HTTP rejection/malformed response/session expiry | Contract error injection and unauthorized tests | U4; exhaustive per-route error and old/new asset cross-product not executed |
| Fresh service-worker/offline shell | `contracts.spec.js:379` | Installed-client upgrade race and platform installation UI not manually verified |
| Microphone | Mocked late-permission/logout and transcription/error scenarios | Physical microphone, granted/denied/unsupported/timeout/oversize/abort combinations not all observed |
| Notifications | Source inspection and existing UI tests where applicable | OS-level granted/denied/unsupported/duplicate/click paths not independently exercised |
| State events, hidden/offline, polling takeover | State-events tests and contract lease test | Saturation and every cross-tab overlap not measured |
| Accessibility and console/network | Automated core-view axe/layout/browser-error assertions | All dialogs, long/error states, physical mobile keyboard, reduced motion, and manual focus audit remain unperformed |

## Areas checked without an additional actionable finding

- `APP_PASSWORD` minimum length, SQLCipher fail-closed startup, session cookies, CSRF structure, maintenance/readiness protection, and restore session invalidation.
- Local profile and competition authority versus OpenAI conversation continuity; external provider/calendar content remains data rather than instructions.
- Local-first workout creation, adaptive preview/apply boundaries, explicit remote synchronization, conflict adoption, tombstones, and duplicate repair.
- Calendar URL restrictions, bounded parsing, Markdown sanitization, voice non-persistence, redacted diagnostics, and service-worker API exclusion.
- Non-root/read-only Docker runtime, pinned/hash-locked dependencies, immutable release-source/version checks, and protected-main release flow.
- Current schema initialization and repository transaction/reader ownership under the isolated test suite.

## Limitations and follow-up

- The browser process was deliberately interrupted during test 244/270 after repeated desktop startup failures. The 17 completed failures are listed above; the active case and remaining 26 cases have no completed desktop result. This is not a clean browser certification.
- Real OpenAI/Gemini semantic behavior, live Intervals/Garmin/calendar/weather/GitHub contracts, and remote writes were intentionally not exercised.
- Full SQLCipher load, process restart during an effect, restore overlap, and failure-injection journeys need a disposable integration run.
- Current dependency advisory/license checks and GitHub workflow dispatch/settings were not run.
- The next thread should use the independent F1–F5 tasks and U1–U4 investigations above, then consider A1–A3. Update a remediation log only after each task has observable evidence; do not mark a defect resolved from code changes alone.

## Completion statement

`Complete for the recorded source snapshot; all checklist domains were reviewed or explicitly blocked.` This is a complete source-and-test review, not a certification of unavailable live-provider or unfinished browser runtime behavior.
