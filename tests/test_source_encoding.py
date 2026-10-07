"""Regression tests for source text encoding."""

import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATHS = (
    "server.py",
    "backend/**/*.py",
    "public/**/*.js",
    "public/**/*.html",
    "public/**/*.css",
    "e2e/**/*.js",
)
MOJIBAKE_MARKERS = ("Ã", "â€")
LITERAL_UNICODE_ESCAPE = "\\\\u00"


def tracked_source_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--", *SOURCE_PATHS],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [ROOT / path for path in result.stdout.splitlines()]


class SourceEncodingTests(unittest.TestCase):
    def test_tracked_source_has_no_mojibake_or_literal_unicode_escapes(self):
        failures = []
        for path in tracked_source_files():
            source = path.read_text(encoding="utf-8")
            for marker in MOJIBAKE_MARKERS:
                if marker in source:
                    failures.append(f"{path.relative_to(ROOT)} contains {marker!r}")
            if LITERAL_UNICODE_ESCAPE in source:
                failures.append(
                    f"{path.relative_to(ROOT)} contains a literal \\u00 escape"
                )
        self.assertEqual(failures, [])
