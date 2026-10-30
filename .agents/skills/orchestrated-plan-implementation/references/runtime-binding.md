# Runtime binding

- **Claude Code `Agent`:** use `subagent_type` `explorer`, `implementer`, or
  `reviewer` from `.claude/agents/`; override `model` only for L3 (`opus`). It
  runs in the background unless `run_in_background: false`.
- **T3 `delegate_task`** (Gemini Flash, or background work): call
  `orchestrator_capabilities` once, then pass `isolation: "worktree"`,
  `target.providerInstanceId`, `target.model`, and a complete brief. Retry a
  lost response with the same `clientRequestId`; cancel with `task_cancel`. Do
  not use `t3_thread_launch` or `create_threads` for child work. After the
  completion notification, confirm with one `task_status` call that the child
  stopped writing before integrating.
- **Other hosts** (for example Codex `spawn_agent` with `fork_turns: "none"`):
  only with an explicit model from the tiers and an isolated worktree;
  otherwise stay with the main model.
- Wait for completion notifications; do not poll or sleep.
