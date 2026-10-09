import unittest
from datetime import date

from backend.athlete.local_date import LocalDate


class LocalDateTests(unittest.TestCase):
    def test_accepts_valid_date_and_is_immutable(self):
        value = LocalDate.parse("2026-10-08")
        self.assertEqual(value.isoformat(), "2026-10-08")
        self.assertEqual(value.to_date(), date(2026, 10, 8))
        with self.assertRaises((AttributeError, TypeError)):
            value.value = date(2026, 1, 1)

    def test_rejects_invalid_and_truncated_dates(self):
        for value in ("2026-02-29", "2026-1-01", "2026-02-30", "2026-02-01junk"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                LocalDate.parse(value)

    def test_accepts_leap_day(self):
        self.assertEqual(LocalDate.parse("2024-02-29").isoformat(), "2024-02-29")

    def test_accepts_full_iso_datetimes_for_existing_provider_inputs(self):
        self.assertEqual(
            LocalDate.parse("2026-10-08T23:15:00Z").isoformat(), "2026-10-08"
        )
        self.assertEqual(
            LocalDate.parse("2026-10-08T23:15:00+02:00").isoformat(), "2026-10-08"
        )
