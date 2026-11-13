"""scripts/resolve_review_thread.py with a fake GitHub CLI; no network (#2629)."""

import io
import json
import re
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import resolve_review_thread

ME = "lane-agent"
FIX = "98566e738d2f"


def pull(author=ME, resolved=False, reply_by=ME, reply=f"Fixed in {FIX[:8]}."):
    comments = [{"author": {"login": "gitar-bot"}, "body": "finding"}]
    if reply_by:
        comments.append({"author": {"login": reply_by}, "body": reply})
    return {
        "author": {"login": author},
        "commits": {"nodes": [{"commit": {"oid": FIX + "0" * 28}}]},
        "reviewThreads": {
            "nodes": [
                {
                    "id": "PRRT_a1",
                    "isResolved": resolved,
                    "comments": {"nodes": comments},
                }
            ]
        },
    }


def run(state, thread="PRRT_a1"):
    calls = []

    def fake(*args):
        calls.append(args)
        if args[:2] == ("repo", "view"):
            return {"nameWithOwner": "example/repo"}
        if args[:2] == ("api", "user"):
            return {"login": ME}
        return {"data": {"repository": {"pullRequest": state}}}

    out = io.StringIO()
    with (
        mock.patch.object(resolve_review_thread, "gh_json", side_effect=fake),
        redirect_stdout(out),
        redirect_stderr(io.StringIO()),
    ):
        code = resolve_review_thread.main(["2671", thread])
    mutations = [a for a in calls if any("mutation" in str(x) for x in a)]
    return code, out.getvalue(), mutations


class ResolveReviewThreadTests(unittest.TestCase):
    def test_own_pr_with_a_reply_naming_the_fix_commit_is_resolved(self):
        code, out, mutations = run(pull())
        self.assertEqual(code, 0, out)
        self.assertEqual(len(mutations), 1)
        self.assertIn("id=PRRT_a1", mutations[0])

    def test_every_other_case_is_refused_without_a_mutation(self):
        for label, state in (
            ("someone else's PR", pull(author="someone-else")),
            ("already resolved", pull(resolved=True)),
            ("no reply", pull(reply_by=None)),
            ("reply by another user", pull(reply_by="someone-else")),
            ("reply without a commit", pull(reply="Fixed.")),
            ("commit of another PR", pull(reply="Fixed in abcdef1.")),
        ):
            with self.subTest(label):
                code, out, mutations = run(state)
                self.assertEqual(code, 1)
                self.assertIn("refused:", out)
                self.assertEqual(mutations, [])
        code, _out, mutations = run(pull(), thread="PRRT_other")
        self.assertEqual((code, mutations), (1, []))
        code, _out, mutations = run(pull(), thread="not-a-thread")
        self.assertEqual((code, mutations), (2, []))

    def test_only_the_resolve_mutation_is_allowed_and_only_through_the_script(self):
        # The athlete allowed exactly one GitHub write for agents (#2629).
        source = (ROOT / "scripts/resolve_review_thread.py").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"mutation\(", source), ["mutation("])
        self.assertEqual(
            re.findall(r"\{(\w+)\(input:", source), ["resolveReviewThread"]
        )
        settings = json.loads(
            (ROOT / ".claude/settings.json").read_text(encoding="utf-8-sig")
        )
        allowed = settings["permissions"]["allow"]
        github = [rule for rule in allowed if re.search(r"gh |graphql|resolve", rule)]
        self.assertEqual(
            github,
            [
                "Bash(python scripts/resolve_review_thread.py:*)",
                "PowerShell(python scripts/resolve_review_thread.py:*)",
            ],
        )


if __name__ == "__main__":
    unittest.main()
