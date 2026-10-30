from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class GraphifyHookTests(unittest.TestCase):
    def test_posix_launcher_uses_lf_line_endings(self) -> None:
        launcher = (ROOT / "scripts/graphify-session-start.sh").read_bytes()
        self.assertNotIn(b"\r", launcher)

    @unittest.skipUnless(
        (ROOT / "AGENTS.md").is_file(),
        "Host hook configurations are not packaged in the runtime image",
    )
    def test_native_hook_configs_preserve_existing_codex_and_call_refresh(self) -> None:
        codex = json.loads((ROOT / ".codex/hooks.json").read_text(encoding="utf-8-sig"))
        claude = json.loads(
            (ROOT / ".claude/settings.json").read_text(encoding="utf-8-sig")
        )

        self.assertNotIn("UserPromptSubmit", codex["hooks"])
        for config, key in ((codex, "SessionStart"), (claude, "SessionStart")):
            entries = config["hooks"][key]
            self.assertEqual(len(entries), 1)
            hook = entries[0]["hooks"][0]
            self.assertEqual(hook["type"], "command")
            self.assertEqual(hook["timeout"], 240)
            self.assertIn("graphify-session-start", hook["command"])
            self.assertTrue(
                "matcher" not in entries[0] or entries[0]["matcher"] in ("", "*")
            )
        self.assertEqual(
            claude["hooks"]["SessionStart"][0]["hooks"][0]["shell"], "powershell"
        )
        for event, entries in claude["hooks"].items():
            if event != "SessionStart":
                self.assertNotIn("graphify", json.dumps(entries), event)

    @unittest.skipUnless(
        os.name == "nt" and (ROOT / "AGENTS.md").is_file(),
        "Native PowerShell hooks require Windows and packaged host configurations",
    )
    def test_native_commands_from_nested_path_with_spaces_use_mock_python(self) -> None:
        with tempfile.TemporaryDirectory(prefix="graphify hook ") as temp:
            root = Path(temp) / "fixture repo with spaces"
            nested = root / "nested directory"
            bin_dir = root / "mock bin"
            nested.mkdir(parents=True)
            bin_dir.mkdir()
            (root / "scripts").mkdir()
            shutil.copy(
                ROOT / "scripts/graphify-session-start.ps1",
                root / "scripts/graphify-session-start.ps1",
            )
            (root / "scripts/graphify_local.py").write_text(
                "# synthetic worker\n", encoding="utf-8"
            )
            args_file = root / "invocation.txt"
            (bin_dir / "python.cmd").write_text(
                '@echo off\r\necho %~1^|%~2^|%~3 >> "%GRAPHIFY_TEST_ARGS%"\r\nexit /b 0\r\n',
                encoding="ascii",
            )
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            env = os.environ.copy()
            env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
            env["GRAPHIFY_TEST_ARGS"] = str(args_file)
            configs = (
                json.loads((ROOT / ".codex/hooks.json").read_text(encoding="utf-8")),
                json.loads(
                    (ROOT / ".claude/settings.json").read_text(encoding="utf-8")
                ),
            )
            expected = f"{root / 'scripts/graphify_local.py'}|update|--session-start"
            commands = (
                (
                    [
                        "powershell",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-Command",
                    ],
                    configs[0]["hooks"]["SessionStart"][0]["hooks"][0][
                        "commandWindows"
                    ],
                ),
                (
                    [
                        "powershell",
                        "-NoProfile",
                        "-ExecutionPolicy",
                        "Bypass",
                        "-Command",
                    ],
                    configs[1]["hooks"]["SessionStart"][0]["hooks"][0]["command"],
                ),
            )
            for index, (shell, command) in enumerate(commands):
                result = subprocess.run(
                    [*shell, command],
                    check=False,
                    cwd=nested,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                lines = (
                    [
                        line.rstrip()
                        for line in args_file.read_text(encoding="utf-8").splitlines()
                    ]
                    if args_file.exists()
                    else []
                )
                self.assertEqual(lines, [expected] * (index + 1), result.stderr)
            self.assertEqual(
                [
                    line.rstrip()
                    for line in args_file.read_text(encoding="utf-8").splitlines()
                ],
                [expected, expected],
            )

    @unittest.skipUnless(
        os.name == "nt", "PowerShell launcher behavior is Windows-specific"
    )
    def test_missing_worker_and_python_are_visible_but_non_blocking(self) -> None:
        with tempfile.TemporaryDirectory(prefix="graphify hook ") as temp:
            root = Path(temp) / "fixture repo with spaces"
            nested = root / "nested directory"
            bin_dir = root / "mock bin"
            nested.mkdir(parents=True)
            bin_dir.mkdir()
            (root / "scripts").mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            launcher = ROOT / "scripts/graphify-session-start.ps1"
            env = os.environ.copy()
            env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
            powershell = shutil.which("powershell")
            self.assertIsNotNone(powershell)
            assert powershell is not None

            missing_worker = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(launcher),
                ],
                check=False,
                cwd=nested,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(missing_worker.returncode, 0, missing_worker.stderr)
            self.assertIn("worker missing", missing_worker.stdout)

            (root / "scripts/graphify_local.py").write_text(
                "# synthetic worker\n", encoding="utf-8"
            )
            pythonless_path = [
                entry
                for entry in env["PATH"].split(os.pathsep)
                if not any(
                    (Path(entry) / f"python{suffix}").exists()
                    for suffix in (".exe", ".cmd", ".bat")
                )
            ]
            missing_python = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(launcher),
                ],
                check=False,
                cwd=nested,
                env={**env, "PATH": os.pathsep.join(pythonless_path)},
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(missing_python.returncode, 0, missing_python.stderr)
            self.assertIn("Python is missing", missing_python.stdout)

            (bin_dir / "python.cmd").write_text(
                "@echo off\r\necho synthetic failure\r\nexit /b 2\r\n", encoding="ascii"
            )
            failed_update = subprocess.run(
                [
                    powershell,
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(launcher),
                ],
                check=False,
                cwd=nested,
                env=env,
                capture_output=True,
                text=True,
                timeout=10,
            )
            self.assertEqual(failed_update.returncode, 0, failed_update.stderr)
            self.assertIn("update did not complete", failed_update.stdout)


if __name__ == "__main__":
    unittest.main()
