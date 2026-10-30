"""The agent shell hook blocks commands that touch private runtime paths."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

HOOK = (
    Path(__file__).resolve().parents[1] / "scripts" / "hooks" / "guard_private_paths.py"
)
ENV = "." + "env"
DATA = "da" + "ta/"
TOKENS = "garmin_" + "tokens"


def run_hook(command: str, *, bom: bool = False) -> int:
    body = json.dumps({"tool_name": "Bash", "tool_input": {"command": command}})
    raw = (("\ufeff" if bom else "") + body).encode("utf-8")
    return subprocess.run(
        [sys.executable, str(HOOK)], input=raw, capture_output=True, check=False
    ).returncode


class GuardPrivatePathsTests(unittest.TestCase):
    def test_private_paths_are_blocked(self) -> None:
        for command in (
            f"cat {ENV}",
            f"type {ENV}.local",
            f"ls {DATA}",
            f"Get-Content ./{DATA}coach.db",
            f"docker exec ai-coach ls /{DATA}backups",
            f"cat /srv/{TOKENS}/oauth2_token.json",
        ):
            with self.subTest(command=command):
                self.assertEqual(run_hook(command), 2)
        self.assertEqual(run_hook(f"cat {ENV}", bom=True), 2)

    def test_ordinary_commands_pass(self) -> None:
        for command in (
            f"cat {ENV}.example",
            "git status",
            f"cat tests/{DATA}fixture.json",
            f"grep -r {TOKENS} backend",
            "docker run -v C:\\repo\\data:/data ai-coach:local",
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


if __name__ == "__main__":
    unittest.main()
