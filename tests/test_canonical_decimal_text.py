"""Comma decimal text shared by the canonical mappers and the legacy provider readers."""

from __future__ import annotations

import unittest
from pathlib import Path

from backend.activities.grouping import _as_number as activity_number
from backend.canonical.decimal_text import comma_decimal_float, is_grouped_thousands
from backend.performance.wellness import _as_number as wellness_number
from backend.weather.adaptive import _as_number as weather_number

ROOT = Path(__file__).resolve().parents[1]
# Provider-facing legacy readers that must parse comma text through the helper.
PROVIDER_READER_PACKAGES = ("activities", "performance", "weather")


class GroupedThousandsTests(unittest.TestCase):
    def test_comma_with_three_digits_after_a_short_integer_is_ambiguous(self) -> None:
        for text in ("1,200", "12,345", "999,000", "+1,000", "-1,200", " 1,200 "):
            with self.subTest(text=text):
                self.assertTrue(is_grouped_thousands(text))
                with self.assertRaises(ValueError):
                    comma_decimal_float(text)

    def test_other_comma_text_is_a_decimal(self) -> None:
        cases: tuple[tuple[str, float], ...] = (
            ("80,4", 80.4),
            ("0,500", 0.5),
            ("1,20", 1.2),
            ("1,2000", 1.2),
            ("1000,500", 1000.5),
            (" 70,5 ", 70.5),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertFalse(is_grouped_thousands(text))
                self.assertEqual(comma_decimal_float(text), expected)

    def test_values_without_a_comma_keep_float_parsing(self) -> None:
        self.assertEqual(comma_decimal_float(1200), 1200.0)
        self.assertEqual(comma_decimal_float("1200"), 1200.0)
        self.assertEqual(comma_decimal_float(80.4), 80.4)
        for value in (None, "abc", "1,2,3", ""):
            with self.subTest(value=value), self.assertRaises(ValueError):
                comma_decimal_float(value)


class LegacyReaderTests(unittest.TestCase):
    def test_provider_readers_reject_grouped_thousands(self) -> None:
        for reader in (wellness_number, activity_number, weather_number):
            with self.subTest(reader=reader.__module__):
                self.assertIsNone(reader("1,200"))
                self.assertEqual(reader("80,5"), 80.5)

    def test_provider_readers_do_not_swap_commas_themselves(self) -> None:
        offenders = [
            str(path.relative_to(ROOT))
            for package in PROVIDER_READER_PACKAGES
            for path in sorted((ROOT / "backend" / package).rglob("*.py"))
            if 'replace(",", ".")' in path.read_text(encoding="utf-8")
        ]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
