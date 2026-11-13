"""Comma decimal text shared by the canonical mappers and the legacy provider readers."""

from __future__ import annotations

import unittest
from enum import IntEnum
from pathlib import Path

from backend.activities import calendar_projection, duplicates, matching
from backend.activities.grouping import _as_number as activity_number
from backend.activities.workout_profile import _number as profile_number
from backend.activities.workout_text import _numeric as text_numeric
from backend.athlete.equipment import _valid_positive_number as equipment_positive
from backend.canonical.decimal_text import (
    comma_decimal_float,
    is_grouped_thousands,
    provider_number,
)
from backend.nutrition.food_database import _is_number as food_is_number
from backend.performance.current_metrics import as_number as metric_number
from backend.performance.form_drift import _is_positive as drift_positive
from backend.performance.grade_adjustment import _number as grade_number
from backend.performance.morning_battery import _number as battery_number
from backend.performance.personal_recovery import _number as recovery_number
from backend.performance.session_analysis import _number as analysis_number
from backend.performance.session_execution import _number as execution_number
from backend.performance.wellness import _as_number as wellness_number
from backend.planning import competitions, conflicts
from backend.providers.open_food_facts import _number as food_facts_number
from backend.providers.yazio import bounded_number as yazio_number
from backend.weather.adaptive import _as_number as weather_number

ROOT = Path(__file__).resolve().parents[1]
# Values recorded before #2110 merged the identical copies, per value:
# (finite float, provider number, bounded to 10, finite, finite and positive).
_INF = float("inf")


class _Three(IntEnum):
    """An int subclass: the type()-based finite float rejects it, isinstance does not."""

    THREE = 3


_NUMBER_TABLE: tuple[tuple[object, tuple[object, ...]], ...] = (
    (3, (3.0, 3, 3.0, True, True)),
    (2.5, (2.5, 2.5, 2.5, True, True)),
    (0, (0.0, 0, 0.0, True, False)),
    (-1.5, (-1.5, -1.5, None, True, False)),
    (True, (None, None, None, False, False)),
    (_INF, (None, None, None, False, False)),
    (float("nan"), (None, None, None, False, False)),
    ("4,5", (None, 4.5, None, False, False)),
    ("12", (None, 12, None, False, False)),
    (None, (None, None, None, False, False)),
    ("x", (None, None, None, False, False)),
    ("1,200", (None, None, None, False, False)),
    (_Three.THREE, (None, 3, 3.0, True, True)),
)
_FINITE_FLOAT = (
    profile_number,
    analysis_number,
    grade_number,
    recovery_number,
    execution_number,
)
_PROVIDER = (metric_number, battery_number)
_BOUNDED = (yazio_number, food_facts_number)
_FINITE = (text_numeric, food_is_number)
_POSITIVE = (equipment_positive, drift_positive)
_FIRST_PRESENT = (
    conflicts._first_present,
    competitions._first_present,
    duplicates._first_present,
    matching.first_present,
    calendar_projection._first_present,
)
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


class ProviderNumberTests(unittest.TestCase):
    def test_returns_whole_numbers_as_int_and_rounds_decimals(self) -> None:
        self.assertEqual(provider_number("80,0"), 80)
        self.assertIsInstance(provider_number(80.0), int)
        self.assertEqual(provider_number("80,4567"), 80.46)
        self.assertEqual(provider_number(1200), 1200)

    def test_rejects_ambiguous_invalid_and_non_finite_values(self) -> None:
        for value in ("1,200", None, "", "abc", "nan", "inf", float("inf")):
            with self.subTest(value=value):
                self.assertIsNone(provider_number(value))


class SharedNumberHelperTests(unittest.TestCase):
    def test_every_copy_gives_the_recorded_values(self) -> None:
        for value, expected in _NUMBER_TABLE:
            groups = (
                (_FINITE_FLOAT, expected[0], ()),
                (_PROVIDER, expected[1], ()),
                (_BOUNDED, expected[2], (10,)),
                (_FINITE, expected[3], ()),
                (_POSITIVE, expected[4], ()),
            )
            for helpers, result, extra in groups:
                for helper in helpers:
                    with self.subTest(helper=helper.__module__, value=value):
                        actual = helper(value, *extra)
                        self.assertEqual(result, actual)
                        self.assertIs(type(result), type(actual))

    def test_first_present_copies_skip_only_missing_and_empty_values(self) -> None:
        keys = ("a", "b", "c")
        cases: tuple[tuple[object, object], ...] = (
            ({"a": None, "b": "", "c": 0}, 0),
            ({"a": False, "b": 1}, False),
            ({"b": "x"}, "x"),
            ({}, None),
            ([("a", 1)], None),
            (None, None),
        )
        for helper in _FIRST_PRESENT:
            for item, expected in cases:
                with self.subTest(helper=helper.__module__, item=item):
                    self.assertIs(helper(item, keys), expected)


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
