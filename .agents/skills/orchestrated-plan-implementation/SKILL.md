---
name: orchestrated-plan-implementation
description: Use for every repository work session to decide whether delegating to subagents pays off. Default to doing the work with the main model; delegate only for a clear, cost-effective benefit, using the fixed Claude/Gemini tier mapping. The main model reviews and alone integrates worker results.
license: MIT adaptations; see ../THIRD_PARTY.md.
---

# Orchestration

The main model (parent) owns scope, plan, review, and integration. Workers are
optional helpers for bounded tasks. Only the parent integrates their results.

## 1. Decide: main model or workers

Do the work with the main model unless delegation has a clear benefit that
outweighs the cost of writing briefs and reviewing results. Delegate only when
at least one applies:

- **Parallelism:** two or more substantial, independent work packages with no
  shared files or changing contracts, where running them at once saves real time.
- **Cheaper execution:** large, clearly specified mechanical work (bulk edits,
  fixtures, test sweeps) that a lower tier does well for much less.
- **Context protection:** a broad read-only search across many files where only
  the conclusion matters.
- **Independent review:** a fresh-context review of a risky diff, where seeing it
  without the author's reasoning adds value.

Stay with the main model for sequential or tightly coupled work, anything the
parent can finish in about 15 tool calls, status answers, and closing retros.
State the decision in one line, for example "Main model: small and sequential"
or "Delegating T1, T2: independent, parallel", then continue. An explicit user
requirement for workers, or for doing it alone, overrides this rule.

## 2. Tier mapping

Use these defaults without asking. Always pick the newest version of each
family available in the live catalog (T3 `orchestrator_capabilities`, or the
native tool's model list); never another provider.

| Tier | Tasks | Model | Effort |
| --- | --- | --- | --- |
| L1 easy | Clear target and instructions, cheap acceptance check | Claude Haiku and Gemini Flash, alternating | low (Gemini: `-low` variant) |
| L2 standard | Almost everything: features, multi-file fixes, tests, routine review | Claude Sonnet | medium |
| L3 hard | Only genuinely hard or risky work: migrations, auth/privacy, data integrity, hard diagnosis, critical review | Claude Opus | high |

- Sonnet handles nearly all work; assign L3 only for real difficulty or risk,
  not file count.
- Alternate L1 tasks within a run, starting with Gemini Flash, to spread usage.
  If one is unavailable, use the other.
- Effort never exceeds `high`. Pass model and effort as tool arguments and check
  the returned selection; stop a mismatched run instead of using its output.
- Ask the user only when no model of a needed tier is runnable, or when the user
  asks for different models.

## 3. Dispatch

- **Claude workers:** native `Agent` tool with `model` and `effort`, foreground
  unless parallel; `isolation: "worktree"` for writers. Read-only exploration
  uses the `Explore` agent type.
- **Gemini workers, or background work:** T3 `delegate_task` with
  `isolation: "worktree"`; see [runtime binding](references/runtime-binding.md).
- At most three concurrent workers. Serialize tasks that touch shared files or a
  producer/consumer contract.

Each brief is self-contained: objective, allowed paths, base commit, acceptance
check, applicable AGENTS rules, and the handoff format (changed files, checks
run, open issues). Never include secrets, athlete data, or runtime state.

Workers do not push, open PRs, merge, deploy, message externally, touch live
providers or data, or start nested agents. Writers commit only on their own
worktree branch.

## 4. Review and integrate

- The parent reads the worker's complete diff on its branch, including new and
  deleted files, and checks it against the brief. Worker reports and green tests
  do not replace this.
- Accept by merging or cherry-picking the worker branch into the task branch,
  or reject with reasons. Never overwrite or reset the user's own work.
- For L3 changes, get an independent fresh-context review (Opus) of the diff
  without the author's reasoning, and resolve findings by evidence.
- Retry a failed task at most twice, diagnosing before each retry; then re-scope
  or move it to the next tier, and say so.
- Run required validation on the final integrated tree. The PR workflow's review
  gate and round limit still apply; worker reviews do not replace them.

Keep any task ledger outside tracked source. On resume, reconcile actual worktree
and task state before dispatching anything new; do not duplicate running work.
Report the delegation decision, models used, integrated work, checks, and limits.
