---
name: pacecraft-develop-run-check
description: Base skill. Report the develop push workflow runs for a merged PR's merge commit (or a SHA), one line per workflow, with hints for failures. Use after a merge to see whether develop is green; do not use to rerun or fix a run.
---

# Check the develop runs of a merge

```powershell
python scripts/develop_run_check.py --pr <number>
python scripts/develop_run_check.py --sha <sha>
```

- Read-only. Prints one line per workflow: `<name>: green|pending|failed (<result>) <url>`.
- Exit 0: every run completed green. Exit 1: a run failed, or the PR is not
  merged. Exit 2: bad input or a failed `gh` call. Exit 3: a run is pending or
  none has started yet; check again later.
- A failed run gets a hint. `superseded` means a newer develop push run of the
  same workflow exists: never rerun it, check the newer run. Otherwise the hint
  gives the previous push run's conclusion (`possible flake` when it was
  green) and the failed job names; judge against the PR's changed files before
  rerunning anything.
