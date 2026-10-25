"""Exercise source selection and shard discovery without remote CI side effects."""

import fnmatch
import functools
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from decimal import ROUND_DOWN, Decimal
from pathlib import Path

from tests import run_tests

SPEC = importlib.util.spec_from_file_location(
    "release_source",
    Path(__file__).resolve().parents[1] / ".github/scripts/release_source.py",
)
release_source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_source)


class WorkflowSourceTests(unittest.TestCase):
    def test_ai_docs_requires_guidance_before_discovery(self):
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github/workflows/validate-ai-docs.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("  pull_request:\n", workflow)
        self.assertNotIn("pull_request_target:", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertIn("AI_DOCS_REQUIRED: '1'", workflow)
        validator = workflow.index(
            "python -m unittest discover -s tests -p test_ai_docs_contract.py -v"
        )
        for relative in (
            "AGENTS.md",
            "REVIEW.md",
            ".agents/skills/README.md",
            "tests/test_ai_docs_contract.py",
        ):
            self.assertLess(workflow.index(f"test -f {relative}"), validator)

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

    def test_quality_checks_all_sources_and_merges_every_shard(self):
        root = Path(__file__).resolve().parents[1]
        config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        workflow = (root / ".github/workflows/publish-container.yml").read_text(
            encoding="utf-8"
        )

        self.assertEqual(config["tool"]["ruff"]["target-version"], "py314")
        self.assertIn("DTZ", config["tool"]["ruff"]["lint"]["extend-select"])
        self.assertEqual(config["tool"]["mypy"]["python_version"], "3.14")
        self.assertEqual(config["tool"]["mypy"]["files"], ["."])
        self.assertNotIn("exclude", config["tool"]["mypy"])
        coverage = config["tool"]["coverage"]["run"]
        self.assertEqual(coverage["source"], ["server", "backend"])
        self.assertTrue(coverage["branch"])
        self.assertTrue(coverage["relative_files"])
        self.assertTrue(coverage["parallel"])
        evidence = json.loads(
            (root / "tests/fixtures/quality_baseline.json").read_text(encoding="utf-8")
        )
        diagnostics = evidence["diagnostics"]
        self.assertTrue(diagnostics)
        self.assertLessEqual({item["tool"] for item in diagnostics}, {"ruff", "mypy"})
        evidence = evidence["coverage_evidence"]
        totals = evidence["totals"]
        measured = (
            Decimal(totals["covered_lines"] + totals["covered_branches"])
            * 100
            / Decimal(totals["num_statements"] + totals["num_branches"])
        )
        threshold = config["tool"]["coverage"]["report"]["fail_under"]
        self.assertGreater(threshold, 0)
        self.assertEqual(
            Decimal(str(threshold)),
            measured.quantize(Decimal("0.01"), rounding=ROUND_DOWN),
        )
        self.assertEqual(config["tool"]["coverage"]["report"]["precision"], 2)
        self.assertEqual(evidence["shards"], 4)

        shards = workflow.split("  test_shards:\n", 1)[1].split("  syntax:\n", 1)[0]
        self.assertIn("coverage run tests/run_tests.py --shard", shards)
        self.assertIn('--total "$PYTHON_TEST_SHARDS"', shards)
        self.assertIn("python-coverage-${{ matrix.shard }}", shards)
        self.assertIn("include-hidden-files: true", shards)
        self.assertIn("if-no-files-found: error", shards)
        quality = workflow.split("  quality:\n", 1)[1].split("  image_sbom:\n", 1)[0]
        self.assertIn("pattern: python-coverage-*", quality)
        self.assertNotIn("merge-multiple", quality)
        self.assertIn('for shard in $(seq 1 "$PYTHON_TEST_SHARDS")', quality)
        self.assertIn("::error::Test shard ${shard}", quality)
        self.assertIn("coverage combine", quality)
        self.assertIn("coverage report", quality)
        self.assertNotIn("-ne 4", quality)
        self.assertIn("exit 1", quality)
        self.assertNotIn("coverage run", quality)
        self.assertNotIn("--fail-under", quality)
        self.assertNotIn("ruff format", quality)
        self.assertIn("python tools/quality_baseline.py", quality)
        self.assertNotIn("Run lint baseline", quality)
        self.assertIn("/review/pyproject.toml:ro", workflow)
        self.assertIn("/app/tools:ro", workflow)

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
                    r"(?m)^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?==([^\\\s;]+)", content
                )
            }

        for manifest, lock in (
            ("requirements.in", "requirements.txt"),
            ("requirements-dev.in", "requirements-dev.txt"),
            ("requirements-graphify.in", "requirements-graphify.txt"),
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
        self.assertNotIn("requirements-graphify", dockerfile)
        for path in (root / ".github/workflows").glob("*.yml"):
            self.assertNotIn("requirements-graphify", path.read_text(encoding="utf-8"))
        graphify = (root / "requirements-graphify.txt").read_text(encoding="utf-8")
        # pywin32 has no Linux wheels; keep its transitive pin Windows-only.
        windows_pins = re.findall(r"(?m)^pywin32==.*$", graphify)
        self.assertEqual(len(windows_pins), 1)
        self.assertRegex(
            windows_pins[0], r'^pywin32==[^;\s]+\s*; sys_platform == "win32" '
        )

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
        self.assertEqual(len(checkout_refs), 9)
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

    def test_ci_image_is_built_once_and_shared_by_consumers(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/publish-container.yml").read_text(
            encoding="utf-8"
        )
        self.assertEqual(len(re.findall(r"docker build\s", workflow)), 1)
        image = workflow.split("  image:\n", 1)[1].split("  test_shards:\n", 1)[0]
        self.assertIn("docker build --tag ai-coach:ci .", image)
        self.assertIn("needs: source\n", image)
        upload = image.split("actions/upload-artifact@", 1)[1]
        self.assertIn("name: ai-coach-ci-image", upload)
        self.assertIn("retention-days: 1", upload)
        consumers = {
            "container_tests": (
                workflow.split("  container_tests:\n", 1)[1].split("  test:\n", 1)[0],
                "needs: [source, image]",
            ),
            "image_sbom": (
                workflow.split("  image_sbom:\n", 1)[1].split("  e2e:\n", 1)[0],
                "needs: [source, image]",
            ),
            "e2e": (
                workflow.split("  e2e:\n", 1)[1].split("  browser:\n", 1)[0],
                "needs: [source, image]",
            ),
        }
        for job, (text, needs) in consumers.items():
            with self.subTest(job=job):
                self.assertIn(needs, text)
                self.assertIn("name: ai-coach-ci-image", text)
                self.assertIn("gunzip -c ai-coach-ci-image.tar.gz | docker load", text)
                self.assertNotIn("docker build", text)
        self.assertIn("image: ai-coach:ci", consumers["image_sbom"][0])
        self.assertIn("--workdir /app ai-coach:ci", consumers["container_tests"][0])

    def test_e2e_selects_specs_with_playwright_list_not_file_grep(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/publish-container.yml").read_text(
            encoding="utf-8"
        )
        e2e = workflow.split("  e2e:\n", 1)[1].split("  browser:\n", 1)[0]
        self.assertNotIn("grep -q '@responsive'", e2e)
        self.assertIn('--list --project "$project" --reporter=json', e2e)
        self.assertIn("mapfile -t specs", e2e)

    def test_e2e_runs_beside_unit_tests_and_shards_desktop_completely(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/publish-container.yml").read_text(
            encoding="utf-8"
        )
        e2e = workflow.split("  e2e:\n", 1)[1].split("  browser:\n", 1)[0]
        # Browser checks no longer wait for the unit tests; publishing still needs both.
        self.assertNotIn("needs.test", e2e)
        self.assertIn("needs: [source, test, e2e, browser, quality]", workflow)
        entries = re.findall(
            r"- \{ project: ([a-z-]+), shard: (\d+), shards: (\d+) \}", e2e
        )
        projects = {}
        for project, shard, shards in entries:
            projects.setdefault(project, []).append((int(shard), int(shards)))
        self.assertEqual(
            set(projects),
            {"mobile-small", "mobile", "tablet", "tablet-landscape", "desktop"},
        )
        for project, shards in projects.items():
            with self.subTest(project=project):
                count = shards[0][1]
                self.assertEqual(
                    sorted(shards), [(i, count) for i in range(1, count + 1)]
                )
        self.assertIn("index % shards === shard - 1", e2e)
        self.assertIn(
            "browser-test-artifacts-${{ matrix.project }}-${{ matrix.shard }}", e2e
        )
        self.assertIn("format(' {0}/{1}', matrix.shard, matrix.shards)", e2e)

    def test_e2e_fixtures_reuse_slot_networks_created_before_the_browser(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/publish-container.yml").read_text(
            encoding="utf-8"
        )
        e2e = workflow.split("  e2e:\n", 1)[1].split("  browser:\n", 1)[0]
        start_fixture = e2e.split("start_fixture() {", 1)[1].split("\n          }", 1)[
            0
        ]
        # A fixture that brings its own network adds a host veth mid-spec, and Chromium
        # then fails in-flight requests with ERR_NETWORK_CHANGED.
        self.assertIn('--network "container:$(network_name "$index")"', start_fixture)
        self.assertNotIn("--publish", start_fixture)
        loop = e2e.split('for i in "${!specs[@]}"; do', 1)
        self.assertIn("start_network 0\n", loop[0])
        self.assertIn("start_network 1\n", loop[0])
        self.assertNotIn("start_network", loop[1])

    def test_ci_failure_artifacts_exclude_traces_and_auth_state(self):
        root = Path(__file__).resolve().parents[1]
        config = (root / "playwright.config.cjs").read_text(encoding="utf-8")
        self.assertIn('trace: process.env.CI ? "off" : "retain-on-failure"', config)
        self.assertNotIn('trace: "retain-on-failure"', config)
        workflow = (root / ".github/workflows/publish-container.yml").read_text(
            encoding="utf-8"
        )
        upload = workflow.split("name: Upload browser failure artifacts\n", 1)[1]
        upload = upload.split("      - name:", 1)[0]
        paths = upload.split("path: |\n", 1)[1].split("if-no-files-found:", 1)[0]
        self.assertEqual(paths.split(), ["test-results/", "playwright-report/"])
        # The login state lives outside both uploaded directories.
        self.assertIn(
            'path.join(__dirname, "playwright", ".auth", "user.json")', config
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

    def test_dependabot_tool_bumps_align_the_baseline_without_running_pr_code(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/auto-rebase-squash.yml").read_text(
            encoding="utf-8"
        )
        align = workflow.split("- name: Align quality baseline", 1)[1].split(
            "- name: Rebase eligible pull requests", 1
        )[0]
        self.assertIn("branches:\n      - develop", workflow)
        self.assertIn("schedule:\n    - cron: '23 * * * *'", workflow)
        self.assertNotIn("workflow_dispatch", workflow)
        self.assertNotIn("pull_request", workflow.split("jobs:", 1)[0])
        # The checkout is the pushed develop commit; PR files are only data.
        self.assertIn(
            "persist-credentials: false\n          ref: ${{ github.sha }}", workflow
        )
        self.assertIn("--author app/dependabot", align)
        self.assertIn('startswith("dependabot/")', align)
        self.assertIn("select(.isCrossRepository == false)", align)
        self.assertIn("ref=$head_sha", align)
        self.assertIn("env -u GH_TOKEN python tools/quality_baseline.py", align)
        self.assertIn("--align-versions", align)
        # The commit is rejected when the PR head moved after the reads.
        self.assertIn("createCommitOnBranch", align)
        self.assertIn("expectedHeadOid: $head", align)
        self.assertIn('-f head="$head_sha"', align)
        self.assertIn(
            'headline: "build(deps): align quality baseline tool versions"', align
        )
        self.assertNotIn("--method PUT", align)
        self.assertNotIn("pip install", align)
        self.assertNotIn("git push", workflow)
        self.assertIn(
            "if: ${{ !cancelled() && github.event_name == 'push' "
            "&& steps.branch-app-token.outcome == 'success' }}",
            workflow,
        )

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


@functools.cache
def _discovered_suite():
    """Discover the real suite once per process; imports are cached by name."""
    return run_tests.discover_tests()


def _native_shard_count():
    root = Path(__file__).resolve().parents[1]
    workflow = (root / ".github/workflows/publish-container.yml").read_text(
        encoding="utf-8"
    )
    match = re.search(r"(?m)^  PYTHON_TEST_SHARDS: '(\d+)'$", workflow)
    if match is None:
        raise AssertionError("PYTHON_TEST_SHARDS is not declared at workflow level")
    return int(match.group(1))


def _write_synthetic_module(root, name, class_sizes):
    lines = ["import unittest", ""]
    for class_name, count in class_sizes.items():
        lines.append(f"class {class_name}(unittest.TestCase):")
        lines.extend(f"    def test_{index:02d}(self): pass" for index in range(count))
        lines.append("")
    (root / f"test_{name}.py").write_text("\n".join(lines), encoding="utf-8")


class ShardingContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Module names are unique so they cannot collide with the real suite or
        # with modules imported earlier from another temporary directory.
        directory = tempfile.TemporaryDirectory()
        cls.addClassCleanup(directory.cleanup)
        root = Path(directory.name)
        _write_synthetic_module(root, "shardfixture_alpha", {"A1": 3, "A2": 1})
        _write_synthetic_module(root, "shardfixture_beta", {"B1": 5})
        _write_synthetic_module(root, "shardfixture_gamma", {"C1": 2, "C2": 2, "C3": 1})
        _write_synthetic_module(root, "shardfixture_delta", {"D1": 4, "D2": 1, "D3": 1})
        cls.synthetic = run_tests.discover_tests(root)

    def test_every_test_runs_exactly_once_across_shards(self):
        for suite in (self.synthetic, _discovered_suite()):
            expected = sorted(test.id() for test in suite)
            for total in (1, 2, 3, 4, 5):
                with self.subTest(total=total, tests=len(suite)):
                    ids = [
                        test.id()
                        for shard in range(1, total + 1)
                        for test in run_tests.select_shard(suite, shard, total)
                    ]
                    self.assertEqual(sorted(ids), expected)

    def test_no_test_class_is_split_across_shards(self):
        for suite in (self.synthetic, _discovered_suite()):
            for total in (2, 3, 4):
                owners = {}
                for shard in range(1, total + 1):
                    for test in run_tests.select_shard(suite, shard, total):
                        owners.setdefault(run_tests.class_key(test), set()).add(shard)
                with self.subTest(total=total):
                    self.assertEqual(
                        [key for key, shards in owners.items() if len(shards) > 1],
                        [],
                    )

    def test_shards_are_deterministic_and_independent_of_input_order(self):
        suite = self.synthetic
        for shard in range(1, 4):
            first = [test.id() for test in run_tests.select_shard(suite, shard, 3)]
            again = [test.id() for test in run_tests.select_shard(suite, shard, 3)]
            reversed_input = [
                test.id()
                for test in run_tests.select_shard(list(reversed(suite)), shard, 3)
            ]
            with self.subTest(shard=shard):
                self.assertEqual(first, again)
                self.assertEqual(sorted(first), sorted(reversed_input))

    def test_largest_shard_is_within_the_greedy_balance_bound(self):
        # Heaviest-first assignment guarantees max(load) <= mean + heaviest class.
        suite = _discovered_suite()
        weights = run_tests.class_weights(suite, run_tests.load_durations())
        total = _native_shard_count()
        loads = [
            sum(
                weights[key]
                for key in {
                    run_tests.class_key(test)
                    for test in run_tests.select_shard(suite, shard, total)
                }
            )
            for shard in range(1, total + 1)
        ]
        mean = sum(weights.values()) / total
        self.assertLessEqual(max(loads) - mean, max(weights.values()) + 1e-9)
        self.assertLessEqual(max(loads) - min(loads), max(weights.values()) + 1e-9)

    def test_recorded_durations_outweigh_test_counts(self):
        # B1 has the most tests, but A1 is recorded as the slowest class by far.
        suite = self.synthetic
        durations = {
            f"test_shardfixture_{module}.{name}": 1.0
            for module, names in {
                "alpha": ("A2",),
                "beta": ("B1",),
                "gamma": ("C1", "C2", "C3"),
                "delta": ("D1", "D2"),
            }.items()
            for name in names
        }
        durations["test_shardfixture_alpha.A1"] = 100.0
        weights = run_tests.class_weights(suite, durations)
        # Unrecorded D3 (one test) weighs the median recorded seconds per test:
        # median(0.2, 0.25, 0.5, 0.5, 1, 1, 1, 33.3) = 0.75.
        self.assertAlmostEqual(weights["test_shardfixture_delta.D3"], 0.75)
        first = run_tests.select_shard(suite, 1, 2, durations)
        self.assertEqual(
            {run_tests.class_key(test) for test in first},
            {"test_shardfixture_alpha.A1"},
        )
        without = run_tests.class_weights(suite, {})
        self.assertEqual(without["test_shardfixture_beta.B1"], 5.0)

    def test_recorded_durations_file_is_valid(self):
        durations = run_tests.load_durations()
        self.assertTrue(durations, "tests/test_durations.json is missing or empty")
        self.assertTrue(all(seconds >= 0 for seconds in durations.values()))
        self.assertEqual(list(durations), sorted(durations))
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(
                run_tests.load_durations(Path(directory) / "missing.json"), {}
            )

    def test_native_shard_count_is_declared_once_and_matched_by_the_matrix(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/publish-container.yml").read_text(
            encoding="utf-8"
        )
        shards = workflow.split("  test_shards:\n", 1)[1].split("  syntax:\n", 1)[0]
        matrix = re.search(r"shard: \[([0-9, ]+)\]", shards)
        self.assertIsNotNone(matrix)
        self.assertEqual(
            [int(value) for value in matrix.group(1).split(",")],
            list(range(1, _native_shard_count() + 1)),
        )
        self.assertNotIn("--total 4", workflow)
        self.assertIn("AI_DOCS_REQUIRED: '1'", shards)
        # Rulesets require the "Test shard N/<total>" check names.
        self.assertIn(
            f"name: Test shard ${{{{ matrix.shard }}}}/{_native_shard_count()}\n",
            shards,
        )


class ContainerSuiteContractTests(unittest.TestCase):
    def test_every_container_pattern_matches_a_discovered_module(self):
        modules = {run_tests.module_name(test) for test in _discovered_suite()}
        for pattern in run_tests.CONTAINER_SUITE_PATTERNS:
            with self.subTest(pattern=pattern):
                self.assertTrue(
                    any(fnmatch.fnmatchcase(module, pattern) for module in modules),
                    f"container pattern {pattern!r} matches no test module",
                )

    def test_container_suite_is_non_empty_and_narrower_than_the_full_suite(self):
        suite = _discovered_suite()
        container = run_tests.select_suite(suite, "container")
        self.assertTrue(container)
        self.assertLess(len(container), len(suite))
        modules = {run_tests.module_name(test) for test in container}
        for required in (
            "test_container_delivery",
            "test_db_manager",
            "test_security_resource_limits",
            "test_session_auth_cache",
        ):
            with self.subTest(module=required):
                self.assertIn(required, modules)

    def test_container_suite_is_selectable_from_the_command_line(self):
        runner = Path(run_tests.__file__).resolve()
        with tempfile.TemporaryDirectory() as directory:
            output = subprocess.check_output(
                [sys.executable, str(runner), "--list", "--suite", "container"],
                cwd=directory,
                text=True,
                stderr=subprocess.PIPE,
            )
        ids = output.splitlines()
        self.assertTrue(ids)
        modules = {test_id.split(".", 1)[0] for test_id in ids}
        self.assertTrue(
            all(
                any(
                    fnmatch.fnmatchcase(module, p)
                    for p in run_tests.CONTAINER_SUITE_PATTERNS
                )
                for module in modules
            )
        )
        self.assertEqual(
            len(ids), len(run_tests.select_suite(_discovered_suite(), "container"))
        )

    def test_container_job_runs_the_container_suite_with_matching_mounts(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/publish-container.yml").read_text(
            encoding="utf-8"
        )
        container = workflow.split("  container_tests:\n", 1)[1].split("  test:\n", 1)[
            0
        ]
        self.assertIn("python /review/tests/run_tests.py --suite container", container)
        local = (root / "tests/run_sqlcipher_tests.ps1").read_text(encoding="utf-8")
        # The local SQLCipher runner must keep running the full suite.
        self.assertIn("python /review/tests/run_tests.py @runnerArguments\n", local)
        self.assertNotIn("--suite", local)
        mount_pattern = r':(/[^":\s]+):ro"'
        ci_targets = set(re.findall(mount_pattern, container))
        local_targets = set(re.findall(mount_pattern, local))
        self.assertIn("/review/scripts", ci_targets)
        self.assertEqual(ci_targets - local_targets, set())


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
