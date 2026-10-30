"""Claude Code PreToolUse hook: block shell commands that touch private runtime paths.

File tools are covered by deny rules in .claude/settings.json; this hook covers
Bash/PowerShell, where deny rules cannot see file arguments. Exit code 2 blocks
the call and returns the message to the agent.
"""

import json
import re
import sys

PRIVATE = re.compile(
    r"""(?ix)
    (?:^|[\s"'=/\\])\.env(?:\.(?!example\b)[\w-]+)?(?![\w.-])  # .env, .env.local; not .env.example
    | (?:^|[\s"'=:])(?:\./|\.\\|/)?data[/\\]                     # data/ in the repo, /data in the container
    | garmin_tokens[/\\]                                         # Garmin token store contents
    """
)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except ValueError:
        print("Blocked: unreadable hook input.", file=sys.stderr)
        return 2
    command = str((payload.get("tool_input") or {}).get("command") or "")
    if PRIVATE.search(command):
        print(
            "Blocked: the command touches .env, the data directory, or Garmin tokens. "
            "These hold live secrets and athlete data; use temporary test data instead.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
