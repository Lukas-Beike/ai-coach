"""Committed text files use LF only; a stray CR breaks edit helpers and diffs."""

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def committed_files_with_carriage_returns(root):
    """List indexed text files (binary files excluded) whose blob holds a CR."""
    result = subprocess.run(
        ["git", "grep", "--cached", "-I", "-l", "-P", r"\r"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        raise RuntimeError(result.stderr)
    return result.stdout.split()


class LineEndingTests(unittest.TestCase):
    def test_committed_text_files_have_no_carriage_returns(self):
        if not (ROOT / ".git").exists():
            self.skipTest("Not a git checkout")
        self.assertEqual(committed_files_with_carriage_returns(ROOT), [])

    def test_detector_flags_a_seeded_lone_carriage_return(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            subprocess.run(["git", "init", "-q"], cwd=root, check=True)
            (root / "good.js").write_bytes(b"a\nb\n")
            (root / "bad.js").write_bytes(b"a\rb\n")
            (root / "image.png").write_bytes(b"\x89PNG\0\r\n")
            subprocess.run(
                ["git", "-c", "core.autocrlf=false", "add", "."], cwd=root, check=True
            )
            self.assertEqual(committed_files_with_carriage_returns(root), ["bad.js"])

    def test_gitattributes_normalizes_to_lf(self):
        text = (ROOT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("* text=auto eol=lf", text.splitlines())


if __name__ == "__main__":
    unittest.main()
