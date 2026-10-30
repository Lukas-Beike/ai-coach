"""Synthetic orchestration checks: never invoke Docker or connected providers."""

import hashlib
import importlib.util
import io
import json
import re
import socket
import subprocess
import tempfile
import threading
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "browser_runner", ROOT / "scripts/run_browser_tests.py"
)
assert SPEC is not None and SPEC.loader is not None
runner = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runner)


def report(files=("a.spec.js", "b.spec.js", "c.spec.js")):
    return {
        "errors": [],
        "suites": [
            {
                "specs": [
                    {
                        "file": file,
                        "id": "id-" + file,
                        "title": file,
                        "line": 1,
                        "tests": [{"projectName": "desktop", "projectId": "desktop"}],
                    }
                    for file in files
                ]
            }
        ],
    }


def identities(children):
    return Counter(
        json.dumps(identity, sort_keys=True)
        for child in children
        for identity in child["identities"]
    )


class FakeProcesses:
    """Docker's observed-ID/label protocol, with deterministic failure injection."""

    def __init__(
        self,
        fail_browser=False,
        interrupt=False,
        partial_start=False,
        cleanup_error=False,
        listing=None,
    ):
        self.listing = listing or report()
        self.stop = threading.Event()
        self.commands = []
        self.ids = {}
        self.removed = []
        self.fail_browser, self.interrupt = fail_browser, interrupt
        self.partial_start, self.cleanup_error = partial_start, cleanup_error
        self.active = self.maximum = 0
        self.lock = threading.Lock()
        self.stopped = False

    def stop_all(self):
        self.stopped = True
        self.stop.set()

    def run(self, command, **kwargs):
        with self.lock:
            self.commands.append(command)
        if command[:2] == ["docker", "create"]:
            cid = "%064x" % (len(self.ids) + 1)
            label = command[command.index("--label") + 1].split("=", 1)[1]
            self.ids[cid] = label
            Path(command[command.index("--cidfile") + 1]).write_text(cid)
            if self.partial_start and "python" in command:
                return 9, "discard synthetic sensitive output"
            return 0, cid
        if command[:2] == ["docker", "inspect"]:
            if command[3] == "{{.State.ExitCode}}":
                return 0, "0"
            if self.cleanup_error and self.stopped:
                return 2, "never saved"
            return 0, self.ids[command[-1]]
        if command[:2] == ["docker", "rm"]:
            self.removed.append(command[-1])
            return 0, ""
        if command[:2] == ["docker", "start"]:
            return 0, ""
        if command[0] == "ip":
            return 0, ""
        if "--version" in command:
            return 0, "v24.22.1"
        if "--list" in command:
            return 0, json.dumps(self.listing)
        if command[:2] == ["git", "rev-parse"]:
            return 0, "c7ff60519520d553a00bfd33f6cf884b8de879b8"
        if command[:2] == ["git", "status"]:
            return 0, " M scripts/run_browser_tests.py"
        with self.lock:
            self.active += 1
            self.maximum = max(self.maximum, self.active)
        try:
            if self.interrupt:
                raise InterruptedError
            self.stop.wait(0.03)
            return (
                7 if self.fail_browser else 0
            ), "never retained session-bearing output"
        finally:
            with self.lock:
                self.active -= 1


class BrowserRunnerTests(unittest.TestCase):
    def test_lpt_frozen_median_new_files_and_ties(self):
        files = ["e2e/a", "e2e/b", "e2e/c", "e2e/new"]
        weights = {"e2e/a": 10, "e2e/b": 8, "e2e/c": 2}
        expected = [["e2e/a", "e2e/c"], ["e2e/b", "e2e/new"]]
        self.assertEqual(runner.assign_files(files, weights, 2), expected)
        self.assertEqual(runner.assign_files(reversed(files), weights, 2), expected)
        self.assertEqual(
            runner.assign_files(files, {}, 2),
            [["e2e/a", "e2e/c"], ["e2e/b", "e2e/new"]],
        )

    def test_malformed_weights_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "durations.json"
            for value in (
                None,
                [],
                {},
                {"version": 2, "projects": {}},
                {"version": 1, "projects": {"desktop": {"e2e/a": True}}},
                {"version": 1, "projects": {"desktop": {"e2e/a": -1}}},
                {"version": 1, "projects": {"desktop": {"e2e/a": float("nan")}}},
            ):
                with self.subTest(value=value):
                    path.write_text(json.dumps(value))
                    with self.assertRaises(runner.RunnerError):
                        runner.read_weights(path)

    def test_invalid_and_zero_selection_fail(self):
        listing = runner.parse_listing(report())
        timing = runner.read_weights(None)
        for project, specs, shard, total in (
            ("missing", [], 1, 1),
            ("desktop", ["e2e/absent"], 1, 1),
            ("desktop", [], 0, 1),
            ("desktop", [], 2, 1),
            ("desktop", [], 1, 0),
            ("desktop", [], 4, 4),
        ):
            with (
                self.subTest(project=project, specs=specs, shard=shard, total=total),
                self.assertRaises(runner.RunnerError),
            ):
                runner.select(listing, project, specs, shard, total, timing)
        with self.assertRaises(runner.RunnerError):
            runner.parse_listing({"errors": [{"message": "discard"}]})

    def test_atomic_write_retains_previous_manifest_on_replace_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            runner.atomic_json(path, {"status": "incomplete"})
            with (
                mock.patch.object(Path, "replace", side_effect=OSError),
                self.assertRaises(OSError),
            ):
                runner.atomic_json(path, {"status": "passed"})
            self.assertEqual(json.loads(path.read_text()), {"status": "incomplete"})

    def test_ports_reserved_disjoint_and_collision_is_not_modified(self):
        first, second = runner.reserve_ports(2), runner.reserve_ports(2)
        try:
            ports = [sock.getsockname()[1] for sock in first + second]
            self.assertEqual(len(set(ports)), 4)
            with socket.socket() as conflicting, self.assertRaises(OSError):
                conflicting.bind(("127.0.0.1", ports[0]))
            self.assertEqual(first[0].getsockname()[1], ports[0])
        finally:
            for sock in first + second:
                sock.close()

    def run_main(self, fake, jobs=1, list_only=False, extra_args=(), current=True):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        args = [
            "--project",
            "desktop",
            "--jobs",
            str(jobs),
            "--results-dir",
            temporary.name,
        ]
        args.extend(extra_args)
        if list_only:
            args.append("--list")
        with (
            mock.patch.object(runner, "Processes", return_value=fake),
            mock.patch.object(
                runner,
                "toolchain",
                return_value=("node", Path("cli.js"), {"@playwright/test": "1.64.1"}),
            ),
            mock.patch.object(
                runner, "image_identity", return_value="sha256:" + "a" * 64
            ),
            mock.patch.object(runner, "image_matches_source", return_value=current),
            mock.patch.object(
                runner, "verify_browser", return_value={"mode": "native"}
            ),
            mock.patch.object(runner, "ready"),
            mock.patch("sys.stdout", new_callable=io.StringIO),
            mock.patch("sys.stderr", new_callable=io.StringIO) as stderr,
        ):
            code = runner.main(args)
        self.stderr = stderr.getvalue()
        manifests = list(Path(temporary.name).glob("*/manifest.json"))
        self.assertEqual(len(manifests), 1)
        return code, json.loads(manifests[0].read_text()), manifests[0]

    def test_list_does_not_start_containers_and_never_reports_passed(self):
        fake = FakeProcesses()
        code, value, _ = self.run_main(fake, list_only=True)
        self.assertEqual(code, 0)
        self.assertEqual(value["status"], "listed")
        self.assertFalse(fake.ids)
        self.assertTrue(
            all(child["status"] == "pending" for child in value["children"])
        )

    def test_serial_and_two_lane_bounded_fresh_fixture_resources(self):
        for jobs in (1, 2):
            with self.subTest(jobs=jobs):
                fake = FakeProcesses()
                code, value, _ = self.run_main(fake, jobs=jobs)
                self.assertEqual(code, 0)
                self.assertEqual(value["status"], "passed")
                self.assertEqual(len(value["children"]), 3)
                self.assertEqual(fake.maximum, jobs)
                self.assertEqual(set(fake.removed), set(fake.ids))
                commands = fake.commands
                fixtures = [
                    item
                    for item in commands
                    if item[:2] == ["docker", "create"] and "python" in item
                ]
                self.assertEqual(len(fixtures), 3)
                self.assertEqual(
                    len({item[item.index("--name") + 1] for item in fixtures}), 3
                )
                for item in fixtures:
                    self.assertIn("100:101", item)
                    self.assertIn("--read-only", item)
                    self.assertIn("AI_COACH_DISPOSABLE_FIXTURE=1", item)
                    self.assertIn("/data:uid=100,gid=101,mode=0700", item)
                    self.assertTrue(
                        item[item.index("--network") + 1].startswith("container:")
                    )
                network_creates = [
                    index
                    for index, item in enumerate(commands)
                    if item[:2] == ["docker", "create"] and "sleep" in item
                ]
                browsers = [
                    index
                    for index, item in enumerate(commands)
                    if item[0] == "node" and "test" in item and "--list" not in item
                ]
                self.assertLess(max(network_creates), min(browsers))
                self.assertEqual(len(value["resources"]["ports"]), jobs * 2)

    def test_failed_child_survives_cleanup_failure_and_does_not_save_raw_output(self):
        fake = FakeProcesses(fail_browser=True, cleanup_error=True)
        code, value, path = self.run_main(fake)
        self.assertNotEqual(code, 0)
        self.assertEqual(value["status"], "failed")
        self.assertEqual(value["children"][0]["exit_code"], 7)
        self.assertTrue(value["cleanup_errors"])
        text = path.read_text() + "".join(
            p.read_text() for p in path.parent.rglob("process.txt")
        )
        for forbidden in (
            runner.FAKE_PASSWORD,
            "state.json",
            "session-bearing",
            "E2E_APP_PASSWORD",
        ):
            self.assertNotIn(forbidden, text)

    def test_host_network_error_needs_every_failing_test_to_name_it(self):
        marker = '"console: Failed to load resource: net::ERR_NO_BUFFER_SPACE"\n'
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            self.assertIsNone(runner.host_network_error(output))

            def report(name, text):
                path = output / "artifacts" / name / "error-context.md"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")

            report("first", marker)
            self.assertEqual(
                "net::ERR_NO_BUFFER_SPACE", runner.host_network_error(output)
            )
            report("second", "expect(received).toEqual(expected)\n")
            self.assertIsNone(runner.host_network_error(output))

    def test_host_network_error_reads_only_per_test_reports(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            nested = output / "report" / "data" / "error-context.md"
            nested.parent.mkdir(parents=True)
            nested.write_text("net::ERR_NO_BUFFER_SPACE\n", encoding="utf-8")
            self.assertIsNone(runner.host_network_error(output))
            outside = output / "outside.md"
            outside.write_text("net::ERR_NO_BUFFER_SPACE\n", encoding="utf-8")
            link = output / "artifacts" / "case" / "error-context.md"
            link.parent.mkdir(parents=True)
            try:
                link.symlink_to(outside)
            except OSError:
                self.skipTest("symlinks are not available")
            self.assertIsNone(runner.host_network_error(output))

    def test_host_network_failure_is_reported_as_infrastructure(self):
        fake = FakeProcesses(fail_browser=True)
        with mock.patch.object(
            runner, "host_network_error", return_value="net::ERR_NO_BUFFER_SPACE"
        ):
            code, value, _path = self.run_main(fake)
        self.assertNotEqual(code, 0)
        self.assertEqual(value["status"], "failed")
        self.assertEqual(
            value["children"][0]["infrastructure_error"], "net::ERR_NO_BUFFER_SPACE"
        )
        self.assertIn("host network error", value["error"])
        self.assertIn("--project desktop", value["error"])

    def test_failed_tests_report_location_and_first_error_line(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            self.assertEqual([], runner.failed_tests(output))
            path = output / "artifacts" / "case" / "error-context.md"
            path.parent.mkdir(parents=True)
            path.write_text(
                "# Test info\n\n- Name: login >> opens chat\n"
                "- Location: e2e/login.spec.js:12:3\n\n# Error details\n\n```\n"
                f"Error: fill {runner.FAKE_PASSWORD} failed\n"
                "second line stays out\n```\n",
                encoding="utf-8",
            )
            self.assertEqual(
                [
                    {
                        "location": "e2e/login.spec.js:12:3",
                        "error": "Error: fill [redacted] failed",
                    }
                ],
                runner.failed_tests(output),
            )

    def test_failed_child_surfaces_first_error_in_output_and_manifest(self):
        failure = {"location": "e2e/a.spec.js:3:1", "error": "Error: expected 1"}
        fake = FakeProcesses(fail_browser=True)
        with mock.patch.object(runner, "failed_tests", return_value=[failure] * 2):
            code, value, _path = self.run_main(fake)
        self.assertNotEqual(code, 0)
        self.assertEqual([failure] * 2, value["children"][0]["failures"])
        self.assertIn("e2e/a.spec.js:3:1: Error: expected 1", value["error"])
        self.assertIn("+1 more", value["error"])
        self.assertIn("Browser run failed: " + value["error"], self.stderr)
        self.assertNotIn("session-bearing", self.stderr)

    def test_first_error_line_stays_inside_the_error_block(self):
        self.assertEqual("", runner.first_error_line(["# Test info"]))
        for block in (
            ["# Error details", "", "```", "```", "# Page snapshot", "- generic"],
            ["# Error details", "", "# Page snapshot", "- generic"],
        ):
            self.assertEqual("", runner.first_error_line(block))

    def test_retry_reports_of_one_failure_are_listed_once(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for name in ("case", "case-retry1"):
                path = output / "artifacts" / name / "error-context.md"
                path.parent.mkdir(parents=True)
                path.write_text(
                    "- Location: e2e/a.spec.js:3:1\n# Error details\n```\nError: x\n",
                    encoding="utf-8",
                )
            self.assertEqual(1, len(runner.failed_tests(output)))

    def test_child_without_test_report_says_it_failed_outside_a_test(self):
        code, value, _path = self.run_main(FakeProcesses(fail_browser=True))
        self.assertNotEqual(code, 0)
        self.assertEqual([], value["children"][0]["failures"])
        self.assertIn("no test report", self.stderr)

    def test_outdated_application_image_warns_and_is_recorded(self):
        code, value, _path = self.run_main(FakeProcesses(), current=False)
        self.assertEqual(code, 0)
        self.assertIs(False, value["images"]["application_matches_source"])
        self.assertIn("docker build -t ai-coach:e2e .", self.stderr)
        for current in (True, None):
            self.run_main(FakeProcesses(), current=current)
            self.assertNotIn("Warning", self.stderr)

    def test_image_source_comparison_hashes_content_and_ignores_bytecode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "backend" / "__pycache__").mkdir(parents=True)
            source = root / "backend" / "module.py"
            source.write_text("one", encoding="utf-8")
            digest = runner.source_digest(root, runner.APPLICATION_SOURCES)
            (root / "backend" / "__pycache__" / "module.pyc").write_text("x")
            self.assertEqual(
                digest, runner.source_digest(root, runner.APPLICATION_SOURCES)
            )
            containers = mock.Mock(run_id="run")
            processes = mock.Mock()
            processes.run.return_value = (0, digest + "\n")
            self.assertTrue(
                runner.image_matches_source(processes, containers, "image", root)
            )
            script = containers.create.call_args.args[1][-1]
            self.assertIn("def source_digest", script)
            source.write_text("two", encoding="utf-8")
            self.assertFalse(
                runner.image_matches_source(processes, containers, "image", root)
            )
            processes.run.return_value = (1, "")
            self.assertIsNone(
                runner.image_matches_source(processes, containers, "image", root)
            )
            containers.create.side_effect = runner.RunnerError("unavailable")
            self.assertIsNone(
                runner.image_matches_source(processes, containers, "image", root)
            )

    def run_with_cleanup_exception(self, fake):
        snapshots = []
        write = runner.atomic_json

        def record(path, value):
            write(path, value)
            snapshots.append(json.loads(path.read_text()))

        with (
            mock.patch.object(
                runner.Containers,
                "cleanup",
                side_effect=OSError("synthetic private detail"),
            ),
            mock.patch.object(runner, "atomic_json", side_effect=record),
        ):
            code, value, path = self.run_main(fake)
        self.assertTrue(value["cleanup_errors"])
        self.assertEqual(value["phases"]["cleanup"]["status"], "failed")
        self.assertEqual(
            set(value["resources"]["containers_not_confirmed_removed"]),
            set(fake.ids) - set(fake.removed),
        )
        self.assertTrue(value["resources"]["containers_not_confirmed_removed"])
        self.assertTrue(fake.stopped)
        self.assertEqual(fake.active, 0)
        self.assertNotIn("synthetic private detail", path.read_text())
        for snapshot in snapshots:
            if any(
                phase["status"] == "failed" for phase in snapshot["phases"].values()
            ):
                self.assertNotEqual(snapshot["status"], "passed")
                self.assertNotEqual(snapshot["exit_code"], 0)
        self.assertEqual(snapshots[-1], value)
        return code, value

    def test_cleanup_exception_after_passed_children_cannot_pass(self):
        code, value = self.run_with_cleanup_exception(FakeProcesses())
        self.assertEqual(code, 1)
        self.assertEqual(value["exit_code"], 1)
        self.assertEqual(value["status"], "failed")
        self.assertTrue(all(child["status"] == "passed" for child in value["children"]))

    def test_cleanup_exception_retains_original_child_failure(self):
        original_code, original, _ = self.run_main(FakeProcesses(fail_browser=True))
        code, value = self.run_with_cleanup_exception(FakeProcesses(fail_browser=True))
        self.assertEqual(code, original_code)
        self.assertEqual(value["exit_code"], original_code)
        self.assertEqual(value["status"], "failed")
        self.assertEqual(value["error"], original["error"])
        self.assertEqual(value["children"][0]["exit_code"], 7)
        self.assertEqual(value["children"][0]["status"], "failed")

    def test_cleanup_exception_retains_interruption(self):
        code, value = self.run_with_cleanup_exception(FakeProcesses(interrupt=True))
        self.assertEqual(code, 130)
        self.assertEqual(value["exit_code"], 130)
        self.assertEqual(value["status"], "interrupted")
        self.assertEqual(value["error"], "Run interrupted")
        self.assertTrue(
            any(child["status"] == "interrupted" for child in value["children"])
        )

    def test_interrupted_children_are_reaped_before_owned_cleanup(self):
        fake = FakeProcesses(interrupt=True)
        code, value, _ = self.run_main(fake)
        self.assertEqual(code, 130)
        self.assertEqual(value["status"], "interrupted")
        self.assertTrue(fake.stopped)
        self.assertEqual(fake.active, 0)
        self.assertEqual(set(fake.removed), set(fake.ids))
        self.assertTrue(
            any(child["status"] == "interrupted" for child in value["children"])
        )

    def test_partial_start_collects_cid_and_cleanup_only_observed_ids(self):
        fake = FakeProcesses(partial_start=True)
        code, value, _ = self.run_main(fake)
        self.assertNotEqual(code, 0)
        self.assertEqual(value["status"], "failed")
        self.assertEqual(set(fake.removed), set(fake.ids))
        with tempfile.TemporaryDirectory() as temporary:
            owned = runner.Containers(fake, Path(temporary), "my-run")
            with self.assertRaises(runner.RunnerError):
                owned.remove("f" * 64)
            owned.observed.add("e" * 64)
            fake.ids["e" * 64] = "unrelated-run"
            self.assertEqual(owned.cleanup(), ["Owned container cleanup failed"])
            self.assertNotIn("e" * 64, fake.removed)

    def test_auth_and_output_paths_are_disjoint_and_private(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = runner.parser().parse_args(["--project", "desktop"])
            evidence = runner.Evidence(root, "run", args)
            execute = runner.Execution(
                ROOT,
                args,
                evidence,
                FakeProcesses(),
                None,
                root,
                "image",
                {},
                "node",
                "cli",
            )
            command_a, env_a, _ = execute.browser_command(
                {"project": "desktop", "file": "e2e/a.spec.js"},
                9100,
                root / "out-a",
                root / "private-a",
            )
            _, env_b, _ = execute.browser_command(
                {"project": "desktop", "file": "e2e/b.spec.js"},
                9101,
                root / "out-b",
                root / "private-b",
            )
            self.assertNotEqual(
                env_a["E2E_AUTH_STATE_PATH"], env_b["E2E_AUTH_STATE_PATH"]
            )
            self.assertNotEqual(
                env_a["PLAYWRIGHT_HTML_OUTPUT_DIR"], env_b["PLAYWRIGHT_HTML_OUTPUT_DIR"]
            )
            self.assertFalse(
                Path(env_a["E2E_AUTH_STATE_PATH"]).is_relative_to(root / "out-a")
            )
            self.assertIn("--trace=off", command_a)

    def test_synthetic_identity_parity_across_all_projects_and_shards(self):
        listing_report = report()
        projects = {"desktop", "mobile", "mobile-small", "tablet", "tablet-landscape"}
        for spec in listing_report["suites"][0]["specs"]:
            spec["tests"] = [
                {"projectName": project, "projectId": project}
                for project in sorted(projects)
            ]
        listing = runner.parse_listing(listing_report)
        timing = runner.read_weights(None)
        baseline = runner.select(listing, "all", [], 1, 1, timing)
        self.assertEqual({child["project"] for child in baseline}, projects)
        self.assertEqual(sum(identities(baseline).values()), 15)
        combined = []
        for project in sorted(projects):
            for shard in (1, 2):
                combined += runner.select(listing, project, [], shard, 2, timing)
        self.assertEqual(identities(baseline), identities(combined))
        self.assertTrue(all(count == 1 for count in identities(combined).values()))

    def test_missing_or_mismatched_locked_toolchain_fails_without_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            packages = ("@playwright/test", "playwright", "playwright-core")
            (root / "package-lock.json").write_text(
                json.dumps(
                    {
                        "packages": {
                            "node_modules/" + package: {"version": "1.64.1"}
                            for package in packages
                        }
                    }
                )
            )
            with self.assertRaisesRegex(
                runner.RunnerError, "Locked local Playwright missing"
            ):
                runner.toolchain(root)
            for package in packages:
                installed = root / "node_modules" / package / "package.json"
                installed.parent.mkdir(parents=True, exist_ok=True)
                installed.write_text(json.dumps({"version": "1.64.1"}))
            with (
                mock.patch.object(runner.shutil, "which", return_value=None) as which,
                self.assertRaisesRegex(runner.RunnerError, "Node is unavailable"),
            ):
                runner.toolchain(root)
            which.assert_called_once_with("node")
            installed.write_text(json.dumps({"version": "wrong"}))
            with self.assertRaisesRegex(
                runner.RunnerError, "differs from package-lock"
            ):
                runner.toolchain(root)

    def test_manifest_exists_before_the_first_tool_child(self):
        fake = FakeProcesses()
        original = fake.run
        observed = []

        def inspect_first(command, **kwargs):
            if not observed:
                # The test helper's fresh parent is the only evidence directory in its
                # patched Evidence constructor, captured before any child is launched.
                value = json.loads(created[0].read_text())
                self.assertEqual(value["status"], "incomplete")
                self.assertIsNone(value["exit_code"])
                observed.append(True)
            return original(command, **kwargs)

        created = []
        init = runner.Evidence.__init__

        def record(instance, directory, run_id, args):
            init(instance, directory, run_id, args)
            created.append(directory / "manifest.json")

        fake.run = inspect_first
        with mock.patch.object(runner.Evidence, "__init__", record):
            self.run_main(fake, list_only=True)
        self.assertTrue(observed)

    def test_cleanup_orders_browser_then_fixture_then_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            fake = FakeProcesses()
            containers = runner.Containers(fake, Path(temporary), "my-run")
            network = containers.create(
                "acb-my-run-net-0", ["image", "sleep", "infinity"]
            )
            fixture = containers.create("acb-my-run-fixture-0", ["image", "python"])
            browser = containers.create("acb-my-run-browser-0", ["image", "node"])
            self.assertEqual(containers.cleanup(), [])
            self.assertEqual(fake.removed, [browser, fixture, network])

    def test_container_name_collision_does_not_authorize_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            fake = FakeProcesses()

            def collision(command, **kwargs):
                return 1, "Unrelated container name already in use"

            fake.run = collision
            containers = runner.Containers(fake, Path(temporary), "my-run")
            with self.assertRaises(runner.RunnerError):
                containers.create("collision", ["image"])
            self.assertEqual(containers.cleanup(), [])
            self.assertFalse(fake.removed)

    def test_readiness_is_bounded_and_cancelled_without_fallback(self):
        with self.assertRaises(runner.RunnerError):
            runner.ready(1, threading.Event(), timeout=0)
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(InterruptedError):
            runner.ready(1, cancelled)

    def test_cancellation_terminates_and_reaps_owned_process_group(self):
        processes = runner.Processes()
        child = mock.Mock()
        child.pid = 123
        child.poll.return_value = None

        def cancelled(**kwargs):
            processes.stop.set()
            raise subprocess.TimeoutExpired(["synthetic"], 0.2)

        child.communicate.side_effect = cancelled
        with (
            mock.patch.object(runner.subprocess, "Popen", return_value=child) as popen,
            mock.patch.object(processes, "terminate") as terminate,
            self.assertRaises(InterruptedError),
        ):
            processes.run(["synthetic"])
        terminate.assert_called_once_with(child)
        child.wait.assert_called_once()
        self.assertFalse(processes.active)
        if runner.os.name == "nt":
            flags = popen.call_args.kwargs["creationflags"]
            self.assertTrue(flags & subprocess.CREATE_NO_WINDOW)
            self.assertTrue(flags & subprocess.CREATE_NEW_PROCESS_GROUP)
        else:
            self.assertTrue(popen.call_args.kwargs["start_new_session"])

    def test_prepared_compatibility_requires_declared_version_and_observed_revision(
        self,
    ):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "node_modules/playwright-core").mkdir(parents=True)
            (root / "scripts").mkdir()
            (root / "node_modules/playwright-core/browsers.json").write_text(
                json.dumps(
                    {
                        "browsers": [
                            {"name": "chromium", "revision": "1248"},
                            {"name": "chromium-headless-shell", "revision": "1248"},
                        ]
                    }
                )
            )
            pin = root / "scripts/browser_environment.json"
            image = "example:v1@sha256:" + "a" * 64
            pin.write_text(json.dumps({"version": "1.64.1", "image": image}))
            args = runner.parser().parse_args(
                ["--project", "desktop", "--browser-image", image]
            )
            versions = {"@playwright/test": "1.64.1"}
            fake = FakeProcesses()
            containers = mock.Mock(run_id="my-run")
            containers.create.return_value = "a" * 64

            def observed(command, **kwargs):
                if command[:2] == ["docker", "start"]:
                    return 0, json.dumps(
                        {
                            "revisions": {
                                "chromium": "wrong",
                                "chromium_headless_shell": "1248",
                            }
                        }
                    )
                return 0, "0"

            fake.run = observed
            with (
                mock.patch.object(runner.sys, "platform", "linux"),
                mock.patch.object(runner, "browser_options", return_value=[]),
                mock.patch.object(runner, "image_identity", return_value="image-id"),
            ):
                with self.assertRaisesRegex(runner.RunnerError, "revisions differ"):
                    runner.verify_browser(
                        root, args, "node", versions, fake, containers, root
                    )
                containers.remove.assert_not_called()
                pin.write_text(json.dumps({"version": "wrong", "image": image}))
                containers.reset_mock()
                with self.assertRaisesRegex(runner.RunnerError, "locked declared"):
                    runner.verify_browser(
                        root, args, "node", versions, fake, containers, root
                    )
                containers.create.assert_not_called()
            with (
                mock.patch.object(runner.sys, "platform", "win32"),
                self.assertRaisesRegex(runner.RunnerError, "Linux host"),
            ):
                runner.verify_browser(
                    root, args, "node", versions, fake, containers, root
                )

    def test_expected_identities_survive_spec_and_shard_filters(self):
        listing = report()
        for spec in listing["suites"][0]["specs"]:
            spec["tests"].append({"projectName": "mobile", "projectId": "mobile"})
        for project in ("desktop", "mobile", "all"):
            expected = [
                identity
                for (name, _), values in runner.parse_listing(listing).items()
                if project == "all" or name == project
                for identity in values
            ]
            for options in (
                ("--shard", "1", "--total", "2"),
                ("--shard", "2", "--total", "2"),
                ("--spec", "e2e/b.spec.js"),
            ):
                with self.subTest(project=project, options=options):
                    code, value, _ = self.run_main(
                        FakeProcesses(listing=listing),
                        list_only=True,
                        extra_args=("--project", project, *options),
                    )
                    self.assertEqual(code, 0)
                    self.assertCountEqual(
                        value["selection"]["expected_identities"], expected
                    )
                    self.assertLess(len(identities(value["children"])), len(expected))
                    selection = value["selection"]
                    self.assertEqual(selection["project"], project)
                    self.assertEqual(
                        selection["mode"],
                        "complete"
                        if project == "all" and "--spec" not in options
                        else "focused",
                    )
                    self.assertEqual(
                        selection["specs"],
                        ["e2e/b.spec.js"] if "--spec" in options else [],
                    )
                    self.assertEqual(
                        selection["total"], 2 if "--total" in options else 1
                    )
                    self.assertEqual(
                        selection["shard"],
                        int(options[1]) if "--shard" in options else 1,
                    )

    def test_manifest_hashes_complete_e2e_sources_and_public_inputs(self):
        code, value, _ = self.run_main(FakeProcesses(), list_only=True)
        self.assertEqual(code, 0)
        expected = {
            path
            for path in (
                "scripts/run_browser_tests.py",
                "playwright.config.cjs",
                "public/index.html",
                "public/service-worker.js",
                "package.json",
                "package-lock.json",
                "e2e/browser_durations.json",
                "scripts/browser_environment.json",
            )
            if (ROOT / path).is_file()
        }
        expected.update(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "e2e").rglob("*")
            if path.suffix in {".js", ".py"} and path.is_file()
        )
        self.assertEqual(set(value["inputs"]), expected)
        self.assertTrue(
            {
                "e2e/auth.setup.js",
                "e2e/fixture_runtime.py",
                "e2e/read-fixture.js",
                "e2e/helpers/ui.js",
                "e2e/helpers/connections.js",
            }.issubset(expected)
        )
        for path in expected:
            self.assertEqual(
                value["inputs"][path],
                hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
            )

    def test_source_hashes_ignore_auth_runtime_and_detect_helper_changes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "e2e/helpers/nested").mkdir(parents=True)
            helper = root / "e2e/helpers/nested/helper.py"
            helper.write_text("# synthetic source v1")
            (root / "e2e/state.json").write_text('{"synthetic": "runtime"}')
            (root / "e2e/helpers/output.txt").write_text("synthetic output")
            (root / "e2e/.auth").mkdir()
            (root / "e2e/.auth/state.json").write_text("{}")
            (root / "e2e/.auth/ignored.js").write_text("// runtime, not source")
            durations = root / "durations.json"
            durations.write_text("{}")
            before = runner.source_hashes(root, durations)
            self.assertEqual(
                set(before), {"e2e/helpers/nested/helper.py", "durations.json"}
            )
            helper.write_text("# synthetic source v2")
            after = runner.source_hashes(root, durations)
            self.assertNotEqual(
                before["e2e/helpers/nested/helper.py"],
                after["e2e/helpers/nested/helper.py"],
            )
            self.assertEqual(before["durations.json"], after["durations.json"])

    def test_prepared_commands_select_both_source_reading_specs(self):
        node, cli = "synthetic-node", Path("synthetic-cli.js")
        listing = runner.parse_listing(
            report(("contracts.spec.js", "css-cascade.spec.js"))
        )
        timing = runner.read_weights(None)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            args = runner.parser().parse_args(
                [
                    "--project",
                    "desktop",
                    "--browser-image",
                    "synthetic-image",
                ]
            )
            containers = mock.Mock(run_id="prepared-commands")
            containers.create.return_value = "a" * 64
            execute = runner.Execution(
                ROOT,
                args,
                runner.Evidence(root, "run", args),
                FakeProcesses(),
                containers,
                root,
                "app-image",
                {"id": "browser-image-id"},
                node,
                cli,
            )
            for file in ("e2e/contracts.spec.js", "e2e/css-cascade.spec.js"):
                with self.subTest(file=file):
                    child = runner.select(listing, "desktop", [file], 1, 1, timing)[0]
                    # Only command construction is modeled as Linux here; no host-network run.
                    with (
                        mock.patch.object(
                            runner.os, "getuid", return_value=1000, create=True
                        ),
                        mock.patch.object(
                            runner.os, "getgid", return_value=1000, create=True
                        ),
                    ):
                        command, _, cid = execute.browser_command(
                            child, 9100, root / "results", root / "private"
                        )
                    self.assertEqual(command, ["docker", "start", "--attach", cid])
                    creation = containers.create.call_args.args[1]
                    self.assertEqual(creation[:2], ["--network", "host"])
                    mounts = [
                        creation[i + 1]
                        for i, item in enumerate(creation)
                        if item == "--volume"
                    ]
                    self.assertEqual(
                        set(mounts),
                        {
                            *(runner.browser_mounts(ROOT)[1::2]),
                            str(root / "results") + ":/results",
                            str(root / "private") + ":/private",
                        },
                    )
                    self.assertIn("E2E_AUTH_STATE_PATH=/private/state.json", creation)
                    self.assertIn(
                        "E2E_PHASE_TIMINGS_PATH=/private/phase.json", creation
                    )
                    self.assertIn("E2E_BASE_URL=http://127.0.0.1:9100", creation)
                    self.assertIn("E2E_APP_PASSWORD=" + runner.FAKE_PASSWORD, creation)
                    self.assertIn(
                        "PLAYWRIGHT_HTML_OUTPUT_DIR=/results/report", creation
                    )
                    self.assertIn("--read-only", creation)
                    self.assertIn("--cap-drop=ALL", creation)
                    self.assertIn("no-new-privileges:true", creation)
                    self.assertEqual(
                        creation[creation.index("--user") + 1], "1000:1000"
                    )
                    arguments = creation[creation.index("browser-image-id") + 3 :]
                    self.assertIn("--workers=1", arguments)
                    self.assertIn("--trace=off", arguments)
                    self.assertEqual(
                        arguments[arguments.index("--project") + 1], "desktop"
                    )
                    self.assertEqual(arguments[1], re.escape(file) + "$")
                    observed = [
                        {"identities": values}
                        for (project, candidate), values in listing.items()
                        if project == "desktop" and re.search(arguments[1], candidate)
                    ]
                    self.assertEqual(identities([child]), identities(observed))

    def test_prepared_mounts_exclude_repository_root_live_data_and_socket(self):
        mounts = runner.browser_mounts(ROOT)
        mounted = [
            mounts[index + 1] for index, item in enumerate(mounts) if item == "--volume"
        ]
        self.assertEqual(
            set(mounted),
            {
                str(ROOT / "node_modules") + ":/work/node_modules:ro",
                str(ROOT / "e2e") + ":/work/e2e:ro",
                str(ROOT / "playwright.config.cjs") + ":/work/playwright.config.cjs:ro",
                str(ROOT / "public/index.html") + ":/work/public/index.html:ro",
                str(ROOT / "public/service-worker.js")
                + ":/work/public/service-worker.js:ro",
            },
        )
        self.assertEqual(len(mounted), 5)
        for source in mounted:
            self.assertTrue(source.endswith(":ro"))
            self.assertNotIn(".env", source)
            self.assertNotIn("docker.sock", source)
            self.assertFalse(source.startswith(str(ROOT) + ":"))


if __name__ == "__main__":
    unittest.main()
