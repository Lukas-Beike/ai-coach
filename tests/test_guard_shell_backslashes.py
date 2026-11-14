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
            # Python "\\\\" is the doubled backslash the shell tool collapses.
            "python - <<'EOF'\ntext = text.replace('a\\\\nb', 'c')\nEOF",
            'python3.12 - <<"PY"\nprint("\\\\n")\nPY',
            "cat <<'EOF' | python -\nx = '\\\\'\nEOF",
            "node - <<EOF\nconsole.log('a\\\\b')\nEOF",
            "bash -s <<'EOF'\nprintf 'a\\\\nb'\nEOF",
            "python<<\\EOF\nx = '\\\\'\nEOF",
            "python - <<'END-PY'\nx = 'a\\\\b'\nEND-PY",
            "cat > scripts/x.py <<'EOF'\npattern = r'\\\\s+'\nEOF",
            "cat <<-'EOF' | tee notes.md\n\tC:\\\\Users\\x\n\tEOF",
            "py.exe - <<'EOF'\nprint('\\\\')\nEOF",
            # Inline programs and in-place edits with a doubled backslash.
            "python -c \"print('a\\\\b')\"",
            # Separators inside the quoted program do not split it (Gitar P2).
            "python -c \"import re; print(re.sub('\\\\s', '', s))\"",
            "python -c \"import re\nprint('a\\\\b')\"",
            "node -e 'a(); b(\"\\\\\")' | tail -1",
            "node --eval \"s.replace(/\\\\\\\\/g, '')\"",
            "perl -pi -e 's/\\\\s/x/' f.txt",
            "pwsh -Command \"'a\\\\b' -replace 'x'\"",
            "sed -i 's/(?:\\\\s+x\\\\b)/y/' scripts/issue_status.py",
            "cd repo && sed -i.bak 's/a\\\\b/c/' f",
            "sed --in-place 's/a\\\\b/c/' f",
            "sed -e 's/a\\\\b/c/' -i f",
        ):
            with self.subTest(command=command):
                result = run_hook(command)
                self.assertEqual(result.returncode, 2)
                self.assertIn(b"Write or Edit tool", result.stderr)

    def test_other_commands_pass(self) -> None:
        for command in (
            "git commit -q -F - <<'EOF'\nfix(x): subject\n\nBody text.\nEOF",
            "git commit -q -F - <<'EOF'\nbuild: block python -c and sed -i with \\\\\nEOF",
            "git commit -q -F - <<'EOF' >/dev/null\nfix: C:\\\\Users\nEOF",
            "python - <<'EOF'\nprint('a single \\n stays')\nEOF",
            "cat <<'EOF'\nC:\\\\Users\\x shown, not written\nEOF",
            "python -I scripts/x.py --pattern 'a\\\\b'",
            "sed -i 's/a/b/' f && grep -E 'a\\\\b' g",
            "python -I -c \"s = '<<EOF'\"\necho done",
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
        for body in (b"not json", b"[]", b'{"tool_input": "x"}'):
            with self.subTest(body=body):
                result = subprocess.run(
                    [sys.executable, str(HOOK)],
                    input=body,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
