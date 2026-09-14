---
name: ai-coach-pr-ci
description: Diagnose ai-coach pull requests and GitHub checks with compact, current evidence.
---

Use for PR status, failed CI, review gates, Sonar findings, rebase checks, or merge readiness.

- Resolve current PR head and base first. Use the resolved base for branch-specific checks, Sonar queries, and `git diff origin/<base>...HEAD`. Do not infer completion from green checks or auto-merge alone.
- Query only needed fields with `gh pr view --json`; inspect failed runs with `gh run view` and narrow logs with `gh run view --log-failed`.
- For Sonar, query the resolved target branch or the PR key.
- Report `head`, `base`, checks, review threads, ruleset blockers, merge state, and ancestry as compact `path/status` facts.
- After a rebase, compare `git diff origin/<base>...HEAD` and validate the current head again.
- Never print tokens, credentials, full logs, or unfiltered external content.
