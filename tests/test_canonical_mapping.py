"""Mapping issues, mapping results and number coercion for provider mappers."""

from __future__ import annotations

import math
import unittest
from dataclasses import FrozenInstanceError
from decimal import Decimal
from typing import Any

from backend.canonical.mapping import (
    MAX_ISSUE_TEXT_LENGTH,
    MAX_NUMBER_TEXT_LENGTH,
    IssueReason,
    MappingIssue,
    MappingResult,
    coerce_comma_decimal_number,
    coerce_number,
)


def untyped(value: object) -> Any:
    """Pass deliberately wrong types through static checks."""
    return value


class IssueReasonTests(unittest.TestCase):
    def test_reason_values_are_stable_snake_case_text(self) -> None:
        self.assertEqual(
            {
                "missing",
                "invalid_type",
                "invalid_number",
                "out_of_range",
                "unknown_value",
                "unsupported",
            },
            {reason.value for reason in IssueReason},
        )


class MappingIssueTests(unittest.TestCase):
    def test_accepts_identifiers_and_optional_record_reference(self) -> None:
        issue = MappingIssue("fake-activity-1", "avg_hr", IssueReason.OUT_OF_RANGE)

        self.assertEqual("fake-activity-1", issue.record_ref)
        self.assertEqual("avg_hr", issue.field)
        self.assertIs(IssueReason.OUT_OF_RANGE, issue.reason)
        self.assertIsNone(MappingIssue(None, "name", IssueReason.MISSING).record_ref)

    def test_is_immutable_and_slotted(self) -> None:
        issue = MappingIssue(None, "name", IssueReason.MISSING)

        self.assertFalse(hasattr(issue, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            issue.field = "other"  # type: ignore[misc]

    def test_rejects_reason_given_as_text(self) -> None:
        with self.assertRaisesRegex(TypeError, "reason must be a IssueReason"):
            MappingIssue(None, "name", untyped("missing"))

    def test_rejects_blank_or_non_text_field(self) -> None:
        with self.assertRaisesRegex(ValueError, "field must be non-empty text"):
            MappingIssue(None, "   ", IssueReason.MISSING)
        with self.assertRaisesRegex(TypeError, "field must be text"):
            MappingIssue(None, untyped(3), IssueReason.MISSING)

    def test_rejects_blank_or_non_text_record_reference(self) -> None:
        with self.assertRaisesRegex(ValueError, "record_ref must be non-empty"):
            MappingIssue("", "name", IssueReason.MISSING)
        with self.assertRaisesRegex(TypeError, "record_ref must be text"):
            MappingIssue(untyped(7), "name", IssueReason.MISSING)

    def test_bounds_record_reference_and_field_length(self) -> None:
        too_long = "x" * (MAX_ISSUE_TEXT_LENGTH + 1)
        with self.assertRaisesRegex(ValueError, "record_ref must be at most 200"):
            MappingIssue(too_long, "name", IssueReason.MISSING)
        with self.assertRaisesRegex(ValueError, "field must be at most 200"):
            MappingIssue(None, too_long, IssueReason.MISSING)


class MappingResultTests(unittest.TestCase):
    def test_defaults_to_no_records_and_no_issues(self) -> None:
        result: MappingResult[int] = MappingResult()

        self.assertEqual((), result.records)
        self.assertEqual((), result.issues)

    def test_holds_records_and_issues_as_tuples(self) -> None:
        issue = MappingIssue("fake-1", "load", IssueReason.INVALID_NUMBER)
        result = MappingResult(records=(1, 2), issues=(issue,))

        self.assertEqual((1, 2), result.records)
        self.assertEqual((issue,), result.issues)

    def test_is_immutable(self) -> None:
        result: MappingResult[int] = MappingResult()

        with self.assertRaises(FrozenInstanceError):
            result.records = (1,)  # type: ignore[misc]

    def test_rejects_lists_instead_of_tuples(self) -> None:
        with self.assertRaisesRegex(TypeError, "records must be a tuple"):
            MappingResult(records=untyped([1]))
        with self.assertRaisesRegex(TypeError, "issues must be a tuple"):
            MappingResult(issues=untyped([]))

    def test_rejects_non_issue_entries(self) -> None:
        with self.assertRaisesRegex(TypeError, "issues must be a MappingIssue"):
            MappingResult(issues=untyped(("missing field",)))


class CoerceNumberTests(unittest.TestCase):
    def test_accepts_finite_numbers_and_returns_floats(self) -> None:
        cases: tuple[tuple[object, float], ...] = (
            (72, 72.0),
            (72.5, 72.5),
            (-3, -3.0),
            (0, 0.0),
            (10**300, 1e300),
        )
        for value, expected in cases:
            with self.subTest(value=value):
                result = coerce_number(value)
                self.assertIsInstance(result, float)
                self.assertEqual(expected, result)

    def test_accepts_dot_decimal_text_with_surrounding_whitespace(self) -> None:
        cases: tuple[tuple[str, float], ...] = (
            ("72.5", 72.5),
            ("  72.5  ", 72.5),
            ("72", 72.0),
            ("-0.5", -0.5),
            ("+1.25", 1.25),
            (".5", 0.5),
            ("5.", 5.0),
            ("1e3", 1000.0),
            ("1E-2", 0.01),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(expected, coerce_number(text))

    def test_rejects_comma_decimal_and_python_only_spellings(self) -> None:
        for text in ("1,5", "1_000", "1.0.0", "0x10", "١٢"):
            with self.subTest(text=text):
                self.assertIsNone(coerce_number(text))

    def test_rejects_blank_text_and_words(self) -> None:
        for text in ("", "   ", "abc", "-", "."):
            with self.subTest(text=text):
                self.assertIsNone(coerce_number(text))

    def test_rejects_non_finite_text_and_numbers(self) -> None:
        for text in ("nan", "inf", "-Infinity", "1e400"):
            with self.subTest(text=text):
                self.assertIsNone(coerce_number(text))
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value):
                self.assertIsNone(coerce_number(value))

    def test_rejects_integers_too_large_for_float(self) -> None:
        self.assertIsNone(coerce_number(10**400))

    def test_rejects_booleans_even_though_they_are_integers(self) -> None:
        self.assertIsNone(coerce_number(True))
        self.assertIsNone(coerce_number(False))

    def test_rejects_none_bytes_containers_and_other_numeric_types(self) -> None:
        for value in (None, b"1.5", [1.5], {"value": 1.5}, Decimal("1.5")):
            with self.subTest(value=repr(value)):
                self.assertIsNone(coerce_number(untyped(value)))

    def test_rejects_text_longer_than_the_bound(self) -> None:
        self.assertIsNone(coerce_number("1" * (MAX_NUMBER_TEXT_LENGTH + 1)))
        self.assertIsNone(coerce_number("1" * 65 + ".0"))


class CommaDecimalNumberTests(unittest.TestCase):
    def test_comma_text_reads_the_comma_as_the_decimal_mark(self) -> None:
        cases: tuple[tuple[str, float], ...] = (
            ("80,4", 80.4),
            ("58,2", 58.2),
            (" 70,5 ", 70.5),
            ("-0,5", -0.5),
            ("1,5e1", 15.0),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(expected, coerce_comma_decimal_number(text))

    def test_text_that_is_still_malformed_after_the_swap_is_rejected(self) -> None:
        for text in ("1,2,3", ",", "", "abc", "nan", "1_0,5", "1,5x", "1" * 65):
            with self.subTest(text=text):
                self.assertIsNone(coerce_comma_decimal_number(text))

    def test_other_values_follow_coerce_number(self) -> None:
        for value in (72, 72.5, True, None, math.nan, b"1,5", [1.5]):
            with self.subTest(value=repr(value)[:40]):
                self.assertEqual(
                    coerce_comma_decimal_number(untyped(value)),
                    coerce_number(untyped(value)),
                )


if __name__ == "__main__":
    unittest.main()
