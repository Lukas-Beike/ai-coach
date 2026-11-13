"""Claude Code PreToolUse hook: block git commands that discard work (#2635).

Idea from Matt Pocock's git-guardrails-claude-code (MIT); see
.agents/skills/THIRD_PARTY.md. It blocks `git reset --hard`, `git clean -f`, a
forced branch delete, discarding checkouts and restores of the whole tree
(`.`, `:/`, `*`, `checkout -f`, `switch --discard-changes`) and a force push
without a lease; `--force-with-lease` (branch_sync.py), normal pushes and
`git restore --staged .` stay allowed. Like guard_private_paths.py it is a
text safety net, not a sandbox: it reads each shell segment after joining line
continuations and dropping quotes, so a commit message that merely names such a
command is blocked too; pass that text through a file. Exit code 2 blocks.
"""

import json
import re
import sys

CONTINUATION = re.compile(r"(?:\\|`)\r?\n")
QUOTES = re.compile(r"[\"'`]")
SEGMENT = re.compile(r"[;&|\n()]+")
# git, its global options (-C <dir>, -c <key=value>, --flags), the subcommand.
GIT = re.compile(
    r"(?:^|\s)(?i:git)(?:\.exe)?((?:\s+-[Cc]\s+\S+|\s+--?[\w-]+(?:=\S+)?)*)\s+(\S+)(.*)"
)
WHOLE_TREE = {".", "./", ".\\", ":/", ":/*", "*"}


def _short(args: list[str], letter: str) -> bool:
    return any(
        a.startswith("-") and not a.startswith("--") and letter in a for a in args
    )


def _discards(subcommand: str, args: list[str]) -> bool:
    if subcommand == "reset":
        return any(a.startswith("--ha") and "--hard".startswith(a) for a in args)
    if subcommand == "clean":
        return "--force" in args or _short(args, "f")
    if subcommand == "branch":
        deleting = "--delete" in args or _short(args, "d")
        forcing = "--force" in args or _short(args, "f")
        return _short(args, "D") or (deleting and forcing)
    if subcommand == "checkout":
        return "--force" in args or _short(args, "f") or bool(WHOLE_TREE & set(args))
    if subcommand == "restore":
        staged_only = bool({"--staged", "-S"} & set(args)) and not (
            {"--worktree", "-W"} & set(args)
        )
        return bool(WHOLE_TREE & set(args)) and not staged_only
    if subcommand == "switch":
        return bool({"--discard-changes", "--force", "-f"} & set(args))
    if subcommand == "push":
        return (
            "--force" in args
            or _short(args, "f")
            or any(a.startswith("+") for a in args)
        )
    return False


def blocked(command: str) -> bool:
    text = QUOTES.sub("", CONTINUATION.sub(" ", command))
    for segment in SEGMENT.split(text):
        match = GIT.search(segment)
        if match and _discards(match.group(2), match.group(3).split()):
            return True
    return False


def main() -> int:
    try:
        payload = json.loads(sys.stdin.buffer.read().decode("utf-8-sig"))
    except ValueError:
        print("Blocked: unreadable hook input.", file=sys.stderr)
        return 2
    if blocked(str((payload.get("tool_input") or {}).get("command") or "")):
        print(
            "Blocked: this git command discards work (reset --hard, clean -f, a "
            "forced branch delete, a whole-tree checkout/restore, or a force push "
            "without a lease). Use a WIP commit, `git worktree remove` of a clean "
            "worktree, or `git push --force-with-lease`; ask the user if you really "
            "need it. If you only mention the command, pass the text through a file.",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
