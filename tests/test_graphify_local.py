import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from scripts import graphify_local as graph


class GraphifyLocalPureTests(TestCase):
    def test_backend_backup_and_runtime_domains_are_included(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            owners = (
                "coach",
                "planning",
                "sync",
                "providers",
                "db",
                "http_api",
                "backup",
                "athlete",
                "activities",
                "calendar",
                "diagnostics",
                "history",
                "nutrition",
                "performance",
                "runtime",
                "weather",
                "canonical",
            )
            for domain in owners:
                path = root / "backend" / domain / "service.py"
                path.parent.mkdir(parents=True)
                path.write_text("pass\n")
            for rel in (
                "backend/coach/data/fixture.py",
                "backend/backup/data/fixture.py",
                "backend/runtime/logs/private.py",
                "data/fixture.py",
                "backups/fixture.py",
            ):
                path = root / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("pass\n")
            included = {
                f"backend/{domain}/service.py"
                for domain in owners
                if graph.safe_path(root, f"backend/{domain}/service.py")
            }
            self.assertEqual(
                included, {f"backend/{domain}/service.py" for domain in owners}
            )
            self.assertTrue(
                all(
                    graph.safe_path(root, rel) is None
                    for rel in (
                        "backend/coach/data/fixture.py",
                        "backend/backup/data/fixture.py",
                        "backend/runtime/logs/private.py",
                        "data/fixture.py",
                        "backups/fixture.py",
                    )
                )
            )

    def test_scanner_failure_in_state_never_records_clean_hashes(self):
        binding = {"scanner": "synthetic", "engine": [["engine", [1]]]}
        for prior in (None, {"binding": binding, "clean_hashes": []}):
            with self.subTest(prior=prior), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                source = root / "source.py"
                source.write_text("pass\n")
                cache = graph.runtime(root) / "scan-cache.json"
                if prior is not None:
                    cache.parent.mkdir(parents=True)
                    cache.write_text(json.dumps(prior))
                before = cache.read_bytes() if prior is not None else None
                with (
                    patch.object(
                        graph, "corpus_paths", return_value=[("backend/x.py", source)]
                    ),
                    patch.object(
                        graph, "scan", side_effect=graph.Unavailable("failed")
                    ),
                    patch.object(graph, "_scan_binding", return_value=binding),
                    self.assertRaises(graph.Unavailable),
                ):
                    graph.state(root)
                if prior is None:
                    self.assertFalse(cache.exists())
                else:
                    self.assertEqual(cache.read_bytes(), before)

    def test_local_environment_excludes_secrets_and_disables_backends(self):
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(
                "os.environ",
                {
                    "OPENAI_API_KEY": "synthetic",
                    "GARMIN_TOKEN": "synthetic",
                    "GRAPHIFY_BACKEND": "remote",
                },
                clear=True,
            ),
        ):
            env = graph.local_env(Path(temp))
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("GARMIN_TOKEN", env)
        self.assertEqual(env["GRAPHIFY_BACKEND"], "none")
        self.assertEqual(env["GRAPHIFY_NO_AUTO_REFRESH"], "1")


@unittest.skipUnless(
    shutil.which("git"), "Git is required for synthetic worktree fixtures"
)
class GraphifyLocalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        scanner = self.root / "synthetic-sonar"
        scanner.touch()
        scanner_path = patch.object(graph.shutil, "which", return_value=str(scanner))
        scanner_path.start()
        self.addCleanup(scanner_path.stop)
        # Environment leases must never touch the real shared directory.
        shared = patch.object(graph, "shared_base", return_value=self.root / "shared")
        shared.start()
        self.addCleanup(shared.stop)
        # CI hosts have no Sonar secrets engine; without one no cache is reused.
        engine = patch.object(
            graph, "_scan_engine", return_value=[["sonar-secrets-1", [1, 2, 3]]]
        )
        engine.start()
        self.addCleanup(engine.stop)
        (self.root / ".gitignore").write_text(".graphify-local/\ngraphify-out/\n")
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        (self.root / "backend").mkdir()
        (self.root / "backend" / "one.py").write_text("def one(): return 1\n")
        subprocess.run(
            ["git", "-C", str(self.root), "add", "backend/one.py"], check=True
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(self.root),
                "-c",
                "user.name=test",
                "-c",
                "user.email=test@example.invalid",
                "commit",
                "-qm",
                "fixture",
            ],
            check=True,
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_allowlist_ignores_credentials(self):
        (self.root / "backend" / ".env").write_text("not inspected")
        (self.root / ".graphify-local").mkdir()
        (self.root / ".graphify-local" / "bad.py").write_text("ignored")
        with patch.object(graph, "scan") as scanner:
            paths = graph.corpus_paths(self.root)
            self.assertEqual([name for name, _ in paths], ["backend/one.py"])
            graph.scan(paths)
            scanner.assert_called_once()

    def test_sonar_secrets_worktree_is_excluded_at_any_depth(self):
        nested = self.root / "tests" / ".sonar-secrets-cli-workdir" / "fixture.py"
        nested.parent.mkdir(parents=True)
        nested.write_text("pass\\n")
        self.assertIsNone(
            graph.safe_path(self.root, "tests/.sonar-secrets-cli-workdir/fixture.py")
        )

    def test_symlink_escape_is_excluded(self):
        with tempfile.TemporaryDirectory() as outside_dir:
            outside = Path(outside_dir) / "outside.py"
            outside.write_text("ignored")
            try:
                (self.root / "backend" / "escape.py").symlink_to(outside)
            except OSError:
                self.skipTest("symlink creation is unavailable on this Windows account")
            paths = graph.corpus_paths(self.root)
            self.assertEqual([name for name, _ in paths], ["backend/one.py"])

    def test_scanner_failure_fails_closed_without_forwarding_output(self):
        with (
            patch.object(graph.shutil, "which", return_value="sonar"),
            patch.object(
                graph.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    [], 2, b"secret finding", b"raw"
                ),
            ),
            self.assertRaises(graph.Unavailable),
        ):
            graph.scan(
                [("backend/one.py", self.root / "backend/one.py")],
                time.monotonic() + 5,
            )

    def test_scanner_missing_fails_closed(self):
        with (
            patch.object(graph.shutil, "which", return_value=None),
            self.assertRaises(graph.Unavailable),
        ):
            graph.scan(
                [("backend/one.py", self.root / "backend/one.py")],
                time.monotonic() + 5,
            )

    def test_scanner_batches_paths(self):
        paths = [
            (f"backend/file-{i}.py", self.root / "backend" / "one.py")
            for i in range(71)
        ]
        with (
            patch.object(graph.shutil, "which", return_value="sonar"),
            patch.object(
                graph.subprocess, "run", return_value=subprocess.CompletedProcess([], 0)
            ) as run,
        ):
            graph.scan(paths, time.monotonic() + 5)
        self.assertEqual(run.call_count, 3)
        self.assertLessEqual(
            max(len(call.args[0]) - 3 for call in run.call_args_list), 35
        )

    def test_generation_pointer_rejects_traversal(self):
        with self.assertRaises(graph.Unavailable):
            graph.generation_dir(self.root, {"generation": "../outside"})

    def test_fingerprint_changes_for_content_branch_and_dirty_state(self):
        with patch.object(graph, "scan"):
            _, original, _ = graph.state(self.root, time.monotonic() + 5)
            (self.root / "backend" / "one.py").write_text("def one(): return 2\n")
            _, changed, _ = graph.state(self.root, time.monotonic() + 5)
            self.assertNotEqual(original, changed)
            (self.root / "backend" / "one.py").write_text("def one(): return 1\n")
            subprocess.run(
                ["git", "-C", str(self.root), "checkout", "-qb", "other"], check=True
            )
            _, branch, _ = graph.state(self.root, time.monotonic() + 5)
            self.assertNotEqual(original, branch)

    def test_deleted_and_renamed_files_change_corpus(self):
        with patch.object(graph, "scan"):
            initial, old, _ = graph.state(self.root, time.monotonic() + 5)
            (self.root / "backend" / "one.py").rename(
                self.root / "backend" / "renamed.py"
            )
            renamed, new, _ = graph.state(self.root, time.monotonic() + 5)
            self.assertNotEqual(old, new)
            self.assertEqual([p for p, _ in initial], ["backend/one.py"])
            self.assertEqual([p for p, _ in renamed], ["backend/renamed.py"])

    def test_unchanged_generation_reused_and_failure_keeps_previous(self):
        rt = graph.runtime(self.root)
        rt.mkdir()
        tool = rt / "venv" / "Scripts" / "graphify.exe"
        tool.parent.mkdir(parents=True)
        tool.touch()
        invocations = []

        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if "update" in command:
                invocations.append(command)
                if len(invocations) == 1:
                    out = rt / "cache"
                    out.mkdir(parents=True)
                    (out / "graph.json").write_text(
                        json.dumps(
                            {
                                "nodes": [{"id": "n"}],
                                "edges": [{"source": "n", "target": "n"}],
                            }
                        )
                    )
                    return subprocess.CompletedProcess(command, 0)
                return subprocess.CompletedProcess(command, 1)
            return real_run(command, **kwargs)

        with (
            patch.object(graph, "scan"),
            patch.object(graph, "executable", return_value=tool),
            patch.object(graph, "verify_version", return_value=True),
            patch.object(graph.subprocess, "run", side_effect=fake_run),
        ):
            self.assertEqual(graph.update(self.root), 0)
            current = json.loads((rt / "current.json").read_text())
            generation = current["generation"]
            self.assertEqual(graph.update(self.root), 0)
            self.assertEqual(len(invocations), 1)
            (self.root / "backend" / "one.py").write_text("def one(): return 2\n")
            self.assertEqual(graph.update(self.root), 2)
            current = json.loads((rt / "current.json").read_text())
            self.assertEqual(current["generation"], generation)
            self.assertFalse(current["stale"])

    def test_edit_during_graph_build_never_publishes_fresh_pointer(self):
        rt = graph.runtime(self.root)
        tool = rt / "venv" / "Scripts" / "graphify.exe"
        tool.parent.mkdir(parents=True)
        tool.touch()
        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if "update" in command:
                (self.root / "backend" / "one.py").write_text("def one(): return 2\\n")
                out = rt / "cache"
                out.mkdir(parents=True, exist_ok=True)
                (out / "graph.json").write_text(
                    json.dumps(
                        {
                            "nodes": [{"id": "n"}],
                            "edges": [{"source": "n", "target": "n"}],
                        }
                    )
                )
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, **kwargs)

        with (
            patch.object(graph, "scan"),
            patch.object(graph, "executable", return_value=tool),
            patch.object(graph, "verify_version", return_value=True),
            patch.object(graph.subprocess, "run", side_effect=fake_run),
        ):
            self.assertEqual(graph.update(self.root), 2)
        self.assertFalse((rt / "current.json").exists())

    def test_old_pointer_schema_is_rebuilt_and_gets_metadata(self):
        rt = graph.runtime(self.root)
        generation = "c" * 32
        graph_file = rt / "generations" / generation / "graphify-out" / "graph.json"
        graph_file.parent.mkdir(parents=True)
        graph_file.write_text(json.dumps({"nodes": [{"id": "n"}], "edges": []}))
        (rt / "current.json").write_text(
            json.dumps(
                {
                    "generation": generation,
                    "fingerprint": "legacy",
                    "schema": 3,
                    "graphify_version": graph.VERSION,
                    "stale": False,
                }
            )
        )
        tool = rt / "venv" / "Scripts" / "graphify.exe"
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.touch()
        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if "update" in command:
                out = rt / "cache"
                out.mkdir(parents=True, exist_ok=True)
                (out / "graph.json").write_text(
                    json.dumps(
                        {
                            "nodes": [{"id": "n"}],
                            "edges": [{"source": "n", "target": "n"}],
                        }
                    )
                )
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, **kwargs)

        with (
            patch.object(graph, "scan"),
            patch.object(graph, "executable", return_value=tool),
            patch.object(graph, "verify_version", return_value=True),
            patch.object(graph.subprocess, "run", side_effect=fake_run),
        ):
            self.assertEqual(graph.update(self.root), 0)
        pointer = json.loads((rt / "current.json").read_text())
        self.assertEqual(pointer["schema"], graph.WRAPPER_SCHEMA)
        self.assertIn("metadata", pointer)

    def test_edit_during_publication_window_is_not_stamped_with_old_graph(self):
        rt = graph.runtime(self.root)
        tool = rt / "venv" / "Scripts" / "graphify.exe"
        tool.parent.mkdir(parents=True)
        tool.touch()
        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if "update" in command:
                out = rt / "cache"
                out.mkdir(parents=True, exist_ok=True)
                (out / "graph.json").write_text(
                    json.dumps(
                        {
                            "nodes": [{"id": "n"}],
                            "edges": [{"source": "n", "target": "n"}],
                        }
                    )
                )
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, **kwargs)

        real_copy = shutil.copy2

        def edit_then_copy(source, destination):
            (self.root / "backend" / "one.py").write_text("def one(): return 2\\n")
            return real_copy(source, destination)

        with (
            patch.object(graph, "scan"),
            patch.object(graph, "executable", return_value=tool),
            patch.object(graph, "verify_version", return_value=True),
            patch.object(graph.subprocess, "run", side_effect=fake_run),
            patch.object(graph.shutil, "copy2", side_effect=edit_then_copy),
        ):
            self.assertEqual(graph.update(self.root), 0)
        pointer = json.loads((rt / "current.json").read_text())
        self.assertNotEqual(
            pointer["metadata"]["files"], graph._metadata(self.root)["files"]
        )
        self.assertFalse(graph._metadata_current(self.root, pointer))

    def test_warm_update_uses_metadata_without_scan_or_source_read(self):
        rt = graph.runtime(self.root)
        generation = "a" * 32
        graph_file = rt / "generations" / generation / "graphify-out" / "graph.json"
        graph_file.parent.mkdir(parents=True)
        graph_file.write_text('{"nodes":[],"edges":[]}')
        pointer = {
            "generation": generation,
            "fingerprint": "old",
            "schema": graph.WRAPPER_SCHEMA,
            "graphify_version": graph.VERSION,
            "stale": False,
            "metadata": graph._metadata(self.root),
            "graph_sha256": hashlib.sha256(graph_file.read_bytes()).hexdigest(),
        }
        (rt / "current.json").write_text(json.dumps(pointer))
        (rt / "scan-cache.json").write_text(
            json.dumps({"binding": graph._scan_binding(), "clean_hashes": []})
        )
        source_read_bytes = Path.read_bytes

        def guarded_read_bytes(path):
            if path == self.root / "backend" / "one.py":
                raise AssertionError("source read")
            return source_read_bytes(path)

        with (
            patch.object(graph, "scan", side_effect=AssertionError("scan")),
            patch.object(Path, "read_bytes", guarded_read_bytes),
            patch.object(graph, "verify_version", return_value=True),
        ):
            self.assertEqual(graph.update(self.root), 0)

    def test_fingerprint_match_refreshes_metadata_and_remains_warm(self):
        rt = graph.runtime(self.root)
        generation = "d" * 32
        graph_file = rt / "generations" / generation / "graphify-out" / "graph.json"
        graph_file.parent.mkdir(parents=True)
        graph_file.write_text('{"nodes":[{"id":"n"}],"edges":[]}')
        old_metadata = graph._metadata(self.root)
        with patch.object(graph, "scan"):
            fingerprint = graph.state(self.root)[1]
        pointer = {
            "generation": generation,
            "fingerprint": fingerprint,
            "schema": graph.WRAPPER_SCHEMA,
            "graphify_version": graph.VERSION,
            "updated": 1,
            "stale": False,
            "metadata": old_metadata,
            "graph_sha256": hashlib.sha256(graph_file.read_bytes()).hexdigest(),
        }
        (rt / "current.json").write_text(json.dumps(pointer))
        source = self.root / "backend" / "one.py"
        before = source.stat()
        os.utime(
            source,
            ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000),
        )
        self.assertNotEqual(old_metadata, graph._metadata(self.root))
        tool = rt / "venv" / "Scripts" / "graphify.exe"
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.touch()
        with (
            patch.object(graph, "scan") as scanner,
            patch.object(graph, "executable", return_value=tool),
            patch.object(graph, "verify_version", return_value=True),
        ):
            self.assertEqual(graph.update(self.root), 0)
            scanner.assert_not_called()
            current = json.loads((rt / "current.json").read_text())
            self.assertEqual(current["generation"], generation)
            self.assertEqual(current["metadata"], graph._metadata(self.root))
            self.assertEqual(
                current["graph_sha256"],
                hashlib.sha256(graph_file.read_bytes()).hexdigest(),
            )
            self.assertFalse(current["stale"])
            self.assertEqual(graph.active_graph(self.root)[1], graph_file)
            self.assertEqual(graph.update(self.root), 0)
            scanner.assert_not_called()

    def test_corrupt_graph_is_not_reused_or_blessed_by_metadata_refresh(self):
        rt = graph.runtime(self.root)
        generation = "f" * 32
        graph_file = rt / "generations" / generation / "graphify-out" / "graph.json"
        graph_file.parent.mkdir(parents=True)
        graph_file.write_text('{"nodes":[{"id":"original"}],"edges":[]}')
        with patch.object(graph, "scan"):
            fingerprint = graph.state(self.root)[1]
        pointer = {
            "generation": generation,
            "fingerprint": fingerprint,
            "schema": graph.WRAPPER_SCHEMA,
            "graphify_version": graph.VERSION,
            "stale": False,
            "metadata": {},
            "graph_sha256": hashlib.sha256(graph_file.read_bytes()).hexdigest(),
        }
        (rt / "current.json").write_text(json.dumps(pointer))
        graph_file.write_text('{"nodes":[{"id":"corrupt"}],"edges":[]}')
        tool = rt / "venv" / "Scripts" / "graphify.exe"
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.touch()
        out = rt / "cache"
        out.mkdir()
        (out / "graph.json").write_text('{"nodes":[{"id":"rebuilt"}],"edges":[]}')
        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if command[0] == str(tool):
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, **kwargs)

        with (
            patch.object(graph, "scan"),
            patch.object(graph, "executable", return_value=tool),
            patch.object(graph, "verify_version", return_value=True),
            patch.object(graph.subprocess, "run", side_effect=fake_run) as run,
        ):
            self.assertEqual(graph.update(self.root), 0)
        self.assertTrue(
            any(call.args[0][0] == str(tool) for call in run.call_args_list)
        )
        current = json.loads((rt / "current.json").read_text())
        self.assertNotEqual(current["generation"], generation)
        self.assertNotEqual(current["graph_sha256"], pointer["graph_sha256"])
        active_graph = graph.active_graph(self.root)[1]
        self.assertEqual(active_graph.read_text(), (out / "graph.json").read_text())

    def test_missing_graph_checksum_is_not_reused(self):
        rt = graph.runtime(self.root)
        generation = "d" * 32
        graph_file = rt / "generations" / generation / "graphify-out" / "graph.json"
        graph_file.parent.mkdir(parents=True)
        graph_file.write_text('{"nodes":[],"edges":[]}')
        with patch.object(graph, "scan"):
            fingerprint = graph.state(self.root)[1]
        pointer = {
            "generation": generation,
            "fingerprint": fingerprint,
            "schema": graph.WRAPPER_SCHEMA,
            "graphify_version": graph.VERSION,
            "stale": False,
        }
        (rt / "current.json").write_text(json.dumps(pointer))
        tool = rt / "venv" / "Scripts" / "graphify.exe"
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.touch()
        out = rt / "cache"
        out.mkdir()
        (out / "graph.json").write_text('{"nodes":[{"id":"rebuilt"}],"edges":[]}')
        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if "update" in command:
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, **kwargs)

        with (
            patch.object(graph, "scan"),
            patch.object(graph, "executable", return_value=tool),
            patch.object(graph, "verify_version", return_value=True),
            patch.object(graph.subprocess, "run", side_effect=fake_run),
        ):
            self.assertEqual(graph.update(self.root), 0)
        current = json.loads((rt / "current.json").read_text())
        self.assertNotEqual(current["generation"], generation)
        self.assertEqual(
            graph.active_graph(self.root)[1].read_text(),
            (out / "graph.json").read_text(),
        )

    def test_graphify_cli_rejects_flags_and_graph_override(self):
        rt = graph.runtime(self.root)
        generation = "e" * 32
        graph_file = rt / "generations" / generation / "graphify-out" / "graph.json"
        graph_file.parent.mkdir(parents=True)
        graph_file.write_text('{"nodes":[{"id":"n"}],"edges":[]}')
        pointer = {
            "generation": generation,
            "fingerprint": "fixture",
            "schema": graph.WRAPPER_SCHEMA,
            "graphify_version": graph.VERSION,
            "stale": False,
            "metadata": graph._metadata(self.root),
            "graph_sha256": hashlib.sha256(graph_file.read_bytes()).hexdigest(),
        }
        (rt / "current.json").write_text(json.dumps(pointer))
        tool = rt / "venv" / "Scripts" / "graphify.exe"
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.touch()
        launched = []
        real_run = subprocess.run

        def fake_run(command, **kwargs):
            if command[0] == str(tool):
                launched.append(command)
                return subprocess.CompletedProcess(command, 0)
            return real_run(command, **kwargs)

        with (
            patch.object(graph, "repo_root", return_value=self.root),
            patch.object(graph, "verify_version", return_value=True),
            patch.object(graph, "executable", return_value=tool),
            patch.object(graph.subprocess, "run", side_effect=fake_run),
        ):
            self.assertEqual(graph.main(["query", "find", "node"]), 0)
            self.assertEqual(graph.main(["query", "find:thing (v2)"]), 0)
            self.assertEqual(graph.main(["path", "from", "to", "--undirected"]), 0)
            self.assertEqual(graph.main(["explain", "symbol", "--all"]), 0)
            for args in (
                ["query", "find", "--dfs"],
                ["query", "find", "--graph", "other.json"],
                ["query", "find", "--graph=other.json"],
                ["query", "--", "--graph", "other.json"],
                ["query", "find\n--graph=other.json"],
                ["path", "from", "to", "--graph", "other.json"],
                ["path", "from", "to", "--output", "file"],
                ["path", "from", "to", "--directed", "--undirected"],
                ["explain", "symbol", "--graph=other.json"],
                ["explain", "symbol", "--all=true"],
            ):
                with self.subTest(args=args):
                    self.assertEqual(graph.main(args), 2)
            self.assertEqual(graph.main(["path", "from", "to", "extra"]), 2)
            self.assertEqual(graph.main(["explain", "symbol", "extra"]), 2)
        self.assertEqual(len(launched), 4)
        self.assertTrue(all(command[-2] == "--graph" for command in launched))
        self.assertEqual(launched[1][1:3], ["query", "find:thing (v2)"])

    def test_metadata_invalidation_causes_content_scan(self):
        with patch.object(graph, "scan") as scanner:
            before = graph._metadata(self.root)
            (self.root / "backend" / "one.py").write_text("def one(): return 22\n")
            after = graph._metadata(self.root)
            self.assertNotEqual(before, after)
            paths = graph.corpus_paths(self.root)
            graph.scan(paths)
            scanner.assert_called_once_with(paths)
            graph.state(self.root, time.monotonic() + 5)
            self.assertEqual(scanner.call_count, 2)

    def test_active_graph_and_status_validate_metadata_without_scan(self):
        rt = graph.runtime(self.root)
        generation = "b" * 32
        graph_file = rt / "generations" / generation / "graphify-out" / "graph.json"
        graph_file.parent.mkdir(parents=True)
        graph_file.write_text('{"nodes":[],"edges":[]}')
        pointer = {
            "generation": generation,
            "fingerprint": "old",
            "schema": graph.WRAPPER_SCHEMA,
            "graphify_version": graph.VERSION,
            "stale": False,
            "metadata": graph._metadata(self.root),
            "graph_sha256": hashlib.sha256(graph_file.read_bytes()).hexdigest(),
        }
        (rt / "current.json").write_text(json.dumps(pointer))
        # Reads must not need the Sonar scanner; only updates scan.
        with (
            patch.object(graph, "scan", side_effect=AssertionError("scan")),
            patch.object(graph, "verify_version", return_value=True),
            patch.object(graph.shutil, "which", return_value=None),
        ):
            self.assertEqual(graph.active_graph(self.root)[1], graph_file)
            with (
                patch("sys.argv", ["graphify_local", "status"]),
                patch.object(graph, "repo_root", return_value=self.root),
            ):
                self.assertEqual(graph.main(), 0)

    def test_metadata_detects_ctime_when_mtime_and_size_are_restored(self):
        source = self.root / "backend" / "one.py"
        before = source.stat()
        info = SimpleNamespace(
            st_ino=before.st_ino,
            st_size=before.st_size,
            st_mtime_ns=before.st_mtime_ns,
            st_ctime_ns=before.st_ctime_ns + 1,
        )
        with patch.object(Path, "stat", return_value=info):
            self.assertEqual(
                graph._signature(source),
                (info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns),
            )

    def test_arbitrary_subdirectory_resolves_same_git_root(self):
        subdir = self.root / "backend"
        self.assertEqual(graph.repo_root(subdir), self.root.resolve())

    def test_missing_tool_does_not_install(self):
        with (
            patch.object(graph, "scan"),
            patch.object(graph, "executable", return_value=self.root / "absent"),
            patch.object(graph, "verify_version", return_value=False),
        ):
            self.assertEqual(graph.update(self.root), 2)

    def test_process_lock_serializes_threads_and_releases(self):
        entered = threading.Event()
        release = threading.Event()
        acquired_second = threading.Event()

        def first():
            with graph.process_lock(
                graph.runtime(self.root) / "update.lock", time.monotonic() + 5
            ):
                entered.set()
                release.wait(2)

        def second():
            entered.wait(2)
            with graph.process_lock(
                graph.runtime(self.root) / "update.lock", time.monotonic() + 5
            ):
                acquired_second.set()

        a = threading.Thread(target=first)
        b = threading.Thread(target=second)
        a.start()
        b.start()
        try:
            self.assertTrue(entered.wait(2))
            time.sleep(0.15)
            self.assertFalse(acquired_second.is_set())
        finally:
            release.set()
            a.join(5)
            b.join(5)
        self.assertFalse(a.is_alive())
        self.assertFalse(b.is_alive())
        self.assertTrue(acquired_second.is_set())

    def test_process_lock_serializes_processes_and_releases(self):
        lock = graph.runtime(self.root) / "update.lock"
        ready = self.root / "child-ready"
        code = (
            "from pathlib import Path; import time; from scripts.graphify_local import process_lock; "
            f"p=Path({str(lock)!r}); ready=Path({str(ready)!r}); "
            "cm=process_lock(p); cm.__enter__(); ready.write_text('ready'); "
            "time.sleep(.6); cm.__exit__(None,None,None)"
        )
        child = subprocess.Popen(
            [sys.executable, "-c", code], cwd=Path(__file__).parents[1]
        )
        try:
            limit = time.monotonic() + 5
            while not ready.exists() and time.monotonic() < limit:
                time.sleep(0.02)
            self.assertTrue(ready.exists())
            started = time.monotonic()
            with graph.process_lock(lock, time.monotonic() + 5):
                self.assertGreaterEqual(time.monotonic() - started, 0.3)
        finally:
            child.wait(timeout=5)
        self.assertEqual(child.returncode, 0)


if __name__ == "__main__":
    unittest.main()
