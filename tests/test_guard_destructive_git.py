"""The agent shell hook blocks git commands that discard work (#2635)."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "hooks" / "guard_destructive_git.py"


def run_hook(command: str) -> int:
    body = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=body.encode("utf-8"),
        capture_output=True,
        check=False,
    ).returncode


class GuardDestructiveGitTests(unittest.TestCase):
    def test_destructive_commands_are_blocked(self) -> None:
        for command in (
            "git reset --hard",
            "git reset --hard origin/develop",
            "git -C ../other reset -q --hard HEAD~1",
            "git clean -f",
            "git clean -fd",
            "git clean -xdf",
            "git clean --force",
            "git branch -D feat/x",
            "git branch -Dr origin/x",
            "git branch --delete --force feat/x",
            "git checkout .",
            "git checkout -- .",
            "git restore .",
            "git restore --staged --worktree .",
            "git push --force",
            "git push -f origin feat/x",
            "git push origin +feat/x",
            "git status && git reset --hard",
            "git fetch; git push --force origin feat/x",
            # Forms a shell still runs as the destructive command.
            "git clean -fdx;git status",
            "(git clean -fdx)",
            'bash -c "git push -f origin x"',
            'powershell -Command "git clean -fdx"',
            'git reset "--hard"',
            "git reset '--hard'",
            "git reset `--hard",
            "git push origin '+feat/x'",
            'git checkout -- "."',
            "git reset \\\n  --hard",
            "git push `\n  --force origin x",
            "Git reset --hard",
            "GIT.exe reset --hard",
            "git reset --ha",
            "git branch -d --force x",
            "git branch -df x",
            "git branch --delete x --force",
            "git restore ./",
            "git checkout .\\",
            "git restore :/",
            "git checkout -- *",
            "git checkout -f",
            "git switch --discard-changes develop",
            "git clean --forc",
            "git push --forc origin x",
            "git switch --discard develop",
            "git --git-dir /tmp/x reset --hard",
            "git -C .. -c core.hooksPath=x push --force",
            "/usr/bin/git reset --hard",
        ):
            with self.subTest(command=command):
                self.assertEqual(run_hook(command), 2)

    def test_safe_commands_pass(self) -> None:
        for command in (
            "git push",
            "git push -u origin feat/x",
            "git push --force-with-lease origin feat/x",
            "git push --force-with-lease=feat/x:abc123 --force-if-includes origin feat/x",
            "git reset --soft HEAD~1",
            "git reset HEAD file.py",
            "git clean -n",
            "git branch -d feat/x",
            "git checkout feat/x",
            "git checkout -- public/app.js",
            "git restore public/app.js",
            "git restore --staged public/app.js",
            "git worktree remove ../l16-2614",
            "git log --format=%h -5",
            "echo reset --hard",
            "git restore --staged .",
            'git stash push -m "wip 2 +3"',
            "git switch develop",
            "git -C ../l16-2614 status",
        ):
            with self.subTest(command=command):
                self.assertEqual(run_hook(command), 0)

    def test_unreadable_input_is_blocked(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=b"not json",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)

    def test_hook_runs_beside_the_private_path_guard(self) -> None:
        settings = json.loads(
            (ROOT / ".claude/settings.json").read_text(encoding="utf-8-sig")
        )
        shell = next(
            entry
            for entry in settings["hooks"]["PreToolUse"]
            if entry["matcher"] == "Bash|PowerShell"
        )
        commands = [hook["command"] for hook in shell["hooks"]]
        self.assertTrue(any("guard_private_paths.py" in c for c in commands))
        self.assertTrue(any("guard_destructive_git.py" in c for c in commands))
        self.assertTrue(any("guard_resolve_thread.py" in c for c in commands))
        self.assertTrue(all(hook["onFailure"] == "block" for hook in shell["hooks"]))


if __name__ == "__main__":
    unittest.main()
