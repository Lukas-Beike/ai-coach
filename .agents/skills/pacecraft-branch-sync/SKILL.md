---
name: pacecraft-branch-sync
description: Base skill. Rebase the current feature branch onto origin/develop, check commit subjects against the Conventional Commit types, and optionally push with force-with-lease through the hooks. Use before opening or updating a PR; do not use on develop or main.
---

# Sync a feature branch

```powershell
python scripts/branch_sync.py [--onto origin/develop] [--push]
```

- Refuses on `develop`, `main`, a detached HEAD and uncommitted tracked changes.
  Fetches `origin`, rebases, then lists commit subjects that do not match
  `<type>(<scope>): <description>`.
- Exit 0: in sync (and pushed with `--push`); prints the new HEAD and the
  ahead/behind counts. Exit 1: refused, a rebase conflict (left in progress:
  resolve it and `git rebase --continue`, or `git rebase --abort`) or invalid
  subjects (reword them, then rerun). Exit 2: bad input, a failed git call, or
  no SonarQube CLI for `--push`.
- `--push` runs `git push --force-with-lease -u origin <branch>` with
  `core.hooksPath=.githooks`; never bypass the hooks. The pre-push hook needs
  the SonarQube CLI: the script finds it in the usual install directories and
  adds it to `PATH` for the push only; otherwise install it first (setup
  prerequisite).
- Pushing is an external write: only when the user or a workflow step asks.
