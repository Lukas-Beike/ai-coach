"""Guard the Windows launcher's log handling as text; the launcher is never run."""

import re
import unittest
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "run-server.ps1"


class LauncherLogContractTests(unittest.TestCase):
    def setUp(self):
        self.source = LAUNCHER.read_text(encoding="utf-8")
        invocations = [
            line
            for line in self.source.splitlines()
            if line.lstrip().startswith("&") and '"server.py"' in line
        ]
        self.assertEqual(len(invocations), 1, invocations)
        self.invocation = invocations[0]

    def test_stdout_is_discarded_and_stderr_appended_to_the_launcher_log(self):
        # intervals-coach.log already carries every entry the app prints.
        self.assertNotIn("*>", self.source)
        self.assertIsNone(
            re.search(r"(?:^|\s)[1*]?>{1,2}\s*\$logPath", self.invocation),
            self.invocation,
        )
        self.assertRegex(self.invocation, r"(?:^|\s)>\s*\$null\b")
        self.assertRegex(self.invocation, r"(?:^|\s)2>>\s*\$logPath\b")
        self.assertIn("See $logPath.", self.source)

    def test_launcher_log_rotates_before_start_like_the_app_log(self):
        rotation = self.source.split(self.invocation, 1)[0]
        self.assertRegex(rotation, r"\$\w+\s*=\s*1000000\b")
        self.assertRegex(rotation, r"\$\w*[Bb]ackup\w*\s*=\s*3\b")
        self.assertRegex(rotation, r"Move-Item -LiteralPath \$logPath ")
        self.assertIn('-Destination "$logPath.1"', rotation)


if __name__ == "__main__":
    unittest.main()
