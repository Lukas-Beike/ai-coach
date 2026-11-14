---
name: pacecraft-browser-tests
description: Base skill. Run the Playwright browser tests for the affected project with the isolated runner. Use after changing public/ or e2e/; not for Python tests (pacecraft-run-tests-changed).
---

# Run browser tests

The runner gives every spec its own disposable SQLCipher fixture; do not call
`npm run test:e2e` against a live installation. Projects: `mobile` (390x844),
`tablet-landscape` (844x390), `desktop` (1440x1000). One-time setup is in
[docs/testing.md](../../../docs/testing.md#playwright-browser-e2e-tests):
install the locked Chromium and build the app image.

```powershell
python scripts/run_browser_tests.py --project changed --list
python scripts/run_browser_tests.py --project <project> --spec e2e/<name>.spec.js
python scripts/run_browser_tests.py --project all --keep-going
```

- `--project` is required (one project name, `all`, or `changed`); `--spec`
  repeats. `changed` picks what CI picks for the diff against `--base`
  (default `origin/develop`), from `.github/scripts/ci_changes.py` (#2759):
  nothing for documentation only (exit 0, no run, as CI), `desktop` without a
  UI change, otherwise `all`. One project takes 28-32 min
  locally with `--jobs 1`. Run the
  smallest selection that covers the change: the affected spec on the affected
  project, then the other viewports for layout changes. `--list` resolves the
  selection without Docker or a browser. A spec a selected project does not
  list (a desktop-only spec on mobile) is skipped there with a note.
- Rebuild the image (`docker build -t "$(python scripts/run_browser_tests.py --print-image)" .`)
  after application changes; it is not rebuilt for you, and a run against an
  image that differs from the source stops before any fixture starts.
- Exit 0: passed. Non-zero: a test failed (reports under
  `test-results/browser-runs/`), the host ran out of resources, or the image is
  stale (no reports; rebuild as the message says); the output says which and how
  to rerun. Report what was not run.
- Reports and traces can hold fixture data: never publish them.
- A stopped or killed run cannot clean up after itself. Each run holds a lock
  file in the system temp directory; the next run, or
  `python scripts/run_browser_tests.py --cleanup-stale`, removes the containers
  of runs whose lock nobody holds. Live runs and runs without a lock file on
  this host are never touched (#2721).
- Long runs: the complete selection takes about 24 min with `--jobs 1` and
  15 min with `--jobs 2` (#2149); one project with `--jobs 2` took 15-19 min on
  a loaded host (#2515). Start such a run with the long-run rule of
  [validation](../pacecraft-validation/SKILL.md).
