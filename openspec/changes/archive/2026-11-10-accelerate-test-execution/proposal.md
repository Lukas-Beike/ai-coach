# Proposal

## Why

GitHub feedback is dominated by the browser path: across eight successful runs on 25-26 October 2026, the slowest Python job took a median 2:28, while the slowest browser job took 8:51; individual Chromium system-package installations took over nine minutes. Local Windows validation also repeats expensive fixture construction and has no shared, isolated orchestration entry point for the complete browser matrix.

## What Changes

- Add a shared browser execution command for local development and CI, with explicit project/spec selection, independent run directories, fresh disposable fixtures, bounded concurrency, and persisted timing/results summaries.
- Use a version-matched, digest-pinned prepared browser environment in CI so regular matrix jobs do not install Chromium system packages from Ubuntu mirrors.
- Partition browser spec files by recorded per-project duration, initially evaluating two shards for each mobile/tablet project while retaining two desktop shards and one worker inside each invocation.
- Give every concurrent invocation its own fixture containers, stable network namespaces, ports, authentication state, reports, and cleanup ownership.
- Reduce unnecessary demo-data construction in expensive test fixtures without removing weekday, seed, upgrade, restart, collision, or state-isolation checks.
- Extend the existing local Python shard/container tooling with bounded process execution and explicit focused versus complete validation modes; preserve complete CI coverage and required checks.
- Record comparable local and hosted measurements, including cold/warm setup, execution, queue time where available, total runner-minutes, and process exit status. Persist results even when the interactive session ends.

This is a proposed change to developer-facing test execution behavior, not a documentation backfill. Planning does not implement these changes.

## Capabilities

### New Capabilities

- `isolated-test-execution`: Reproducible local/CI test selection, prepared browser execution, isolated file-level scheduling, bounded Python execution, fixture parity, and durable validation evidence.

### Modified Capabilities

None. `build-release-and-deployment` retains its read-only validation, fail-closed aggregates, immutable source, and publication gates. `web-pwa-and-accessibility` retains every currently selected functional and responsive scenario.

## Impact

- Primary owners: `.github/workflows/publish-container.yml`, `playwright.config.cjs`, `e2e/auth.setup.js`, `e2e/fixture_runtime.py`, `tests/run_tests.py`, and `tests/run_sqlcipher_tests.ps1`.
- Add a small standard-library browser orchestration entry point and a test-only prepared-environment definition/pin where the existing owners cannot express the new behavior; do not introduce a general test framework.
- Update existing CI/browser-selection regression tests and focused orchestration tests, plus `tests/test_fixture_standard_data.py`, as needed. Preserve frozen released-schema fixtures and existing assertion semantics.
- Maintain operational commands in `README.md` and align the disposable-browser runbook with the shared runner.
- No athlete-facing API/UI change, application schema change, production Dockerfile responsibility change, provider call, credential access, live-data mutation, or deployment.
- Exclude test deletion, the three separately identified redundant Python tests, broad parameterization cleanup, automatic impact-based test skipping, new paid infrastructure, and changes to review/release rulesets.
- Measurements are acceptance evidence, not new timing-based correctness gates. The provisional goals are under six minutes median GitHub validation wait and at least 30% lower local complete-run wall time, subject to an explicit comparable local baseline and subsequent measurements.

Inspected source: `c7ff60519520d553a00bfd33f6cf884b8de879b8` on `t3/explore-test-suite-size`. Hosted evidence includes runs [40229467947](https://github.com/Lukas-Beike/ai-coach/actions/runs/40229467947) and [40266532844](https://github.com/Lukas-Beike/ai-coach/actions/runs/40266532844). Their source revisions differ from the inspected checkout; implementation must reconcile the then-current target workflow before relying on those measurements.
