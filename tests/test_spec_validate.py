"""scripts/spec_validate.py with a fake npm; nothing real runs."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import spec_validate

from tests.test_check_changed import FakeRun, run_main


class SpecValidateTests(unittest.TestCase):
    def commands(self, argv):
        runner = FakeRun()
        code, out, _ = run_main(spec_validate, argv, runner)
        return code, out, [call[1:] for call in runner.calls]

    def test_specs_only_by_default(self):
        code, out, calls = self.commands([])
        self.assertEqual(code, 0)
        self.assertIn("ok specs", out)
        self.assertEqual(
            calls,
            [
                [
                    "run",
                    "openspec",
                    "--",
                    "validate",
                    "--specs",
                    "--strict",
                    "--no-interactive",
                ]
            ],
        )

    def test_change_and_all_add_their_validation(self):
        code, _, calls = self.commands(["--change", "add-thing", "--all"])
        self.assertEqual(code, 0)
        self.assertEqual([call[4] for call in calls], ["--specs", "add-thing", "--all"])

    def test_failure_prints_the_tail_and_exits_one(self):
        runner = FakeRun(failing=("--specs",))
        code, out, _ = run_main(spec_validate, [], runner)
        self.assertEqual(code, 1)
        self.assertIn("FAILED specs", out)
        self.assertIn("line 29", out)

    def test_rejects_option_like_change_names_and_reports_missing_npm(self):
        code, _, err = run_main(spec_validate, ["--change=-x"], FakeRun())
        self.assertEqual(code, 2)
        self.assertIn("--change", err)
        code, out, _ = run_main(spec_validate, [], FakeRun(missing=("npm",)))
        self.assertEqual(code, 2)
        self.assertIn("not installed", out)


if __name__ == "__main__":
    unittest.main()
