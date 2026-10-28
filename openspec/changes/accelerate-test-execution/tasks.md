# Tasks

Implementation checklist only. No item below was implemented by the proposal workflow. Preserve the complete test/project set and current required gates throughout. References: [design](design.md) and [isolated-test-execution requirements](specs/isolated-test-execution/spec.md).

## 1. Baseline and durable measurement

- [x] 1.1 Reconcile the implementation branch with its current target and inspect the then-current workflow, runner, fixture, and auth owners; verify by recording revision, dirty-tree state, selected test/project identities, tool versions, and any differences from the inspected proposal baseline.
- [ ] 1.2 Define the small versioned run-summary format and capture comparable local Python/browser baselines plus existing GitHub job/step evidence; verify by delivering phase timings, cold/warm labels, resource settings, exit status, and explicit blocked/unverified entries where prerequisites or terminal results are missing.
- [x] 1.3 Add focused tests for atomic manifest/result writes, failed children, and interrupted evidence; verify that an incomplete or failed summary never reports complete success and contains no auth-state or credential fields.
- [x] 1.4 Document the baseline-recording procedure and provisional goal definitions in README; verify a parent walkthrough can distinguish local full/focused results, hosted critical-path time, and summed runner-minutes without needing chat history.

## 2. Shared browser runner and per-run isolation

- [x] 2.1 Extract the existing CI per-spec lifecycle into the standard-library browser runner with project/spec selection and list mode; verify against Playwright's project-aware listing, including invalid project, invalid shard, and zero-match failures.
- [x] 2.2 Parameterize the auth-state path in auth setup and Playwright configuration and assign unique run/project/shard/spec output paths; verify overlapping disposable invocations do not overwrite sessions, reports, or coverage.
- [x] 2.3 Preserve the two-slot fresh-fixture/prewarm topology with stable network namespaces, bounded readiness, non-root read-only SQLCipher fixtures, and owned resource cleanup; verify startup failure, cancellation, unrelated-resource collision, and a stateful/destructive spec followed by a fresh spec.
- [x] 2.4 Persist selection, phase timing, sanitized output, and child exit results from the runner; verify evidence remains on disk after simulated client interruption and cleanup retains the original failure.
- [x] 2.5 Replace the workflow's inline browser loop with the shared runner using the existing matrix first; update focused CI/browser-selection tests and README/runbook instructions, then verify identical test/project selection, artifact exclusions, aggregate check names, and failure-on-flaky behavior.

## 3. Prepared browser environment

- [x] 3.1 Resolve a digest-pinned prepared browser environment matching the exact locked Playwright version; verify its declared and observed versions and reject a deliberate mismatch without changing the project's dependency version.
- [x] 3.2 Wire that environment into browser CI jobs, using a small test-only preparation definition with existing image/cache facilities only if the matching upstream environment is unavailable; verify ordinary matrix jobs perform no OS-package installation and introduce no privileged PR publication path.
- [ ] 3.3 Validate communication with the existing fixture slots and preserve the supported Windows/native-browser path; verify real disposable login, fresh service-worker installation/offline start, streaming/cancellation, and fixture readiness on the affected environments.
- [ ] 3.4 Add focused prepared-environment compatibility/workflow regressions and document preparation, version updates, and rollback in README; verify cold and warm complete setup costs, dependency failure behavior, and absence of authentication-state or traces in CI uploads.

## 4. Browser scheduling and bounded concurrency

- [x] 4.1 Add frozen per-project/spec duration inputs and deterministic whole-file assignment with documented fallback weights; verify synthetic uneven timings, stable tie-breaking, malformed input, and unseen files without dropping any selected identity.
- [x] 4.2 Add bounded local execution with distinct containers, ports, auth paths, and reports while retaining one Playwright worker per invocation; verify the active-process limit and successful concurrent isolated runs at one and two processes.
- [ ] 4.3 Trial two shards per mobile/tablet project while retaining two desktop shards and the required aggregate contexts; verify every original test/project identity is selected exactly once, new/missing/failed shards fail aggregation, and queued jobs cannot hide missing evidence.
- [ ] 4.4 Update scheduler/selection regression tests and README/runbook concurrency guidance with the scheduling changes; verify deterministic listing and report the wall-time, queue-time, and runner-minute trade-off before retaining the expanded matrix.

## 5. Smaller fixtures with retained lifecycle coverage

- [x] 5.1 Separate reusable planning/calendar synthetic input generation at the existing fixture owner and use it in specialized collision checks; verify all seven weekdays, generated relevant records, and existing date/collision assertions against the full-seed behavior.
- [x] 5.2 Retain full-demo seed, older-version upgrade, repeated-seed, and restart integration cases with independent state; verify their existing outputs and mutation isolation, without changing frozen released-schema fixtures or substituting mocks for the effects under test.
- [ ] 5.3 Measure browser fixture readiness before changing its data scope and remove only demonstrated unrelated setup work; verify every affected browser spec against a fresh disposable fixture and record the per-phase before/after results.
- [x] 5.4 Land focused fixture parity/isolation regression tests and update the fixture ownership documentation where changed; verify the optimized groups and the retained complete lifecycle groups pass together and publish their comparable timings.

## 6. Local Python process execution

- [x] 6.1 Extend the existing SQLCipher PowerShell helper with an explicit bounded worker option and backward-compatible serial mode; verify one current-source image build, separate temporary containers/output ownership, explicit CPU/memory bounds, and no access to live environment/data mounts.
- [x] 6.2 Reuse whole-class shard assignment and aggregate child failures and coverage without collisions; verify every discovered test runs exactly once, no class is split, and failed or missing shard output prevents complete success.
- [x] 6.3 Preserve full-run duration recording semantics and explicit native focused commands; verify partial or sharded timings cannot overwrite the authoritative full-run timing file and that normal execution does not enable per-test dynamic coverage contexts.
- [x] 6.4 Add focused worker/coverage/failure-propagation checks and README examples in the same change; verify the documented one- and two-worker runs and compare them on the same local host and complete selection.

## 7. Final integration and acceptance evidence

- [x] 7.1 Inspect the complete final diff and run affected focused checks, the complete Python suite, compile checks, and repository quality checks appropriate to changed tooling; verify results are tied to the final tree and no existing assertion, timeout, retry, or required check was relaxed.
- [ ] 7.2 Build the application and prepared-browser test environments and run the full isolated five-project browser selection through the final scheduling; verify selection parity, login, fresh PWA/offline behavior, safe Markdown, keyboard/composer behavior, opt-in microphone/notifications, responsive/accessibility checks, and stateful-spec isolation, reporting unavailable checks explicitly.
- [ ] 7.3 Compare each local complete selection to its own recorded baseline and collect at least five comparable naturally occurring successful hosted runs when available; deliver measured wall time and runner consumption, record the provisional six-minute/30-percent goals as met, missed, or unverified, and do not dispatch extra remote work solely because this checklist exists.
- [x] 7.4 Run strict OpenSpec validation and a parent walkthrough of the final tasks/spec/design and README commands; verify every required artifact remains coherent, implementation evidence gaps are explicit, and the closing retrospective reports findings or limits without claiming unrun hosted or platform checks.
