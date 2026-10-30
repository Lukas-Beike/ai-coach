# Runtime binding

Check the host's live tool schemas; do not invent flags or capabilities.

- **Native Claude `Agent`:** set `model` (`haiku`, `sonnet`, `opus`) and
  `effort`. It runs in the background by default; pass
  `run_in_background: false` to get the result in the same turn. Use
  `isolation: "worktree"` for writers and `subagent_type: "Explore"` with
  `model: "haiku"` for read-only search.
- **T3 `delegate_task`:** for Gemini Flash or background work. Call
  `orchestrator_capabilities` once first. Pass `isolation: "worktree"`,
  `target.providerInstanceId`, `target.model`, supported `target.options`, and a
  complete brief. The worktree starts from the parent's last commit, so commit
  what the worker needs first. Use a stable `clientRequestId` when retrying a
  lost response. Cancel with `task_cancel` on the `taskId`; never through the
  child thread. Each new revision or review round is a new `delegate_task`.
  Never substitute `t3_thread_launch` or `create_threads`; those create
  top-level threads outside the parent's control. After the completion
  notification, confirm with one `task_status` call that no child run is still
  writing before integrating or cleaning up.
- **Other hosts:** use the host's isolated worker facility only if it accepts
  an explicit model from the tiers (for Codex `spawn_agent`, pass a complete
  brief with `fork_turns: "none"`). Prepare worker worktrees in the parent when
  the host has no isolation of its own.
- Wait for completion notifications; do not poll or sleep. Pending permission
  approvals stay with their approval holder.
