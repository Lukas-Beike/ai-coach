"""Shared Graphify setup uses only locked packages and isolated synthetic state."""

import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import graphify_local as graph
from scripts import prepare_worktree as prepare

REPO = Path(__file__).resolve().parents[1]
LEASE_HOLDER = Path(__file__).with_name("graphify_lease_holder.py")


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
            ("setup_python", lambda: [sys.executable]),
        ):
            patcher = patch.object(graph, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_run(self, command, **kwargs):
        if command[0] == "git":
            output = b"backend/fixture.py\0" if "ls-files" in command else b"fixture\n"
            return subprocess.CompletedProcess(command, 0, stdout=output)
        if command[1:3] == ["-m", "venv"]:
            graph.executable().parent.mkdir(parents=True, exist_ok=True)
            graph.executable().touch()
            graph.python_executable().touch()
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
                str(graph.python_executable()),
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

    def test_slow_probe_with_matching_marker_reuses_environment(self):
        with patch.object(graph.subprocess, "run", side_effect=self.fake_run):
            graph._setup(self.root)

        def slow_probe(command, **kwargs):
            if "-c" in command and kwargs.get("timeout") == 10:
                raise subprocess.TimeoutExpired(command, 10)
            return self.fake_run(command, **kwargs)

        with (
            patch.object(graph.subprocess, "run", side_effect=slow_probe) as run,
            patch.object(graph, "_discard") as discard,
        ):
            self.assertEqual(graph._setup(self.root), 0)
        discard.assert_not_called()
        self.assertFalse(any("pip" in call.args[0] for call in run.call_args_list))

    def test_ready_marker_is_published_atomically(self):
        marker = graph.shared_environment() / "ready.json"
        replace = graph.os.replace

        def publish(pending, destination):
            self.assertEqual(destination, marker)
            self.assertFalse(marker.exists())
            self.assertEqual(graph.read_json(pending), graph.lock_identity())
            replace(pending, destination)

        with (
            patch.object(graph.subprocess, "run", side_effect=self.fake_run),
            patch.object(graph.os, "replace", side_effect=publish) as move,
        ):
            self.assertEqual(graph._setup(self.root), 0)
        move.assert_called_once()
        self.assertFalse(marker.with_name("ready.json.tmp").exists())

    def test_failed_marker_publication_leaves_environment_unavailable(self):
        with (
            patch.object(graph.subprocess, "run", side_effect=self.fake_run),
            patch.object(graph.os, "replace", side_effect=OSError("synthetic")),
            self.assertRaises(OSError),
        ):
            graph._setup(self.root)
        self.assertFalse((graph.shared_environment() / "ready.json").exists())
        self.assertFalse(graph.verify_version(self.root))

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
            self.assertIsNone(graph._prune())
        self.assertFalse(old.exists())
        self.assertTrue(current.is_dir())
        self.assertTrue(locked.is_dir())
        self.assertTrue(unrelated.is_dir())

    def test_prune_and_setup_keep_environments_that_cannot_be_moved(self):
        current = graph.shared_environment()
        current.mkdir(parents=True)
        (current / "incomplete").touch()
        old = current.parent / ("0.8.1-" + "a" * 16)
        old.mkdir()
        (old / "ready.json").write_text("{}")
        leftover = current.parent / ".deleting-stale"
        leftover.mkdir()
        with (
            patch.object(Path, "rename", side_effect=OSError("in use")),
            contextlib.redirect_stdout(io.StringIO()) as output,
        ):
            self.assertIsNone(graph._prune())
            with (
                patch.object(graph.subprocess, "run", side_effect=self.fake_run),
                self.assertRaises(OSError),
            ):
                graph._setup(self.root)
        self.assertIn("retained (in use)", output.getvalue())
        self.assertTrue((old / "ready.json").is_file())
        self.assertTrue((current / "incomplete").is_file())
        self.assertFalse(leftover.exists())

    def _lease_holder(self, environment):
        holder = subprocess.Popen(
            [sys.executable, str(LEASE_HOLDER), str(environment)],
            cwd=REPO,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )

        def stop():
            holder.kill()
            holder.wait(timeout=30)
            holder.stdin.close()
            holder.stdout.close()

        self.addCleanup(stop)
        self.assertEqual(holder.stdout.readline().strip(), "leased")
        return holder

    def test_prune_and_setup_keep_environments_leased_by_a_running_process(self):
        current = graph.shared_environment()
        current.mkdir(parents=True)
        (current / "incomplete").touch()
        old = current.parent / ("0.8.1-" + "a" * 16)
        old.mkdir()
        (old / "ready.json").write_text("{}")
        self._lease_holder(current)
        old_holder = self._lease_holder(old)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertIsNone(graph._prune())
            with (
                patch.object(graph.subprocess, "run", side_effect=self.fake_run),
                self.assertRaises(graph.EnvironmentInUse),
            ):
                graph._setup(self.root)
        self.assertIn(f"retained (in use): {old.name}", output.getvalue())
        self.assertTrue((old / "ready.json").is_file())
        self.assertTrue((current / "incomplete").is_file())
        # A killed process leaves its lease file, but no longer holds it.
        old_holder.kill()
        old_holder.wait(timeout=30)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertIsNone(graph._prune())
        self.assertIn(f"removed: {old.name}", output.getvalue())
        self.assertFalse(old.exists())
        self.assertEqual(list(graph._leases(old).iterdir()), [])

    def test_finished_lease_is_released_and_removed(self):
        environment = graph.shared_environment()
        with graph.environment_lease(environment, time.monotonic() + 5):
            self.assertTrue(graph._in_use(environment))
        self.assertFalse(graph._in_use(environment))
        self.assertEqual(list(graph._leases(environment).iterdir()), [])

    def test_lease_open_elsewhere_at_exit_does_not_fail_the_command(self):
        environment = graph.shared_environment()
        with graph.environment_lease(environment, time.monotonic() + 5):
            (lease,) = graph._leases(environment).iterdir()
            observer = lease.open("rb")
        observer.close()
        self.assertFalse(graph._in_use(environment))
        self.assertEqual(list(graph._leases(environment).iterdir()), [])

    def test_lease_fails_fast_while_setup_holds_the_environment(self):
        environment = graph.shared_environment()
        with (
            graph.process_lock(environment.with_name(environment.name + ".lock")),
            patch.object(graph, "LEASE_WAIT", 0.2),
            self.assertRaisesRegex(graph.Unavailable, "busy"),
            graph.environment_lease(environment, time.monotonic() + 180),
        ):
            pass

    def test_lock_line_endings_do_not_change_the_environment(self):
        content = self.lock.read_bytes().replace(b"\r\n", b"\n")
        names = set()
        for data in (content, content.replace(b"\n", b"\r\n")):
            self.lock.write_bytes(data)
            names.add(graph.environment_name(graph.lock_identity()))
        self.assertEqual(len(names), 1)

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


class GraphifySnapshotTests(unittest.TestCase):
    def test_update_retries_once_after_source_change(self):
        temp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, temp)
        changed = graph.Unavailable(graph.SOURCE_CHANGED)
        for effects, code, calls in (
            ([changed, None], 0, 2),
            ([changed, changed], 2, 2),
            ([graph.Unavailable("other")], 2, 1),
        ):
            with (
                self.subTest(code=code, calls=calls),
                patch.object(graph, "shared_base", return_value=Path(temp) / "shared"),
                patch.object(graph, "verify_version", return_value=True),
                patch.object(graph, "_update_locked", side_effect=effects) as locked,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(graph.update(Path(temp)), code)
                self.assertEqual(locked.call_count, calls)


class WorktreePreparationTests(unittest.TestCase):
    def test_setup_uses_python_314_even_when_default_python_is_newer(self):
        for platform, version, found, expected in (
            ("nt", (3, 14), None, [sys.executable]),
            ("nt", (3, 15), "py.exe", ["py.exe", "-3.14"]),
            ("posix", (3, 15), "/usr/bin/python3.14", ["/usr/bin/python3.14"]),
        ):
            with (
                self.subTest(platform=platform, version=version),
                patch.object(graph.sys, "version_info", version),
                patch.object(graph, "os", SimpleNamespace(name=platform)),
                patch.object(graph.shutil, "which", return_value=found),
                patch.object(graph.subprocess, "run"),
            ):
                self.assertEqual(graph.setup_python(), expected)

    def test_missing_supported_python_reports_required_version(self):
        with (
            patch.object(graph.sys, "version_info", (3, 15)),
            patch.object(graph.shutil, "which", return_value=None),
            self.assertRaisesRegex(graph.Unavailable, "requires Python 3.14"),
        ):
            graph.setup_python()

    def test_launcher_without_python_314_reports_required_version(self):
        with (
            patch.object(graph.sys, "version_info", (3, 15)),
            patch.object(graph, "os", SimpleNamespace(name="nt")),
            patch.object(graph.shutil, "which", return_value="py.exe"),
            patch.object(
                graph.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, []),
            ),
            self.assertRaisesRegex(graph.Unavailable, "requires Python 3.14"),
        ):
            graph.setup_python()

    def test_windows_shared_base_without_localappdata_is_unavailable(self):
        with (
            patch.object(graph, "os", SimpleNamespace(name="nt", environ={})),
            self.assertRaisesRegex(graph.Unavailable, "LOCALAPPDATA unavailable"),
        ):
            graph.shared_base()

    def test_plain_hook_and_preparation_update_budgets(self):
        for arguments, seconds in (
            (["update"], 180),
            (["update", "--session-start"], 180),
            (["update", "--preparation"], 600),
        ):
            with (
                self.subTest(arguments=arguments),
                tempfile.TemporaryDirectory() as temp,
                patch.object(graph, "repo_root", return_value=Path(temp)),
                patch.object(graph, "verify_version", return_value=True),
                patch.object(
                    graph, "environment_lease", return_value=contextlib.nullcontext()
                ),
                patch.object(graph.time, "monotonic", return_value=100),
                patch.object(
                    graph, "process_lock", return_value=contextlib.nullcontext()
                ) as lock,
                patch.object(graph, "_update_locked") as update,
            ):
                self.assertEqual(graph.main(arguments), 0)
                self.assertEqual(lock.call_args.args[1], 100 + seconds)
                self.assertEqual(update.call_args.args[2], 100 + seconds)

    def test_all_steps_and_failure_propagation(self):
        for results in ([0, 0, 0, 0], [1, 0, 0, 0], [0, 1, 2, 3]):
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
                    [command[2:] for command in calls[1:3]],
                    [["setup"], ["update", "--preparation"]],
                )
                self.assertEqual(calls[3][1:3], ["-m", "pip"])
                self.assertIn("--require-hashes", calls[3])
                self.assertTrue(
                    all(
                        call.kwargs["cwd"]
                        == Path(prepare.__file__).resolve().parents[1]
                        for call in run.call_args_list
                    )
                )

    def test_quality_tools_install_only_hash_locked_ruff_mypy_and_dependencies(self):
        root = Path(prepare.__file__).resolve().parents[1]
        lock = (root / "requirements-dev.txt").read_text(encoding="utf-8")
        selected = prepare.quality_requirements(lock)
        names = set(re.findall(r"(?m)^([A-Za-z0-9][\w.-]*)==", selected))
        self.assertLessEqual({"ruff", "mypy", "librt", "pathspec"}, names)
        self.assertNotIn("sqlcipher3-binary", names)
        blocks = re.split(r"(?m)^(?=[A-Za-z0-9][\w.-]*==)", selected)[1:]
        self.assertTrue(all("--hash=sha256:" in block for block in blocks))
        with self.assertRaises(OSError):
            prepare.quality_requirements("requests==2.0.0\n")

    def test_missing_npm_and_launch_errors_still_attempt_remaining_steps(self):
        with (
            patch.object(prepare.shutil, "which", return_value=None),
            patch.object(
                prepare.subprocess,
                "run",
                side_effect=[
                    OSError("synthetic launch failure"),
                    subprocess.CompletedProcess([], 0),
                    subprocess.CompletedProcess([], 0),
                ],
            ) as run,
        ):
            self.assertEqual(prepare.main(), 1)
            self.assertEqual(run.call_count, 3)


if __name__ == "__main__":
    unittest.main()
