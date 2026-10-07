"""Exercise source selection and shard discovery without remote CI side effects."""

import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import run_tests

SPEC = importlib.util.spec_from_file_location(
    "release_source",
    Path(__file__).resolve().parents[1] / ".github/scripts/release_source.py",
)
release_source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_source)


class WorkflowSourceTests(unittest.TestCase):
    def test_dependabot_covers_all_manifests_on_develop(self):
        root = Path(__file__).resolve().parents[1]
        configuration = (root / ".github/dependabot.yml").read_text(encoding="utf-8")
        updates = re.split(r"  - package-ecosystem: ", configuration)[1:]
        self.assertEqual(
            {update.splitlines()[0] for update in updates},
            {"pip", "npm", "docker", "github-actions"},
        )
        for update in updates:
            self.assertIn("target-branch: develop", update)
            self.assertIn("commit-message:", update)
            self.assertNotIn("ignore:", update)

    def test_workflow_actions_are_immutable_and_ci_does_not_persist_credentials(self):
        root = Path(__file__).resolve().parents[1]
        for path in (root / ".github/workflows").glob("*.yml"):
            workflow = path.read_text(encoding="utf-8")
            for action in re.findall(r"uses: ([^\s#]+)", workflow):
                self.assertRegex(action, r"^[^@]+@[0-9a-f]{40}$", str(path))
        container = (root / ".github/workflows/publish-container.yml").read_text(
            encoding="utf-8"
        )
        self.assertEqual(
            container.count("uses: actions/checkout@"),
            container.count("persist-credentials: false"),
        )

    def test_dependabot_pip_compile_updates_the_hash_locked_docker_inputs(self):
        root = Path(__file__).resolve().parents[1]
        dependabot = (root / ".github/dependabot.yml").read_text(encoding="utf-8")
        dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
        workflow = (root / ".github/workflows/publish-container.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("package-ecosystem: pip", dependabot)
        self.assertIn('directory: "/"', dependabot)

        def pinned_requirements(path):
            content = (root / path).read_text(encoding="utf-8")
            return {
                match.group(1).lower().replace("_", "-"): match.group(2)
                for match in re.finditer(
                    r"(?m)^([A-Za-z0-9_.-]+)==([^\\\s;]+)", content
                )
            }

        for manifest, lock in (
            ("requirements.in", "requirements.txt"),
            ("requirements-dev.in", "requirements-dev.txt"),
        ):
            lock_content = (root / lock).read_text(encoding="utf-8")
            header = "\n".join(lock_content.splitlines()[:8])
            self.assertIn(f"--output-file={lock} {manifest}", header)
            self.assertNotIn("--no-index", header)
            lock_pins = pinned_requirements(lock)
            manifests = pinned_requirements(manifest)
            if manifest == "requirements-dev.in":
                manifests.update(pinned_requirements("requirements.in"))
            for name, version in manifests.items():
                self.assertEqual(
                    lock_pins.get(name), version, f"{name} differs in {lock}"
                )

        self.assertIn("COPY requirements.txt /app/requirements.txt", dockerfile)
        self.assertIn("--require-hashes -r /app/requirements.txt", dockerfile)
        self.assertIn("--require-hashes -r requirements.txt", workflow)
        self.assertIn("--require-hashes -r requirements-dev.txt", workflow)
        self.assertNotIn("requirements.lock", dockerfile + workflow)

    def test_daily_release_limits_default_token_permissions(self):
        workflow = (
            Path(__file__).resolve().parents[1] / ".github/workflows/daily-release.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("permissions:\n  contents: read", workflow)

    def test_executed_source_is_bound_to_the_workflow_event(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/publish-container.yml").read_text(
            encoding="utf-8"
        )
        checkout_refs = re.findall(r"^          ref: (.+)$", workflow, re.MULTILINE)
        self.assertEqual(len(checkout_refs), 8)
        self.assertTrue(all(ref == "${{ github.sha }}" for ref in checkout_refs[1:]))
        self.assertIn("'refs/heads/main' || github.sha", checkout_refs[0])
        self.assertNotIn("source_ref", workflow)
        self.assertIn("SOURCE_REF: ${{ github.sha }}", workflow)
        self.assertIn("TESTED_SHA: ${{ needs.source.outputs.source_sha }}", workflow)
        self.assertIn('release_source.py --verify "$TESTED_SHA"', workflow)
        self.assertIn(
            "github.ref == 'refs/heads/main' && inputs.publish_container == true",
            workflow,
        )

    def test_browser_results_are_aggregated_before_publishing(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/publish-container.yml"
        ).read_text(encoding="utf-8")
        browser = workflow.split("  browser:\n", 1)[1].split("  build-and-push:\n", 1)[
            0
        ]
        self.assertIn("needs: e2e", browser)
        self.assertIn("E2E_RESULT: ${{ needs.e2e.result }}", browser)
        self.assertIn("needs: [source, test, e2e, browser, quality]", workflow)

    def test_published_tags_are_verified_against_the_signed_digest(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/publish-container.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("verify published tag digest parity", workflow)
        self.assertIn("docker buildx imagetools inspect", workflow)
        self.assertIn("Verify image signature", workflow)
        self.assertIn("cosign verify", workflow)

    def test_release_pr_dispatch_selects_its_own_branch_without_source_override(self):
        workflow = (
            Path(__file__).resolve().parents[1] / ".github/workflows/daily-release.yml"
        ).read_text(encoding="utf-8")
        dispatch = workflow.split("trigger_release_test() {", 1)[1].split(
            "ensure_release_test() {", 1
        )[0]
        self.assertIn('--ref "$source_ref"', dispatch)
        self.assertIn('--field "publish_container=false"', dispatch)
        self.assertNotIn('--field "source_ref=', dispatch)

    def test_main_push_test_can_create_the_release_after_promotion_merge(self):
        workflow = (
            Path(__file__).resolve().parents[1] / ".github/workflows/daily-release.yml"
        ).read_text(encoding="utf-8")
        create_release = workflow.split("  create-release:", 1)[1].split(
            "    runs-on:", 1
        )[0]
        self.assertNotIn("workflow_dispatch", create_release)
        self.assertNotIn("chore/release-promotion-", create_release)
        self.assertIn("github.event.workflow_run.event == 'push'", create_release)
        self.assertIn("github.event.workflow_run.head_branch == 'main'", create_release)
        self.assertIn("TESTED_SHA: ${{ github.event.workflow_run.head_sha }}", workflow)
        self.assertIn(
            'tested_tree="$(git show -s --format=\'%T\' "$TESTED_SHA")"', workflow
        )
        self.assertIn(
            'current_main_tree="$(git rev-parse refs/remotes/origin/main^{tree})"',
            workflow,
        )
        self.assertIn('if [[ "$current_main_tree" != "$tested_tree" ]]', workflow)
        self.assertNotIn(
            'git merge-base --is-ancestor "$TESTED_SHA" refs/remotes/origin/main',
            workflow,
        )
        self.assertNotIn("PROMOTION_BRANCH", workflow)
        self.assertNotIn("sleep 10", workflow)
        self.assertIn("queue: max", workflow)
        self.assertIn("branches: [main, 'chore/release-version-*']", workflow)


class CodexReviewWorkflowTests(unittest.TestCase):
    def test_dependabot_automerge_is_limited_to_develop(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/dependabot-automerge.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "github.event.pull_request.user.login == 'dependabot[bot]'", workflow
        )
        self.assertIn("github.event.pull_request.base.ref == 'develop'", workflow)
        self.assertIn(
            "github.event.pull_request.head.repo.full_name == github.repository",
            workflow,
        )

    def test_dependabot_automerge_security_and_major_updates(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/dependabot-automerge.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn("permissions: {}", workflow)
        self.assertIn("pull_request_target:", workflow)
        self.assertIn("--auto --squash", workflow)
        self.assertNotIn("actions/checkout", workflow)
        self.assertNotIn("--admin", workflow)
        self.assertNotIn("update-type", workflow)

    def test_native_review_removes_legacy_release_dispatch(self):
        root = Path(__file__).resolve().parents[1]
        release = (root / ".github/workflows/daily-release.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("codex-code-review.yml", release)
        self.assertFalse((root / ".github/workflows/codex-code-review.yml").exists())


class DiscoveryTests(unittest.TestCase):
    def test_direct_cli_discovers_backend_modules_from_any_working_directory(self):
        runner = Path(run_tests.__file__).resolve()
        with tempfile.TemporaryDirectory() as directory:
            output = subprocess.check_output(
                [sys.executable, str(runner), "--list"],
                cwd=directory,
                text=True,
                stderr=subprocess.PIPE,
            )
        ids = output.splitlines()
        self.assertTrue(
            any(test_id.startswith("test_coach_dialogue.") for test_id in ids)
        )
        self.assertTrue(any(test_id.startswith("test_db_manager.") for test_id in ids))
        self.assertEqual(ids, sorted(set(ids)))

    def test_every_discovered_module_runs_once_across_shards(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("intent", "db", "new_module"):
                (root / f"test_{name}.py").write_text(
                    "import unittest\nclass Case(unittest.TestCase):\n def test_example(self): pass\n",
                    encoding="utf-8",
                )
            tests = run_tests.discover_tests(root)
            expected = [test.id() for test in tests]
            actual = [
                test.id()
                for shard in range(1, 5)
                for test in run_tests.select_shard(tests, shard, 4)
            ]
            self.assertEqual(len(expected), 3)
            self.assertCountEqual(actual, expected)
            self.assertEqual(len(actual), len(set(actual)))

    def test_discovery_import_failure_is_fatal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test_broken_fixture.py").write_text(
                "raise RuntimeError('synthetic import failure')", encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "synthetic import failure"):
                run_tests.discover_tests(root)


@unittest.skipUnless(
    shutil.which("git"),
    "Git fixture contracts run in native CI; Git is not an application runtime dependency",
)
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
        return subprocess.check_output(
            ["git", "-C", str(self.root), *args], text=True, stderr=subprocess.PIPE
        ).strip()

    def commit(self, version):
        (self.root / "server.py").write_text(
            f'APP_VERSION = "{version}"\n', encoding="utf-8"
        )
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
        self.assertEqual(
            release_source.resolve(self.root, "develop"), self.git("rev-parse", "HEAD")
        )

    def test_read_only_release_pr_version_must_match_application(self):
        self.commit("1.7.3")
        result = subprocess.run(
            [
                sys.executable,
                str(
                    Path(__file__).resolve().parents[1]
                    / ".github/scripts/release_source.py"
                ),
                "--source",
                "develop",
                "--expected-version",
                "1.7.3",
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        mismatch = subprocess.run(
            [
                sys.executable,
                str(
                    Path(__file__).resolve().parents[1]
                    / ".github/scripts/release_source.py"
                ),
                "--source",
                "develop",
                "--expected-version",
                "1.7.4",
            ],
            cwd=self.root,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertNotEqual(mismatch.returncode, 0)

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

    def test_resolve_rejects_invalid_source_reference(self):
        for invalid in ["-o", "--output", "develop;rm", "foo..bar", "refs/heads/.."]:
            with self.assertRaisesRegex(ValueError, "valid source reference"):
                release_source.resolve(self.root, invalid)

    def test_verify_rejects_invalid_sha(self):
        with self.assertRaisesRegex(ValueError, "differs"):
            release_source.verify(self.root, "invalid-sha", "1.7.2")

    def test_tag_version_must_match_application(self):
        self.git("tag", "9.0.0")
        with self.assertRaisesRegex(ValueError, "APP_VERSION"):
            release_source.resolve(self.root, "9.0.0", "9.0.0")

    def test_build_verification_requires_fetching_the_release_tag(self):
        clone = self.root / "checkout"
        subprocess.check_output(
            ["git", "clone", "--depth=1", "--no-tags", self.root.as_uri(), str(clone)],
            stderr=subprocess.PIPE,
        )
        with self.assertRaises(subprocess.CalledProcessError):
            release_source.verify(clone, self.sha, "1.7.2")
        release_source.git(clone, "fetch", "--unshallow", "--tags", "origin")
        release_source.git(clone, "fetch", "origin", "main:refs/remotes/origin/main")
        release_source.verify(clone, self.sha, "1.7.2")


class ReleaseWorkflowTests(unittest.TestCase):
    def test_daily_release_uses_release_tree_to_count_new_commits(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "daily-release.yml"
        ).read_text(encoding="utf-8")
        release_counting = workflow.split('if [[ -n "$latest_tag" ]]', 1)[1].split(
            'echo "Commits since latest release:', 1
        )[0]

        self.assertIn(
            'release_tree="$(git show -s --format=\'%T\' "$latest_tag")"',
            release_counting,
        )
        self.assertIn("git log HEAD --format='%H %T'", release_counting)
        self.assertNotIn('git merge-base "$latest_tag" HEAD', release_counting)
        self.assertIn("count_releaseable_commits()", workflow)
        self.assertIn(
            r"!/^chore\(release\): set application version to [0-9]+\.[0-9]+\.[0-9]+( \(#[0-9]+\))?$/",
            workflow,
        )
        self.assertEqual(
            workflow.count('commit_count="$(count_releaseable_commits '), 2
        )
