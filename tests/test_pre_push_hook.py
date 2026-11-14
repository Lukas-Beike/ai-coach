"""The pre-push hook runs the secret scan first, then the quality ratchet."""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parents[1] / ".githooks/pre-push"
STUB = """import os, sys
from pathlib import Path
with open(os.environ["HOOK_LOG"], "a", encoding="utf-8") as log:
    print(Path(__file__).name, sys.stdin.read().strip(), file=log)
sys.exit(int(os.environ.get({name!r}, "0")))
"""


@unittest.skipUnless(shutil.which("sh") and shutil.which("git"), "needs sh and git")
class PrePushHookTests(unittest.TestCase):
    def run_hook(self, secrets="0", quality="0", dirty_quality=None):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            for path, name in (
                ("scripts/check_push_secrets.py", "SECRETS_EXIT"),
                ("tools/quality_baseline.py", "QUALITY_EXIT"),
            ):
                (root / path).parent.mkdir(exist_ok=True)
                (root / path).write_text(STUB.format(name=name), encoding="utf-8")
            subprocess.run([*git, "add", "."], cwd=root, check=True)
            subprocess.run([*git, "commit", "-qm", "stubs"], cwd=root, check=True)
            if dirty_quality is not None:
                # An uncommitted edit that would fail if the hook ran it.
                (root / "tools/quality_baseline.py").write_text(
                    f"raise SystemExit({dirty_quality})\n", encoding="utf-8"
                )
            bin_dir = root / "bin"
            bin_dir.mkdir()
            shim = bin_dir / "python"
            shim.write_text(
                f'#!/bin/sh\nexec "{Path(sys.executable).as_posix()}" "$@"\n'
            )
            shim.chmod(0o755)
            log = root / "log"
            result = subprocess.run(
                ["sh", HOOK.as_posix()],
                cwd=root,
                input="refs/heads/x 1 refs/heads/x 0\n",
                capture_output=True,
                text=True,
                check=False,
                timeout=60,
                env={
                    **os.environ,
                    "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
                    "HOOK_LOG": str(log),
                    "SECRETS_EXIT": secrets,
                    "QUALITY_EXIT": quality,
                },
            )
            text = log.read_text(encoding="utf-8") if log.exists() else ""
            lines = [line.rstrip() for line in text.splitlines()]
            return result, lines

    def test_clean_push_runs_both_checks_in_order(self):
        result, lines = self.run_hook()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            lines,
            [
                "check_push_secrets.py refs/heads/x 1 refs/heads/x 0",
                "quality_baseline.py",
            ],
        )

    def test_secret_scan_failure_stops_before_quality(self):
        result, lines = self.run_hook(secrets="3")
        self.assertEqual(result.returncode, 3)
        self.assertEqual(len(lines), 1)

    def test_quality_regression_blocks_the_push(self):
        for quality, reason, other in (
            ("1", "found new findings", "could not run"),
            ("2", "could not run", "found new findings"),
        ):
            with self.subTest(quality=quality):
                result, _lines = self.run_hook(quality=quality)
                self.assertEqual(result.returncode, 1)
                self.assertIn(reason, result.stderr)
                self.assertNotIn(other, result.stderr)

    def test_quality_runs_on_committed_head_not_the_working_tree(self):
        result, lines = self.run_hook(dirty_quality=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(lines[-1], "quality_baseline.py")


if __name__ == "__main__":
    unittest.main()
