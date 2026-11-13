---
name: pacecraft-resolve-thread
description: Base skill. Resolve one review thread on your own PR after replying with the fix commit's SHA. The only GitHub write agents may make without asking (athlete decision #2629); use from the pr workflow, never on someone else's PR.
---

# Resolve thread

```bash
python scripts/resolve_review_thread.py <pr> <thread-id>
```

- The thread id (`PRRT_...`) comes from
  [pr-state](../pacecraft-pr-state/SKILL.md).
- Run it alone through the Bash tool, from a checkout whose `scripts/` matches
  origin/develop; the `guard_resolve_thread.py` hook blocks anything else.
- It sends only the `resolveReviewThread` mutation, and only when you authored
  the PR, the thread is open, and its last comment is your reply naming a
  commit of the PR made after the finding.
- Exit 0: resolved. Exit 1: refused, with the reason; leave the thread to the
  user. Exit 2: bad input or a failed `gh` call.
