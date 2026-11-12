"""scripts/check_changed.py with a fake subprocess; nothing real runs."""

import io
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_changed
import gh_cli


class FakeRun:
    """Stands in for subprocess.run; `failing` names a word in the argv to fail."""

    def __init__(self, failing=(), missing=()):
        self.failing = failing
        self.missing = missing
        self.calls = []

    def __call__(self, argv, **_kwargs):
        self.calls.append(argv)
        if any(word in argv[0] for word in self.missing):
            raise FileNotFoundError(argv[0])
        failed = any(word in argv for word in self.failing)
        output = "\n".join(f"line {n}" for n in range(30)) if failed else "fine"
        return subprocess.CompletedProcess(argv, 1 if failed else 0, output, None)


def fake_git(changed, untracked=()):
    def git(*args, **_kwargs):
        if args[0] == "merge-base":
            return "abc123\n"
        if args[0] == "diff":
            return "\n".join(changed)
        return "\n".join(untracked)

    return git


def run_main(module, argv, runner, git=None):
    out, err = io.StringIO(), io.StringIO()
    with (
        mock.patch.object(check_changed.subprocess, "run", runner),
        mock.patch.object(check_changed, "git", git or fake_git(["backend/x.py"])),
        redirect_stdout(out),
        redirect_stderr(err),
    ):
        code = module.main(argv)
    return code, out.getvalue(), err.getvalue()


class CheckChangedTests(unittest.TestCase):
    def test_runs_the_steps_in_order_with_the_base(self):
        runner = FakeRun()
        code, out, _ = run_main(check_changed, ["--base", "origin/main"], runner)
        self.assertEqual(code, 0)
        steps = [line.split()[1] for line in out.splitlines()]
        self.assertEqual(steps, ["tests", "compile", "quality"])
        self.assertTrue(all(line.startswith("ok ") for line in out.splitlines()))
        first = runner.calls[0]
        self.assertEqual(first[0], sys.executable)
        self.assertEqual(first[-3:], ["--changed", "--base", "origin/main"])
        self.assertEqual(runner.calls[1][1:3], ["-m", "compileall"])

    def test_a_failure_does_not_stop_later_steps_and_shows_a_tail(self):
        runner = FakeRun(failing=("compileall",))
        code, out, _ = run_main(check_changed, [], runner)
        self.assertEqual(code, 1)
        self.assertEqual(len(runner.calls), 3)
        self.assertIn("FAILED compile", out)
        self.assertIn("ok quality", out)
        self.assertIn("line 29", out)
        self.assertIn("line 10", out)
        self.assertNotIn("line 9\n", out)

    def test_node_tests_run_with_the_flag_or_when_the_diff_has_js(self):
        cases = [
            (["--js"], ["backend/x.py"], True),
            ([], ["public/app.js"], True),
            ([], ["tests/a.test.cjs"], True),
            ([], ["backend/x.py", "README.md"], False),
        ]
        for argv, changed, expected in cases:
            with self.subTest(argv=argv, changed=changed):
                runner = FakeRun()
                run_main(check_changed, argv, runner, fake_git(changed))
                node = [call for call in runner.calls if call[0] == "node"]
                self.assertEqual(len(node), int(expected))
                if expected:
                    self.assertEqual(node[0][1], "--test")
                    self.assertTrue(
                        all(path.endswith(".cjs") for path in node[0][2:]), node[0]
                    )
                    self.assertGreater(len(node[0]), 3)

    def test_untracked_js_counts_as_a_change(self):
        git = fake_git(["backend/x.py"], untracked=["public/new.mjs"])
        runner = FakeRun()
        run_main(check_changed, [], runner, git)
        self.assertEqual(sum(call[0] == "node" for call in runner.calls), 1)

    def test_missing_tool_is_exit_two_and_other_steps_still_run(self):
        runner = FakeRun(missing=("node",))
        code, out, _ = run_main(check_changed, ["--js"], runner)
        self.assertEqual(code, 2)
        self.assertIn("FAILED node-tests", out)
        self.assertIn("node is not installed", out)
        self.assertIn("ok quality", out)

    def test_unknown_base_is_exit_two(self):
        def git(*_args, **_kwargs):
            raise gh_cli.CliError("git merge-base failed: bad revision")

        runner = FakeRun()
        code, _, err = run_main(check_changed, ["--base", "nope"], runner, git)
        self.assertEqual(code, 2)
        self.assertIn("bad revision", err)
        self.assertEqual(runner.calls, [])


if __name__ == "__main__":
    unittest.main()
