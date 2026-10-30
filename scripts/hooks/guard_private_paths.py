"""Claude Code PreToolUse hook: block shell commands that touch private runtime paths.

File tools are covered by deny rules in .claude/settings.json; this hook covers
Bash/PowerShell, where deny rules cannot see file arguments. It is a simple
safety net that matches clear path forms in the command text, not a sandbox:
it cannot tell a path from a search term, so it avoids bare words. Exit code 2
blocks the call and returns the message to the agent.
"""

import json
import re
import sys

START = r"(?:^|[\s\"'=:])"  # start of a shell word or assignment value
END = r"(?=$|[\s\"'/\\;|&)])"  # end of a path segment

PRIVATE = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"(?:^|[\s\"'=:/\\*])\.env(?:\.[\w-]+)*(?![\w.-])",  # .env, *.env, .env.local
        START + r"(?:\.{1,2}[/\\]|/)data" + END,  # ./data, ../data, /data
        START + r"data[/\\]",  # data/... relative to the repo
        r"[/\\]ai-coach[/\\]data" + END,  # primary checkout data dir
        r"[/\\]garmin_tokens|garmin_tokens[/\\]",  # Garmin token store as a path
    )
)
TEMPLATE = re.compile(r"\.env\.example(?![\w.-])", re.IGNORECASE)


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except ValueError:
        print("Blocked: unreadable hook input.", file=sys.stderr)
        return 2
    command = str((payload.get("tool_input") or {}).get("command") or "")
    command = TEMPLATE.sub(" ", command)
    if any(pattern.search(command) for pattern in PRIVATE):
        print(
            "Blocked: the command touches .env, the data directory, or Garmin tokens. "
            "These hold live secrets and athlete data; use temporary test data instead. "
            "If you only mention such a path (for example in a commit message), "
            "pass the text through a file.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
