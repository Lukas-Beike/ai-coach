"""Exercise the diagnostic ratchet without running providers or changing sources."""

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import quality_baseline


class QualityBaselineTests(unittest.TestCase):
    def setUp(self):
        self.versions = {"ruff": "0.16.10", "mypy": "2.4.0"}
        self.existing = {
            "tool": "ruff",
            "path": "backend/example.py",
            "line": 4,
            "column": 2,
            "code": "F401",
            "message_sha256": "a" * 64,
        }
        self.baseline = {
            "schema": 1,
            "versions": self.versions,
            "diagnostics": [self.existing],
        }

    def check(self, diagnostics):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = quality_baseline.check(self.baseline, self.versions, diagnostics)
        return result, output.getvalue()

    def test_existing_diagnostic_is_accepted(self):
        self.assertEqual(self.check([self.existing])[0], 0)

    def test_line_and_column_shifts_do_not_change_debt(self):
        moved = {**self.existing, "line": 9, "column": 1}
        result, output = self.check([moved])
        self.assertEqual(result, 0)
        self.assertIn("0 new, 0 obsolete", output)

    def test_new_violation_cannot_replace_one_fixed_violation(self):
        changed = {**self.existing, "code": "F811"}
        result, output = self.check([changed])
        self.assertEqual(result, 1)
        self.assertIn("NEW ruff backend/example.py:4 F811", output)
        self.assertIn("OBSOLETE ruff backend/example.py F401", output)

    def test_committed_baseline_stores_line_independent_entries(self):
        root = Path(__file__).resolve().parents[1]
        baseline = json.loads(
            (root / "tests/fixtures/quality_baseline.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            {tuple(sorted(item)) for item in baseline["diagnostics"]},
            {("code", "message_sha256", "path", "tool")},
        )

    def test_snapshot_writes_line_independent_entries(self):
        output = io.StringIO()
        with (
            patch(
                "tools.quality_baseline.collect",
                return_value=(self.versions, [self.existing]),
            ),
            patch.object(
                sys, "argv", ["quality_baseline.py", "--snapshot", "--base", "a" * 40]
            ),
            contextlib.redirect_stdout(output),
        ):
            self.assertEqual(quality_baseline.main(), 0)
        snapshot = json.loads(output.getvalue())
        self.assertEqual(
            snapshot["diagnostics"],
            [
                {
                    "tool": "ruff",
                    "path": "backend/example.py",
                    "code": "F401",
                    "message_sha256": "a" * 64,
                }
            ],
        )

    def test_obsolete_diagnostic_requires_baseline_cleanup(self):
        result, output = self.check([])
        self.assertEqual(result, 1)
        self.assertIn("1 obsolete", output)
        self.assertIn("Regenerate with", output)

    def test_removed_baseline_entry_cannot_be_reintroduced(self):
        self.baseline["diagnostics"] = []
        result, output = self.check([self.existing])
        self.assertEqual(result, 1)
        self.assertIn("NEW ruff backend/example.py:4", output)

    def test_duplicate_diagnostics_are_not_collapsed(self):
        self.assertEqual(self.check([self.existing, self.existing])[0], 1)

    def test_formatter_diagnostics_are_rejected_from_the_quality_baseline(self):
        self.baseline["diagnostics"] = [{"tool": "format"}]
        with self.assertRaisesRegex(RuntimeError, "Ruff and mypy"):
            self.check([])

    def test_formatter_is_not_collected_by_the_quality_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "sample.py").write_text("value = 1\n", encoding="utf-8")
            with patch("tools.quality_baseline.run") as mocked_run:
                mocked_run.side_effect = [
                    "ruff 0.16.10\n",
                    "mypy 2.4.0\n",
                    "[]",
                    "",
                ]
                quality_baseline.collect(root)
            commands = [call.args[0] for call in mocked_run.call_args_list]
        self.assertTrue(any(command[:2] == ["ruff", "check"] for command in commands))
        self.assertTrue(any(command[0] == "mypy" for command in commands))
        self.assertFalse(any("format" in command for command in commands))

    def test_tool_version_drift_is_fatal(self):
        with self.assertRaisesRegex(RuntimeError, "versions"):
            quality_baseline.check(self.baseline, {"ruff": "9.0.0"}, [])

    def test_all_source_boundaries_and_new_files_are_discovered(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = [
                ".github/scripts/new.py",
                "backend/new.py",
                "backend/contract.pyi",
                "backend/data/new.py",
                "e2e/new.py",
                "garmin-login.py",
                "server.py",
                "tests/new.py",
                "tools/new.py",
            ]
            for filename in [*expected, ".venv/generated.py", "data/private.py"]:
                path = root / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            self.assertEqual(quality_baseline.source_files(root), sorted(expected))

    def test_messages_are_hashed_without_source_content(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            item = {
                "filename": str(root / "server.py"),
                "location": {"row": 1, "column": 1},
                "code": "F401",
                "message": "synthetic diagnostic",
            }
            result = quality_baseline.diagnostic("ruff", item, root)
            self.assertNotIn("message", result)
            self.assertNotIn("synthetic", str(result))
            self.assertEqual(result["path"], "server.py")
            self.assertEqual(len(result["message_sha256"]), 64)

    @patch("tools.quality_baseline.subprocess.run")
    def test_tool_failure_cannot_become_baseline_debt(self, mocked_run):
        mocked_run.return_value.returncode = 2
        with self.assertRaisesRegex(RuntimeError, "exit 2"):
            quality_baseline.run(["mypy"], Path.cwd())

    @patch("tools.quality_baseline.subprocess.run")
    def test_failure_without_diagnostics_is_fatal(self, mocked_run):
        mocked_run.return_value.returncode = 1
        mocked_run.return_value.stdout = ""
        with self.assertRaisesRegex(RuntimeError, "without diagnostic"):
            quality_baseline.run(["ruff"], Path.cwd())
