r"""Claude Code PreToolUse hook: block Bash edits whose backslashes collapse (#2793).

On the Windows host the Bash tool turns `\\` into `\`, also inside a quoted
heredoc (#2723), so an edit script written inline silently changes its
patterns. This hook blocks, for the Bash tool only:
- a heredoc with a backslash in its body that feeds an interpreter (python,
  node, bash, sh, perl, ruby, also `python -`, `bash -s`) or is written to a
  file (`>` or `tee`);
- an inline edit or one-liner holding a doubled backslash: `python -c`,
  `node -e`, `perl -e`/`-pi`, `ruby -e`, `sed -i`.
A heredoc without backslashes (a commit message) and read-only commands pass.
Exit code 2 blocks.
"""

import json
import re
import sys

INTERPRETER = r"(?:python3?|py|node|bash|sh|perl|ruby)(?:\.exe)?"
FEEDS = re.compile(
    rf"(?:^|[\s;&|(/\\]){INTERPRETER}(?:\s|$)|(?<![0-9&])>(?!&)|\btee\b",
    re.IGNORECASE,
)
HEREDOC = re.compile(r"<<-?[ \t]*(['\"]?)([A-Za-z_]\w*)\1")
ONE_LINER = re.compile(
    rf"(?:^|[\s;&|(/\\]){INTERPRETER}\s+(?:-\S+\s+)*-(?:[ce]|p?i\w*)\b"
    r"|(?:^|[\s;&|(])sed(?:\.exe)?\s+(?:-\S+\s+)*-[A-Za-z]*i",
    re.IGNORECASE,
)


def _heredoc_bodies(command: str):
    """(introducing line, body) for each heredoc; an unterminated body runs to the end."""
    lines = command.split("\n")
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        for match in HEREDOC.finditer(line):
            end = index
            while end < len(lines) and lines[end].strip() != match[2]:
                end += 1
            yield line, "\n".join(lines[index:end])
            index = end + 1


def blocked(command: str) -> bool:
    for head, body in _heredoc_bodies(command):
        if "\\" in body and FEEDS.search(head):
            return True
    return "\\\\" in command and bool(ONE_LINER.search(command))


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except ValueError:
        print("Blocked: unreadable hook input.", file=sys.stderr)
        return 2
    if payload.get("tool_name") != "Bash":
        return 0
    if blocked(str((payload.get("tool_input") or {}).get("command") or "")):
        print(
            "Blocked: the Bash tool on this host collapses `\\\\` to `\\` in "
            "heredocs and one-liners (#2723, #2793), so this edit would change its "
            "own patterns. Write the file with the Write or Edit tool, or put the "
            "edit logic in a scratchpad script written with Write and run it by path.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
