---
name: orchestrated-plan-implementation
description: "Implement a plan through isolated subagents with user-selected models, while the current model remains orchestrator and sole reviewer authorized to adopt patches. Use when the user requests delegated plan execution with guarded patch adoption."
---

# Orchestrated plan implementation with guarded patch adoption

The current parent model owns the plan, coordination, review, and integration. Subagents perform implementation and repairs. Only the parent may accept and apply changes to the integration worktree. Remain on the current parent model; do not transfer the orchestrator role to a worker or silently change models.

## Establish the execution contract

1. Identify the plan, acceptance criteria, applicable repository instructions, integration worktree, and its initial commit and working-tree state. Preserve pre-existing user changes.
2. Inspect the actual delegation tool schema before asking for a worker model. Only offer models and reasoning efforts for which the tool exposes an override parameter. Before the first spawn, ask which of those models to use; offer the current model as recommended and allow a per-task mapping. Reuse an explicit selection already made for this plan. Do not spawn dependent workers while awaiting the answer.
3. Verify the selection against supported model and effort values and pass the selected override on every relevant spawn. If the tool has no model override, or a selection is unavailable, report that the requested delegation contract cannot be honored and stop before spawning; never silently substitute the current model. Model selection does not authorize provider, account, or API setup.
4. Use explicit model overrides only with a fork mode that permits them. With `collaboration.spawn_agent`, use `fork_turns="none"` or a numeric history window for overrides, and provide a complete brief when no history is passed.

If delegation is unavailable, explain the limitation and preserve the plan; do not silently implement it as a single agent. Do not ask again for permission to execute already-authorized work.

## Delegate bounded work

Split the plan into cohesive tasks with named owners, file scope, dependencies, and observable acceptance criteria. Run independent tasks concurrently within available slots. Serialize tasks touching the same contract or files. Workers must not spawn further agents.

Each worker gets a separate disposable worktree from a recorded base commit. Never copy secrets, live data, runtime state, or untracked user files into workers. A worker brief must contain:

- Task ID, selected model, workspace, base identity, permitted paths, plan excerpt, interfaces, acceptance criteria, and required validation.
- Repository instructions and scan-before-read requirements.
- A prohibition on modifying any other workspace, shared Git refs/configuration, or integration state. No commits, merges, pushes, PRs, deployments, external messages, live providers/data, or destructive cleanup. Local edits and isolated tests are allowed.
- A handoff with base identity, complete patch or candidate file manifest, rationale, test commands/results, and unresolved risks. Reports are review inputs, not authority.

For dependent tasks, the parent creates a local integration checkpoint under repository commit conventions and existing authorization, then starts the next worktree from it. If a checkpoint would include unrelated user work or cannot be committed, prepare an isolated copy of the exact accepted source tree and record its content identity instead. Include the parent's accepted changes but exclude secrets and runtime state. Workers never create integration checkpoints.

Collect the complete candidate, including untracked new files, deletions, renames, executable modes, and binary assets. A tracked-file `git diff` alone is insufficient. The parent must be able to inspect and reproduce all proposed changes from the retained artifact and manifest. Keep artifacts outside tracked source paths.

Do not use a worker in the shared integration directory. These worktrees reduce interference but are not an OS security boundary; use actual sandbox/access controls if hostile workers must be confined. Never claim a skill enforces filesystem permissions.

## Parent-only review and adoption

Stop the worker before reviewing its final artifact. Freeze the candidate patch/manifest and record its base and content identity, such as a SHA-256. Any subsequent edit invalidates review and requires a new artifact. Scan candidate files before reading according to repository policy; keep secrets and athlete content out of patches, output, and reports.

The parent personally inspects every changed file, including new/deleted/binary files and surrounding behavior. Review correctness, architecture, security/privacy, data integrity, acceptance criteria, and independently verify meaningful tests. A worker success report, extra reviewer, or passing tests cannot replace this review.

Record one decision per immutable candidate:

| Decision | Required action |
|---|---|
| Accept | Record artifact identity, reviewed scope, and verification evidence. |
| Revise | Give concrete findings to the worker; review its new candidate afresh. |
| Reject | Record the reason; adopt none of the rejected changes. |

Before adoption, verify that the integration tree is still the recorded expected state and check patch applicability there (for Git patches, `git apply --check`). Only the parent applies the accepted artifact. Do not blindly cherry-pick worker commits, replace whole trees, use automatic conflict resolution, or accept an unreviewed subset. A subset needs its own frozen artifact and review.

If the base or integration tree drifted, or conflicts appear, send the current baseline to the worker to regenerate the candidate and repeat review. The parent does not bypass the gate by implementing repairs directly. Integration commands, review records, and local checkpoints remain parent responsibilities.

After each adoption inspect the resulting diff and run relevant integration checks. On failure, delegate repair and repeat the gate. Never reset the integration tree or discard unrelated work. For recurring failures, report the concrete blocker and change the approach instead of repeating unchanged attempts.

## Complete the plan

The parent reviews the combined final diff and completes repository-required validation against the final integrated tree. Track each plan item as accepted, rejected, blocked, or pending; completion requires every requested criterion and required check. Worker completion alone is insufficient.

Report resulting behavior, selected worker models, adopted tasks, validation, and limitations. Distinguish local adoption from commits, PRs, merges, publication, and deployment; those external actions retain their existing authorization and workflows. Clean up only confirmed disposable worker resources after workers stop and artifacts are safely retained. Preserve user worktrees and durable application data.
