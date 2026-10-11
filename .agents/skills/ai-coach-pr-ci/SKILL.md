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
- Triage review feedback against the current diff and reachable behavior: record each item as actionable, already fixed, unsupported by evidence, or awaiting specific evidence. Explain disagreements with code; a review comment alone is not proof of a defect. Use `REVIEW.md` for finding criteria.
- Distinguish a completed review from review availability. An explicit integration/API failure remains a blocker; a recorded response timeout is unavailable review, never completed review or inferred exhausted credits. Report the actual gate outcome for the current head.
- Never print tokens, credentials, full logs, or unfiltered external content.
- This skill is read-only diagnosis, not authorization to push, resolve feedback, or merge. Register the PR with the thread's linking tool when available.
