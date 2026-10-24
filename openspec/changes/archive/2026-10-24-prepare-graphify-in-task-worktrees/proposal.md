# Proposal

## Why

Graphify is required in every agent session, but each new task worktree starts
without its per-worktree environment, so the SessionStart hook reports
`Graphify 0.9.93 unavailable; run setup` and agents navigate without a graph
(#1435). The same worktree preparation gap leaves Node development dependencies
missing, so OpenSpec, Playwright and `node --test` fail in fresh worktrees
(#1404). The current Graphify install is pinned only at the top level, and
Dependabot never sees it.

## What Changes

- Add `requirements-graphify.in` and a hash-locked, platform-independent
  `requirements-graphify.txt` generated with the README pip-compile recipe.
  Graphify setup installs only with `--require-hashes` from that lock, and the
  wrapper derives its Graphify version from the lock.
- Replace the per-worktree Graphify virtual environment with one shared
  environment per Graphify version and lock hash under the user's local
  application data. Creation is serialized by a lock; an unchanged lock reuses
  the environment without network access. Graph generations, locks, home and
  exports stay per worktree under `.graphify-local/`.
- Add an explicit `prune` command that removes shared environments other than
  the current one. Nothing is deleted automatically.
- Add `scripts/prepare_worktree.py`, a cross-platform worktree preparation entry
  point that runs `npm ci --ignore-scripts`, Graphify `setup` and a first
  `update`, and exits non-zero when any step fails.
- Keep hooks, `update`, `query`, `status` and exports offline; a test fails if
  they invoke an installer.
- Update the Graphify skill, root `AGENTS.md`, skill index and README: Graphify
  is prepared automatically, T3 Code hook delivery was observed, and manual
  `setup` remains a fallback.
- After merge, point the T3 project worktree-creation script at the new entry
  point (outside the repository).

## Capabilities

### New Capabilities

None. This is developer tooling; no application behavior changes.

### Modified Capabilities

None. The change sets `skip_specs: true`.

## Impact

- Code: `scripts/graphify_local.py`, new `scripts/prepare_worktree.py`,
  `tests/test_graphify_hooks.py` and a new focused Graphify setup test,
  `tests/test_ci_contracts.py` lock/manifest coverage.
- Dependencies: new development-only lock pair; never installed into the app
  environment, CI app jobs or the Docker image (the Dockerfile copies explicit
  files only). Dependabot's existing pip entry for `/` is expected to pick up
  the pair.
- Docs: `.agents/skills/ai-coach-graphify/SKILL.md`, `.agents/skills/README.md`,
  `AGENTS.md`, `README.md`.
- Systems: T3 project setup script (updated after merge, with user approval).
- Issues: closes #1435 and #1404.
