"""Guard demo-container naming, fixture startup, and the container file ownership."""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_MARKER = "AI_COACH_DISPOSABLE_FIXTURE"
DEMO_SCRIPT = ROOT / "scripts" / "demo-container.ps1"
DEMO_NAME = "ai-coach-demo"

# Stand-in for the docker CLI. It records each argv as one JSON line and fails the
# subcommands named in FAKE_DOCKER_FAIL, so the PowerShell script runs without a
# daemon. Only this stub is executed; no real docker command or container is involved.
FAKE_DOCKER_SHIM = r'''
import json
import os
import sys

arguments = sys.argv[1:]
with open(os.environ["FAKE_DOCKER_LOG"], "a", encoding="utf-8") as log:
    log.write(json.dumps(arguments) + "\n")
command = arguments[0] if arguments else ""
failing = {item for item in os.environ.get("FAKE_DOCKER_FAIL", "").split(",") if item}
if command in failing:
    sys.stderr.write(f"fake docker: {command} failed\n")
    sys.exit(1)
if command == "ps":
    sys.stdout.write(os.environ.get("FAKE_DOCKER_PS", ""))
elif command == "run":
    sys.stdout.write("fake-container-id\n")
sys.exit(0)
'''


def _write_fake_docker(bin_dir, shim_path):
    python = sys.executable
    # PowerShell on Windows resolves docker.cmd; PowerShell on POSIX resolves the executable.
    (bin_dir / "docker.cmd").write_text(
        f'@"{python}" "{shim_path}" %*\r\n', encoding="ascii"
    )
    posix = bin_dir / "docker"
    posix.write_text(f'#!/bin/sh\nexec "{python}" "{shim_path}" "$@"\n', encoding="utf-8")
    posix.chmod(posix.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


class _HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/api/health" else 404)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format, *args):
        return


def _read(relative_path):
    return (ROOT / relative_path).read_text(encoding="utf-8")


class FixtureDisposableMarkerTests(unittest.TestCase):
    def run_fixture(self, marker):
        env = {key: value for key, value in os.environ.items() if key != FIXTURE_MARKER}
        if marker is not None:
            env[FIXTURE_MARKER] = marker
        # The guard runs before the fixture touches the environment or imports the
        # server, so a refused start cannot bind a port or write any data.
        return subprocess.run(
            [sys.executable, str(ROOT / "e2e" / "fixture_runtime.py")],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_fixture_refuses_to_start_without_marker(self):
        result = self.run_fixture(None)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"{FIXTURE_MARKER}=1 is required", result.stderr)
        self.assertEqual(result.stdout, "")

    def test_fixture_refuses_any_marker_value_other_than_exact_one(self):
        for marker in ("", "0", "true", "yes", " 1"):
            with self.subTest(marker=marker):
                result = self.run_fixture(marker)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(f"{FIXTURE_MARKER}=1 is required", result.stderr)


@unittest.skipUnless(
    shutil.which("pwsh") or shutil.which("powershell"),
    "PowerShell is not available on this runner",
)
class DemoContainerScriptTests(unittest.TestCase):
    """Runs scripts/demo-container.ps1 against a fake docker that records every call."""

    def setUp(self):
        self.shell = shutil.which("pwsh") or shutil.which("powershell")
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.bin_dir = root / "bin"
        self.bin_dir.mkdir()
        shim = root / "fake_docker.py"
        shim.write_text(FAKE_DOCKER_SHIM, encoding="utf-8")
        _write_fake_docker(self.bin_dir, shim)
        self.log = root / "docker-calls.jsonl"

    def calls(self):
        if not self.log.exists():
            return []
        lines = self.log.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines]

    def commands(self):
        return [call[0] for call in self.calls()]

    def run_script(self, *arguments, fail=(), ps_output=""):
        self.log.unlink(missing_ok=True)
        path_key = next((key for key in os.environ if key.upper() == "PATH"), "PATH")
        environment = {
            **os.environ,
            path_key: os.pathsep.join([str(self.bin_dir), os.environ.get(path_key, "")]),
            "FAKE_DOCKER_LOG": str(self.log),
            "FAKE_DOCKER_FAIL": ",".join(fail),
            "FAKE_DOCKER_PS": ps_output,
        }
        result = subprocess.run(
            [
                self.shell,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(DEMO_SCRIPT),
                *arguments,
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        return result, self.calls()

    def test_refused_names_stop_before_any_docker_call(self):
        for name in ("ai-coach", "AI-COACH", "ai-coach-prod", "production"):
            with self.subTest(name=name):
                result, calls = self.run_script("-Name", name)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Refusing container name", result.stdout + result.stderr)
                self.assertEqual(calls, [])

    def test_demo_and_fixture_names_pass_the_guard_before_docker_runs(self):
        for name in (DEMO_NAME, "fixture-check"):
            with self.subTest(name=name):
                result, calls = self.run_script("-Name", name, "-SkipBuild", fail=("ps",))
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Listing containers failed", result.stdout + result.stderr)
                self.assertEqual([call[0] for call in calls], ["ps"])

    def test_build_failure_stops_before_any_container_change(self):
        result, calls = self.run_script("-Name", DEMO_NAME, fail=("build",))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Image build failed", result.stdout + result.stderr)
        self.assertEqual([call[0] for call in calls], ["build"])

    def test_listing_failure_stops_before_stop_or_remove(self):
        result, calls = self.run_script("-Name", DEMO_NAME, "-SkipBuild", fail=("ps",))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Listing containers failed", result.stdout + result.stderr)
        self.assertEqual([call[0] for call in calls], ["ps"])

    def test_stop_failure_keeps_the_existing_container(self):
        result, calls = self.run_script(
            "-Name", DEMO_NAME, "-SkipBuild", ps_output="old-container\n", fail=("stop",)
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Stopping container", result.stdout + result.stderr)
        self.assertEqual([call[0] for call in calls], ["ps", "stop"])

    def test_remove_failure_prevents_a_new_container_from_starting(self):
        result, calls = self.run_script(
            "-Name", DEMO_NAME, "-SkipBuild", ps_output="old-container\n", fail=("rm",)
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Removing container", result.stdout + result.stderr)
        self.assertEqual([call[0] for call in calls], ["ps", "stop", "rm"])

    def test_existing_container_is_stopped_then_removed_without_volumes(self):
        result, calls = self.run_script(
            "-Name", DEMO_NAME, "-SkipBuild", ps_output="old-container\n", fail=("run",)
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls[1:3], [["stop", DEMO_NAME], ["rm", DEMO_NAME]])
        self.assertEqual(calls[3][0], "run")
        self.assertIn("Starting container", result.stdout + result.stderr)
        for call in calls:
            if call[0] in {"stop", "rm"}:
                self.assertNotIn("-v", call)
                self.assertNotIn("--volumes", call)
        self.assertNotIn("volume", self.commands())

    def test_absent_container_is_created_without_stop_or_remove(self):
        result, calls = self.run_script("-Name", DEMO_NAME, "-SkipBuild", fail=("run",))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual([call[0] for call in calls], ["ps", "run"])

    def test_run_arguments_keep_the_demo_on_loopback_and_disposable(self):
        _, calls = self.run_script(
            "-Name", DEMO_NAME, "-SkipBuild", "-Port", "8099", fail=("run",)
        )
        run = next(call for call in calls if call[0] == "run")
        self.assertIn("127.0.0.1:8099:8090", run)
        self.assertNotIn("0.0.0.0", " ".join(run))
        self.assertIn("AI_COACH_DISPOSABLE_FIXTURE=1", run)
        self.assertIn("FIXTURE_AUTO_SEED=1", run)
        self.assertFalse(any(argument.endswith(":/data") for argument in run))

    def test_persist_uses_a_named_volume_and_never_removes_volumes(self):
        _, calls = self.run_script(
            "-Name",
            DEMO_NAME,
            "-SkipBuild",
            "-Persist",
            ps_output="old-container\n",
            fail=("run",),
        )
        run = next(call for call in calls if call[0] == "run")
        self.assertIn(f"{DEMO_NAME}-data:/data", run)
        for call in calls:
            if call[0] == "rm":
                self.assertNotIn("-v", call)

    def test_healthy_demo_reports_ready_on_loopback(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _HealthHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(thread.join, 5)
        self.addCleanup(server.shutdown)
        port = server.server_address[1]

        result, calls = self.run_script("-Name", DEMO_NAME, "-SkipBuild", "-Port", str(port))

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Demo ready", result.stdout)
        self.assertEqual(calls[-1][0], "run")


class ContainerRuntimeTests(unittest.TestCase):
    def test_app_code_is_not_writable_by_the_app_user(self):
        dockerfile = _read("Dockerfile")
        self.assertIn("chown -R app:app /data", dockerfile)
        self.assertNotIn("chown -R app:app /app", dockerfile)
        self.assertIn("chmod -R a-w /app", dockerfile)
        self.assertIn("\nUSER app\n", dockerfile)
        self.assertIn("EXPOSE 8090", dockerfile)
        self.assertIn('CMD ["python", "/app/server.py"]', dockerfile)

    def test_app_user_ids_match_the_documented_bind_mount_owner(self):
        dockerfile = _read("Dockerfile")
        self.assertIn("addgroup --system --gid 101 app", dockerfile)
        self.assertIn("adduser --system --uid 100 --ingroup app app", dockerfile)
        readme = _read("README.md")
        installation = readme.split("## Installation & Deployment\n", 1)[1]
        for heading in (
            "### Docker Run\n",
            "### Docker Compose\n",
            "### Unraid Deployment Guide\n",
        ):
            with self.subTest(section=heading.strip()):
                section = installation.split(heading, 1)[1].split("\n### ", 1)[0]
                self.assertIn("chown -R 100:101 ", section)
                self.assertIn("UID 100", section)
                self.assertIn("GID 101", section)

    def test_ci_fixture_container_declares_itself_disposable(self):
        workflow = _read(".github/workflows/publish-container.yml")
        e2e = workflow.split("  e2e:\n", 1)[1].split("  browser:\n", 1)[0]
        launch = e2e.split("docker run --detach", 1)[1]
        launch = launch.split("fixture_runtime.py", 1)[0]
        self.assertIn(f"--env {FIXTURE_MARKER}=1", launch)


if __name__ == "__main__":
    unittest.main()
