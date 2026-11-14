"""The agent shell hook blocks edits whose backslashes the Bash tool collapses (#2793)."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "scripts" / "hooks" / "guard_shell_backslashes.py"


def run_hook(command: str, tool: str = "Bash") -> subprocess.CompletedProcess:
    body = json.dumps({"tool_name": tool, "tool_input": {"command": command}})
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=body.encode("utf-8"),
        capture_output=True,
        check=False,
    )


class GuardShellBackslashesTests(unittest.TestCase):
    def test_backslash_edits_are_blocked_with_the_hint(self) -> None:
        for command in (
            "python - <<'EOF'\ntext = text.replace('a\\\\nb', 'c')\nEOF",
            'python3 - <<"PY"\nprint("\\n")\nPY',
            "cat <<'EOF' | python -\nx = '\\\\'\nEOF",
            "node - <<EOF\nconsole.log('a\\\\b')\nEOF",
            "bash -s <<'EOF'\nprintf 'a\\nb'\nEOF",
            "cat > scripts/x.py <<'EOF'\npattern = r'\\s+'\nEOF",
            "cat <<-'EOF' | tee notes.md\n\tC:\\Users\\x\n\tEOF",
            "py.exe - <<'EOF'\nprint('\\\\')",
            # One-liners and in-place edits with a doubled backslash.
            "python -c \"print('a\\\\\\\\b')\"",
            "node -e \"s.replace(/\\\\\\\\/g, '')\"",
            "perl -pi -e 's/\\\\\\\\s/x/' f.txt",
            "sed -i 's/(?:\\\\s+x\\\\b)/y/' scripts/issue_status.py",
            "cd repo && sed -i.bak 's/a\\\\\\\\b/c/' f",
        ):
            with self.subTest(command=command):
                result = run_hook(command)
                self.assertEqual(result.returncode, 2)
                self.assertIn(b"Write or Edit tool", result.stderr)

    def test_other_commands_pass(self) -> None:
        for command in (
            "git commit -q -F - <<'EOF'\nfix(x): subject\n\nBody text.\nEOF",
            "python - <<'EOF'\nprint('no backslash here')\nEOF",
            "cat <<'EOF'\nC:\\Users\\x shown, not written\nEOF",
            "sed -n 's/a\\\\\\\\b/c/p' f.txt",
            "sed -i 's/tests +12 \\/ -3/tests +11 \\/ -3/' pr.md",
            "grep -E 'a\\\\\\\\|b' f.txt",
            "python scripts/issue_status.py 2799",
            "printf '%s\\n' line >> notes.md",
            "python -m unittest tests.test_x 2>&1 | tail -3",
        ):
            with self.subTest(command=command):
                self.assertEqual(run_hook(command).returncode, 0)

    def test_only_the_bash_tool_is_checked(self) -> None:
        command = "python -c \"print('a\\\\\\\\b')\""
        self.assertEqual(run_hook(command, tool="PowerShell").returncode, 0)

    def test_unreadable_input_is_blocked(self) -> None:
        result = subprocess.run(
            [sys.executable, str(HOOK)],
            input=b"not json",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
