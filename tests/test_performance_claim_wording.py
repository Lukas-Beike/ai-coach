"""Runtime sources must not make statements the M2 and M3 evidence cards forbid."""

import re
import unittest
from pathlib import Path

from performance_claim_support import claim_wording_violations

ROOT = Path(__file__).resolve().parents[1]
SOURCES = (
    "backend/performance/personal_recovery.py",
    "backend/performance/report_service.py",
    "backend/coach/tool_schemas.py",
    "backend/coach/context.py",
    "backend/coach/activity_read_tools.py",
    "public/analysis.js",
    "public/index.html",
)


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class ClaimWordingScanTests(unittest.TestCase):
    def test_runtime_sources_use_no_forbidden_recovery_wording(self):
        for path in SOURCES:
            with self.subTest(path=path):
                self.assertEqual([], claim_wording_violations(_read(path)))

    def test_recovery_labels_do_not_call_the_range_a_basis(self):
        self.assertIsNone(re.search(r"\bBasis\b", _read("public/analysis.js")))

    def test_scan_flags_forbidden_terms_and_unqualified_sri(self):
        for text in (
            "Schlafschuld",
            "Persönliche Normalbereiche",
            "Grüner Bereich",
            "the sleep debt grows",
            "clinical range",
            "sleep_regularity",
            "This is the SRI.",
            "Sleep Regularity Index of 80",
        ):
            with self.subTest(text=text):
                self.assertTrue(claim_wording_violations(text))

    def test_scan_allows_an_sri_only_in_a_denial(self):
        for text in (
            "it is not the Sleep Regularity Index",
            "ist kein Sleep Regularity Index.",
            "this is not the\n    Sleep Regularity Index.",
        ):
            with self.subTest(text=text):
                self.assertEqual([], claim_wording_violations(text))


if __name__ == "__main__":
    unittest.main()
