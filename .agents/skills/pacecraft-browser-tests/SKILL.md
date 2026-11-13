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
python scripts/run_browser_tests.py --project all --list
python scripts/run_browser_tests.py --project <project> --spec e2e/<name>.spec.js
python scripts/run_browser_tests.py --project all --keep-going
```

- `--project` is required (one project name or `all`); `--spec` repeats. Run the
  smallest selection that covers the change: the affected spec on the affected
  project, then the other viewports for layout changes. `--list` resolves the
  selection without Docker or a browser. A spec a selected project does not
  list (a desktop-only spec on mobile) is skipped there with a note.
- Rebuild the image (`docker build -t "$(python scripts/run_browser_tests.py --print-image)" .`)
  after application changes; it is not rebuilt for you.
- Exit 0: passed. Non-zero: a test failed (reports under
  `test-results/browser-runs/`) or the host ran out of resources; the output says
  which and how to rerun. Report what was not run.
- Reports and traces can hold fixture data: never publish them.
- Long runs: a complete local browser selection takes about 15-25 min (one
  project with `--jobs 2` about 15-20 min on a loaded host), the native Windows
  Python suite 25-35 min, `run_sqlcipher_tests.ps1 -Suite all` 3-5 min, a soak as
  long as planned. Start such a run in the background with an explicit limit above
  that duration (the host allows up to 2 h; the default 30 min stops it) and wait
  on it before ending the turn.
