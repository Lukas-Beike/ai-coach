# Design

## Context

See [proposal.md](proposal.md) for scope and motivation. This design applies because the change spans local tooling, CI orchestration, browser session isolation, and performance-sensitive fixtures.

Inspected revision: `c7ff60519520d553a00bfd33f6cf884b8de879b8`. The working branch was clean before scaffolding this change. The planning session uses parent-only execution; no independent worker review or runtime implementation validation is claimed.

Observed owners and behavior:
- `.github/workflows/publish-container.yml` builds the application image once, starts browser jobs after the image, and runs Python shards in parallel. Browser setup installs Chromium system dependencies separately from the Chromium binary cache.
- The inline browser loop discovers files through Playwright, gives each spec a fresh fixture, prewarms one successor, and creates stable network namespaces before Chromium starts. Preserve the reason for this topology: changing host interfaces mid-test previously caused network-change errors.
- `playwright.config.cjs` has one worker, desktop functional coverage, four additional responsive projects, and CI failure-on-flaky behavior.
- `e2e/auth.setup.js` and the Playwright config currently share one authentication-state path. Separate local processes must not continue sharing that path.
- `tests/run_tests.py` already implements deterministic, duration-weighted assignment of whole classes. `tests/run_sqlcipher_tests.ps1` builds current source and runs the complete suite in one networkless container limited to one CPU.
- `tests/test_fixture_standard_data.py` constructs full demo datasets in several lifecycle tests, including seven independent weekday collision cases. Historical recorded class time is not a hosted critical-path measurement.

Hosted baseline on 25-26 October 2026: twelve completed runs, eight successful. Slowest job medians among successful runs were 148 seconds for Python and 530.5 seconds for browser jobs. The browser path finished later in all twelve runs. Run [40229467947](https://github.com/Lukas-Beike/ai-coach/actions/runs/40229467947) spent 575 seconds installing system packages and 167 seconds executing its slowest browser job's tests; run [40266532844](https://github.com/Lukas-Beike/ai-coach/actions/runs/40266532844) spent 490 and 304 seconds respectively. These runs cover different commits, so they establish priority, not controlled before/after gains.

The Windows browser runbook describes a full isolated matrix exceeding two hours; this was not newly benchmarked here. The previous broad local per-test-context coverage session lost its terminal status after a host interruption. Neither observation is a measured local baseline for this implementation.

## Goals / Non-Goals

**Goals:**
- Improve complete validation wall time without changing the selected test/project set or weakening correctness checks.
- Make focused local runs easy to invoke and unmistakably scoped.
- Share the existing fixture lifecycle between local execution and CI, keeping orchestration small and dependency-light.
- Bound concurrency, retain independent state, and make result ownership and failure propagation auditable.
- Measure setup, execution, and resource consumption separately.

**Non-Goals:**
- Removing or retagging tests to meet a duration target.
- Replacing unittest, Playwright, Docker, SQLCipher, or current release gates.
- Making multiple Playwright workers share a mutable application fixture.
- Adding a persistent fixture service, general build cache framework, production schema migration, or new paid runner infrastructure.
- Claiming provider/mobile-device behavior from synthetic desktop-browser fixtures.

## Decisions

### 1. Extract the existing browser loop into one standard-library command

Add `scripts/run_browser_tests.py` as the orchestration owner, with the CI workflow and README calling it. Proposed inputs are `--project`, repeatable `--spec`, `--shard`, `--total`, `--jobs`, `--image`, `--results-dir`, and `--list`; final spelling can follow existing repository conventions without changing the specified behavior.

Use Playwright's locked local CLI and its project-aware JSON listing. Never infer the set through a filename grep or a cached global/npx fallback. List mode resolves the same assignment used by execution and does not start fixtures. Complete mode lists all configured projects; focused requests report their limited scope. A zero-match request is an error.

Keep fixture lifecycle, process supervision, summary writing, and file assignment cohesive. Use subprocess argument arrays and standard-library facilities; no shell-generated deletion commands or new orchestration dependency. Local Windows process launching must not open visible helper windows.

Alternative: keep separate Bash and PowerShell implementations. Rejected because their selection, cleanup, and isolation behavior would drift. Alternative: a generic multi-runner framework. Rejected as unnecessary for the existing two test engines.

### 2. Separate preparation from browser execution

Use a prepared Linux browser environment pinned by digest and matched to the exact locked `@playwright/test` version. Resolve and verify that digest before wiring it into CI; the documentation's example version is not the project's pin. The [official image documentation](https://playwright.dev/docs/docker) confirms that browser images contain browsers and system dependencies and require project/image version agreement.

Prefer the matching upstream prepared image. If that exact environment cannot be obtained, retain the same architecture with a small test-only image definition preparing the locked toolchain once through the existing CI image/cache facilities. Do not silently alter the dependency version or add a privileged PR registry-publishing workflow. No application code or athlete/runtime data belongs in the reusable browser environment.

Record the resolved browser version, image digest, OS, and package-lock identity in the run summary. Validate version compatibility before invoking tests. Ordinary matrix jobs do not run OS-package installation. Locked project dependencies remain installed from the checked-out lockfile, with dependency installation scripts disabled unless an existing prerequisite requires otherwise.

The application image remains a separate current-source artifact and keeps its existing non-root runtime and SQLCipher settings. Locally, prepare locked Node/Chromium tooling once when inputs change; focus runs need not download it repeatedly. Do not remove mandatory application rebuilds after application/dependency/startup changes.

Alternative: cache the Chromium binary alone. Insufficient because it does not cache OS packages. Alternative: change only the moving Ubuntu runner label. Insufficient evidence that this removes the dependency-download tail.

### 3. Give each invocation a resource namespace and own its children

Generate a run identity plus project/shard identity. Use it for both prewarm slots, network/container labels, port reservations, auth-state paths, coverage files, and result directories. Configure auth setup and Playwright storage state from the same per-invocation path. Each spec gets a separate report subdirectory and authenticates against its own fresh fixture.

Retain the current two-slot prewarming model and create network namespaces before launching browsers. On Linux CI, make the prepared browser environment reach only the intended loopback fixture endpoints with explicit networking; verify localhost/service-worker behavior in the disposable environment. Keep the existing supported Windows/native-browser path, avoiding reliance on Linux host networking on Docker Desktop.

Readiness waits remain bounded. Reserve/verify ports and record the observed container identities before cleanup. On cancellation or child failure, stop and reap owned children, then remove only owned disposable resources. Cleanup failures remain visible without replacing the original test failure. Never use production mounts, `.env`, persistent-volume deletion, shared authentication files, or session-bearing CI trace uploads.

Alternative: increase `workers` in the current Playwright config. Rejected because test scenarios intentionally mutate shared application/session state.

### 4. Schedule whole browser files using frozen measured weights

Store a small timing input keyed by project and relative spec file, following the existing Python timing-file pattern. The exact fixture and browser environment identity accompanies the measurement. Use longest-first assignment to the least-loaded shard, stable path tie-breaking, and a deterministic median fallback for unseen files. Ignore timings as a selection filter: missing, stale, or unavailable timings never drop tests. Validate malformed timing inputs clearly.

Every job in a run uses the same frozen selection/timing input; do not repartition from measurements collected partway through the run. Keep files intact and retain one worker inside an invocation. This follows Playwright's supported [file-level sharding boundary](https://playwright.dev/docs/test-sharding), while the shared runner preserves per-file fixture reset.

After prepared-environment validation, evaluate two shards for each of the four mobile/tablet projects; retain two desktop shards. Keep existing required aggregate contexts and Python shard names. A larger browser matrix increases scheduling/setup and runner-minutes; retain the larger matrix only with measured wall-time benefit and documented resource cost.

Locally default to conservative serial execution for compatibility, with an explicit bounded two-process mode as the first benchmark candidate. Do not launch every project/shard at once on an unmeasured Docker Desktop host.

### 5. Reduce fixture work at its existing owner

Separate reusable synthetic input generation by relevant domain in `e2e/fixture_runtime.py` or a small adjacent fixture-only module. Specialized calendar/collision tests use the same relevant planning/calendar generation as the full seed without generating unrelated nutrition, performance, or activity history.

Maintain all seven weekday cases. Keep full-demo lifecycle, old-version upgrade, restart, and repeated-seed checks executing the real complete seed. Never replace integration outcomes with mocks merely to make these tests faster. Prefer immutable generated inputs copied per case; do not start with a database-snapshot cache or shared mutable database.

Audit which setup phases actually dominate browser runs before reducing browser fixture inputs. Current CI prewarming already hides some setup work, and the normal fixture startup only auto-seeds demo data when configured. Do not assume all browser specs currently pay for full demo seeding.

Alternative: cache one writable database for many tests. Rejected because it changes state isolation and can hide lifecycle defects.

### 6. Extend local Python orchestration instead of replacing it

Extend `tests/run_sqlcipher_tests.ps1` with a bounded worker/process option while retaining the existing invocation and serial default. Build the application image once from current worktree inputs, then invoke the existing `--shard/--total` interface in separate temporary containers with distinct outputs. Keep per-container CPU/memory limits explicit and benchmark one versus two workers within the host's capacity.

Preserve whole-class assignment, synthetic temporary data, network isolation, read-only inputs, and complete coverage merging when coverage is requested. Use existing unittest module/pattern selection for focused native development; no automatic impact-based skipping or new test framework. Routine timing and complete validation do not require expensive per-test dynamic coverage contexts; reserve them for focused redundancy investigations.

Refreshing `tests/test_durations.json` follows the existing full-run recording recipe and does not overwrite it from partial/sharded measurements.

### 7. Persist evidence and treat speed as an evaluated outcome

Write a small versioned JSON summary plus sanitized child output into the run directory. At minimum record revision/worktree state, selection mode, project/shard or Python class partition, tool/image identities, cold/warm state, phase start/end times, exit status, and completed/failed/interrupted state. Write the manifest before launching work and update results atomically as children finish.

CI uploads only a sanitized summary and the already allowed failure artifacts. Authentication state and session-bearing traces remain local and excluded. Where a hosted process is forcibly stopped before finalization, an incomplete manifest is unverified/interrupted evidence, never a pass.

Compare browser setup, fixture readiness, authentication, execution, image transfer, critical-path wall time, queue delay where available, and total runner-minutes. Use the same local hardware/settings and test selection before/after. Collect at least five comparable successful hosted runs before claiming a hosted median improvement, while reporting failures and cold-cache results separately.

Evaluation goals: GitHub median wait from workflow creation until required test/browser/quality gates finish below six minutes, excluding review/publication; local complete Python and complete browser selections each at least 30% faster than their own newly recorded baseline. These are provisional optimization goals, not timing-based correctness gates or guaranteed results. If a goal is missed, retain the evidence and identify the remaining phase instead of weakening checks or removing cases.

## Risks / Trade-offs

- A prepared image may replace apt delay with a large cold pull -> measure complete cold/warm startup and pin a reproducible version; preserve the previous environment path as an explicit rollback.
- Extra shards can increase runner-minutes or queue delays -> start with two, record both cost and wall time, and keep serial/fewer-shard execution available.
- Per-run paths can still collide if one caller uses legacy defaults -> make the shared runner pass the same explicit auth/output identity to setup and execution; test overlapping invocations.
- Windows and Linux process/network behavior differ -> preserve stable per-slot networking, unique loopback endpoints, bounded hidden subprocesses, and platform-specific failure checks.
- Smaller fixtures can stop exercising an interaction -> compare relevant generated records and retain full-seed lifecycle cases and existing assertions; do not alter released-schema fixtures.
- Timing inputs can drift after dependencies or tests change -> record provenance and include every unseen file using a stable fallback.
- Background/client interruptions can lose final status -> persist an initial manifest and incremental child results; incomplete evidence remains visibly unverified.

## Migration Plan

1. Reconcile the implementation baseline and then-current workflow; record local and hosted baselines without changing selected tests.
2. Introduce the shared runner with serial execution, isolated per-run paths, and persisted evidence; switch the CI inline loop only after selection/fixture parity checks.
3. Adopt the prepared browser environment, retaining the same matrix initially; validate network, installation, fresh PWA, and failure artifacts.
4. Enable measured file-weight scheduling and bounded parallel modes; trial the expanded mobile/tablet matrix and compare runner-minutes.
5. Apply focused fixture reductions and local Python process support; update measurements and README commands after each stage.
6. Run complete required validation on the final tree and record performance goals as met, missed, or unverified. Do not change required checks, retries, assertions, or timeout limits to obtain a pass.

Roll back each stage independently: return to serial/fewer shards, restore the prior browser-environment setup, or revert a fixture optimization while retaining the shared selection and evidence contracts. This migration changes disposable test infrastructure only; it does not migrate or recreate athlete storage.

## Evidence and planned verification
These are proposed developer-facing contracts, not a claim that the new entry points or optimizations already exist. Current source at `c7ff60519520d553a00bfd33f6cf884b8de879b8`: `tests/run_tests.py`, `tests/run_sqlcipher_tests.ps1`, `playwright.config.cjs`, `e2e/auth.setup.js`, `e2e/fixture_runtime.py`, `.github/workflows/publish-container.yml`, and `README.md`.

Existing regression owners to preserve and extend: `tests/test_ci_contracts.py`, `tests/browser-selection.test.cjs`, and `tests/test_fixture_standard_data.py`. New execution/isolation/result scenarios require focused implementation tests. The existing `build-release-and-deployment` and `web-pwa-and-accessibility` contracts remain authoritative for validation gates and application behavior.

## Open Questions

No unresolved product or contract decision blocks the plan. The exact matching prepared-image digest and the best local concurrency limit are implementation-time compatibility/performance measurements within the decisions above; a mismatch is reported rather than silently changing dependencies or isolation.
