"""scripts/issue_create.py with a fake GitHub CLI; no network."""

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gh_cli
import issue_create

EXISTING = [
    {
        "number": 7,
        "title": "fix(sync): retry the Garmin refresh after a timeout",
        "state": "OPEN",
        "url": "u7",
    },
    {
        "number": 9,
        "title": "feat(ui): darker calendar header",
        "state": "CLOSED",
        "url": "u9",
    },
]


class FakeGh:
    def __init__(self, issues):
        self.issues = issues
        self.calls = []

    def __call__(self, argv, **_kwargs):
        self.calls.append(argv)
        if argv[1:3] == ["issue", "list"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.issues), "")
        if argv[1:3] == ["issue", "create"]:
            return subprocess.CompletedProcess(
                argv, 0, "https://example.test/issues/10\n", ""
            )
        return subprocess.CompletedProcess(argv, 1, "", "unexpected call")

    def created(self):
        return [call for call in self.calls if call[1:3] == ["issue", "create"]]


class IssueCreateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.body = Path(self.tmp.name) / "body.md"
        self.body.write_text(
            "## Context\n\nObserved and expected behaviour.\n", encoding="utf-8"
        )

    def run_script(self, *args, issues=EXISTING):
        fake = FakeGh(issues)
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(gh_cli.subprocess, "run", fake),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = issue_create.main(["--body-file", str(self.body), *args])
        return code, out.getvalue(), err.getvalue(), fake

    def test_creates_with_body_file_labels_and_assignee(self):
        code, out, _, fake = self.run_script(
            "--title",
            "fix(calendar): keep the week when paging",
            "--label",
            "bug",
            "--assignee",
            "@me",
        )
        self.assertEqual(code, 0)
        self.assertIn("created: https://example.test/issues/10", out)
        (call,) = fake.created()
        self.assertIn(str(self.body), call)
        self.assertEqual(call[call.index("--label") + 1], "bug")
        self.assertEqual(call[call.index("--assignee") + 1], "@me")

    def test_refuses_likely_duplicate_unless_forced(self):
        title = "fix(sync): retry the Garmin refresh after timeout"
        code, out, _, fake = self.run_script("--title", title)
        self.assertEqual(code, 1)
        self.assertIn("#7", out)
        self.assertEqual(fake.created(), [])
        code, _, _, fake = self.run_script("--title", title, "--force-new")
        self.assertEqual(code, 0)
        self.assertEqual(len(fake.created()), 1)

    def test_dry_run_creates_nothing(self):
        code, out, _, fake = self.run_script(
            "--title", "docs(setup): name the Sonar CLI", "--dry-run"
        )
        self.assertEqual(code, 0)
        self.assertIn("dry run", out)
        self.assertEqual(fake.created(), [])

    def test_rejects_titles_outside_the_convention(self):
        for title in (
            "Fix the calendar",
            "fix: ",
            "feature(ui): new view",
            "fix(UI): x y",
            "fix(ui): " + "x" * 120,
        ):
            with self.subTest(title=title):
                code, _, err, fake = self.run_script("--title", title)
                self.assertEqual(code, 2)
                self.assertIn("title must be", err)
                self.assertEqual(fake.calls, [])

    def test_hyphenated_words_are_not_credentials(self):
        self.body.write_text(
            "Use a risk-adjusted-training-load-model.\n", encoding="utf-8"
        )
        code, _, err, _ = self.run_script("--title", "feat(ui): show load", "--dry-run")
        self.assertEqual((code, err), (0, ""))

    def test_refuses_empty_and_secret_shaped_bodies(self):
        for text in ("  \n", "token ghp_" + "a" * 36 + "\n"):
            with self.subTest(text=text[:8]):
                self.body.write_text(text, encoding="utf-8")
                code, _, err, fake = self.run_script("--title", "fix(ui): keep focus")
                self.assertEqual(code, 2)
                self.assertNotIn("ghp_", err)
                self.assertEqual(fake.calls, [])


if __name__ == "__main__":
    unittest.main()
