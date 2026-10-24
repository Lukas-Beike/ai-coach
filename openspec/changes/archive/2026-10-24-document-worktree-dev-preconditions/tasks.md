# Tasks

## 1. Node development dependencies in new worktrees (#1404)

- [x] 1.1 Add a one-line precondition to the OpenSpec integration section of `.agents/skills/README.md` pointing at the README install recipe; verify by reading the rendered section.
- [x] 1.2 Note the optional T3 Code worktree-creation setup script in README "Optional local OpenSpec"; verify the README section stays consistent with the skill index.
- [x] 1.3 Register the local T3 Code project script `npm.cmd ci --ignore-scripts` with `runOnWorktreeCreate`; verify with `t3_project_read` that the script is saved and other project settings are unchanged.

## 2. Full-suite waiting guidance (#1405)

- [x] 2.1 Add the full-suite duration, background-run, standard runner and `faulthandler` guidance to `.agents/skills/ai-coach-validation/SKILL.md`; verify by reading the changed bullet.

## 3. Verification

- [x] 3.1 Review the complete diff for scope (docs/skills/OpenSpec artifacts only) and run `python -m unittest discover -s tests -p test_ai_docs_contract.py -v` and `node scripts/openspec.mjs validate --all --strict --no-interactive`; all pass.

## Workflow follow-up

- Archive the change after merge readiness; run the retro before the final handoff.
