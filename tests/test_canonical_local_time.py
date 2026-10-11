"""Local wall-clock rules for provider datetimes around Europe/Berlin DST changes."""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.local_time import (
    MAX_PROVIDER_DATETIME_LENGTH,
    local_date,
    localize_wall_time,
    parse_provider_datetime,
)

BERLIN = ZoneInfo("Europe/Berlin")
NEW_YORK = ZoneInfo("America/New_York")
CET = timedelta(hours=1)
CEST = timedelta(hours=2)


def untyped(value: object) -> Any:
    """Pass deliberately wrong types through static checks."""
    return value


def naive(text: str) -> datetime:
    return datetime.fromisoformat(text)


class LocalizeWallTimeTests(unittest.TestCase):
    def test_naive_wall_time_takes_the_zone_offset(self) -> None:
        result = localize_wall_time(naive("2026-03-01T07:30:00"), BERLIN)

        self.assertIs(BERLIN, result.tzinfo)
        self.assertEqual(CET, result.utcoffset())
        self.assertEqual("2026-03-01T07:30:00", result.replace(tzinfo=None).isoformat())

    def test_aware_input_is_returned_unchanged(self) -> None:
        value = datetime(2026, 3, 1, 7, 30, tzinfo=UTC)

        self.assertIs(value, localize_wall_time(value, BERLIN))

    def test_spring_gap_moves_forward_under_the_pre_transition_offset(self) -> None:
        # 2026-03-29: clocks jump from 02:00 CET straight to 03:00 CEST.
        cases = (
            ("2026-03-29T01:59:00", "2026-03-29T01:59:00", CET),
            ("2026-03-29T02:00:00", "2026-03-29T03:00:00", CEST),
            ("2026-03-29T02:30:00", "2026-03-29T03:30:00", CEST),
            ("2026-03-29T02:59:00", "2026-03-29T03:59:00", CEST),
            ("2026-03-29T03:00:00", "2026-03-29T03:00:00", CEST),
            ("2026-03-29T03:01:00", "2026-03-29T03:01:00", CEST),
        )
        for wall, expected_wall, expected_offset in cases:
            with self.subTest(wall=wall):
                result = localize_wall_time(naive(wall), BERLIN)
                self.assertEqual(expected_wall, result.replace(tzinfo=None).isoformat())
                self.assertEqual(expected_offset, result.utcoffset())

    def test_autumn_overlap_takes_the_first_occurrence(self) -> None:
        # 2026-10-25: 03:00 CEST falls back to 02:00 CET, so 02:00-02:59 repeats.
        cases = (
            ("2026-10-25T01:59:00", CEST),
            ("2026-10-25T02:00:00", CEST),
            ("2026-10-25T02:30:00", CEST),
            ("2026-10-25T02:59:00", CEST),
            ("2026-10-25T03:00:00", CET),
            ("2026-10-25T03:01:00", CET),
        )
        for wall, expected_offset in cases:
            with self.subTest(wall=wall):
                result = localize_wall_time(naive(wall), BERLIN)
                self.assertEqual(expected_offset, result.utcoffset())
                self.assertEqual(wall, result.replace(tzinfo=None).isoformat())

    def test_fold_on_naive_input_is_ignored(self) -> None:
        second_occurrence = naive("2026-10-25T02:30:00").replace(fold=1)

        result = localize_wall_time(second_occurrence, BERLIN)

        self.assertEqual(CEST, result.utcoffset())
        self.assertEqual(0, result.fold)

    def test_localised_gap_time_names_the_intended_instant(self) -> None:
        result = localize_wall_time(naive("2026-03-29T02:30:00"), BERLIN)

        self.assertEqual(datetime(2026, 3, 29, 1, 30, tzinfo=UTC), result)


class ParseProviderDatetimeTests(unittest.TestCase):
    def test_t_and_space_separators_are_equivalent(self) -> None:
        expected = datetime(2026, 3, 29, 3, 30, tzinfo=BERLIN)

        for text in ("2026-03-29T02:30:00", "2026-03-29 02:30:00"):
            with self.subTest(text=text):
                result = parse_provider_datetime(text, BERLIN)
                assert result is not None
                self.assertEqual(expected, result)
                self.assertEqual(CEST, result.utcoffset())

    def test_trailing_z_is_utc(self) -> None:
        for text in ("2026-10-08T07:15:00Z", "2026-10-08 07:15:00Z"):
            with self.subTest(text=text):
                result = parse_provider_datetime(text, BERLIN)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(timedelta(0), result.utcoffset())
                self.assertEqual(datetime(2026, 10, 8, 7, 15, tzinfo=UTC), result)

    def test_explicit_offset_is_kept_as_sent(self) -> None:
        result = parse_provider_datetime("2026-10-08T07:15:00+02:00", BERLIN)

        assert result is not None
        self.assertEqual(CEST, result.utcoffset())
        self.assertEqual(7, result.hour)
        self.assertEqual(datetime(2026, 10, 8, 5, 15, tzinfo=UTC), result)

    def test_fractional_seconds_are_accepted(self) -> None:
        result = parse_provider_datetime("2026-10-08T07:15:00.250Z", BERLIN)

        assert result is not None
        self.assertEqual(250_000, result.microsecond)

    def test_naive_text_is_localised_at_the_fixture_boundaries(self) -> None:
        cases = (
            ("2026-03-29T01:59:00", CET),
            ("2026-03-29T03:01:00", CEST),
            ("2026-10-25T01:59:00", CEST),
            ("2026-10-25T03:01:00", CET),
        )
        for text, expected_offset in cases:
            with self.subTest(text=text):
                result = parse_provider_datetime(text, BERLIN)
                assert result is not None
                self.assertEqual(expected_offset, result.utcoffset())

    def test_surrounding_whitespace_is_ignored(self) -> None:
        result = parse_provider_datetime("  2026-10-08T07:15:00Z \n", BERLIN)

        self.assertEqual(datetime(2026, 10, 8, 7, 15, tzinfo=UTC), result)

    def test_malformed_or_date_only_text_returns_none(self) -> None:
        cases = (
            "",
            "   ",
            "not a date",
            "2026-10-08",
            "2026-10-08x07:15:00",
            "2026-10-08T",
            "2026-10-08T25:00:00",
            "2026-13-01T00:00:00",
            "2026-10-08T07:15:00+25:00",
            "1" * (MAX_PROVIDER_DATETIME_LENGTH + 1),
            "2026-10-08T07:15:00" + "0" * MAX_PROVIDER_DATETIME_LENGTH,
        )
        for text in cases:
            with self.subTest(text=text[:40]):
                self.assertIsNone(parse_provider_datetime(text, BERLIN))

    def test_non_text_input_returns_none(self) -> None:
        values = (
            None,
            12,
            1.5,
            True,
            b"2026-10-08T07:15:00Z",
            datetime(2026, 10, 8, 7, 15, tzinfo=UTC),
            date(2026, 10, 8),
        )
        for value in values:
            with self.subTest(value=repr(value)[:40]):
                self.assertIsNone(parse_provider_datetime(untyped(value), BERLIN))

    def test_unrepresentable_naive_time_returns_none_instead_of_raising(self) -> None:
        # Localising year 1 under a positive LMT offset leaves datetime's range.
        self.assertIsNone(parse_provider_datetime("0001-01-01T00:00:00", BERLIN))

    def test_aware_extreme_values_are_kept_when_the_zone_can_express_them(self) -> None:
        result = parse_provider_datetime("0001-01-01T00:00:00+00:00", BERLIN)

        self.assertEqual(datetime(1, 1, 1, tzinfo=UTC), result)

    def test_instants_outside_the_range_of_the_zone_return_none(self) -> None:
        # Converting these instants into the zone steps outside datetime's range.
        cases = (
            ("0001-01-01T00:00:00+00:00", NEW_YORK),
            ("9999-12-31T23:59:59-05:00", BERLIN),
            ("9999-12-31T23:59:59-05:00", NEW_YORK),
        )
        for text, zone in cases:
            with self.subTest(text=text, zone=str(zone)):
                self.assertIsNone(parse_provider_datetime(text, zone))

    def test_every_returned_value_is_readable_as_a_local_date(self) -> None:
        texts = (
            "2026-03-29T02:30:00",
            "2026-10-25T02:30:00Z",
            "0001-01-01T00:00:00+00:00",
            "9999-12-31T23:59:59-05:00",
            "9999-12-31T23:59:59+14:00",
        )
        for text in texts:
            for zone in (BERLIN, NEW_YORK, UTC):
                with self.subTest(text=text, zone=str(zone)):
                    parsed = parse_provider_datetime(text, zone)
                    if parsed is not None:
                        self.assertIsInstance(local_date(parsed, zone), date)


class LocalDateTests(unittest.TestCase):
    def test_reads_the_calendar_date_in_the_zone_not_in_utc(self) -> None:
        # 23:30 UTC on 7 October is 01:30 on 8 October in Berlin.
        value = datetime(2026, 10, 7, 23, 30, tzinfo=UTC)

        self.assertEqual(date(2026, 10, 8), local_date(value, BERLIN))

    def test_rolls_over_at_local_midnight(self) -> None:
        cases = (
            (datetime(2026, 10, 7, 21, 59, 59, tzinfo=UTC), date(2026, 10, 7)),
            (datetime(2026, 10, 7, 22, 0, tzinfo=UTC), date(2026, 10, 8)),
            (datetime(2026, 3, 28, 22, 59, 59, tzinfo=UTC), date(2026, 3, 28)),
            (datetime(2026, 3, 28, 23, 0, tzinfo=UTC), date(2026, 3, 29)),
        )
        for value, expected in cases:
            with self.subTest(value=value.isoformat()):
                self.assertEqual(expected, local_date(value, BERLIN))

    def test_parsed_gap_time_keeps_its_local_calendar_date(self) -> None:
        parsed = parse_provider_datetime("2026-03-29T02:30:00", BERLIN)
        assert parsed is not None

        self.assertEqual(date(2026, 3, 29), local_date(parsed, BERLIN))

    def test_naive_input_is_a_programming_error(self) -> None:
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            local_date(naive("2026-10-08T07:15:00"), BERLIN)


if __name__ == "__main__":
    unittest.main()
