"""Shared Graphify setup uses only locked packages and isolated synthetic state."""

import contextlib
import io
import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import graphify_local as graph
from scripts import prepare_worktree as prepare


class GraphifySetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "backend").mkdir()
        (self.root / "backend/fixture.py").write_text("def fixture(): pass\n")
        self.lock = self.root / "requirements-graphify.txt"
        self.lock.write_text(
            "graphifyy==0.9.93 \\\n    --hash=sha256:synthetic\n", encoding="utf-8"
        )
        for name, value in (
            ("LOCK_FILE", self.lock),
            ("VERSION", "0.9.93"),
            ("shared_base", lambda: self.root / "shared"),
        ):
            patcher = patch.object(graph, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_run(self, command, **kwargs):
        if command[0] == "git":
            output = b"backend/fixture.py\0" if "ls-files" in command else b"fixture\n"
            return subprocess.CompletedProcess(command, 0, stdout=output)
        if command[1:3] == ["-m", "venv"]:
            graph.executable(self.root).parent.mkdir(parents=True, exist_ok=True)
            graph.executable(self.root).touch()
            graph.python_executable(self.root).touch()
        if command[1:2] == ["update"]:
            out = Path(kwargs["env"]["GRAPHIFY_OUT"])
            out.mkdir(parents=True, exist_ok=True)
            (out / "graph.json").write_text(
                json.dumps({"nodes": [{"id": "n"}], "edges": []})
            )
        return subprocess.CompletedProcess(command, 0, stdout="0.9.93\n")

    def test_version_requires_one_exact_lock_pin(self):
        for content, expected in (
            ("graphifyy==1.2.3 \\\n", "1.2.3"),
            ("graphifyy[mcp]==1.2.3\n", "1.2.3"),
            ("graphifyy>=1.2.3\n", ""),
            ("graphifyy==1.2.3\ngraphifyy==1.2.4\n", ""),
            ("", ""),
        ):
            with self.subTest(content=content):
                self.lock.write_text(content)
                self.assertEqual(graph.lock_version(self.lock), expected)
        self.lock.unlink()
        self.assertEqual(graph.lock_version(self.lock), "")
        self.assertFalse(graph.verify_version(self.root))
        with self.assertRaises(graph.Unavailable):
            graph._setup(self.root)

    def test_hash_install_ready_marker_and_reuse_across_worktrees(self):
        with patch.object(graph.subprocess, "run", side_effect=self.fake_run) as run:
            self.assertEqual(graph._setup(self.root), 0)
            expected = [
                str(graph.python_executable(self.root)),
                "-m",
                "pip",
                "install",
                "--require-hashes",
                "--only-binary=:all:",
                "--disable-pip-version-check",
                "--no-input",
                "-r",
                str(self.lock),
            ]
            self.assertEqual(run.call_args_list[1].args[0], expected)
            self.assertEqual(
                graph.read_json(graph.shared_environment() / "ready.json"),
                graph.lock_identity(),
            )
            run.reset_mock()
            self.assertEqual(graph._setup(self.root / "other worktree"), 0)
            self.assertEqual(run.call_count, 1)
            self.assertIn("-c", run.call_args.args[0])

    def test_incomplete_environment_is_recreated_and_marker_mismatch_unavailable(self):
        environment = graph.shared_environment()
        environment.mkdir(parents=True)
        leftover = environment / "incomplete"
        leftover.touch()
        with patch.object(graph.subprocess, "run", side_effect=self.fake_run):
            graph._setup(self.root)
            self.assertFalse(leftover.exists())
            marker = environment / "ready.json"
            marker.write_text(
                json.dumps({"version": graph.VERSION, "lock_sha256": "wrong"})
            )
            self.assertFalse(graph.verify_version(self.root))
            graph._setup(self.root)
            self.assertTrue(graph.verify_version(self.root))
            self.lock.write_text(self.lock.read_text() + "# changed lock\n")
            self.assertNotEqual(environment, graph.shared_environment())
            self.assertFalse(graph.verify_version(self.root))

    def test_failed_hash_install_never_writes_ready_marker(self):
        def failed(command, **kwargs):
            if "pip" in command:
                raise subprocess.CalledProcessError(1, command)
            return self.fake_run(command, **kwargs)

        with (
            patch.object(graph.subprocess, "run", side_effect=failed),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            graph._setup(self.root)
        self.assertFalse((graph.shared_environment() / "ready.json").exists())
        self.assertFalse(graph.verify_version(self.root))

    def test_concurrent_setups_install_once(self):
        entered = threading.Event()
        release = threading.Event()
        errors = []

        def slow_run(command, **kwargs):
            if "pip" in command:
                entered.set()
                if not release.wait(5):
                    raise RuntimeError("test release timed out")
            return self.fake_run(command, **kwargs)

        def setup():
            try:
                graph._setup(self.root)
            except (OSError, RuntimeError, subprocess.SubprocessError) as exc:
                errors.append(exc)

        with patch.object(graph.subprocess, "run", side_effect=slow_run) as run:
            first = threading.Thread(target=setup)
            second = threading.Thread(target=setup)
            first.start()
            try:
                self.assertTrue(entered.wait(5))
                second.start()
                time.sleep(0.1)
            finally:
                release.set()
                first.join(5)
                if second.ident is not None:
                    second.join(5)
            self.assertFalse(first.is_alive())
            self.assertFalse(second.is_alive())
            self.assertEqual(errors, [])
            self.assertEqual(
                sum("pip" in call.args[0] for call in run.call_args_list), 1
            )

    def test_prune_only_removes_noncurrent_unlocked_environment_directories(self):
        current = graph.shared_environment()
        current.mkdir(parents=True)
        old = current.parent / ("0.8.1-" + "a" * 16)
        locked = current.parent / ("0.8.2-" + "b" * 16)
        unrelated = current.parent / "unrelated"
        for directory in (old, locked, unrelated):
            directory.mkdir()
        with graph.process_lock(locked.with_name(locked.name + ".lock")):
            self.assertEqual(graph._prune(), 0)
        self.assertFalse(old.exists())
        self.assertTrue(current.is_dir())
        self.assertTrue(locked.is_dir())
        self.assertTrue(unrelated.is_dir())

    def test_navigation_and_session_start_never_install_even_when_missing(self):
        commands = (
            ["update"],
            ["update", "--session-start"],
            ["status"],
            ["query", "activity_detail"],
            ["path", "a", "b"],
            ["explain", "a"],
            [
                "export",
                "html",
                "--output",
                str(self.root / ".graphify-local/exports/g.html"),
            ],
            ["mcp"],
        )
        for available in (False, True):
            if available:
                with patch.object(graph.subprocess, "run", side_effect=self.fake_run):
                    graph._setup(self.root)
            for command in commands:
                with (
                    self.subTest(available=available, command=command),
                    patch.object(graph, "repo_root", return_value=self.root),
                    patch.object(graph.shutil, "which", return_value="sonar"),
                    patch.object(
                        graph.subprocess, "run", side_effect=self.fake_run
                    ) as run,
                    contextlib.redirect_stdout(io.StringIO()),
                    contextlib.redirect_stderr(io.StringIO()),
                ):
                    self.assertEqual(graph.main(command), 0 if available else 2)
                    for call in run.call_args_list:
                        args = call.args[0]
                        self.assertFalse(
                            any(
                                Path(str(arg)).stem.lower() in {"pip", "pip3", "npm"}
                                for arg in args
                            ),
                            args,
                        )
                        self.assertNotIn("venv", args)


class WorktreePreparationTests(unittest.TestCase):
    def test_all_steps_and_failure_propagation(self):
        for results in ([0, 0, 0], [1, 0, 0], [0, 1, 2]):
            with (
                self.subTest(results=results),
                patch.object(prepare.shutil, "which", return_value="npm.cmd"),
                patch.object(
                    prepare.subprocess,
                    "run",
                    side_effect=[
                        subprocess.CompletedProcess([], code) for code in results
                    ],
                ) as run,
            ):
                self.assertEqual(prepare.main(), int(any(results)))
                calls = [call.args[0] for call in run.call_args_list]
                self.assertEqual(calls[0], ["npm.cmd", "ci", "--ignore-scripts"])
                self.assertEqual(
                    [command[-1] for command in calls[1:]], ["setup", "update"]
                )
                self.assertTrue(
                    all(
                        call.kwargs["cwd"]
                        == Path(prepare.__file__).resolve().parents[1]
                        for call in run.call_args_list
                    )
                )

    def test_missing_npm_and_launch_errors_still_attempt_remaining_steps(self):
        with (
            patch.object(prepare.shutil, "which", return_value=None),
            patch.object(
                prepare.subprocess,
                "run",
                side_effect=[
                    OSError("synthetic launch failure"),
                    subprocess.CompletedProcess([], 0),
                ],
            ) as run,
        ):
            self.assertEqual(prepare.main(), 1)
            self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
