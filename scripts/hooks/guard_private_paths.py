"""Claude Code PreToolUse hook: block shell commands that touch private runtime paths.

File tools are covered by deny rules in .claude/settings.json; this hook covers
Bash/PowerShell, where deny rules cannot see file arguments. It is a safety net
that matches command text, not a sandbox. Exit code 2 blocks the call and
returns the message to the agent.
"""

import json
import re
import sys

# Docker arguments that hand a path to the container without exposing its
# contents to the agent: volume mounts and --env-file.
PASS_THROUGH = re.compile(
    r"""(?x)
    (?:--env-file|-v|--volume|--mount)(?:=|\s+)
    (?:"[^"]*"|'[^']*'|\S+)
    """
)

PRIVATE = re.compile(
    r"""(?ix)
    (?:^|[\s"'=:/\\])\.env(?:\.(?!example\b)[\w-]+)*(?![\w.-])  # .env, .env.local, .env.production.local
    | (?:^|[\s"'=:])(?:\.{1,2}[/\\]|/)?data(?=$|[\s"'/\\;|&)])   # data, ./data, ../data, /data
    | [/\\]data[/\\]                                             # .../data/... in absolute paths
    | [/\\]garmin_tokens(?=$|[\s"'/\\;|&)])                      # Garmin token store
    """
)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except ValueError:
        print("Blocked: unreadable hook input.", file=sys.stderr)
        return 2
    command = str((payload.get("tool_input") or {}).get("command") or "")
    if PRIVATE.search(PASS_THROUGH.sub(" ", command)):
        print(
            "Blocked: the command touches .env, the data directory, or Garmin tokens. "
            "These hold live secrets and athlete data; use temporary test data instead.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
