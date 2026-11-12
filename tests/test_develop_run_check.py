"""scripts/develop_run_check.py with a fake GitHub CLI; no network."""

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import develop_run_check
import gh_cli

MERGED = {"mergedAt": "2026-11-11T10:00:00Z", "mergeCommit": {"oid": "abc12345def"}}


def run_record(
    run_id, workflow, sha, created, status="completed", conclusion="success"
):
    return {
        "databaseId": run_id,
        "workflowName": workflow,
        "status": status,
        "conclusion": conclusion,
        "url": f"https://example.test/runs/{run_id}",
        "headSha": sha,
        "createdAt": created,
    }


class FakeGh:
    def __init__(self, pr=MERGED, runs=(), jobs=()):
        self.pr, self.runs, self.jobs = pr, list(runs), list(jobs)
        self.calls = []

    def __call__(self, argv, **_kwargs):
        self.calls.append(argv)
        if argv[1:3] == ["pr", "view"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps(self.pr), "")
        if argv[1:3] == ["run", "list"]:
            runs = self.runs
            if "--commit" in argv:
                sha = argv[argv.index("--commit") + 1]
                runs = [r for r in runs if r["headSha"] == sha]
            return subprocess.CompletedProcess(argv, 0, json.dumps(runs), "")
        if argv[1:3] == ["run", "view"]:
            return subprocess.CompletedProcess(
                argv, 0, json.dumps({"jobs": self.jobs}), ""
            )
        return subprocess.CompletedProcess(argv, 1, "", "unexpected call")


def check(*args, **fake_kwargs):
    fake = FakeGh(**fake_kwargs)
    out, err = io.StringIO(), io.StringIO()
    with (
        mock.patch.object(gh_cli.subprocess, "run", fake),
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        code = develop_run_check.main(list(args))
    return code, out.getvalue(), err.getvalue(), fake


SHA = "abc12345def"
CI = ("CI", SHA, "2026-11-11T10:01:00Z")
FAILED_JOBS = [
    {"name": "tests (3.14)", "conclusion": "failure"},
    {"name": "lint", "conclusion": "success"},
]


class DevelopRunCheckTests(unittest.TestCase):
    def test_refuses_unmerged_pr_without_listing_runs(self):
        for pr in ({"mergedAt": None, "mergeCommit": None}, {"mergedAt": "x"}):
            with self.subTest(pr=pr):
                code, out, _, fake = check("--pr", "5", pr=pr)
                self.assertEqual(code, 1)
                self.assertIn("not merged", out)
                self.assertFalse([c for c in fake.calls if c[1:3] == ["run", "list"]])

    def test_all_green_resolves_the_merge_commit(self):
        runs = [run_record(1, *CI), run_record(2, "Docs", SHA, "2026-11-11T10:02:00Z")]
        code, out, _, fake = check("--pr", "#5", runs=runs)
        self.assertEqual(code, 0)
        self.assertEqual(len(out.splitlines()), 2)
        self.assertIn("CI: green", out)
        listing = fake.calls[1]
        self.assertEqual(listing[listing.index("--commit") + 1], SHA)
        self.assertEqual(listing[listing.index("--branch") + 1], "develop")
        self.assertEqual(listing[listing.index("--event") + 1], "push")

    def test_pending_and_missing_runs_exit_three(self):
        runs = [run_record(1, *CI, status="in_progress", conclusion=None)]
        code, out, _, _ = check("--sha", SHA, runs=runs)
        self.assertEqual((code, "CI: pending" in out), (3, True))
        code, out, _, _ = check("--sha", SHA, runs=[])
        self.assertEqual((code, "no develop push runs" in out), (3, True))

    def test_failure_beats_pending(self):
        runs = [
            run_record(1, *CI, conclusion="failure"),
            run_record(2, "Docs", SHA, "2026-11-11T10:02:00Z", "queued", None),
        ]
        code, _, _, _ = check("--sha", SHA, runs=runs, jobs=FAILED_JOBS)
        self.assertEqual(code, 1)

    def test_failed_run_reports_previous_conclusion_and_failed_jobs(self):
        previous = run_record(0, "CI", "older", "2026-11-10T10:00:00Z")
        runs = [previous, run_record(1, *CI, conclusion="failure")]
        code, out, _, fake = check("--sha", SHA, runs=runs, jobs=FAILED_JOBS)
        self.assertEqual(code, 1)
        self.assertIn("CI: failed (failure)", out)
        self.assertIn("possible flake: previous push run 0 success", out)
        self.assertIn("failed jobs: tests (3.14)", out)
        self.assertNotIn("lint", out)
        self.assertIn(["gh", "run", "view", "1", "--json", "jobs"], fake.calls)

    def test_failed_run_after_failed_previous_is_not_a_flake(self):
        previous = run_record(
            0, "CI", "older", "2026-11-10T10:00:00Z", conclusion="failure"
        )
        runs = [previous, run_record(1, *CI, conclusion="failure")]
        _, out, _, _ = check("--sha", SHA, runs=runs, jobs=FAILED_JOBS)
        self.assertIn("previous push run 0 failure", out)
        self.assertNotIn("possible flake", out)

    def test_failed_run_with_newer_push_run_is_superseded(self):
        newer = run_record(
            3, "CI", "newer", "2026-11-11T11:00:00Z", "in_progress", None
        )
        runs = [run_record(1, *CI, conclusion="failure"), newer]
        code, out, _, fake = check("--sha", SHA, runs=runs, jobs=FAILED_JOBS)
        self.assertEqual(code, 1)
        self.assertIn("superseded: newer push run 3", out)
        self.assertIn("do not rerun", out)
        self.assertNotIn("possible flake", out)
        self.assertFalse([c for c in fake.calls if c[1:3] == ["run", "view"]])

    def test_bad_input_and_failed_gh_exit_two(self):
        for args in (["--pr", "0"], ["--pr", "x"], [], ["--pr", "1", "--sha", "a"]):
            with self.subTest(args=args), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as raised:
                    develop_run_check.main(args)
                self.assertEqual(raised.exception.code, 2)
        fake = mock.Mock(
            return_value=subprocess.CompletedProcess(
                [], 1, "", "HTTP 401: Bad credentials"
            )
        )
        err = io.StringIO()
        with (
            mock.patch.object(gh_cli.subprocess, "run", fake),
            redirect_stderr(err),
            redirect_stdout(io.StringIO()),
        ):
            code = develop_run_check.main(["--sha", SHA])
        self.assertEqual(code, 2)
        self.assertIn("failed", err.getvalue())
        # A run record without a field is a malformed answer, not an unmerged PR.
        broken = {k: v for k, v in run_record(1, *CI).items() if k != "conclusion"}
        code, out, _, _ = check("--sha", SHA, runs=[broken])
        self.assertEqual(code, 2)
        self.assertNotIn("refused", out)


if __name__ == "__main__":
    unittest.main()
