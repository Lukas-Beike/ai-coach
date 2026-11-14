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
PIN = ["--squash", "--match-head-commit", "feedc0de"]


def view(state="OPEN", checks=(GREEN,), **extra):
    merge = {"oid": "0123456789abcdef"} if state == "MERGED" else None
    return {
        "state": state, "baseRefName": "develop", "headRefOid": "feedc0de",
        "autoMergeRequest": None, "mergeCommit": merge,
        "statusCheckRollup": list(checks), "comments": [], "reviews": [], **extra,
    }  # fmt: skip


def run(case, *args, auto_error="", views=None):
    """Run main against a stub that answers `pr view` from `views` in order."""
    calls, views = [], list(views or [view()])

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
    writes = [call for call in calls if call[:2] == ["pr", "merge"]]
    return code, out.getvalue() + err.getvalue(), writes, sleep.call_count


class PrMergeTests(unittest.TestCase):
    def test_arms_squash_auto_merge_on_the_read_head(self):
        code, out, writes, _ = run(self, 7)
        self.assertEqual((code, writes), (0, [["pr", "merge", "7", "--auto", *PIN]]))
        self.assertIn("auto-merge armed", out)

    def test_clean_status_refusal_merges_the_same_head_directly(self):
        # #2776: GitHub refuses auto-merge for a PR whose checks already passed
        code, out, writes, _ = run(self, 7, auto_error=CLEAN)
        self.assertEqual((code, writes[-1]), (0, ["pr", "merge", "7", *PIN]))
        self.assertIn("merged feedc0de directly", out)

    def test_refusals_never_merge_directly(self):
        for kwargs, expect in (
            ({"auto_error": "GraphQL: Base branch policy"}, 2),
            ({"views": [view(baseRefName="feature/x")]}, 1),
            ({"views": [view(autoMergeRequest={"mergeMethod": "SQUASH"})]}, 0),
        ):
            with self.subTest(expect=expect):
                code, _, writes, _ = run(self, 7, **kwargs)
                self.assertEqual(code, expect)
                self.assertNotIn(["pr", "merge", "7", *PIN], writes)

    def test_wait_polls_in_turn_until_merged(self):
        # #2795: no yield on a watcher that may never wake on the merge
        views = [view(), view(), view(), view("MERGED")]
        code, out, _, sleeps = run(self, 7, "--wait", 5, views=views)
        self.assertEqual((code, sleeps), (0, 2))
        self.assertIn("merged: 0123456789", out)

    def test_wait_stops_on_close_failure_feedback_or_timeout(self):
        late = view(reviews=[{"body": "finding"}])
        for polls, minutes, expect in (
            ([view("CLOSED")], 5, 1),
            ([view(checks=(GREEN, RED))], 5, 1),
            ([late], 5, 1),
            ([view()] * 4, 1, 3),
        ):
            with self.subTest(expect=expect, polls=len(polls)):
                code, _, _, sleeps = run(
                    self, 7, "--wait", minutes, views=[view(), *polls]
                )
                self.assertEqual((code, sleeps), (expect, len(polls) - 1))


if __name__ == "__main__":
    unittest.main()
