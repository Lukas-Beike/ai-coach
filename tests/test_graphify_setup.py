"""Shared Graphify setup uses only locked packages and isolated synthetic state."""

import contextlib
import hashlib
import io
import json
import subprocess
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts import graphify_local as graph
from scripts import prepare_worktree as prepare


class GraphifySetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.scanner = self.root / "synthetic-sonar"
        self.scanner.touch()
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
            self.assertEqual(graph._prune(), 0)
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
            self.assertEqual(graph._prune(), 0)
            with (
                patch.object(graph.subprocess, "run", side_effect=self.fake_run),
                self.assertRaises(OSError),
            ):
                graph._setup(self.root)
        self.assertIn("retained (in use)", output.getvalue())
        self.assertTrue((old / "ready.json").is_file())
        self.assertTrue((current / "incomplete").is_file())
        self.assertFalse(leftover.exists())

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
                    patch.object(graph.shutil, "which", return_value=str(self.scanner)),
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


class GraphifyScanCacheTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        source = self.root / "backend/fixture.py"
        source.parent.mkdir()
        source.write_text("pass\n")
        self.paths = [("backend/fixture.py", source)]
        self.scanner = self.root / "synthetic-sonar"
        self.scanner.touch()
        self.cache = graph.runtime(self.root) / "scan-cache.json"
        self.scans = []
        self.scan_result = 0
        self.engine = [["sonar-secrets-1", [1, 2, 3]]]
        for patcher in (
            patch.object(graph, "_scan_engine", side_effect=lambda: self.engine),
            patch.object(graph, "corpus_paths", side_effect=lambda root: self.paths),
            patch.object(graph.shutil, "which", return_value=str(self.scanner)),
            patch.object(graph.subprocess, "run", side_effect=self.fake_run),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def fake_run(self, command, **kwargs):
        if command[1:3] == ["analyze", "secrets"]:
            self.scans.append(command[3:])
            if isinstance(self.scan_result, Exception):
                raise self.scan_result
            return subprocess.CompletedProcess(command, self.scan_result)
        return subprocess.CompletedProcess(command, 0, stdout=b"fixture\n")

    def state(self):
        with graph.process_lock(graph.runtime(self.root) / "update.lock"):
            return graph.state(self.root)

    def test_unchanged_content_is_hashed_but_not_rescanned(self):
        initial = self.state()
        self.scans.clear()
        with patch.object(
            Path, "read_bytes", autospec=True, side_effect=Path.read_bytes
        ) as read:
            self.assertEqual(self.state(), initial)
        self.assertIn(self.paths[0][1], [call.args[0] for call in read.call_args_list])
        self.assertEqual(self.scans, [])

    def test_changed_and_new_content_are_scanned_and_cache_keeps_current_only(self):
        initial = self.state()
        source = self.paths[0][1]
        source.write_text("pass # changed\n")
        new = source.with_name("new.py")
        new.write_text("pass # new\n")
        self.paths.append(("backend/new.py", new))
        self.scans.clear()
        self.state()
        self.assertEqual(self.scans, [[str(source), str(new)]])
        cached = json.loads(self.cache.read_text())["clean_hashes"]
        self.assertNotIn(initial[2]["backend/fixture.py"], cached)
        source.write_text("pass\n")
        self.scans.clear()
        self.assertEqual(
            self.state()[2]["backend/fixture.py"], initial[2]["backend/fixture.py"]
        )
        self.assertEqual(self.scans, [[str(source)]])

    def test_finding_and_scanner_failure_refuse_update_and_record_nothing(self):
        self.state()
        prior = self.cache.read_bytes()
        self.paths[0][1].write_text("pass # edited\n")
        for result in (1, OSError("synthetic"), subprocess.TimeoutExpired("sonar", 1)):
            with (
                self.subTest(result=type(result).__name__),
                patch.object(graph, "verify_version", return_value=True),
                patch.object(graph, "_run_graphify") as build,
            ):
                self.scan_result = result
                self.assertEqual(graph.update(self.root), 2)
                self.assertEqual(self.cache.read_bytes(), prior)
                self.assertFalse((graph.runtime(self.root) / "current.json").exists())
                build.assert_not_called()

    def test_failed_later_batch_records_no_hashes_from_clean_first_batch(self):
        for index in range(36):
            source = self.root / f"backend/batch-{index}.py"
            source.write_text(f"value = {index}\n")
            self.paths.append((f"backend/batch-{index}.py", source))
        real_run = self.fake_run

        def fail_second(command, **kwargs):
            result = real_run(command, **kwargs)
            if len(self.scans) == 2:
                result.returncode = 1
            return result

        with (
            patch.object(graph.subprocess, "run", side_effect=fail_second),
            self.assertRaises(graph.Unavailable),
        ):
            self.state()
        self.assertEqual(len(self.scans), 2)
        self.assertFalse(self.cache.exists())

    def test_scanner_schema_and_rules_changes_force_full_scan(self):
        for change in ("signature", "path", "engine", "schema", "rules"):
            with self.subTest(change=change):
                self.state()
                self.scans.clear()
                if change == "signature":
                    self.scanner.write_text("changed scanner")
                    self.state()
                elif change == "path":
                    other_scanner = self.root / "other-sonar"
                    other_scanner.touch()
                    with patch.object(
                        graph.shutil, "which", return_value=str(other_scanner)
                    ):
                        self.state()
                elif change == "engine":
                    self.engine = [["sonar-secrets-2", [4, 5, 6]]]
                    self.state()
                elif change == "schema":
                    with patch.object(
                        graph, "WRAPPER_SCHEMA", graph.WRAPPER_SCHEMA + 1
                    ):
                        self.state()
                else:
                    with patch.object(
                        graph, "ROOT_FILES", graph.ROOT_FILES | {"new.py"}
                    ):
                        self.state()
                self.assertEqual(self.scans, [[str(self.paths[0][1])]])

    def test_update_retries_once_after_source_change(self):
        changed = graph.Unavailable(graph.SOURCE_CHANGED)
        for effects, code, calls in (
            ([changed, None], 0, 2),
            ([changed, changed], 2, 2),
            ([graph.Unavailable("other")], 2, 1),
        ):
            with (
                self.subTest(code=code, calls=calls),
                patch.object(graph, "verify_version", return_value=True),
                patch.object(graph, "_update_locked", side_effect=effects) as locked,
                contextlib.redirect_stdout(io.StringIO()),
            ):
                self.assertEqual(graph.update(self.root), code)
                self.assertEqual(locked.call_count, calls)

    def test_unresolved_engine_never_reuses_cache(self):
        self.engine = None
        self.state()
        self.scans.clear()
        self.state()
        self.assertEqual(self.scans, [[str(self.paths[0][1])]])

    def test_scanner_change_invalidates_current_graph_without_source_edits(self):
        output = graph.runtime(self.root) / "cache/graph.json"
        output.parent.mkdir(parents=True)
        output.write_text('{"nodes":[{"id":"n"}],"edges":[]}')
        with (
            patch.object(graph, "verify_version", return_value=True),
            patch.object(graph, "_run_graphify", return_value=output) as build,
        ):
            self.assertEqual(graph.update(self.root), 0)
            pointer = (graph.runtime(self.root) / "current.json").read_bytes()
            self.scans.clear()
            self.scanner.write_text("updated scanner")
            self.scan_result = 1
            self.assertEqual(graph.update(self.root), 2)
            self.assertEqual(self.scans, [[str(self.paths[0][1])]])
            self.assertEqual(
                (graph.runtime(self.root) / "current.json").read_bytes(), pointer
            )
            self.assertEqual(build.call_count, 1)

    def test_corrupt_or_unreadable_cache_forces_full_scan(self):
        for content in ("broken JSON", "[]", '{"clean_hashes": [42]}'):
            with self.subTest(content=content):
                self.state()
                self.cache.write_text(content)
                self.scans.clear()
                self.state()
                self.assertEqual(self.scans, [[str(self.paths[0][1])]])
        read_text = Path.read_text

        def unreadable(path, *args, **kwargs):
            if path == self.cache:
                raise OSError("synthetic")
            return read_text(path, *args, **kwargs)

        self.scans.clear()
        with patch.object(Path, "read_text", unreadable):
            self.state()
        self.assertEqual(self.scans, [[str(self.paths[0][1])]])

    def test_file_or_scanner_changed_during_scan_is_not_recorded(self):
        stable = self.root / "backend/stable.py"
        stable.write_text("value = 1\n")
        self.paths.append(("backend/stable.py", stable))
        for changed in (self.paths[0][1], self.scanner):
            with self.subTest(changed=changed.name):
                self.cache.unlink(missing_ok=True)
                hashes = {
                    rel: hashlib.sha256(path.read_bytes()).hexdigest()
                    for rel, path in self.paths
                }

                def edit(paths, deadline, target=changed, **kwargs):
                    target.write_text("pass # concurrent edit\n")

                with (
                    patch.object(graph, "scan", side_effect=edit),
                    self.assertRaises(graph.Unavailable),
                ):
                    self.state()
                if changed == self.scanner:
                    self.assertFalse(self.cache.exists())
                else:
                    # Only the file scanned unchanged is recorded for a retry.
                    self.assertEqual(
                        json.loads(self.cache.read_text())["clean_hashes"],
                        [hashes["backend/stable.py"]],
                    )

    def test_cache_is_published_atomically(self):
        replace = graph.os.replace

        def publish(pending, destination):
            self.assertEqual(destination, self.cache)
            self.assertFalse(self.cache.exists())
            self.assertEqual(len(graph.read_json(pending)["clean_hashes"]), 1)
            replace(pending, destination)

        with patch.object(graph.os, "replace", side_effect=publish) as move:
            self.state()
        move.assert_called_once()


class WorktreePreparationTests(unittest.TestCase):
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
                    [command[2:] for command in calls[1:]],
                    [["setup"], ["update", "--preparation"]],
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
