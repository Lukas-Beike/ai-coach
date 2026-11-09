"""Fail when the documented schema and export format versions lag the code."""

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.backup.export import PRIVACY_EXPORT_FORMAT_VERSION
from backend.db.schema import CURRENT_SCHEMA_VERSION

# (document, pattern for the documented current schema version)
SCHEMA_CLAIMS = (
    ("README.md", r"the current schema is v(\d+)"),
    ("docs/schema-history.md", r"The current schema is version (\d+)"),
    ("docs/operations.md", r"the current schema \(version (\d+)\)"),
)
EXPORT_CLAIMS = (("docs/operations.md", r"Export format version (\d+)"),)


def documented(path: str, pattern: str) -> list[int]:
    text = (ROOT / path).read_text(encoding="utf-8")
    return [int(value) for value in re.findall(pattern, text)]


class DocsVersionDriftTest(unittest.TestCase):
    def assert_claims(self, claims, expected: int) -> None:
        for path, pattern in claims:
            with self.subTest(path=path):
                values = documented(path, pattern)
                self.assertTrue(
                    values, f"{path} no longer states the version ({pattern})"
                )
                self.assertEqual(set(values), {expected}, path)

    def test_documented_schema_version_matches_code(self) -> None:
        self.assert_claims(SCHEMA_CLAIMS, CURRENT_SCHEMA_VERSION)

    def test_documented_export_format_version_matches_code(self) -> None:
        self.assert_claims(EXPORT_CLAIMS, PRIVACY_EXPORT_FORMAT_VERSION)

    def test_schema_history_describes_every_version_from_the_baseline(self) -> None:
        text = (ROOT / "docs/schema-history.md").read_text(encoding="utf-8")
        for version in range(22, CURRENT_SCHEMA_VERSION + 1):
            with self.subTest(version=version):
                self.assertRegex(
                    text, rf"[Vv]ersion {version} (adds|records|stores|gives)"
                )


if __name__ == "__main__":
    unittest.main()
