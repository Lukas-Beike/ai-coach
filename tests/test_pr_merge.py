"""scripts/pr_merge.py with a stubbed GitHub CLI; no network, no sleeping."""

import io
import json
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import gh_cli
import pr_merge

CLEAN = (
    "GraphQL: Pull request Pull request is in clean status (enablePullRequestAutoMerge)"
)
GREEN = {
    "__typename": "CheckRun",
    "name": "unit",
    "status": "COMPLETED",
    "conclusion": "SUCCESS",
}
RED = {**GREEN, "conclusion": "FAILURE"}


def view(state, checks=(GREEN,)):
    merge = {"oid": "0123456789abcdef"} if state == "MERGED" else None
    return {"state": state, "mergeCommit": merge, "statusCheckRollup": list(checks)}


def run(case, *args, auto_error="", views=()):
    """Run main against a stub that answers `pr view` from `views` in order."""
    calls, views = [], list(views)

    def fake(argv, **_kwargs):
        calls.append(argv[1:])
        if argv[1:3] == ["pr", "view"]:
            return subprocess.CompletedProcess(argv, 0, json.dumps(views.pop(0)), "")
        failed = auto_error and "--auto" in argv
        return subprocess.CompletedProcess(argv, int(bool(failed)), "", auto_error)

    out, err = io.StringIO(), io.StringIO()
    with (
        mock.patch.object(gh_cli.subprocess, "run", fake),
        mock.patch.object(pr_merge.time, "sleep") as sleep,
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        code = pr_merge.main([str(arg) for arg in args])
    case.assertEqual(views, [], "every stubbed state was polled")
    return code, out.getvalue() + err.getvalue(), calls, sleep.call_count


class PrMergeTests(unittest.TestCase):
    def test_arms_squash_auto_merge(self):
        code, out, calls, _ = run(self, 7)
        self.assertEqual(
            (code, calls), (0, [["pr", "merge", "7", "--auto", "--squash"]])
        )
        self.assertIn("auto-merge armed", out)

    def test_clean_status_refusal_merges_directly(self):
        # #2776: GitHub refuses auto-merge for a PR whose checks already passed
        code, out, calls, _ = run(self, 7, auto_error=CLEAN)
        self.assertEqual(code, 0)
        self.assertEqual(calls[-1], ["pr", "merge", "7", "--squash"])
        self.assertIn("merged directly", out)

    def test_other_refusal_fails_without_a_direct_merge(self):
        code, out, calls, _ = run(self, 7, auto_error="GraphQL: Base branch policy")
        self.assertEqual((code, len(calls)), (2, 1))
        self.assertIn("Base branch policy", out)

    def test_wait_polls_in_turn_until_merged(self):
        # #2795: no yield on a watcher that may never wake on the merge
        views = [view("OPEN"), view("OPEN"), view("MERGED")]
        code, out, _, sleeps = run(self, 7, "--wait", 5, views=views)
        self.assertEqual((code, sleeps), (0, 2))
        self.assertIn("merged: 0123456789", out)

    def test_wait_stops_on_close_failure_or_timeout(self):
        for views, minutes, expect in (
            ([view("CLOSED")], 5, 1),
            ([view("OPEN", (GREEN, RED))], 5, 1),
            ([view("OPEN")] * 4, 1, 3),
        ):
            with self.subTest(expect=expect, polls=len(views)):
                code, _, _, sleeps = run(self, 7, "--wait", minutes, views=views)
                self.assertEqual((code, sleeps), (expect, len(views) - 1))


if __name__ == "__main__":
    unittest.main()
