"""Exercise release events and shell guards without GitHub or repository writes."""

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github/workflows/daily-release.yml"
).read_text(encoding="utf-8")
CREATE_RELEASE = WORKFLOW.split("  create-release:\n", 1)[1]
BUMP_STEP = WORKFLOW.split(
    "      - name: Create version bump PR or promote release\n", 1
)[1]
BLOCKER_STEP = WORKFLOW.split(
    "      - name: Hold scheduled release for release blockers\n", 1
)[1].split("      - name:", 1)[0]
POLICY = (Path(__file__).resolve().parents[1] / "docs/ci-and-releases.md").read_text(
    encoding="utf-8"
)


class ReleaseEventTests(unittest.TestCase):
    def test_only_successful_main_push_tests_can_create_a_release(self):
        condition = CREATE_RELEASE.split("    if: >-\n", 1)[1].split("    runs-on:", 1)[
            0
        ]
        condition = " ".join(condition.split()).replace("&&", "and").replace("||", "or")
        cases = [
            ("workflow_run", "push", "main", "success", True),
            ("workflow_run", "push", "main", "failure", False),
            ("workflow_run", "push", "main", "cancelled", False),
            ("workflow_run", "push", "develop", "success", False),
            ("workflow_run", "workflow_dispatch", "main", "success", False),
            (
                "workflow_run",
                "workflow_dispatch",
                "chore/release-promotion-1.7.3",
                "success",
                False,
            ),
            (
                "workflow_run",
                "pull_request",
                "chore/release-promotion-1.7.3",
                "success",
                False,
            ),
            ("pull_request", "push", "main", "success", False),
        ]
        for event_name, event, branch, conclusion, expected in cases:
            with self.subTest(
                event_name=event_name, event=event, branch=branch, conclusion=conclusion
            ):
                github = SimpleNamespace(
                    event_name=event_name,
                    repository="Lukas-Beike/ai-coach",
                    event=SimpleNamespace(
                        workflow_run=SimpleNamespace(
                            name="Test and publish container image",
                            event=event,
                            head_branch=branch,
                            head_repository=SimpleNamespace(
                                full_name="Lukas-Beike/ai-coach"
                            ),
                            conclusion=conclusion,
                        )
                    ),
                )
                self.assertIs(
                    eval(condition, {"__builtins__": {}}, {"github": github}), expected
                )


class ReleaseBlockerGateTests(unittest.TestCase):
    def test_only_the_schedule_is_gated_and_every_release_step_honors_it(self):
        self.assertIn("        if: github.event_name == 'schedule'\n", BLOCKER_STEP)
        prepare = WORKFLOW.split("  prepare-version:\n", 1)[1].split(
            "  create-release:\n", 1
        )[0]
        steps = prepare.split("      - name: ")[2:]
        self.assertEqual(len(steps), 3)
        for step in steps:
            self.assertIn("if: steps.release-blocker.outputs.blocked != 'true'", step)

    def test_policy_documents_the_label(self):
        self.assertIn("`release-blocker`", POLICY)


@unittest.skipIf(
    os.name == "nt" or not shutil.which("bash"), "Requires the Linux CI Bash runtime"
)
class ReleaseBlockerShellTests(unittest.TestCase):
    def run_gate(self, issues="", prs="", fail="none"):
        with tempfile.TemporaryDirectory() as temp:
            output, summary = Path(temp) / "output", Path(temp) / "summary"
            mocks = textwrap.dedent(
                r"""
                gh() {
                  case "$1" in
                    "$FAIL") return 1 ;;
                    issue) printf '%s' "$ISSUES" ;;
                    pr) printf '%s' "$PRS" ;;
                  esac
                }
                """
            )
            script = textwrap.dedent(BLOCKER_STEP.split("        run: |\n", 1)[1])
            result = subprocess.run(
                ["bash", "--noprofile", "--norc", "-c", mocks + script],
                env={
                    "PATH": os.environ["PATH"],
                    "REPOSITORY": "example/release-test",
                    "ISSUES": issues,
                    "PRS": prs,
                    "FAIL": fail,
                    "GITHUB_OUTPUT": str(output),
                    "GITHUB_STEP_SUMMARY": str(summary),
                },
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
            texts = [
                p.read_text("utf-8") if p.exists() else "" for p in (output, summary)
            ]
            return result, *texts

    def test_open_blockers_hold_the_release_with_a_summary(self):
        result, output, summary = self.run_gate(issues="12\n", prs="34\n")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, "blocked=true\n")
        self.assertIn("#12, #34", summary)

    def test_no_blockers_release_as_before(self):
        result, output, summary = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(output, "blocked=false\n")
        self.assertEqual(summary, "")

    def test_failed_query_fails_without_releasing(self):
        for failing in ("issue", "pr"):
            with self.subTest(failing=failing):
                result, output, _ = self.run_gate(fail=failing)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn("blocked=false", output)


@unittest.skipIf(
    os.name == "nt" or not shutil.which("bash"), "Requires the Linux CI Bash runtime"
)
class ReleaseShellGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "server.py").write_text(
            'APP_VERSION = "1.7.3"\n', encoding="utf-8"
        )
        (self.root / "operations").touch()

    def run_script(self, script, **overrides):
        environment = {
            "PATH": os.environ["PATH"],
            "REPOSITORY": "example/release-test",
            "TESTED_SHA": "a" * 40,
            "TESTED_TREE": "c" * 40,
            "CURRENT_MAIN_TREE": "c" * 40,
            "EVENT_NAME": "workflow_run",
            "WORKFLOW_RUN_BRANCH": "chore/release-version-1.7.3",
            "MERGED_VERSION_PR": "",
            "PR_STATE": "OPEN",
            "DISPATCH_FAIL": "false",
            "MERGE_DURING_DISPATCH": "false",
            "TEST_CHECK_COUNT": "0",
            "TEST_RUN_COUNT": "0",
        }
        environment.update(overrides)
        mocks = r"""
            git() {
              printf '%s\n' "git $*" >> operations
              case "$*" in
                'fetch --no-tags origin refs/heads/main:refs/remotes/origin/main'|\
                'fetch --no-tags origin refs/heads/develop:refs/remotes/origin/develop'|\
                'reset --hard origin/main'|'reset --hard origin/develop') return 0 ;;
                'rev-parse refs/remotes/origin/main^{tree}') printf '%s\n' "$CURRENT_MAIN_TREE" ;;
                'rev-parse HEAD^{tree}') printf '%s\n' "$CURRENT_MAIN_TREE" ;;
                'show -s --format=%T '* ) printf '%s\n' "$TESTED_TREE" ;;
                *) return 97 ;;
              esac
            }
            gh() {
              printf '%s\n' "gh $*" >> operations
              case "$*" in
                'release view 1.7.3 --repo example/release-test') return 0 ;;
                'pr list --repo example/release-test --base develop '* )
                  printf '%s' "$MERGED_VERSION_PR" ;;
                'pr view 123 --repo example/release-test --json state '* )
                  printf '%s' "$PR_STATE" ;;
                'pr view 123 --repo example/release-test --json state,autoMergeRequest '* )
                  if [[ "$PR_STATE" == "MERGED" ]]; then printf true; else printf false; fi ;;
                'pr merge 123 --repo example/release-test --auto --squash')
                  [[ "$PR_STATE" == "OPEN" ]] ;;
                'pr view 123 --repo example/release-test --json statusCheckRollup '* )
                  printf '%s' "$TEST_CHECK_COUNT" ;;
                'pr view 123 --repo example/release-test --json headRefOid '* )
                  printf '%s' "$TESTED_SHA" ;;
                'run list '* ) printf '%s' "$TEST_RUN_COUNT" ;;
                'workflow run '* )
                  if [[ "$MERGE_DURING_DISPATCH" == "true" ]]; then PR_STATE=MERGED; fi
                  [[ "$DISPATCH_FAIL" == "false" ]] ;;
                *) return 97 ;;
              esac
            }
            sleep() {
              printf '%s\n' "sleep $*" >> operations
              return 97
            }
        """
        result = subprocess.run(
            ["bash", "--noprofile", "--norc", "-c", textwrap.dedent(mocks) + script],
            cwd=self.root,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        operations = (self.root / "operations").read_text(encoding="utf-8")
        return result, operations

    def release_test_script(self):
        functions = WORKFLOW.split("          enable_auto_merge() {", 1)[1].split(
            "          version_merge=false", 1
        )[0]
        return (
            "set -euo pipefail\nenable_auto_merge() {"
            + textwrap.dedent(functions)
            + "\nensure_release_test 123 chore/release-version-1.7.3 1.7.3\n"
            + "enable_auto_merge 123\n"
        )

    def test_open_pr_dispatches_release_test(self):
        result, operations = self.run_script(self.release_test_script())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("gh workflow run publish-container.yml", operations)
        self.assertGreater(
            operations.index("gh pr merge"), operations.index("gh workflow run")
        )

    def test_merged_pr_does_not_dispatch_on_deleted_branch(self):
        result, operations = self.run_script(
            self.release_test_script(), PR_STATE="MERGED"
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("gh workflow run", operations)
        self.assertNotIn("gh pr merge", operations)

    def test_merge_during_failed_dispatch_is_successful(self):
        result, operations = self.run_script(
            self.release_test_script(),
            DISPATCH_FAIL="true",
            MERGE_DURING_DISPATCH="true",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("merged during test dispatch", result.stdout)
        self.assertIn("gh workflow run", operations)
        self.assertNotIn("gh pr merge", operations)

    def test_unrelated_dispatch_failure_remains_a_failure(self):
        result, _ = self.run_script(self.release_test_script(), DISPATCH_FAIL="true")
        self.assertEqual(result.returncode, 1, result.stderr)

    def test_existing_tests_do_not_dispatch_again(self):
        for overrides in ({"TEST_CHECK_COUNT": "1"}, {"TEST_RUN_COUNT": "1"}):
            with self.subTest(overrides=overrides):
                result, operations = self.run_script(
                    self.release_test_script(), **overrides
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn("gh workflow run", operations)

    def test_matching_tested_main_can_continue_without_querying_a_promotion_pr(self):
        script = textwrap.dedent(CREATE_RELEASE.split("        run: |\n", 1)[1])
        result, operations = self.run_script(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("git reset --hard origin/main", operations)
        self.assertIn("gh release view 1.7.3", operations)
        self.assertNotIn("gh pr", operations)
        self.assertNotIn("sleep", operations)

    def test_stale_test_result_cannot_reset_main_or_create_a_release(self):
        script = textwrap.dedent(CREATE_RELEASE.split("        run: |\n", 1)[1])
        result, operations = self.run_script(script, CURRENT_MAIN_TREE="d" * 40)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("is not the current main tree", result.stdout)
        self.assertNotIn("git reset", operations)
        self.assertNotIn("gh ", operations)

    def test_same_tree_on_a_new_main_commit_can_create_a_release(self):
        script = textwrap.dedent(CREATE_RELEASE.split("        run: |\n", 1)[1])
        result, operations = self.run_script(script, TESTED_SHA="b" * 40)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("same tree as the tested commit", result.stdout)
        self.assertIn("git reset --hard origin/main", operations)

    def test_unmerged_version_test_defers_without_waiting_or_mutating(self):
        script = textwrap.dedent(
            BUMP_STEP.split("        run: |\n", 1)[1].split(
                '          app_version="', 1
            )[0]
        )
        result, operations = self.run_script(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("its merged event will resume promotion", result.stdout)
        self.assertNotIn("git ", operations)
        self.assertNotIn("sleep", operations)

    def test_already_merged_version_test_refreshes_develop_without_waiting(self):
        script = textwrap.dedent(
            BUMP_STEP.split("        run: |\n", 1)[1].split(
                '          app_version="', 1
            )[0]
        )
        result, operations = self.run_script(script, MERGED_VERSION_PR="123")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("git reset --hard origin/develop", operations)
        self.assertNotIn("sleep", operations)

    def test_pending_promotion_has_a_same_tree_duplicate_guard(self):
        prepare = WORKFLOW.split("  prepare-version:\n", 1)[1].split(
            "  create-release:\n", 1
        )[0]
        self.assertIn(
            'main_tree="$(git rev-parse refs/remotes/origin/main^{tree})"',
            prepare,
        )
        self.assertIn(
            'if [[ "$main_tree" == "$develop_tree" ]]; then',
            prepare,
        )
        self.assertIn(
            "Main already contains the current develop tree; no promotion is needed.",
            prepare,
        )
        self.assertLess(
            prepare.index(
                'if [[ "$version_merge" != "true" && -n "$REQUESTED_VERSION" ]]'
            ),
            prepare.index('if [[ "$main_tree" == "$develop_tree" ]]; then'),
        )


if __name__ == "__main__":
    unittest.main()
