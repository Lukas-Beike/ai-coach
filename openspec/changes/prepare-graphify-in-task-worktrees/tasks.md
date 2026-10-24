# Tasks

## 1. Hash-locked Graphify dependencies

- [ ] 1.1 Add `requirements-graphify.in` and generate `requirements-graphify.txt` with `pip-compile --allow-unsafe --generate-hashes` on Python 3.14; verify the lock contains `graphifyy==0.9.93` and `pywin32` only with a `sys_platform == "win32"` marker, and that a Linux `python:3.14` compile yields the same package set
- [ ] 1.2 Extend `tests/test_ci_contracts.py` lock/manifest coverage to the Graphify pair and assert the Dockerfile and CI install steps never reference it; verify with `python -m unittest tests.test_ci_contracts -v`
- [ ] 1.3 Add the Graphify pair to README's dependency-maintenance recipe; verify the documented command matches the one used in 1.1

## 2. Shared, hash-verified Graphify environment

- [ ] 2.1 Derive `VERSION` from the lock, fail closed on a missing/ambiguous pin, and verify with a unit test using temporary lock files
- [ ] 2.2 Move the virtual environment to the shared base keyed by version and lock hash, with in-place creation under a process lock and a final `ready.json` marker; verify with synthetic tests for reuse without install, incomplete-environment recreation, marker mismatch and concurrent setup serialization
- [ ] 2.3 Install with `--require-hashes --only-binary=:all:` from the lock; verify with a test that the pip command is exactly hash-based and that a failed install leaves no marker
- [ ] 2.4 Add the explicit `prune` command; verify with a test that only non-current, unlocked sibling environments are removed
- [ ] 2.5 Add the offline test: `update`, `status`, `query` and the session-start path never call pip, `-m venv` or npm, including with a missing environment; verify with `python -m unittest tests.test_graphify_hooks -v` and the new test module
- [ ] 2.6 Run a real local `setup` (network allowed for this step only), `update`, `status` and `query activity_detail`; verify `status` prints `Graphify local: current`, a second `setup` performs no install, and a tampered lock hash makes setup fail

## 3. Worktree preparation entry point

- [ ] 3.1 Add `scripts/prepare_worktree.py` running `npm ci --ignore-scripts`, Graphify `setup` and `update`, continuing independent steps and exiting non-zero on any failure; verify with synthetic subprocess tests for success, npm failure and Graphify failure
- [ ] 3.2 Run `python scripts/prepare_worktree.py` in this worktree; verify `npm run openspec -- --version` succeeds and `graphify_local.py status` reports current

## 4. Guidance

- [ ] 4.1 Update `.agents/skills/ai-coach-graphify/SKILL.md`, `.agents/skills/README.md`, root `AGENTS.md` and README's Graphify and OpenSpec sections: automatic preparation, shared hash-locked environment, observed T3 hook delivery, manual `setup`/`prune` as fallback; verify no remaining "optional"/"explicitly once"/"T3 Code hook delivery is unverified" statements via `rg`

## 5. Integration checks

- [ ] 5.1 Run `python -m unittest discover -s tests -v`, `python -m compileall -q server.py backend tests scripts`, repo-wide ruff/mypy as CI does, and `npm run openspec -- validate prepare-graphify-in-task-worktrees --strict`; record results

## Workflow follow-up

- Archive the change after review; sync is not applicable (`skip_specs: true`).
- After merge, replace the T3 project script `node-dev-deps` with `python scripts/prepare_worktree.py` (`runOnWorktreeCreate: true`), launch a fresh task worktree, and verify: no "run setup" in the first hook, `status` current, `query activity_detail` returns results, `npm run openspec -- --version` succeeds.
- Verify Dependabot detects `requirements-graphify.txt` on its next run.
