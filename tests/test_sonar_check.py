"""scripts/sonar_check.py with a fake Sonar CLI; no network, no real analysis."""

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import sonar_check

FAKE_SECRET = "AKIA" + "X" * 16
ANALYZE = {
    "issues": [
        {
            "ruleKey": "python:S1192",
            "file": "backend/a.py",
            "line": 12,
            "message": f"literal {FAKE_SECRET} duplicated",
        },
        {
            "ruleKey": "python:S5899",
            "file": "tests/b.py",
            "textRange": {"startLine": 3},
        },
    ],
    "secrets": [{"rule": "secrets:S6290", "file": "backend/c.py", "line": 7}],
    "failures": [{"file": "backend/d.py", "message": FAKE_SECRET}],
}
CLEAN: dict[str, list] = {"issues": []}
FORBIDDEN = {"issues": [], "globalError": {"kind": "forbidden", "message": FAKE_SECRET}}
# The shape `sonar analyze` printed on 2026-11-11: nested sections, the global
# error inside `agentic`, and CLI `messages` that are not issues.
NESTED = {
    "secrets": {"issues": [{"ruleKey": "secrets:S6290", "file": "a.py", "line": 2}], "summary": {}},
    "agentic": {
        "files": ["a.py"], "failures": [], "skipped": [], "summary": {"totalIssues": 0},
        "globalError": {"kind": "forbidden", "message": FAKE_SECRET},
    },
    "messages": [{"text": FAKE_SECRET}],
}  # fmt: skip
LIST_ISSUES = {
    "issues": [
        {
            "rule": "python:S3776",
            "component": "proj:backend/e.py",
            "line": 40,
            "message": FAKE_SECRET,
        }
    ],
    "paging": {"total": 1},
}


class FakeSonar:
    def __init__(self, payload, returncode=0, banner="SONAR banner\n"):
        self.text = banner + (
            payload if isinstance(payload, str) else json.dumps(payload)
        )
        self.returncode = returncode
        self.calls = []

    def __call__(self, argv, **_kwargs):
        self.calls.append(argv)
        return subprocess.CompletedProcess(
            argv, self.returncode, self.text, FAKE_SECRET
        )


def run_main(argv, fake, found="/bin/sonar"):
    out, err = io.StringIO(), io.StringIO()
    with (
        mock.patch.object(sonar_check, "find_sonar", return_value=found),
        mock.patch.object(sonar_check.subprocess, "run", fake),
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        code = sonar_check.main(argv)
    return code, out.getvalue(), err.getvalue()


class SonarCheckTests(unittest.TestCase):
    def test_analyze_prints_counts_and_locations_even_after_a_non_zero_exit(self):
        fake = FakeSonar(ANALYZE, returncode=1)
        code, out, _ = run_main(["--base", "origin/main"], fake)
        self.assertEqual(code, 1)
        self.assertEqual(
            fake.calls[0][1:],
            ["analyze", "--base", "origin/main", "--format", "json"],
        )
        self.assertIn("issues 3, failures 1", out)
        self.assertIn("section issues: 2", out)
        self.assertIn("section secrets: 1", out)
        self.assertIn("issue python:S1192 backend/a.py:12", out)
        self.assertIn("issue python:S5899 tests/b.py:3", out)
        self.assertIn("issue secrets:S6290 backend/c.py:7", out)

    def test_no_payload_text_is_ever_printed(self):
        for payload in (ANALYZE, FORBIDDEN, LIST_ISSUES, NESTED):
            with self.subTest(keys=sorted(payload)):
                _, out, err = run_main(["--pr", "5"], FakeSonar(payload))
                self.assertNotIn(FAKE_SECRET, out + err)
                self.assertNotIn("duplicated", out + err)

    def test_forbidden_global_error_is_a_limit_not_a_pass(self):
        code, out, _ = run_main([], FakeSonar(FORBIDDEN, returncode=1))
        self.assertEqual(code, 0)
        self.assertIn("issues 0, failures 0", out)
        self.assertIn("limit:", out)
        self.assertIn("not a pass", out)

    def test_nested_sections_and_global_error_of_the_real_cli(self):
        code, out, _ = run_main([], FakeSonar(NESTED, returncode=1))
        self.assertEqual(code, 1)
        self.assertIn("issues 1, failures 0", out)
        self.assertIn("section agentic: 0", out)
        self.assertNotIn("section messages", out)
        self.assertIn("limit:", out)
        self.assertIn("issue secrets:S6290 a.py:2", out)

    def test_clean_result_has_no_limit_line(self):
        code, out, _ = run_main([], FakeSonar(CLEAN))
        self.assertEqual(code, 0)
        self.assertNotIn("limit", out)

    def test_missing_cli_is_exit_two_with_the_setup_hint(self):
        fake = FakeSonar(CLEAN)
        code, out, err = run_main([], fake, found=None)
        self.assertEqual(code, 2)
        self.assertIn("sonar auth login", err)
        self.assertEqual((out, fake.calls), ("", []))

    def test_pull_request_mode_prints_rule_file_line_only(self):
        fake = FakeSonar(LIST_ISSUES)
        code, out, _ = run_main(["--pr", "#42"], fake)
        self.assertEqual(code, 1)
        self.assertEqual(
            fake.calls[0][1:],
            ["list", "issues", "--pull-request", "42", "--format", "json"],
        )
        self.assertIn("issue python:S3776 backend/e.py:40", out)

    def test_list_form_and_unsafe_fields_are_handled(self):
        payload = [{"rule": "bad rule\nwith newline", "file": "a\nb", "line": "x"}]
        code, out, _ = run_main(["--pr", "1"], FakeSonar(payload))
        self.assertEqual(code, 1)
        self.assertIn("issue ? ?:?", out)

    def test_unusable_output_is_a_failure(self):
        code, out, _ = run_main([], FakeSonar("not json at all", returncode=3))
        self.assertEqual(code, 1)
        self.assertIn("no JSON result (exit 3)", out)
        code, out, _ = run_main([], FakeSonar({"note": "x"}, returncode=3))
        self.assertEqual(code, 1)
        self.assertIn("exit 3 without a listed issue", out)

    def test_bad_pr_number_is_exit_two(self):
        with self.assertRaises(SystemExit) as raised, redirect_stderr(io.StringIO()):
            run_main(["--pr", "0"], FakeSonar(CLEAN))
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
