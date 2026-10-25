# Proposal

## Why

Two recurring agent-session failures waste time in fresh task worktrees
(observed 2026-10-24): OpenSpec, Playwright and other Node tooling fail with
`ERR_MODULE_NOT_FOUND` until someone runs `npm ci --ignore-scripts` (#1404),
and the roughly 20-minute full unit suite is aborted as a suspected hang and
re-run through a custom runner that reports false import errors (#1405).

## What Changes

- `.agents/skills/README.md` (OpenSpec integration): state that a new worktree
  needs `npm.cmd ci --ignore-scripts` once before the first OpenSpec CLI call,
  pointing at the README recipe.
- `README.md` (Optional local OpenSpec): note that a T3 Code project can run
  that install as a worktree-creation setup script.
- Local T3 Code project setting (outside the repository): add a setup script
  `npm.cmd ci --ignore-scripts` with `runOnWorktreeCreate` so new task
  worktrees have the pinned Node development dependencies.
- `.agents/skills/ai-coach-validation/SKILL.md`: state the expected full-suite
  duration (about 20 minutes locally on Windows), run it in the background with
  a completion notification, use the standard `python -m unittest discover -s
  tests` from the repository root (focused modules via `-p <file>`), and
  diagnose a suspected hang with `faulthandler` instead of killing the run or
  writing a custom runner.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. This is developer tooling and agent guidance only; application behavior,
API, persistence and specs are unchanged, so the change declares
`skip_specs: true`.

## Impact

- Documentation and skill text only; no application code, schema, dependency
  pin or Docker image change.
- The T3 setup script needs network access when a worktree is created and
  installs only the hash-locked `package-lock.json` dependencies with lifecycle
  scripts disabled. It is local host configuration, not tracked source.
- Exclusions: Graphify worktree setup (#1435) remains separate.
