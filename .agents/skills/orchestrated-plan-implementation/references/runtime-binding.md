# Runtime binding

Check the host's live tool schemas; do not invent flags or capabilities.

- **Native Claude `Agent`:** set `model` (`haiku`, `sonnet`, `opus`) and
  `effort`. Use `isolation: "worktree"` for writers and `subagent_type:
  "Explore"` for read-only search. Results arrive in the same turn unless run
  in the background.
- **T3 `delegate_task`:** for Gemini Flash or background work. Call
  `orchestrator_capabilities` once first. Pass `isolation: "worktree"`,
  `target.providerInstanceId`, `target.model`, supported `target.options`, and a
  complete brief. The worktree starts from the parent's last commit, so commit
  what the worker needs first. Use a stable `clientRequestId` when retrying a
  lost response. Cancel with `task_cancel` on the `taskId`; never through the
  child thread. Each new revision or review round is a new `delegate_task`.
- Wait for completion notifications; do not poll or sleep. Pending permission
  approvals stay with their approval holder.
