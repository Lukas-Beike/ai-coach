"""Synthetic local-runner lifecycle and evidence checks; Docker is always mocked."""

import contextlib
import ctypes
import io
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from scripts import run_sqlcipher_tests as local
from tests import run_tests


class RunnerEvidenceTests(unittest.TestCase):
    def run_fixture(self, case):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "result.json"
        args = ["run_tests.py", "--result-json", str(path)]
        tests = list(
            run_tests.iter_tests(unittest.defaultTestLoader.loadTestsFromTestCase(case))
        )
        with (
            mock.patch.object(sys, "argv", args),
            mock.patch.object(run_tests, "discover_tests", return_value=tests),
            contextlib.redirect_stdout(io.StringIO()),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            code = run_tests.main()
        return code, json.loads(path.read_text())

    def test_setup_class_error_does_not_claim_selected_tests_ran(self):
        class Broken(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                raise RuntimeError("synthetic setup failure")

            def test_case(self):
                self.fail("must not run")

        code, result = self.run_fixture(Broken)
        self.assertEqual(code, 1)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["tests_run"], 0)
        self.assertEqual(result["executed_ids"], [])
        self.assertEqual(len(result["selected_ids"]), 1)
        self.assertEqual(result["errors"], 1)
        self.assertIn("setUpClass", result["error_ids"][0])

    def test_skip_counts_and_exact_selection(self):
        class Skipped(unittest.TestCase):
            @unittest.skip("synthetic skip")
            def test_case(self):
                pass

        code, result = self.run_fixture(Skipped)
        self.assertEqual(code, 0)
        self.assertEqual(result["skips"], 1)
        self.assertEqual(result["tests_run"], 1)
        self.assertEqual(result["executed_ids"], result["selected_ids"])

    def test_partial_and_list_recording_rejected_without_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "durations.json"
            path.write_text("existing")
            for selection in (["--total", "2"], ["--suite", "container"], ["--list"]):
                with (
                    mock.patch.object(
                        sys,
                        "argv",
                        ["runner", "--record-durations", str(path), *selection],
                    ),
                    contextlib.redirect_stderr(io.StringIO()),
                    self.assertRaises(SystemExit),
                ):
                    run_tests.parse_args()
                self.assertEqual(path.read_text(), "existing")

    def test_empty_list_fails_with_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            with (
                mock.patch.object(
                    sys, "argv", ["runner", "--list", "--result-json", str(path)]
                ),
                mock.patch.object(run_tests, "discover_tests", return_value=[]),
                self.assertRaises(SystemExit),
            ):
                run_tests.main()
            self.assertEqual(json.loads(path.read_text())["status"], "empty")


def plan(shard, total):
    all_ids = [f"synthetic.Class{i}.test_case" for i in range(1, total + 1)]
    return {
        "version": 1,
        "status": "selected",
        "suite": "all",
        "shard": shard,
        "total": total,
        "discovered_ids": all_ids,
        "suite_ids": all_ids,
        "selected_ids": [all_ids[shard - 1]],
        "selected_classes": [f"synthetic.Class{shard}"],
    }


def passed(selection):
    return {
        **selection,
        "status": "passed",
        "tests_run": 1,
        "skips": 0,
        "failures": 0,
        "errors": 0,
        "executed_ids": selection["selected_ids"],
    }


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.args = local.parse_args(
            ["--results-dir", str(self.root), "--workers", "2"]
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.owner = local.Supervisor(self.args)

    def test_bounded_serial_default_and_invalid_workers(self):
        self.assertEqual(local.parse_args([]).workers, 1)
        for count in ("0", "5", "-1"):
            with (
                contextlib.redirect_stderr(io.StringIO()),
                self.assertRaises(SystemExit),
            ):
                local.parse_args(["--workers", count])

    def test_recording_rejects_shards_before_any_process(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            local.parse_args(
                ["--workers", "2", "--record-durations-directory", str(self.root)]
            )

    def test_initial_manifest_and_disjoint_invocations(self):
        manifest = json.loads((self.owner.output / "summary.json").read_text())
        self.assertEqual(manifest["version"], 1)
        self.assertEqual(manifest["status"], "preparing")
        self.assertEqual(manifest["cache_state"], "unknown")
        with contextlib.redirect_stdout(io.StringIO()):
            another = local.Supervisor(self.args)
        self.assertNotEqual(self.owner.output, another.output)
        self.assertFalse(self.owner.processes)

    def test_mount_allowlist_resource_limits_and_network(self):
        command = self.owner.container(
            "test-1", self.owner.output, ["python", "runner"], "sha256:image"
        )
        for value in (
            "--read-only",
            "none",
            "--memory=512m",
            "--cpus=1",
            "--cap-drop=ALL",
        ):
            self.assertIn(value, command)
        mounts = [
            command[i + 1] for i, item in enumerate(command) if item == "--volume"
        ]
        self.assertEqual(len(mounts), len(local.INPUTS) + len(local.EXTRA_MOUNTS) + 1)
        self.assertTrue(all(mount.endswith(":ro") for mount in mounts[:-1]))
        self.assertFalse(any(".env" in item or ":/data" in item for item in mounts))
        self.assertNotIn("--env-file", command)
        self.assertNotIn(
            "--rm", command
        )  # Retain observed IDs for ownership-checked cleanup.

    def test_complete_static_inputs_and_built_application_mounts(self):
        for relative in (
            "backend",
            "requirements-graphify.in",
            "requirements-graphify.txt",
            "run-server.ps1",
            "AGENTS.md",
            "REVIEW.md",
            ".agents",
            ".codex/hooks.json",
            ".claude/settings.json",
        ):
            self.assertIn(relative, local.INPUTS)
        command = self.owner.container(
            "test-1", self.owner.output, ["python", "/app/tests/run_tests.py"], "image"
        )
        mounts = [
            command[i + 1] for i, item in enumerate(command) if item == "--volume"
        ]
        for relative in local.IMAGE_INPUTS:
            self.assertFalse(any(f":/app/{relative}:" in mount for mount in mounts))
        self.assertTrue(any(":/review/backend:ro" in mount for mount in mounts))
        self.assertTrue(any(":/app/tests:ro" in mount for mount in mounts))
        self.assertFalse(
            any(":/review:ro" in mount or ".git:" in mount for mount in mounts)
        )

    def test_test_image_preparation_keeps_tool_installation_out_of_test_commands(self):
        definition = (local.ROOT / "scripts/Dockerfile.sqlcipher-tests").read_text()
        self.assertIn("FROM ${APP_IMAGE}", definition)
        self.assertIn("apt-get install -y --no-install-recommends git", definition)
        self.assertTrue(definition.rstrip().endswith("USER app"))
        command = self.owner.container(
            "test-1", self.owner.output, ["python", "runner"], "image"
        )
        self.assertNotIn("apt-get", " ".join(command))

    def test_prerequisite_assertions_run_inside_networkless_nonroot_test_image(self):
        with mock.patch.object(self.owner, "command") as run:
            self.owner.check_prerequisites("sha256:test")
        command, name = run.call_args.args
        self.assertEqual(name, "prerequisites")
        self.assertIn("--read-only", command)
        self.assertIn("none", command)
        self.assertIn("sha256:test", command)
        script = command[-1]
        compile(script, "prerequisites", "exec")
        self.assertIn("os.geteuid() == 100", script)
        self.assertIn("['git','--version']", script)
        self.assertIn("/app/backend/__init__.py", script)
        self.assertIn("missing read-only review input", script)

    def test_class_partition_validation_rejects_duplicate_missing_and_split(self):
        plans = [plan(1, 2), plan(2, 2)]
        local.validate_selection(plans)
        for changed in ("selected_ids", "selected_classes"):
            broken = [plans[0], {**plans[1], changed: plans[0][changed]}]
            with self.assertRaises(ValueError):
                local.validate_selection(broken)
        with self.assertRaises(ValueError):
            local.validate_selection(plans[:1])

    def test_result_rejects_suite_error_missing_or_changed_selection(self):
        selection = plan(1, 1)
        local.validate_result(selection, passed(selection))
        for delta in (
            {"status": "running"},
            {"errors": 1},
            {"selected_ids": []},
            {"tests_run": 0},
        ):
            with self.assertRaises(ValueError):
                local.validate_result(selection, {**passed(selection), **delta})

    def test_cleanup_reaps_before_owned_removal_and_never_removes_other_owner(self):
        process = mock.Mock()
        process.poll.return_value = None
        self.owner.processes = [process]
        cidfile = self.owner.output / "owned.cid"
        cidfile.write_text("a" * 64)
        self.owner.containers = [cidfile]

        def inspected(*args, **kwargs):
            stop.assert_called_once_with(process)
            process.wait.assert_called_once()
            return b"unrelated-run"

        with (
            mock.patch.object(
                local, "terminate_tree", side_effect=lambda child: child.wait()
            ) as stop,
            mock.patch.object(local.subprocess, "check_output", side_effect=inspected),
            mock.patch.object(local.subprocess, "run") as remove,
        ):
            self.assertFalse(self.owner.cleanup())
            remove.assert_not_called()

    def test_coverage_requires_exactly_one_nonempty_file_for_every_shard(self):
        for index in (1, 2):
            (self.owner.output / f"shard-{index}").mkdir()
        (self.owner.output / "shard-1/.coverage.synthetic").write_bytes(b"synthetic")
        with self.assertRaisesRegex(ValueError, "coverage"):
            self.owner.combine_coverage("image")
        (self.owner.output / "shard-2/.coverage.one").write_bytes(b"synthetic")
        (self.owner.output / "shard-2/.coverage.two").write_bytes(b"synthetic")
        with self.assertRaisesRegex(ValueError, "coverage"):
            self.owner.combine_coverage("image")

    def test_coverage_wheel_must_match_locked_hash(self):
        wheel = self.root / "coverage-1.0-py3-none-any.whl"
        wheel.write_bytes(b"synthetic wheel")
        (self.root / "requirements-dev.txt").write_text(
            "coverage==1.0 \\\n    --hash=sha256:" + "0" * 64 + "\n"
        )
        with self.assertRaisesRegex(ValueError, "hash"):
            local.coverage_wheel(wheel, self.root)
        digest = local.hashlib.sha256(wheel.read_bytes()).hexdigest()
        (self.root / "requirements-dev.txt").write_text(
            "coverage==1.0 \\\n    --hash=sha256:" + digest + "\n"
        )
        self.assertEqual(local.coverage_wheel(wheel, self.root), digest)

    def test_coverage_merge_names_only_the_expected_shard_files(self):
        self.args.coverage_wheel = self.root / "coverage-1.0-synthetic.whl"
        for index in (1, 2):
            directory = self.owner.output / f"shard-{index}"
            directory.mkdir()
            (directory / ".coverage.synthetic").write_bytes(b"synthetic")
        (self.owner.output / ".coverage.unrelated").write_bytes(b"unrelated")

        def combined(command, name):
            self.assertEqual(name, "coverage-combine")
            script = command[-1]
            compile(script, "synthetic-coverage-preparation", "exec")
            self.assertIn("--no-index", script)
            self.assertIn("--no-deps", script)
            self.assertIn("'/results/shard-1/.coverage.synthetic'", script)
            self.assertIn("'/results/shard-2/.coverage.synthetic'", script)
            self.assertNotIn(".coverage.unrelated", script)
            self.assertNotIn("dynamic_context", script)
            (self.owner.output / "coverage/.coverage").write_bytes(b"combined")

        with mock.patch.object(self.owner, "command", side_effect=combined):
            self.owner.combine_coverage("image")

    def test_unreaped_child_defers_all_container_removal(self):
        child = mock.Mock()
        child.poll.return_value = None
        self.owner.processes = [child]
        with (
            mock.patch.object(
                local,
                "terminate_tree",
                side_effect=OSError("synthetic termination failure"),
            ),
            mock.patch.object(local.subprocess, "check_output") as inspect,
        ):
            self.assertFalse(self.owner.cleanup())
            inspect.assert_not_called()

    def test_cancellation_stops_a_real_owned_descendant(self):
        self.check_real_owned_descendant(parent_exits=False)

    def test_cleanup_stops_descendants_after_the_parent_exits(self):
        self.check_real_owned_descendant(parent_exits=True)

    def check_real_owned_descendant(self, parent_exits):
        ready = self.root / "descendant.json"
        descendant = (
            "import json,os,socket,sys;from pathlib import Path;"
            "s=socket.socket();s.bind(('127.0.0.1',0));s.listen();"
            "p=Path(sys.argv[1]);q=p.with_suffix('.tmp');"
            "q.write_text(json.dumps({'pid':os.getpid(),'port':s.getsockname()[1]}));q.replace(p);"
            "\nwhile True:\n c,_=s.accept();c.send(b'x');c.close()"
        )
        parent = (
            "import subprocess,sys,time;"
            f"subprocess.Popen([sys.executable,'-c',{descendant!r},{str(ready)!r}]);"
            + ("time.sleep(0.4)" if parent_exits else "time.sleep(120)")
        )
        child = self.owner.spawn([sys.executable, "-c", parent], "tree")
        observed = None
        descendant_handle = None
        kernel = None
        cleaned = False
        try:
            deadline = time.monotonic() + 10
            while not ready.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), "owned descendant reached readiness")
            observed = json.loads(ready.read_text())
            if os.name == "nt":
                kernel = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel.OpenProcess.argtypes = [
                    ctypes.c_uint32,
                    ctypes.c_int,
                    ctypes.c_uint32,
                ]
                kernel.OpenProcess.restype = ctypes.c_void_p
                kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
                kernel.WaitForSingleObject.restype = ctypes.c_uint32
                kernel.CloseHandle.argtypes = [ctypes.c_void_p]
                descendant_handle = kernel.OpenProcess(0x100000, False, observed["pid"])
                self.assertTrue(descendant_handle)
            if parent_exits:
                self.assertEqual(child.wait(timeout=10), 0)
            with socket.create_connection(
                ("127.0.0.1", observed["port"]), timeout=1
            ) as connection:
                self.assertEqual(connection.recv(1), b"x")
            cleaned = self.owner.cleanup()
            self.assertTrue(cleaned)
            self.assertIsNotNone(child.poll())
            if kernel is not None:
                self.assertEqual(kernel.WaitForSingleObject(descendant_handle, 5000), 0)
            else:
                try:
                    with socket.create_connection(
                        ("127.0.0.1", observed["port"]), timeout=1
                    ) as connection:
                        self.assertNotEqual(connection.recv(1), b"x")
                except OSError:
                    pass
        finally:
            if kernel is not None and descendant_handle:
                kernel.CloseHandle(descendant_handle)
            if not cleaned:
                self.owner.cleanup()
            if child.poll() is None:
                local.terminate_tree(child)
            # Failure cleanup is limited to this exact observed synthetic child.
            if observed and not cleaned:
                if os.name == "nt":
                    subprocess.run(
                        ["taskkill", "/PID", str(observed["pid"]), "/T", "/F"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=15,
                        check=False,
                        **local.hidden(),
                    )
                else:
                    try:
                        os.kill(observed["pid"], signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_windows_children_are_hidden(self):
        with (
            mock.patch.object(local.os, "name", "nt"),
            mock.patch.object(
                local.subprocess, "CREATE_NO_WINDOW", 0x08000000, create=True
            ),
        ):
            self.assertEqual(local.hidden(), {"creationflags": 0x08000000})

    def run_mocked(self, failure=None):
        spawned = []

        def spawn(command, name):
            # Every process must see an initial durable manifest first.
            self.assertTrue((self.owner.output / "summary.json").is_file())
            spawned.append((command, name))
            process = mock.Mock()
            process.poll.return_value = 0
            process.wait.return_value = 0
            if name == "docker-version":
                (self.owner.output / "docker-version.log").write_text(
                    "synthetic-client/server"
                )
            if name == "build":
                (self.owner.output / "image.id").write_text("sha256:" + "b" * 64)
            if name == "inspect-test-source":
                (self.owner.output / "inspect-test-source.log").write_text(
                    "sha256:" + "b" * 64
                )
            if name == "prepare-test-image":
                (self.owner.output / "test-image.id").write_text("sha256:" + "c" * 64)
            if name.startswith("list-"):
                index = int(name.split("-")[1])
                (self.owner.output / f"shard-{index}/selection.json").write_text(
                    json.dumps(plan(index, 2))
                )
            if name.startswith("test-"):
                index = int(name.split("-")[1])
                if failure != "missing" or index != 2:
                    result = passed(plan(index, 2))
                    if failure == "suite_error" and index == 2:
                        result.update(
                            status="failed", errors=1, tests_run=0, executed_ids=[]
                        )
                    (self.owner.output / f"shard-{index}/result.json").write_text(
                        json.dumps(result)
                    )
                if failure == "nonzero" and index == 2:
                    process.poll.return_value = 1
            return process

        with (
            mock.patch.object(self.owner, "spawn", side_effect=spawn),
            mock.patch.object(
                local,
                "source_identity",
                return_value={"revision": "synthetic", "dirty": True},
            ),
            mock.patch.object(self.owner, "cleanup", return_value=True),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            code = self.owner.execute()
        return (
            code,
            spawned,
            json.loads((self.owner.output / "summary.json").read_text()),
        )

    def test_build_once_current_image_disjoint_shards_and_incremental_results(self):
        code, spawned, summary = self.run_mocked()
        self.assertEqual(code, 0)
        self.assertEqual(summary["status"], "passed")
        self.assertEqual(sum(name == "build" for _, name in spawned), 1)
        tests = [command for command, name in spawned if name.startswith("test-")]
        self.assertEqual(len(tests), 2)
        self.assertNotEqual(
            tests[0][tests[0].index("--name") + 1],
            tests[1][tests[1].index("--name") + 1],
        )
        self.assertTrue(all("sha256:" + "c" * 64 in command for command in tests))
        self.assertEqual(summary["image"], "sha256:" + "b" * 64)
        self.assertEqual(summary["test_image"], "sha256:" + "c" * 64)
        names = [name for _, name in spawned]
        self.assertEqual(names.count("prepare-test-image"), 1)
        self.assertLess(names.index("build"), names.index("prepare-test-image"))
        self.assertLess(names.index("prepare-test-image"), names.index("prerequisites"))
        self.assertLess(names.index("prerequisites"), names.index("list-1"))
        preparation = next(
            command for command, name in spawned if name == "prepare-test-image"
        )
        tag = f"ai-coach-sqlcipher-source:{self.owner.run_id}"
        self.assertIn(f"APP_IMAGE={tag}", preparation)
        self.assertIn(
            (["docker", "tag", "sha256:" + "b" * 64, tag], "tag-test-source"), spawned
        )
        self.assertIn(
            (["docker", "image", "rm", tag], "remove-test-source-tag"), spawned
        )
        self.assertTrue(all("/app/tests/run_tests.py" in command for command in tests))
        self.assertTrue(all("coverage" not in command for command in tests))
        self.assertEqual(
            [shard["status"] for shard in summary["shards"]], ["passed", "passed"]
        )

    def test_nonzero_missing_and_suite_error_cannot_pass(self):
        for failure in ("nonzero", "missing", "suite_error"):
            with self.subTest(failure=failure):
                # Each attempt needs its own resource namespace.
                with contextlib.redirect_stdout(io.StringIO()):
                    self.owner = local.Supervisor(self.args)
                code, _, summary = self.run_mocked(failure)
                self.assertEqual(code, 1)
                self.assertEqual(summary["status"], "failed")
                self.assertEqual(summary["shards"][1]["status"], "failed")

    def test_interruption_preserves_nonpassing_evidence(self):
        with (
            mock.patch.object(local, "source_identity", side_effect=KeyboardInterrupt),
            mock.patch.object(self.owner, "cleanup", return_value=True),
        ):
            self.assertEqual(self.owner.execute(), 1)
        self.assertEqual(
            json.loads((self.owner.output / "summary.json").read_text())["status"],
            "interrupted",
        )


if __name__ == "__main__":
    unittest.main()
