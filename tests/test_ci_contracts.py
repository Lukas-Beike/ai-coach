"""Exercise source selection and shard discovery without remote CI side effects."""
import importlib.util
import re
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest

import run_tests

SPEC = importlib.util.spec_from_file_location("release_source", Path(__file__).resolve().parents[1] / ".github/scripts/release_source.py")
release_source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_source)


class WorkflowSourceTests(unittest.TestCase):
    def test_executed_source_is_bound_to_the_workflow_event(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/publish-container.yml").read_text(encoding="utf-8")
        checkout_refs = re.findall(r"^          ref: (.+)$", workflow, re.M)
        self.assertEqual(len(checkout_refs), 8)
        self.assertTrue(all(ref == "${{ github.sha }}" for ref in checkout_refs[1:]))
        self.assertIn("'refs/heads/main' || github.sha", checkout_refs[0])
        self.assertNotIn("source_ref", workflow)
        self.assertIn("SOURCE_REF: ${{ github.sha }}", workflow)
        self.assertIn("TESTED_SHA: ${{ needs.source.outputs.source_sha }}", workflow)
        self.assertIn('release_source.py --verify "$TESTED_SHA"', workflow)
        self.assertIn("github.ref == 'refs/heads/main' && inputs.publish_container == true", workflow)

    def test_release_pr_dispatch_selects_its_own_branch_without_source_override(self):
        workflow = (Path(__file__).resolve().parents[1] / ".github/workflows/weekly-release.yml").read_text(encoding="utf-8")
        dispatch = workflow.split("trigger_release_test() {", 1)[1].split("ensure_release_test() {", 1)[0]
        self.assertIn('--ref "$source_ref"', dispatch)
        self.assertIn('--field "publish_container=false"', dispatch)
        self.assertNotIn('--field "source_ref=', dispatch)


class CodexReviewWorkflowTests(unittest.TestCase):
    def test_codex_gate_uses_subscription_review_and_required_check_context(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/codex-code-review.yml").read_text(encoding="utf-8")
        action = (root / ".github/actions/codex-review-gate/action.yml").read_text(encoding="utf-8")

        self.assertIn("pull_request_target:", workflow)
        self.assertIn("ready_for_review", workflow)
        self.assertIn("issue_comment:", workflow)
        self.assertIn("github.run_id", workflow)
        self.assertIn("github.event.pull_request.draft != true", workflow)
        self.assertIn("uses: ./.github/actions/codex-review-gate", workflow)
        self.assertIn("check-name: Codex code review", workflow)
        self.assertNotIn("openai/codex-action", workflow)
        self.assertNotIn("openai-api-key", workflow)

        self.assertIn("checks.create", action)
        self.assertIn("issues.listComments", action)
        self.assertIn("pulls.listReviews", action)
        self.assertIn("codex-pull-request-review-summary", action)
        self.assertIn("codex-security-review:v1", action)
        self.assertIn("summaryStatus === 'completed'", action)
        self.assertIn("context.payload.comment?.created_at", action)
        self.assertIn("Date.parse(review.submitted_at) >= minimumSubmittedAt", action)
        self.assertIn("/\\[P[0-3]\\]/gi", action)
        self.assertIn("Math.min(currentPollSeconds * 2, 120)", action)
        self.assertIn("pull_request_review_id", action)
        self.assertIn("review.commit_id === headSha", action)
        self.assertNotIn("comment.commit_id === headSha", action)
        self.assertIn("core.setFailed", action)
        self.assertFalse((root / ".github/codex/prompts/review.md").exists())


class DiscoveryTests(unittest.TestCase):
    def test_direct_cli_discovers_backend_modules_from_any_working_directory(self):
        runner = Path(run_tests.__file__).resolve()
        with tempfile.TemporaryDirectory() as directory:
            output = subprocess.check_output([sys.executable, str(runner), "--list"], cwd=directory, text=True, stderr=subprocess.PIPE)
        ids = output.splitlines()
        self.assertTrue(any(test_id.startswith("test_coach_intent.") for test_id in ids))
        self.assertTrue(any(test_id.startswith("test_db_manager.") for test_id in ids))
        self.assertEqual(ids, sorted(set(ids)))

    def test_every_discovered_module_runs_once_across_shards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("intent", "db", "new_module"):
                (root / f"test_{name}.py").write_text("import unittest\nclass Case(unittest.TestCase):\n def test_example(self): pass\n", encoding="utf-8")
            tests = run_tests.discover_tests(root)
            expected = [test.id() for test in tests]
            actual = [test.id() for shard in range(1, 5) for test in run_tests.select_shard(tests, shard, 4)]
            self.assertEqual(len(expected), 3)
            self.assertCountEqual(actual, expected)
            self.assertEqual(len(actual), len(set(actual)))

    def test_discovery_import_failure_is_fatal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test_broken_fixture.py").write_text("raise RuntimeError('synthetic import failure')", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "synthetic import failure"):
                run_tests.discover_tests(root)


@unittest.skipUnless(shutil.which("git"), "Git fixture contracts run in native CI; Git is not an application runtime dependency")
class ReleaseSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git("init", "--initial-branch=develop")
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.commit("1.7.2")
        self.sha = self.git("rev-parse", "HEAD")
        self.git("tag", "1.7.2")
        self.git("branch", "main")
        self.git("update-ref", "refs/remotes/origin/main", self.sha)

    def git(self, *args):
        return subprocess.check_output(["git", "-C", str(self.root), *args], text=True, stderr=subprocess.PIPE).strip()

    def commit(self, version):
        (self.root / "server.py").write_text(f'APP_VERSION = "{version}"\n', encoding="utf-8")
        self.git("add", "server.py")
        self.git("commit", "-m", "test: fixture")

    def test_source_and_tag_must_identify_same_commit(self):
        self.assertEqual(release_source.resolve(self.root, self.sha, "1.7.2"), self.sha)
        self.commit("1.7.3")
        with self.assertRaisesRegex(ValueError, "different commits"):
            release_source.resolve(self.root, self.git("rev-parse", "HEAD"), "1.7.2")

    def test_release_rejects_mutable_branch_source(self):
        with self.assertRaisesRegex(ValueError, "immutable commit SHA"):
            release_source.resolve(self.root, "develop", "1.7.2")

    def test_read_only_release_pr_can_resolve_before_its_tag_exists(self):
        self.commit("1.7.3")
        self.assertEqual(release_source.resolve(self.root, "develop"), self.git("rev-parse", "HEAD"))

    def test_release_rejects_commit_outside_main(self):
        self.commit("1.7.3")
        self.git("tag", "1.7.3")
        with self.assertRaisesRegex(ValueError, "protected main history"):
            release_source.resolve(self.root, "1.7.3", "1.7.3")

    def test_moving_branch_cannot_change_resolved_checkout(self):
        source = release_source.resolve(self.root, "1.7.2", "1.7.2")
        self.commit("1.7.3")
        with self.assertRaisesRegex(ValueError, "differs"):
            release_source.verify(self.root, source, "1.7.2")
        self.git("checkout", "--detach", source)
        release_source.verify(self.root, source, "1.7.2")

    def test_tag_version_must_match_application(self):
        self.git("tag", "9.0.0")
        with self.assertRaisesRegex(ValueError, "APP_VERSION"):
            release_source.resolve(self.root, "9.0.0", "9.0.0")

    def test_build_verification_requires_fetching_the_release_tag(self):
        clone = self.root / "checkout"
        subprocess.check_output(["git", "clone", "--depth=1", "--no-tags", self.root.as_uri(), str(clone)], stderr=subprocess.PIPE)
        with self.assertRaises(subprocess.CalledProcessError):
            release_source.verify(clone, self.sha, "1.7.2")
        release_source.git(clone, "fetch", "--unshallow", "--tags", "origin")
        release_source.git(clone, "fetch", "origin", "main:refs/remotes/origin/main")
        release_source.verify(clone, self.sha, "1.7.2")
