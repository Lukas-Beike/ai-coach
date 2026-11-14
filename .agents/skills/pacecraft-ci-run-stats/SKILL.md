---
name: pacecraft-ci-run-stats
description: Base skill. Measure CI run times of the Test and publish container image workflow for a time window - count, median, p90, run types with job counts and optional job queue time - with one fixed definition. Use for CI-speed baselines and before/after claims; read-only, never to dispatch runs.
---

# CI run statistics

```powershell
python scripts/ci_run_stats.py --since <UTC start> --until <UTC end> [--event pull_request] [--all-conclusions] [--first-attempts] [--queue]
```

- Read-only `gh api` calls. The definition (window, created-to-updated
  minutes, inclusive linear p90, run types) is in `docs/testing.md`; quote the
  command with every baseline so numbers stay comparable across issues.
- Successful runs only unless `--all-conclusions` (then a per-conclusion
  line; run types cover successful runs). Run types: `full`, `desktop-only`,
  `docs-only`, `other` (a reused run). Re-runs are reported; leave them out
  with `--first-attempts` when they would distort a comparison.
- Exit 0: printed. Exit 1: no run in the window. Exit 2: bad input, a failed
  `gh` call, or a window that reaches the API's 1000-run cap (split it).
