# Spec Delta

## Purpose

Provide developers and CI with reproducible, isolated test execution that reduces avoidable setup and fixture work while retaining the selected functional, responsive, security, and persistence checks and their failure signals.

The requirements below are proposed behavior; baseline source references do not claim that the new behavior is already implemented.

## ADDED Requirements

### Requirement: Explicit selection preserves the complete validation set
The test entry points SHALL expose explicit focused and complete selections. Complete execution SHALL preserve the existing test cases, assertions, and project assignments. Focused execution SHALL identify its limited selection and SHALL NOT represent itself as complete validation.

#### Scenario: Complete browser execution is partitioned
- **WHEN** the complete browser selection is divided between jobs
- **THEN** the union of selected test/project identities equals the unpartitioned selection and every identity is assigned exactly once.

#### Scenario: Developer requests a focused run
- **WHEN** a developer selects a project, spec, or Python module
- **THEN** the runner reports that selection and its result without omitting any case inside the selected scope or claiming complete-suite success.

#### Scenario: Invalid or empty selection
- **WHEN** an unknown project, invalid shard, or selection matching no tests is requested
- **THEN** execution fails clearly rather than returning a successful empty run.

Baseline evidence and verification owners: `playwright.config.cjs`, `tests/run_tests.py`, and `tests/browser-selection.test.cjs`.

### Requirement: Prepared browser execution matches the locked toolchain
Regular CI browser jobs SHALL use a prepared, immutable browser environment containing the browser and required system packages for the locked test-tool version. Preparation SHALL be distinct from ordinary test execution, and missing or incompatible tooling SHALL fail explicitly.

#### Scenario: Ordinary browser job
- **WHEN** a regular CI browser job starts using the prepared environment
- **THEN** it executes the locked browser toolchain without installing browser system packages from operating-system mirrors during that job.

#### Scenario: Locked browser version changes
- **WHEN** the browser test dependency changes
- **THEN** the prepared environment identity changes with it and a mismatched existing environment is rejected before test execution.

#### Scenario: Local preparation is missing
- **WHEN** a local run lacks its required locked toolchain or application image
- **THEN** it reports the missing prerequisite and does not silently use an unrelated cached executable or bypass encrypted application startup.

Baseline evidence and verification owners: `.github/workflows/publish-container.yml` and `package-lock.json`; new compatibility checks are planned.

### Requirement: Concurrent invocations own disjoint resources
Each concurrent invocation SHALL own distinct container and network names, loopback ports, authentication-state files, result directories, and coverage outputs. A run SHALL NOT read another invocation's session state or stop, overwrite, or remove resources it does not own.

#### Scenario: Two local browser invocations overlap
- **WHEN** two invocations authenticate against different disposable fixtures
- **THEN** each retains its own valid session and neither invocation overwrites the other's authentication or result files.

#### Scenario: Port or output ownership conflicts
- **WHEN** a requested resource is already in use by another invocation or an unrelated application
- **THEN** the runner chooses and reports a verified available resource or fails without altering the existing owner.

#### Scenario: Cancellation or partial startup
- **WHEN** an invocation is cancelled or startup fails after some resources were created
- **THEN** its active children are stopped before cleanup and only its observed disposable resources are removed, without deleting persistent volumes or another run's evidence.

Baseline evidence and verification owners: `e2e/auth.setup.js` and `playwright.config.cjs`; new concurrent-isolation checks are planned.

### Requirement: Browser specs receive independent disposable state
Every browser spec invocation SHALL start from fresh synthetic application state with mocked providers and authenticated SQLCipher startup. Prewarming SHALL preserve this isolation, stable networking during browser execution, and the existing non-root read-only fixture runtime boundary.

#### Scenario: Previous spec deletes data or sessions
- **WHEN** a subsequent spec starts after a destructive or stateful spec
- **THEN** its fixture and authentication are independent of the earlier spec's mutations.

#### Scenario: Next fixture is prewarmed
- **WHEN** another fixture starts while a browser spec is executing
- **THEN** the current browser endpoint and network remain stable and no application state is shared between the two fixtures.

#### Scenario: Fixture cannot become ready
- **WHEN** a fixture does not become ready within the bounded readiness period
- **THEN** the invocation fails with sanitized diagnostics and does not continue against an old or connected installation.

Baseline evidence and verification owners: `e2e/fixture_runtime.py` and the existing workflow per-spec loop; lifecycle regressions include `tests/test_fixture_standard_data.py`.

### Requirement: Browser scheduling is deterministic and bounded
Browser scheduling SHALL keep each spec file intact, retain one worker within each spec invocation, and support an explicit bounded shard/process count. Given the same selection and timing input, the assignment SHALL be deterministic and SHALL include new specs without recorded durations.

#### Scenario: Duration-aware file assignment
- **WHEN** per-project file timings are available
- **THEN** files are assigned using those recorded weights without splitting a file or changing which tests run for that project.

#### Scenario: Timing record is missing
- **WHEN** a selected file has no timing record
- **THEN** it receives a documented deterministic fallback weight and remains in the complete selection.

#### Scenario: Parallel execution is constrained locally
- **WHEN** a local concurrency limit is configured
- **THEN** the number of active invocations never exceeds that limit and independent processes retain separate fixtures and reports.

Baseline evidence and verification owners: the workflow browser matrix and `tests/browser-selection.test.cjs`; duration-weighted browser assignment is proposed.

### Requirement: Local Python execution preserves class and coverage ownership
Local Python execution SHALL reuse the existing class-preserving shard assignment with an explicit bounded process count. Complete container validation SHALL use the current application build, isolated temporary data, and the existing SQLCipher path; each coverage shard SHALL have an independent output.

#### Scenario: Complete local Python suite is sharded
- **WHEN** a developer runs the complete suite across several processes
- **THEN** every discovered test executes exactly once, each test class stays in one shard, and the aggregate preserves any child failure.

#### Scenario: Application source changed
- **WHEN** container validation is requested after application, dependency, or startup inputs changed
- **THEN** the test application image is rebuilt from those inputs before being used as current validation evidence.

#### Scenario: Complete coverage evidence is requested
- **WHEN** all Python shards finish
- **THEN** their coverage outputs can be combined without overwriting one another and missing or failed shards cannot produce complete successful evidence.

Baseline evidence and verification owners: `tests/run_tests.py`, `tests/run_sqlcipher_tests.ps1`, and `tests/test_ci_contracts.py`.

### Requirement: Smaller fixtures retain the tested domain behavior
Fixture optimization SHALL preserve each existing scenario's relevant records, expected results, and state isolation. Specialized cases SHALL retain their upgrade, restart, idempotence, and weekday coverage; complete-demo checks SHALL continue to exercise complete synthetic demo construction.

#### Scenario: Calendar collision checks use smaller inputs
- **WHEN** collision cases for all seven weekdays avoid unrelated synthetic history
- **THEN** they still use the same relevant planning/calendar generation behavior and retain every existing collision and date assertion.

#### Scenario: Complete seed lifecycle is checked
- **WHEN** full-demo creation, an older demo version, or a repeated seed/start is tested
- **THEN** the complete-seed lifecycle and its existing assertions remain exercised independently of smaller specialized fixtures.

#### Scenario: One optimized case changes its fixture
- **WHEN** that case mutates its prepared data
- **THEN** later cases start with independent state rather than inheriting a shared mutable fixture.

Baseline evidence and verification owners: `e2e/fixture_runtime.py` and `tests/test_fixture_standard_data.py`.

### Requirement: Execution evidence survives interruption without exposing sessions
Every launched invocation SHALL persist its selection, revision, environment identity, phase timings, and final or interrupted status outside live application storage. Failed or interrupted runs SHALL remain distinguishable from passing runs, and reports intended for CI publication SHALL exclude credentials, authentication state, and session-bearing traces.

#### Scenario: Interactive client disconnects
- **WHEN** the interactive session ends before test execution finishes
- **THEN** completed results remain available on disk and unfinished invocations are identifiable without being counted as passed.

#### Scenario: Evidence contains a failed child
- **WHEN** a child process, fixture preparation, or required test fails
- **THEN** the summary and aggregate exit status retain the failure and cleanup does not erase the sanitized evidence.

#### Scenario: Browser reports are uploaded
- **WHEN** CI publishes diagnostic artifacts
- **THEN** the artifact selection excludes authentication-state files, credentials, and session-bearing traces even for newly added shards.

Baseline evidence and verification owners: the workflow artifact exclusions and `playwright.config.cjs`; durable per-invocation summaries require new tests.

### Requirement: Performance comparisons retain their provenance
Performance comparisons SHALL distinguish setup, fixture, authentication, test execution, queue delay where available, and summed runner time. They SHALL identify the source/environment and cold or warm state, and SHALL NOT classify a timing target as a correctness failure or substitute local timings for hosted critical-path evidence.

#### Scenario: Before and after results are compared
- **WHEN** an optimization is evaluated
- **THEN** the comparison records the selection and environment differences and separates observed wall-time improvement from additional concurrent runner consumption.

#### Scenario: Runner is slow but tests are correct
- **WHEN** a run misses a performance goal while its required checks pass
- **THEN** the performance report records the missed goal without changing the functional test result.

#### Scenario: Prerequisite or terminal result is unavailable
- **WHEN** a benchmark lacks Docker, a browser, SQLCipher support, or a recoverable terminal result
- **THEN** that evidence is reported as blocked, not run, or unverified rather than successful.

Baseline evidence and verification owners: `README.md`, `tests/test_durations.json`, and the hosted run evidence recorded in the change design; expanded phase comparisons are proposed.
