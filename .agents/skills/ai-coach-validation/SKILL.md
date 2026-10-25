---
name: ai-coach-validation
description: Choose focused ai-coach backend, browser, PWA, and Docker checks for a change.
---

Use after changes or when validating a suspected regression.

- Backend: run focused tests first, then `python tests/run_tests.py` or `python -m unittest discover -s tests -v`. Run `python -m compileall -q server.py backend tests` for syntax checks. `python tests/run_tests.py --suite container` runs only the container-sensitive subset; `tests/run_sqlcipher_tests.ps1` runs the full suite inside Docker.
- Full suite duration: it takes about 20 minutes locally on Windows, and dot output can pause on slow tests. Run it in the background with a completion notification and wait. Run it from the repository root with the commands above (focused modules via `-p <file>`), never an ad-hoc runner outside the repository. Diagnose a suspected hang in a focused rerun with `faulthandler.dump_traceback_later` instead of killing the run.
- Changed backend files: mirror CI with `ruff check <files>` and `ruff format --check <files>`. Run mypy over the whole repository, never per file: with `follow_imports = skip` a single-file run treats imports as `Any` and hides errors CI's ratchet finds. As a local approximation of the ratchet, run `python -m mypy --config-file pyproject.toml --no-incremental --cache-dir "$(mktemp -d)" --no-error-summary` and inspect errors in and around the changed files; it relies on `files = ["."]` instead of the ratchet's explicit file list, so results can differ slightly. `python tools/quality_baseline.py` is the exact ratchet; on Windows it can fail on command-line length (WinError 206), in which case run it in Docker/CI.
- Browser: follow `ai-coach-pwa-e2e/references/browser-validation.md` for the disposable fixture runtime; preserve timing, viewports, accessibility, login, and streaming assertions. Never run against a connected installation.
- JavaScript: run affected `tests/*.cjs` with `node --test` and syntax-check changed scripts with `node --check`.
- PWA assets: when `public/index.html`, any asset listed in `service-worker.js`, or `service-worker.js` changes, verify matching asset query and cache versions.
- Docker or startup changes: run `docker build -t ai-coach:local .`.
- Dependency upgrades: follow [dependency maintenance](references/dependency-maintenance.md) for upstream changes, actual call sites, hash locks, and compatibility evidence.
- Use temporary data and mocked providers. Never use real `.env`, `/data`, credentials, or athlete data.
- Optional real-model checks: agents may use the existing local CLIProxyAPI for bounded synthetic manual probes under the [README runbook](../../../README.md#optional-local-cliproxyapi-probes). Use confirmed OAuth/subscription routing with paid API-key fallbacks disabled; check availability/models first, keep probes out of ordinary tests/CI, and report subscription quota use and compatibility limits. Fixtures remain the default; proxy success does not validate remote conversations, background jobs, or production behavior.
- Verify the final changed state: bind results to the revision and any uncommitted changes tested. After a material edit or rebase, rerun affected checks before reusing earlier success. Inspect child-test failures and artifacts rather than relying only on a wrapper exit code.
- For a functional regression, demonstrate the original trigger and the corrected behavior with a focused check where feasible. Static contract checks validate instruction structure, not skill behavior; local checks do not establish hosted review, merge, publication, or deployment.
- Report each check as passed, failed, blocked, or not run, including the shortest decisive evidence and the reason for skipped checks.
