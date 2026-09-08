"""Exercise release events and shell guards without GitHub or repository writes."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import textwrap
from types import SimpleNamespace
import unittest


WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github/workflows/weekly-release.yml"
).read_text(encoding="utf-8")
CREATE_RELEASE = WORKFLOW.split("  create-release:\n", 1)[1]


class ReleaseEventTests(unittest.TestCase):
    def test_only_successful_main_push_tests_can_create_a_release(self):
        condition = CREATE_RELEASE.split("    if: >-\n", 1)[1].split(
            "    runs-on:", 1
        )[0]
        condition = " ".join(condition.split()).replace("&&", "and").replace("||", "or")
        cases = [
            ("workflow_run", "push", "main", "success", True),
            ("workflow_run", "push", "main", "failure", False),
            ("workflow_run", "push", "main", "cancelled", False),
            ("workflow_run", "push", "develop", "success", False),
            ("workflow_run", "workflow_dispatch", "main", "success", False),
            ("workflow_run", "workflow_dispatch", "chore/release-promotion-1.7.3", "success", False),
            ("workflow_run", "pull_request", "chore/release-promotion-1.7.3", "success", False),
            ("pull_request", "push", "main", "success", False),
        ]
        for event_name, event, branch, conclusion, expected in cases:
            with self.subTest(event_name=event_name, event=event, branch=branch, conclusion=conclusion):
                github = SimpleNamespace(
                    event_name=event_name,
                    event=SimpleNamespace(workflow_run=SimpleNamespace(
                        name="Test and publish container image",
                        event=event,
                        head_branch=branch,
                        conclusion=conclusion,
                    )),
                )
                self.assertIs(eval(condition, {"__builtins__": {}}, {"github": github}), expected)


@unittest.skipIf(os.name == "nt" or not shutil.which("bash"), "Requires the Linux CI Bash runtime")
class ReleaseShellGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "server.py").write_text('APP_VERSION = "1.7.3"\n', encoding="utf-8")
        (self.root / "operations").touch()

    def run_script(self, script, **overrides):
        environment = {
            "PATH": os.environ["PATH"],
            "REPOSITORY": "example/release-test",
            "TESTED_SHA": "a" * 40,
            "CURRENT_MAIN_SHA": "a" * 40,
            "EVENT_NAME": "workflow_run",
            "WORKFLOW_RUN_BRANCH": "chore/release-version-1.7.3",
            "MERGED_VERSION_PR": "",
        }
        environment.update(overrides)
        mocks = r"""
            git() {
              printf '%s\n' "git $*" >> operations
              case "$*" in
                'fetch --no-tags origin refs/heads/main:refs/remotes/origin/main'|\
                'fetch --no-tags origin refs/heads/develop:refs/remotes/origin/develop'|\
                'reset --hard origin/main'|'reset --hard origin/develop') return 0 ;;
                'rev-parse refs/remotes/origin/main') printf '%s\n' "$CURRENT_MAIN_SHA" ;;
                *) return 97 ;;
              esac
            }
            gh() {
              printf '%s\n' "gh $*" >> operations
              case "$*" in
                'release view 1.7.3 --repo example/release-test') return 0 ;;
                'workflow run codex-code-review.yml --repo example/release-test --ref develop --field pull_request_number=437') return 0 ;;
                'pr list --repo example/release-test --base develop '* )
                  printf '%s' "$MERGED_VERSION_PR" ;;
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

    def test_promotion_validation_dispatch_uses_trusted_develop(self):
        function = textwrap.dedent(WORKFLOW.split('          ensure_promotion_gate() {', 1)[1].split(
            '          ensure_release_test() {', 1
        )[0])
        result, operations = self.run_script(
            'set -euo pipefail\nensure_promotion_gate() {' + function + '\nensure_promotion_gate 437\n'
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            operations.strip(),
            'gh workflow run codex-code-review.yml --repo example/release-test --ref develop --field pull_request_number=437',
        )

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
        result, operations = self.run_script(script, CURRENT_MAIN_SHA="b" * 40)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("is not the current main commit", result.stdout)
        self.assertNotIn("git reset", operations)
        self.assertNotIn("gh ", operations)

    def test_unmerged_version_test_defers_without_waiting_or_mutating(self):
        script = textwrap.dedent(WORKFLOW.split("        run: |\n", 1)[1].split(
            '          app_version="', 1
        )[0])
        result, operations = self.run_script(script)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("its merged event will resume promotion", result.stdout)
        self.assertNotIn("git ", operations)
        self.assertNotIn("sleep", operations)

    def test_already_merged_version_test_refreshes_develop_without_waiting(self):
        script = textwrap.dedent(WORKFLOW.split("        run: |\n", 1)[1].split(
            '          app_version="', 1
        )[0])
        result, operations = self.run_script(script, MERGED_VERSION_PR="123")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("git reset --hard origin/develop", operations)
        self.assertNotIn("sleep", operations)


if __name__ == "__main__":
    unittest.main()
