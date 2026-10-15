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


def validation_script():
    """Return the run: script of the validation step, dedented."""
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    start = lines.index("      - name: Validate PR title and commit subjects")
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


if __name__ == "__main__":
    unittest.main()
