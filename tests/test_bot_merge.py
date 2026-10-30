"""Exercise bot eligibility and merge requests without contacting GitHub."""

import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from tools import bot_merge


def pull(author="dependabot[bot]", base="develop", branch="deps", sha="a" * 40):
    return {
        "number": 1,
        "state": "open",
        "draft": False,
        "user": {"login": author},
        "base": {"ref": base},
        "head": {"repo": {"full_name": "owner/repo"}, "ref": branch, "sha": sha},
        "auto_merge": {"enabled_by": {"login": "app"}},
    }


class BotMergeTests(unittest.TestCase):
    def test_workflow_has_event_retries_and_disabled_deployment_gate(self):
        workflow = (
            Path(__file__).resolve().parents[1] / ".github/workflows/bot-merge.yml"
        ).read_text(encoding="utf-8")
        for event in (
            "pull_request_target:",
            "pull_request_review_thread:",
            "check_run:",
            "workflow_run:",
            "status:",
            "schedule:",
        ):
            self.assertIn(event, workflow)
        self.assertIn("vars.BOT_MERGE_ENABLED == 'true'", workflow)
        self.assertIn("ref: develop", workflow)
        self.assertIn("cancel-in-progress: false", workflow)

    def test_eligibility_uses_author_repository_and_target(self):
        pr = pull()
        self.assertTrue(bot_merge.eligible(pr, "owner/repo"))
        pr["user"]["login"] = "human"
        pr["head"]["ref"] = "dependabot/fake"
        self.assertFalse(bot_merge.eligible(pr, "owner/repo"))
        self.assertFalse(bot_merge.eligible(pull(base="main"), "owner/repo"))
        self.assertFalse(bot_merge.eligible(pull(), "other/repo"))
        pr = pull()
        pr["draft"] = True
        self.assertFalse(bot_merge.eligible(pr, "owner/repo"))
        del pr["draft"]
        self.assertFalse(bot_merge.eligible(pr, "owner/repo"))
        pr = pull()
        pr["auto_merge"] = None
        self.assertFalse(bot_merge.eligible(pr, "owner/repo"))

    def test_release_requires_author_branch_target_and_auto_merge(self):
        pr = pull("ai-coach-release-bot[bot]", "main", "chore/release-promotion-1.2.3")
        self.assertTrue(bot_merge.eligible(pr, "owner/repo"))
        pr["auto_merge"] = None
        self.assertFalse(bot_merge.eligible(pr, "owner/repo"))
        pr["auto_merge"] = {}
        self.assertFalse(bot_merge.eligible(pr, "owner/repo"))

    def test_merge_uses_fresh_head_and_squash(self):
        pr = pull(sha="b" * 40)
        calls = []

        def api(path, token, payload=None):
            calls.append((path, payload))
            if "pulls?" in path:
                return [{"number": 1}] if path.endswith("&page=1") else []
            if path.endswith("/merge"):
                return {"merged": True}
            return pr

        with patch.object(bot_merge, "request", side_effect=api):
            bot_merge.run("owner/repo", "fake")
        self.assertEqual(calls[-1][1], {"sha": "b" * 40, "merge_method": "squash"})

    def test_release_requires_successful_github_actions_test(self):
        pr = pull("ai-coach-release-bot[bot]", "develop", "chore/release-version-1.2.3")
        paths = []

        def api(path, token, payload=None):
            paths.append(path)
            if "pulls?" in path:
                return [{"number": 1}] if path.endswith("&page=1") else []
            if "check-runs" in path:
                return {
                    "check_runs": [
                        {
                            "name": "test",
                            "status": "completed",
                            "conclusion": "failure",
                            "app": {"id": 15368},
                        }
                    ]
                }
            return pr

        with patch.object(bot_merge, "request", side_effect=api):
            bot_merge.run("owner/repo", "fake")
        self.assertFalse(any(path.endswith("/merge") for path in paths))

    def test_release_successful_test_must_be_from_github_actions(self):
        pr = pull("ai-coach-release-bot[bot]", "develop", "chore/release-version-1.2.3")
        merges = []
        check = {
            "name": "test",
            "status": "completed",
            "conclusion": "success",
            "app": {"id": 999},
        }

        def api(path, token, payload=None):
            if "pulls?" in path:
                return [{"number": 1}] if path.endswith("&page=1") else []
            if "check-runs" in path:
                return {"check_runs": [check]}
            if path.endswith("/merge"):
                merges.append(payload)
                return {"merged": True}
            return pr

        with patch.object(bot_merge, "request", side_effect=api):
            bot_merge.run("owner/repo", "fake")
            self.assertEqual(merges, [])
            check["app"]["id"] = 15368
            bot_merge.run("owner/repo", "fake")
        self.assertEqual(merges, [{"sha": "a" * 40, "merge_method": "squash"}])

    def test_release_accepts_test_on_github_test_merge_commit(self):
        pr = pull("ai-coach-release-bot[bot]", "develop", "chore/release-version-1.2.3")
        pr["merge_commit_sha"] = "b" * 40
        merges = []

        def api(path, token, payload=None):
            if "pulls?" in path:
                return [{"number": 1}] if path.endswith("&page=1") else []
            if "check-runs" in path:
                if "b" * 40 in path:
                    return {
                        "check_runs": [
                            {
                                "name": "test",
                                "status": "completed",
                                "conclusion": "success",
                                "app": {"id": 15368},
                            }
                        ]
                    }
                return {"check_runs": []}
            if path.endswith("/merge"):
                merges.append(payload)
                return {"merged": True}
            return pr

        with patch.object(bot_merge, "request", side_effect=api):
            bot_merge.run("owner/repo", "fake")
        self.assertEqual(merges, [{"sha": "a" * 40, "merge_method": "squash"}])

    def test_closed_pr_is_not_merged(self):
        pr = pull()
        pr["state"] = "closed"
        self.assertFalse(bot_merge.eligible(pr, "owner/repo"))

    def test_failed_api_response_does_not_claim_merge(self):
        pr = pull()

        def api(path, token, payload=None):
            if "pulls?" in path:
                return [{"number": 1}] if path.endswith("&page=1") else []
            if path.endswith("/merge"):
                return {"merged": False}
            return pr

        with (
            patch.object(bot_merge, "request", side_effect=api),
            self.assertRaises(RuntimeError),
        ):
            bot_merge.run("owner/repo", "fake")

    def test_changed_head_rejection_does_not_retry_the_merge(self):
        pr = pull()
        merges = []

        def api(path, token, payload=None):
            if "pulls?" in path:
                return [{"number": 1}] if path.endswith("&page=1") else []
            if path.endswith("/merge"):
                merges.append(payload)
                raise HTTPError("https://example.invalid", 409, "changed", {}, None)
            return pr

        with patch.object(bot_merge, "request", side_effect=api):
            bot_merge.run("owner/repo", "fake")
        self.assertEqual(len(merges), 1)

    def test_blocked_pr_does_not_prevent_other_pr_attempts(self):
        merges = []

        def api(path, token, payload=None):
            if "pulls?" in path:
                return (
                    [{"number": 1}, {"number": 2}] if path.endswith("&page=1") else []
                )
            if path.endswith("/1/merge"):
                merges.append(1)
                raise HTTPError("https://example.invalid", 405, "blocked", {}, None)
            if path.endswith("/2/merge"):
                merges.append(2)
                return {"merged": True}
            return pull()

        with patch.object(bot_merge, "request", side_effect=api):
            bot_merge.run("owner/repo", "fake")
        self.assertEqual(merges, [1, 2])

    def test_duplicate_attempt_cannot_merge_closed_pr(self):
        pr = pull()
        merges = []

        def api(path, token, payload=None):
            if "pulls?" in path:
                return [{"number": 1}] if path.endswith("&page=1") else []
            if path.endswith("/merge"):
                merges.append(payload)
                pr["state"] = "closed"
                return {"merged": True}
            return pr

        with patch.object(bot_merge, "request", side_effect=api):
            bot_merge.run("owner/repo", "fake")
            bot_merge.run("owner/repo", "fake")
        self.assertEqual(len(merges), 1)

    def test_unexpected_permission_error_fails_run(self):
        def api(path, token, payload=None):
            if "pulls?" in path:
                return [{"number": 1}] if path.endswith("&page=1") else []
            if path.endswith("/merge"):
                raise HTTPError("https://example.invalid", 403, "denied", {}, None)
            return pull()

        with (
            patch.object(bot_merge, "request", side_effect=api),
            self.assertRaises(HTTPError),
        ):
            bot_merge.run("owner/repo", "fake")
