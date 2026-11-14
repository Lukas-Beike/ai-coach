"""Execute the Conventional Commits validation step against a stubbed gh CLI."""

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[1] / ".github/workflows/validate-conventions.yml"
)

# A shell function prepended to the step, not an executable on PATH: the CI
# container runs tests with a noexec /tmp.
FAKE_GH = textwrap.dedent(
    """\
    gh() {
      if [[ "${FAKE_GH_MODE:-ok}" == "fail" ]]; then
        echo "synthetic gh api failure" >&2
        return 1
      fi
      printf '%s\\n' "${FAKE_GH_SUBJECTS:-}"
    }
    """
)


def validation_script(step="Validate PR title and commit subjects"):
    """Return the run: script of the named step, dedented."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = lines.index(f"      - name: {step}")
    run_index = next(
        index for index in range(start, len(lines)) if lines[index] == "        run: |"
    )
    body = []
    for line in lines[run_index + 1 :]:
        if line.strip() and not line.startswith("          "):
            break
        body.append(line)
    return textwrap.dedent("\n".join(body)) + "\n"


def find_bash():
    """Return a bash that actually runs (Windows may resolve a WSL stub first)."""
    candidate = shutil.which("bash")
    if candidate is None:
        return None
    try:
        probe = subprocess.run(
            [candidate, "-c", "exit 0"], capture_output=True, check=False, timeout=30
        )
    except OSError, subprocess.SubprocessError:
        return None
    return candidate if probe.returncode == 0 else None


BASH = find_bash()


@unittest.skipUnless(BASH, "a working bash is required to run the workflow step")
class ValidateConventionsWorkflowTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.script = root / "validate.sh"
        self.script.write_text(FAKE_GH + validation_script(), encoding="utf-8")
        self.env = {
            **os.environ,
            "GH_TOKEN": "synthetic-token",
            "PR_NUMBER": "7",
            "REPOSITORY": "example/ai-coach",
            "PR_TITLE": "feat(coach): add synthetic change",
        }

    def run_step(self, mode="ok", subjects=""):
        env = {**self.env, "FAKE_GH_MODE": mode, "FAKE_GH_SUBJECTS": subjects}
        return subprocess.run(
            [BASH, "--noprofile", "--norc", str(self.script)],
            capture_output=True,
            check=False,
            text=True,
            env=env,
            timeout=60,
        )

    def test_failing_gh_api_fails_the_step(self):
        result = self.run_step(mode="fail")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("synthetic gh api failure", result.stderr)

    def test_empty_commit_listing_fails_the_step(self):
        result = self.run_step(subjects="")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("No commit subjects returned", result.stdout)

    def test_valid_commit_subjects_pass(self):
        result = self.run_step(
            subjects="fix(sync): keep finished job items\nfeat!: drop legacy path"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Invalid commit subject", result.stdout)

    def test_invalid_commit_subject_fails_the_step(self):
        result = self.run_step(subjects="fix(sync): valid one\nUpdate branch")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Invalid commit subject: Update branch", result.stdout)


# GitHub's parsed closing references for the issue-link step, one number per line.
FAKE_CLOSING_GH = (
    "gh() {\n"
    '  [[ "$*" == *owner=example\\ * && "$*" == *closingIssuesReferences* ]] \\\n'
    '    || { echo "bad gh call" >&2; return 1; }\n'
    '  [[ "${FAKE_GH_MODE:-ok}" == fail ]] && { echo "synthetic gh api failure" >&2; return 1; }\n'
    '  if [[ -n "${FAKE_LATE:-}" && ! -e "$FAKE_LATE" ]]; then : > "$FAKE_LATE"; return 0; fi\n'
    '  printf "%s" "${FAKE_CLOSING:-}"\n'
    "}\n"
)


@unittest.skipUnless(BASH, "a working bash is required to run the workflow step")
class IssueLinkStepTests(unittest.TestCase):
    def run_step(self, body, closing="", base="develop", mode="ok", late=""):
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / "link.sh"
            script.write_text(
                FAKE_CLOSING_GH
                + validation_script("Require an issue link in the PR body"),
                encoding="utf-8",
            )
            return subprocess.run(
                [BASH, "--noprofile", "--norc", str(script)],
                capture_output=True,
                check=False,
                text=True,
                env={
                    **os.environ,
                    "PR_BODY": body,
                    "FAKE_CLOSING": closing,
                    "FAKE_GH_MODE": mode,
                    "FAKE_LATE": late,
                    "REPOSITORY": "example/ai-coach",
                    "PR_NUMBER": "7",
                    "BASE_REF": base,
                    "DEFAULT_BRANCH": "develop",
                    "CLOSING_RETRY_SECONDS": "0",
                },
                timeout=60,
            )

    def test_closes_and_part_of_pass(self):
        for body, closing in (
            ("Closes #1906", "1906\n"),
            ("Summary\n\nPart of #12 (slice 1)", ""),
            ("fixes #3", "3\n"),
        ):
            with self.subTest(body=body):
                result = self.run_step(body, closing)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_issue_github_would_close_without_closes_fails(self):
        # #2578 said "This PR does not close #2148", and GitHub closed #2148 (#2648).
        for body in (
            "Part of #2148\n\nThis PR does not close #2148.",
            "Closes #10\n\nThis does not fix #11 (follow-up).",
        ):
            with self.subTest(body=body):
                closing = "2148\n" if "2148" in body else "10\n11\n"
                result = self.run_step(body, closing)
                self.assertNotEqual(result.returncode, 0)
                issue = "2148" if "2148" in body else "11"
                self.assertIn(f"GitHub will close #{issue}", result.stdout)
        self.assertIn(
            "close #2148",
            self.run_step(
                "Part of #2148\n\nThis PR does not close #2148.", "2148\n"
            ).stdout,
        )

    def test_a_late_parse_is_waited_for(self):
        # The first read misses #2148 although the body names it (#2648 review).
        with tempfile.TemporaryDirectory() as temp:
            result = self.run_step(
                "Part of #2148\n\nThis PR does not close #2148.",
                "2148\n",
                late=str(Path(temp) / "first-call"),
            )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GitHub will close #2148", result.stdout)

    def test_other_base_branches_and_gh_failures(self):
        # Closing references exist only for PRs into the default branch.
        body = "Part of #5\n\nThis does not close #5."
        self.assertEqual(self.run_step(body, "5\n", base="feat/x").returncode, 0)
        result = self.run_step("Closes #5", "5\n", mode="fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("synthetic gh api failure", result.stderr)

    def test_body_without_issue_link_fails(self):
        for body in ("", "Refs #12", "See issue 12", "Closes#12", "PreCloses #12"):
            with self.subTest(body=body):
                result = self.run_step(body)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Closes #N", result.stdout)

    def test_bot_pull_requests_are_exempt(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        step = workflow.split("      - name: Require an issue link in the PR body", 1)[
            1
        ]
        self.assertIn("if: github.event.pull_request.user.type != 'Bot'", step)


# server.py at the base and head commits, as the contents API returns it raw.
FAKE_VERSION_GH = (
    "gh() {\n"
    '  [[ "$*" == *contents/server.py?ref=* ]] || { echo "bad gh call" >&2; return 1; }\n'
    '  [[ "${FAKE_GH_MODE:-ok}" == fail ]] && { echo "synthetic gh api failure" >&2; return 1; }\n'
    '  if [[ "$*" == *ref=base-sha* ]]; then printf "%s\\n" "${FAKE_BASE:-}";\n'
    '  else printf "%s\\n" "${FAKE_HEAD:-}"; fi\n'
    "}\n"
)


@unittest.skipUnless(BASH, "a working bash is required to run the workflow step")
class AppVersionStepTests(unittest.TestCase):
    def run_step(self, base, head, mode="ok"):
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / "version.sh"
            script.write_text(
                FAKE_VERSION_GH
                + validation_script("Keep APP_VERSION at or above the base branch"),
                encoding="utf-8",
            )
            return subprocess.run(
                [BASH, "--noprofile", "--norc", str(script)],
                capture_output=True,
                check=False,
                text=True,
                env={
                    **os.environ,
                    "GH_TOKEN": "synthetic-token",
                    "REPOSITORY": "example/ai-coach",
                    "BASE_SHA": "base-sha",
                    "HEAD_SHA": "head-sha",
                    "FAKE_BASE": base,
                    "FAKE_HEAD": head,
                    "FAKE_GH_MODE": mode,
                },
                timeout=60,
            )

    @staticmethod
    def server(version):
        return f'"""Server."""\n\nAPP_NAME = "Pacecraft"\nAPP_VERSION = "{version}"\n'

    def test_a_lower_version_fails(self):
        for base, head in (
            ("2.1.10", "2.1.9"),
            ("2.1.0", "1.9.9"),
            ("3.0.0", "2.10.0"),
        ):
            with self.subTest(base=base, head=head):
                result = self.run_step(self.server(base), self.server(head))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"APP_VERSION {head} is lower than {base}", result.stdout)

    def test_an_equal_or_higher_version_passes(self):
        for base, head in (
            ("2.1.10", "2.1.10"),
            ("2.1.9", "2.1.10"),
            ("2.1.10", "3.0.0"),
        ):
            with self.subTest(base=base, head=head):
                result = self.run_step(self.server(base), self.server(head))
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_missing_version_or_gh_failure_fails(self):
        result = self.run_step(self.server("2.1.10"), '"""Server."""\n')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("APP_VERSION not found", result.stdout)
        result = self.run_step("", "", mode="fail")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("synthetic gh api failure", result.stderr)

    def test_the_step_reads_both_files_through_the_api(self):
        # pull_request_target must not check out or run pull-request code.
        step = validation_script("Keep APP_VERSION at or above the base branch")
        self.assertIn("contents/server.py?ref=", step)
        self.assertNotIn("checkout", step)


if __name__ == "__main__":
    unittest.main()
