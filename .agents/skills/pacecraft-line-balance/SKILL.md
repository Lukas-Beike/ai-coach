---
name: pacecraft-line-balance
description: Base skill. Count added and removed lines of a diff or one commit as production, tests and other, ready to paste into a PR body or issue summary. Read-only; use whenever a PR description or summary needs its line balance.
---

# Line balance

```powershell
python scripts/line_balance.py [--base origin/develop] [--head HEAD] [--commit <sha>]
```

Compares `base...head`, or `<sha>^..<sha>` with `--commit`, and prints:

```text
production: +A / -B
tests: +C / -D
other: +E / -F
```

- Production is `backend/`, `server.py` and `public/`; tests are `tests/` and
  `e2e/`; other is docs, skills, scripts and configuration. Binary files
  count as 0.
- Fetch the base first (`git fetch origin`) so the numbers match the PR.
- Exit 0: printed. Exit 2: bad input or a failed `git` call.
- Other scripts reuse `line_balance.balance()`, which returns the same counts
  as a dict of `(added, removed)` pairs.
