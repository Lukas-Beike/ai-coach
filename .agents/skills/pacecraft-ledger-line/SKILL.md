---
name: pacecraft-ledger-line
description: Base skill. Print the one-line orchestrator ledger entry for an issue closed by a merged PR, with the merge commit's line balance. Read-only; use after a PR merged, not before.
---

# Ledger line

```powershell
python scripts/ledger_line.py --issue <n> --pr <m> [--note-file <file>]
```

Prints one line for the orchestrator ledger:

```text
<YYYY-MM-DD> #N closed|part via PR #M <short sha> prod +a/-b tests +c/-d other +e/-f: <note or PR title>
```

- `closed` when the issue is closed, `part` while it stays open (a
  `Part of #N` PR); run it after closing the issue.
- The note is the first non-blank line of `--note-file`, else the PR title.
- The balance comes from the merge commit (see
  [line-balance](../pacecraft-line-balance/SKILL.md)); fetch the base branch
  first so the commit is available locally.
- Exit 0: printed. Exit 1: the PR is not merged; do not write a ledger line
  yet. Exit 2: bad input, credential-shaped note, a missing commit or a failed
  `gh` call.
