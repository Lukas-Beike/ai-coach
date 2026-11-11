"""scripts/issue_update.py with a fake GitHub CLI; no network."""

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
import issue_update

BODY = "## Plan\n- [ ] Add the script\n* [ ] Add the tests\n- [x] Write the issue\n- [ ] Add the docs\n"


class FakeGh:
    def __init__(self, body=BODY, state="OPEN", pulls=()):
        self.body, self.state, self.pulls = body, state, list(pulls)
        self.calls = []
        self.edited_body = None

    def __call__(self, argv, **_kwargs):
        self.calls.append(argv)
        sub = argv[1:3]
        if sub == ["issue", "view"]:
            data = {"body": self.body, "state": self.state}
        elif sub == ["pr", "list"]:
            data = self.pulls
        else:
            if "--body-file" in argv and sub == ["issue", "edit"]:
                path = argv[argv.index("--body-file") + 1]
                self.edited_body = Path(path).read_bytes().decode("utf-8")
            return subprocess.CompletedProcess(argv, 0, "", "")
        return subprocess.CompletedProcess(argv, 0, json.dumps(data), "")

    def writes(self):
        return [
            c[1:4]
            for c in self.calls
            if c[1:3] not in (["issue", "view"], ["pr", "list"])
        ]


class IssueUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "summary.md"
        self.file.write_text("Done: script and tests.\n", encoding="utf-8")

    def run_script(self, *args, **fake_args):
        fake = FakeGh(**fake_args)
        out, err = io.StringIO(), io.StringIO()
        with (
            mock.patch.object(gh_cli.subprocess, "run", fake),
            redirect_stdout(out),
            redirect_stderr(err),
        ):
            code = issue_update.main(list(args))
        return code, out.getvalue(), err.getvalue(), fake

    def test_start_assigns_me_and_labels_in_progress(self):
        code, _, _, fake = self.run_script("start", "12")
        self.assertEqual(code, 0)
        (call,) = fake.calls
        self.assertEqual(
            call[1:],
            [
                "issue",
                "edit",
                "12",
                "--add-assignee",
                "@me",
                "--add-label",
                "in progress",
            ],
        )

    def test_comment_passes_the_body_file_and_never_the_text(self):
        code, _, _, fake = self.run_script(
            "comment", "#12", "--body-file", str(self.file)
        )
        self.assertEqual(code, 0)
        (call,) = fake.calls
        self.assertEqual(
            call[1:], ["issue", "comment", "12", "--body-file", str(self.file)]
        )
        self.assertNotIn("Done: script", " ".join(call))

    def test_comment_refuses_a_secret_shaped_body(self):
        self.file.write_text("key sk-" + "a" * 30, encoding="utf-8")
        code, _, err, fake = self.run_script(
            "comment", "12", "--body-file", str(self.file)
        )
        self.assertEqual(code, 2)
        self.assertNotIn("sk-", err)
        self.assertEqual(fake.writes(), [])

    def test_tick_checks_exactly_one_box_through_a_body_file(self):
        code, out, _, fake = self.run_script("tick", "12", "--part", "add the TESTS")
        self.assertEqual(code, 0)
        self.assertIn("Add the tests", out)
        self.assertEqual(
            fake.edited_body,
            BODY.replace("* [ ] Add the tests", "* [x] Add the tests"),
        )
        self.assertNotIn(fake.edited_body, " ".join(fake.calls[-1]))

    def test_tick_refuses_ambiguous_and_missing_matches(self):
        for part, expect in (
            ("add the", "3 open checkboxes"),
            ("write", "no open checkbox"),
        ):
            with self.subTest(part=part):
                code, out, _, fake = self.run_script("tick", "12", "--part", part)
                self.assertEqual(code, 1)
                self.assertIn(expect, out)
                self.assertIsNone(fake.edited_body)
                self.assertEqual(fake.writes(), [])

    def test_tick_preserves_crlf_line_endings(self):
        body = "- [ ] First\r\n- [ ] Second\r\n"
        code, _, _, fake = self.run_script("tick", "12", "--part", "second", body=body)
        self.assertEqual(code, 0)
        self.assertEqual(fake.edited_body, "- [ ] First\r\n- [x] Second\r\n")

    def test_label_and_assign_repeat_and_need_a_change(self):
        _, _, _, fake = self.run_script(
            "label", "12", "--add", "a", "--add", "b", "--remove", "c"
        )
        self.assertEqual(
            fake.calls[0][4:],
            ["--add-label", "a", "--add-label", "b", "--remove-label", "c"],
        )
        _, _, _, fake = self.run_script("assign", "12", "--remove", "bob")
        self.assertEqual(fake.calls[0][4:], ["--remove-assignee", "bob"])
        code, _, err, fake = self.run_script("label", "12")
        self.assertEqual(code, 2)
        self.assertIn("--add or --remove", err)
        self.assertEqual(fake.calls, [])

    def test_finish_removes_the_in_progress_label(self):
        _, _, _, fake = self.run_script("finish", "12")
        self.assertEqual(fake.calls[0][4:], ["--remove-label", "in progress"])

    def test_close_refuses_open_boxes_and_open_prs_and_writes_nothing(self):
        for fake_args, expect in (
            ({}, "open checkbox: Add the script"),
            (
                {
                    "body": "- [x] done\n",
                    "pulls": [{"number": 5, "state": "OPEN", "title": "t"}],
                },
                "open PR #5",
            ),
        ):
            with self.subTest(expect=expect):
                code, out, _, fake = self.run_script(
                    "close", "12", "--body-file", str(self.file), **fake_args
                )
                self.assertEqual(code, 1)
                self.assertIn(expect, out)
                self.assertEqual(fake.writes(), [])

    def test_close_comments_unlabels_and_closes_when_done(self):
        pulls = [{"number": 5, "state": "MERGED", "title": "t"}]
        code, out, _, fake = self.run_script(
            "close",
            "12",
            "--body-file",
            str(self.file),
            body="- [x] done\n",
            pulls=pulls,
        )
        self.assertEqual(code, 0)
        self.assertIn("closed #12", out)
        self.assertEqual(
            fake.writes(),
            [
                ["issue", "comment", "12"],
                ["issue", "edit", "12"],
                ["issue", "close", "12"],
            ],
        )
        self.assertIn("--body-file", fake.calls[2])
        self.assertIn("#12 in:body", fake.calls[1])

    def test_close_after_a_closing_merge_comments_and_unlabels_only(self):
        code, out, _, fake = self.run_script(
            "close", "12", "--body-file", str(self.file), body="- [x] done\n",
            state="CLOSED",
        )  # fmt: skip
        self.assertEqual(code, 0)
        self.assertIn("#12 was already closed", out)
        self.assertEqual(
            fake.writes(), [["issue", "comment", "12"], ["issue", "edit", "12"]]
        )

    def test_failed_gh_call_exits_2(self):
        def failing(argv, **_kwargs):
            return subprocess.CompletedProcess(argv, 1, "", "not found")

        err = io.StringIO()
        with (
            mock.patch.object(gh_cli.subprocess, "run", failing),
            redirect_stderr(err),
        ):
            self.assertEqual(issue_update.main(["start", "12"]), 2)
        self.assertIn("not found", err.getvalue())


if __name__ == "__main__":
    unittest.main()
