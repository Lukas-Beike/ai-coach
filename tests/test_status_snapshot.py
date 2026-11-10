"""Status snapshot checks with a mocked GitHub CLI; no network."""

import importlib.util
import io
import json
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "status_snapshot", ROOT / "scripts/status_snapshot.py"
)
assert SPEC is not None and SPEC.loader is not None
snapshot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(snapshot)


def fake_gh(responses):
    def run(args, **_kwargs):
        key = " ".join(args[1:3])
        if key == "pr list":
            key = "pr list merged" if "merged" in args else "pr list open"
        if key == "api repos/o/n/compare/abc123...develop":
            key = "compare"
        body = responses[key]
        if isinstance(body, int):
            return subprocess.CompletedProcess(args, body, "", "boom\nmore")
        return subprocess.CompletedProcess(args, 0, json.dumps(body), "")

    return run


RESPONSES = {
    "repo view": {"nameWithOwner": "o/n"},
    "release view": {"tagName": "1.2.0", "publishedAt": "2026-01-02T00:00:00Z"},
    "pr list open": [
        {
            "number": 21,
            "title": "feat: x",
            "baseRefName": "develop",
            "mergeStateStatus": "BLOCKED",
            "autoMergeRequest": {"mergeMethod": "SQUASH"},
            "statusCheckRollup": [
                {"name": "validate", "status": "IN_PROGRESS", "conclusion": ""}
            ],
        }
    ],
    "pr list merged": [
        {
            "number": 7,
            "title": "chore(release): promote 1.1.0 to main",
            "headRefOid": "old",
        },
        {
            "number": 9,
            "title": "chore(release): promote 1.2.0 to main",
            "headRefOid": "abc123",
        },
    ],
    "compare": [
        {
            "sha": "1",
            "message": "fix(a): thing (#11)\n\nbody",
            "date": "2026-01-03T00:00:00Z",
        },
        {"sha": "2", "message": "chore: direct commit", "date": "2026-01-04T00:00:00Z"},
    ],
    "run list": [
        {"event": "schedule", "status": "completed", "conclusion": "", "createdAt": "t"}
    ],
    "issue list": [{"number": 3, "title": "Blocker"}],
}


class StatusSnapshotTests(unittest.TestCase):
    def test_open_checks_report_only_non_passing_names(self):
        rollup = [
            {"name": "ok", "status": "COMPLETED", "conclusion": "SUCCESS"},
            {"name": "skipped", "status": "COMPLETED", "conclusion": "SKIPPED"},
            {"name": "red", "status": "COMPLETED", "conclusion": "FAILURE"},
            {"name": "queued", "status": "QUEUED", "conclusion": ""},
            {"context": "legacy", "state": "PENDING"},
            {"context": "legacy-ok", "state": "SUCCESS"},
        ]
        self.assertEqual(
            snapshot.open_checks(rollup),
            ["red (failure)", "queued (pending)", "legacy (pending)"],
        )

    def test_promotion_matches_release_tag_not_latest_merged(self):
        with mock.patch.object(snapshot.subprocess, "run", fake_gh(RESPONSES)):
            self.assertEqual(snapshot.release_promotion("o/n", "1.1.0")["number"], 7)
            self.assertEqual(snapshot.release_promotion("o/n", "1.2.0")["number"], 9)

    def test_merged_since_release_parses_squash_subjects(self):
        with mock.patch.object(snapshot.subprocess, "run", fake_gh(RESPONSES)):
            merged = snapshot.merged_since("o/n", {"headRefOid": "abc123"})
        self.assertEqual(
            [(m["number"], m["title"]) for m in merged],
            [(11, "fix(a): thing"), (None, "chore: direct commit")],
        )
        self.assertEqual(snapshot.merged_since("o/n", None), [])

    def test_json_output_and_release_runs(self):
        out = io.StringIO()
        with (
            mock.patch.object(snapshot.subprocess, "run", fake_gh(RESPONSES)),
            redirect_stdout(out),
        ):
            self.assertEqual(snapshot.main(["--repo", "o/n", "--json"]), 0)
        data = json.loads(out.getvalue())
        self.assertEqual(data["release"]["tag"], "1.2.0")
        self.assertEqual(data["promotion_pr"], 9)
        self.assertIsNone(data["release_runs"][0]["conclusion"])
        self.assertEqual(data["release_blockers"], [{"number": 3, "title": "Blocker"}])
        self.assertEqual(
            data["open_prs"][0],
            {
                "number": 21,
                "title": "feat: x",
                "base": "develop",
                "merge_state": "BLOCKED",
                "auto_merge": True,
                "open_checks": ["validate (pending)"],
            },
        )

    def test_default_repo_comes_from_gh_repo_view(self):
        calls = []

        def run(args, **kwargs):
            calls.append(args[1:3])
            if args[1:3] == ["repo", "view"]:
                return subprocess.CompletedProcess(args, 0, "o/n\n", "")
            return fake_gh(RESPONSES)(args, **kwargs)

        with (
            mock.patch.object(snapshot.subprocess, "run", run),
            redirect_stdout(io.StringIO()),
        ):
            self.assertEqual(snapshot.main([]), 0)
        self.assertEqual(calls[0], ["repo", "view"])

    def test_text_output_lists_sections(self):
        out = io.StringIO()
        with (
            mock.patch.object(snapshot.subprocess, "run", fake_gh(RESPONSES)),
            redirect_stdout(out),
        ):
            self.assertEqual(snapshot.main(["--repo", "o/n"]), 0)
        text = out.getvalue()
        self.assertIn("release 1.2.0", text)
        self.assertIn("#11 fix(a): thing", text)
        self.assertIn("  chore: direct commit (", text)
        self.assertNotIn("#None", text)
        self.assertIn("Release blockers:\n  #3 Blocker", text)

    def test_gh_failure_exits_nonzero_with_clear_message(self):
        err = io.StringIO()
        with (
            mock.patch.object(snapshot.subprocess, "run", fake_gh({"release view": 1})),
            redirect_stderr(err),
        ):
            self.assertEqual(snapshot.main(["--repo", "o/n"]), 1)
        self.assertIn("status_snapshot: gh release view failed: boom", err.getvalue())

    def test_missing_gh_exits_nonzero(self):
        err = io.StringIO()
        with (
            mock.patch.object(
                snapshot.subprocess, "run", side_effect=FileNotFoundError
            ),
            redirect_stderr(err),
        ):
            self.assertEqual(snapshot.main([]), 1)
        self.assertIn("not installed", err.getvalue())


if __name__ == "__main__":
    unittest.main()
