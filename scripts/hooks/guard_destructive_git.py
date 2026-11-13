"""Claude Code PreToolUse hook: block git commands that discard work (#2635).

Idea from Matt Pocock's git-guardrails-claude-code (MIT); see
.agents/skills/THIRD_PARTY.md. It blocks `git reset --hard`, `git clean -f`,
`git branch -D`, `git checkout .`, `git restore .` and a force push without a
lease; `--force-with-lease` (branch_sync.py) and normal pushes stay allowed.
Like guard_private_paths.py it matches the command text of each shell segment,
so a commit message that merely names such a command is blocked too; pass that
text through a file. Exit code 2 blocks the call.
"""

import json
import re
import sys

# One shell command: up to the next separator.
ARGS = r"[^;&|\n]*"
GIT = r"\bgit\b" + ARGS
BLOCKED = tuple(
    re.compile(GIT + pattern)
    for pattern in (
        r"\breset\b" + ARGS + r"\s--hard\b",
        r"\bclean\b" + ARGS + r"\s(?:-[a-zA-Z]*f[a-zA-Z]*|--force)(?=$|\s)",
        r"\bbranch\b"
        + ARGS
        + r"\s(?:-[a-zA-Z]*D[a-zA-Z]*(?=$|\s)|--delete\s+--force|--force\s+--delete)",
        r"\b(?:checkout|restore)\b" + ARGS + r"\s(?:--\s+)?\.(?=$|[\s;&|])",
        r"\bpush\b"
        + ARGS
        + r"\s(?:--force(?![-\w])|-[a-zA-Z]*f[a-zA-Z]*(?=$|\s)|\+\S)",
    )
)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except ValueError:
        print("Blocked: unreadable hook input.", file=sys.stderr)
        return 2
    command = str((payload.get("tool_input") or {}).get("command") or "")
    if any(pattern.search(command) for pattern in BLOCKED):
        print(
            "Blocked: this git command discards work (reset --hard, clean -f, "
            "branch -D, checkout/restore ., or a force push without a lease). "
            "Use a WIP commit, `git worktree remove` of a clean worktree, or "
            "`git push --force-with-lease`; ask the user if you really need it. "
            "If you only mention the command, pass the text through a file.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
