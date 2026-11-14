---
name: pacecraft-ci-run-stats
description: Base skill. Measure CI run times of the Test and publish container image workflow for a time window - count, median, p90, run types with job counts and optional job queue time - with one fixed definition. Use for CI-speed baselines and before/after claims; read-only, never to dispatch runs.
---

# CI run statistics

```powershell
python scripts/ci_run_stats.py --since <UTC start> --until <UTC end> [--event pull_request] [--all-conclusions] [--queue]
```

- Read-only `gh api` calls. The definition (window, created-to-updated
  minutes, inclusive linear p90, run types) is in `docs/testing.md`; quote the
  command with every baseline so numbers stay comparable across issues.
- Successful runs only unless `--all-conclusions`. Run types: `full`,
  `desktop-only`, `docs-only`, `other` (a reused run).
- Exit 0: printed. Exit 2: bad input or a failed `gh` call.
