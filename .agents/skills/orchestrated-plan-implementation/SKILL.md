---
name: orchestrated-plan-implementation
description: Use when considering subagents or parallel workers for repository work. Default to the main model; delegate only for a clear, cost-effective benefit, using the fixed Claude/Gemini tiers and the repository agent definitions. The main model reviews and alone integrates worker results.
license: MIT adaptations; see ../THIRD_PARTY.md.
---

# Orchestration

The main model does the work unless delegation clearly pays off. Subagents give
parallelism, keep noisy output away, or give a fresh reviewer; they cost tokens
and do not give better answers. Delegate only for:

- **Parallelism:** two or more substantial, independent tasks with no shared
  files or changing contracts.
- **Cheaper execution:** large, clearly specified mechanical work a lower tier
  does well.
- **Noisy search:** a broad read-only search where only the conclusion matters.
- **Independent review:** a risky diff reviewed without the author's reasoning.

State the decision in one line and continue. An explicit user instruction wins.

## Tiers

Use these without asking, always the newest version available. Effort never
exceeds `high`.

| Tier | Tasks | Model and effort | Agent definition |
| --- | --- | --- | --- |
| L1 | Clear target and instructions, cheap check, read-only search | Haiku (low) alternating with Gemini Flash (`-low`), starting with Gemini | `explorer` for search |
| L2 | Almost everything, including routine review | Sonnet (medium) | `implementer`, `reviewer` |
| L3 | Only genuinely hard or risky work: migrations, auth/privacy, data integrity, hard diagnosis | Opus (high) | `implementer`/`reviewer` with `model: "opus"` |

The definitions in `.claude/agents/` pin model and effort and, for `explorer`
and `reviewer`, read-only tools; put the diff in the `reviewer` brief, since it
cannot run git. Gemini Flash runs through T3 `delegate_task`; see
[runtime binding](references/runtime-binding.md). If a tier is unavailable, use
the other L1 model or stay with the main model and say so.

## Dispatch and integrate

- Commit what a worker or reviewer must see first; worktrees start from the last
  commit. Writers use `isolation: "worktree"`. Pass `run_in_background: false`
  unless several workers run in parallel. At most three at once.
- The brief is self-contained: objective, allowed paths, base commit, acceptance
  check, and handoff format. No secrets or athlete data.
- Workers commit on their own branch with Conventional Commit subjects and never
  push, open PRs, merge, or start other agents.
- The parent reads each worker's complete diff before taking it, then
  cherry-picks or rebases its commits (no merge commits). If the base moved or a
  conflict appears, review the result again or have the worker redo it.
- A reported deviation that changes athlete-visible output or durable data
  compared with the base branch is a regression until the athlete has accepted
  it: fix it or ask, and never brief reviewers on it as intended. Internal
  refactors and deviations the athlete already decided are not covered.
- Retry a failed task at most twice, then re-scope or move up a tier.
- Worker results never replace validation on the final tree or the PR review.
