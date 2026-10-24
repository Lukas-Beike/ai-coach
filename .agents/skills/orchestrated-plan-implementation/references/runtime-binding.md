# Runtime binding adapters

Inspect the host's current schemas; do not invent flags or capabilities.

- **T3:** use `delegate_task` with `isolation: "worktree"`, explicit
  `target.providerInstanceId`, `target.model`, supported `target.options`, role,
  complete brief, and normally `mode: "async"`. This is required for isolated
  checkout binding, cross-provider work, native-unsupported models, requested
  options, and same-model nonempty inherited options. Its worktree starts from
  the parent's local commit, excludes uncommitted edits, and runs project setup.
- T3 task handles are `taskId` for `task_status`/`task_cancel`; `childThreadId`
  is backing storage. Use stable `clientRequestId` on retries of a lost response
  to avoid duplicates. For each new revision/review round call `delegate_task`
  again with a new key, original brief, current baseline/candidate, prior findings,
  responses, and unresolved objections. Do not continue review rounds through
  `t3_thread_send`. Use `workState`/`hasPendingChildRuns` to check remaining writers.
- Missing lazy T3 tools warrant one bounded direct capabilities attempt; use the
  host-documented `acp-mcp-call` fallback when advertised, without raw provider
  CLI/account setup. `t3_thread_launch`/`create_threads` are top-level conversations
  and require a separate-thread request; do not substitute them for child tasks.
- **Other hosts:** native delegation is suitable only if exact model/options,
  isolated source, and lifecycle requirements are supported. Prepare worker
  worktrees in the parent when no binding facility exists. With
  `collaboration.spawn_agent`, overrides require `fork_turns: "none"` and a
  complete brief. Use no invented enum values or inheritance modes.
- Keep runtime permissions inherited unless the user chooses a supported mode.
  Answer factual child questions from authorized context; pending permission
  approvals stay with their existing approval holder. Question tools cannot
  grant permission. Cancel through the adapter owning the task handle.
