---
name: pacecraft-run-tests-changed
description: Base skill. Run the local checks for a change - affected Python tests, compileall, the quality ratchet and, when JavaScript changed, the Node tests. Use before a commit or PR; not for the full suite or browser tests (pacecraft-browser-tests).
---

# Run the checks for a change

From the repository root:

```powershell
python scripts/check_changed.py [--base origin/develop] [--js]
```

- Runs `tests/run_tests.py --changed --base <base>`, `compileall`,
  `tools/quality_baseline.py` and, with `--js` or when the diff against the base
  touches a `.js`, `.cjs` or `.mjs` file, `node --test tests/*.cjs`.
- Every step runs even after a failure. One line per step
  (`ok|FAILED <step> (<seconds>s)`), then the last 20 lines of each failed step.
- Exit 0: all passed. Exit 1: a step failed; fix it and rerun, never relax a
  check. Exit 2: unknown base ref or a tool (such as `node`) is missing.
- When the selector falls back to the full suite, the `tests` step is slow;
  that is expected.
