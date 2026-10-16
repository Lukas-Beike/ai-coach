"""Guard demo-container naming, fixture startup, and the container file ownership."""

import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_MARKER = "AI_COACH_DISPOSABLE_FIXTURE"


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


class DemoContainerScriptTests(unittest.TestCase):
    def test_name_check_precedes_every_docker_call(self):
        script = _read("scripts/demo-container.ps1")
        guard = script.index("Refusing container name")
        for call in ("docker build", "docker ps", "docker stop", "docker rm"):
            with self.subTest(call=call):
                self.assertLess(guard, script.index(call))
        self.assertNotIn("docker rm -v", script)
        self.assertIn(f"{FIXTURE_MARKER}=1", script)

    def test_native_docker_failures_stop_the_script(self):
        script = _read("scripts/demo-container.ps1")
        # Each docker call (build, ps, stop, rm, run) must be followed by an exit-code check.
        self.assertGreaterEqual(script.count("$LASTEXITCODE -ne 0"), 5)
        self.assertIn("Demo container did not become healthy on port $Port", script)
        self.assertLess(
            script.index("did not become healthy"), script.index("Demo ready")
        )
        self.assertNotIn("docker rm -v", script)

    def test_script_refuses_production_and_non_demo_names(self):
        shell = shutil.which("pwsh") or shutil.which("powershell")
        if shell is None:
            self.skipTest("PowerShell is not available on this runner")
        script = str(ROOT / "scripts" / "demo-container.ps1")
        for name in ("ai-coach", "AI-COACH", "ai-coach-prod", "production"):
            with self.subTest(name=name):
                result = subprocess.run(
                    [
                        shell,
                        "-NoProfile",
                        "-NonInteractive",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-File",
                        script,
                        "-Name",
                        name,
                        "-SkipBuild",
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    timeout=120,
                    check=False,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Refusing container name", result.stdout + result.stderr)


class ContainerRuntimeTests(unittest.TestCase):
    def test_app_code_is_not_writable_by_the_app_user(self):
        dockerfile = _read("Dockerfile")
        self.assertIn("chown -R app:app /data", dockerfile)
        self.assertNotIn("chown -R app:app /app", dockerfile)
        self.assertIn("chmod -R a-w /app", dockerfile)
        self.assertIn("\nUSER app\n", dockerfile)
        self.assertIn("EXPOSE 8090", dockerfile)
        self.assertIn('CMD ["python", "/app/server.py"]', dockerfile)

    def test_ci_fixture_container_declares_itself_disposable(self):
        workflow = _read(".github/workflows/publish-container.yml")
        launch = workflow.split("docker run --detach --name ai-coach-e2e", 1)[1]
        launch = launch.split("fixture_runtime.py", 1)[0]
        self.assertIn(f"--env {FIXTURE_MARKER}=1", launch)


if __name__ == "__main__":
    unittest.main()
