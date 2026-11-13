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

CONTINUATION = re.compile(r"[\\`]\r?\n")
QUOTES = re.compile(r"[\"'`]")
SEGMENT = re.compile(r"[;&|\n()]+")
GIT_NAMES = {"git", "git.exe"}
# Global options that take the next word as their value (`git -C <dir> ...`).
GLOBAL_WITH_VALUE = {
    "-C",
    "-c",
    "--git-dir",
    "--work-tree",
    "--namespace",
    "--config-env",
}
WHOLE_TREE = {".", "./", ".\\", ":/", ":/*", "*"}


def _long(names: set[str], option: str) -> bool:
    """The option or an abbreviation git accepts for it (`--ha` for `--hard`)."""
    return any(len(name) > 2 and option.startswith(name) for name in names)


# Per subcommand: does it discard work, given the argument set and the letters
# of all short-option groups (-fdx gives "fdx")?
RULES = {
    "reset": lambda names, short: _long(names, "--hard"),
    "clean": lambda names, short: _long(names, "--force") or "f" in short,
    "branch": lambda names, short: (
        "D" in short
        or (
            (_long(names, "--delete") or "d" in short)
            and (_long(names, "--force") or "f" in short)
        )
    ),
    "checkout": lambda names, short: (
        _long(names, "--force") or "f" in short or bool(WHOLE_TREE & names)
    ),
    # Only `--staged` (without `--worktree`) unstages and keeps the files.
    "restore": lambda names, short: (
        bool(WHOLE_TREE & names)
        and (
            _long(names, "--worktree")
            or "W" in short
            or not (_long(names, "--staged") or "S" in short)
        )
    ),
    "switch": lambda names, short: (
        _long(names, "--discard-changes") or _long(names, "--force") or "f" in short
    ),
    "push": lambda names, short: (
        _long(names, "--force") or "f" in short or any(a.startswith("+") for a in names)
    ),
}


def _discards(subcommand: str, args: list[str]) -> bool:
    rule = RULES.get(subcommand)
    short = "".join(a[1:] for a in args if a.startswith("-") and not a.startswith("--"))
    return bool(rule and rule(set(args), short))


def _git_call(words: list[str], start: int) -> bool:
    """Whether the git call starting after words[start] discards work."""
    index = start + 1
    while index < len(words) and words[index].startswith("-"):
        index += 2 if words[index] in GLOBAL_WITH_VALUE else 1
    return index < len(words) and _discards(words[index], words[index + 1 :])


def blocked(command: str) -> bool:
    text = QUOTES.sub("", CONTINUATION.sub(" ", command))
    for segment in SEGMENT.split(text):
        words = segment.split()
        for index, word in enumerate(words):
            name = word.replace("\\", "/").rsplit("/", 1)[-1].lower()
            if name in GIT_NAMES and _git_call(words, index):
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
