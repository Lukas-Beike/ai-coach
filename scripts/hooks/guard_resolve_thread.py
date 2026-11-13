"""Claude Code PreToolUse hook: the review-thread resolve script runs only as itself.

`.claude/settings.json` allows `python scripts/resolve_review_thread.py` without
a prompt (athlete decision #2629). That rule matches command text, so this hook
blocks any shell command that names the script unless the whole command is
exactly `python scripts/resolve_review_thread.py <pr> <PRRT_id>` and the script,
its `gh_cli.py` helper and `scripts/` hold no change against origin/develop.
Exit code 2 blocks the call.
"""

import json
import re
import subprocess
import sys

EXACT = re.compile(r"python scripts/resolve_review_thread\.py \d+ PRRT_[A-Za-z0-9_-]+")


def unchanged() -> bool:
    """No edit of the script or helper, and no added module that could shadow them."""
    diff = subprocess.run(
        [
            "git",
            "diff",
            "--quiet",
            "origin/develop",
            "--",
            "scripts/resolve_review_thread.py",
            "scripts/gh_cli.py",
        ],
        capture_output=True,
        check=False,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", "scripts"],
        capture_output=True,
        text=True,
        check=False,
    )
    return diff.returncode == 0 and status.returncode == 0 and not status.stdout.strip()


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except ValueError:
        print("Blocked: unreadable hook input.", file=sys.stderr)
        return 2
    command = str((payload.get("tool_input") or {}).get("command") or "")
    if "resolve_review_thread" not in command:
        return 0
    if EXACT.fullmatch(command.strip()) and unchanged():
        return 0
    print(
        "Blocked: the review-thread resolve script runs only as "
        "`python scripts/resolve_review_thread.py <pr> <PRRT_id>`, alone, from a "
        "checkout whose scripts/ matches origin/develop (#2629).",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
