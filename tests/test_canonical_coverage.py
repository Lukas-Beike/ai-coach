"""Provider coverage summaries and mapping issue counting."""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from types import MappingProxyType
from typing import Any

from backend.canonical.coverage import ProviderCoverage, count_issues
from backend.canonical.mapping import IssueReason, MappingIssue
from backend.canonical.vocabulary import ProviderId

AWARE_TIME = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
# Deliberately naive: the validation under test must reject it.
NAIVE_TIME = datetime(2026, 1, 2, 3, 4)  # noqa: DTZ001


def untyped(value: object) -> Any:
    """Pass deliberately wrong types through static checks."""
    return value


def make_coverage(**overrides: object) -> ProviderCoverage:
    fields: dict[str, object] = {
        "provider": ProviderId.INTERVALS,
        "retrieved_at": AWARE_TIME,
        "activity_count": 2,
        "observation_count": 3,
        "issue_counts": {IssueReason.MISSING: 1},
        "first_observed_on": date(2026, 1, 1),
        "last_observed_on": date(2026, 1, 31),
    }
    fields.update(overrides)
    return ProviderCoverage(**fields)  # type: ignore[arg-type]


class ProviderCoverageValidTests(unittest.TestCase):
    def test_accepts_full_summary(self) -> None:
        coverage = make_coverage()

        self.assertIs(ProviderId.INTERVALS, coverage.provider)
        self.assertEqual(AWARE_TIME, coverage.retrieved_at)
        self.assertEqual(2, coverage.activity_count)
        self.assertEqual(3, coverage.observation_count)
        self.assertEqual(1, coverage.issue_counts[IssueReason.MISSING])
        self.assertEqual(date(2026, 1, 1), coverage.first_observed_on)
        self.assertEqual(date(2026, 1, 31), coverage.last_observed_on)

    def test_accepts_empty_summary_without_dates_or_retrieval_time(self) -> None:
        coverage = make_coverage(
            retrieved_at=None,
            activity_count=0,
            observation_count=0,
            issue_counts={},
            first_observed_on=None,
            last_observed_on=None,
        )

        self.assertIsNone(coverage.retrieved_at)
        self.assertEqual(0, coverage.activity_count)
        self.assertEqual(0, len(coverage.issue_counts))
        self.assertIsNone(coverage.first_observed_on)

    def test_accepts_single_day_range(self) -> None:
        day = date(2026, 3, 4)
        coverage = make_coverage(first_observed_on=day, last_observed_on=day)

        self.assertEqual(day, coverage.first_observed_on)
        self.assertEqual(day, coverage.last_observed_on)

    def test_is_immutable(self) -> None:
        coverage = make_coverage()

        with self.assertRaises(FrozenInstanceError):
            coverage.activity_count = 9  # type: ignore[misc]


class ProviderCoverageValidationTests(unittest.TestCase):
    def test_rejects_invalid_provider(self) -> None:
        with self.assertRaisesRegex(TypeError, "provider must be a ProviderId"):
            make_coverage(provider="intervals")

    def test_rejects_invalid_retrieval_time(self) -> None:
        with self.assertRaisesRegex(TypeError, "retrieved_at must be a datetime"):
            make_coverage(retrieved_at=untyped("2026-01-02"))
        with self.assertRaisesRegex(ValueError, "retrieved_at must be timezone-aware"):
            make_coverage(retrieved_at=NAIVE_TIME)

    def test_rejects_invalid_counters(self) -> None:
        cases: tuple[tuple[str, object, type[Exception], str], ...] = (
            ("activity_count", True, TypeError, "activity_count must be an integer"),
            ("activity_count", 1.0, TypeError, "activity_count must be an integer"),
            ("activity_count", "2", TypeError, "activity_count must be an integer"),
            ("activity_count", -1, ValueError, "activity_count must be non-negative"),
            (
                "observation_count",
                False,
                TypeError,
                "observation_count must be an integer",
            ),
            (
                "observation_count",
                -4,
                ValueError,
                "observation_count must be non-negative",
            ),
        )
        for field, value, error, message in cases:
            with (
                self.subTest(field=field, value=value),
                self.assertRaisesRegex(error, message),
            ):
                make_coverage(**{field: value})

    def test_rejects_issue_counts_that_are_not_a_mapping(self) -> None:
        with self.assertRaisesRegex(TypeError, "issue_counts must be a mapping"):
            make_coverage(issue_counts=untyped([IssueReason.MISSING]))

    def test_rejects_issue_count_keys_that_are_not_reasons(self) -> None:
        with self.assertRaisesRegex(
            TypeError, "issue_counts key must be a IssueReason"
        ):
            make_coverage(issue_counts=untyped({"missing": 1}))

    def test_rejects_invalid_issue_count_values(self) -> None:
        with self.assertRaisesRegex(TypeError, "issue_counts value must be an integer"):
            make_coverage(issue_counts=untyped({IssueReason.MISSING: True}))
        with self.assertRaisesRegex(
            ValueError, "issue_counts value must be non-negative"
        ):
            make_coverage(issue_counts={IssueReason.MISSING: -1})

    def test_rejects_dates_given_as_datetimes(self) -> None:
        with self.assertRaisesRegex(TypeError, "first_observed_on must be a date"):
            make_coverage(first_observed_on=untyped(AWARE_TIME))
        with self.assertRaisesRegex(TypeError, "last_observed_on must be a date"):
            make_coverage(last_observed_on=untyped(AWARE_TIME))

    def test_rejects_only_one_observed_date(self) -> None:
        message = "must both be set or both be None"
        with self.assertRaisesRegex(ValueError, message):
            make_coverage(last_observed_on=None)
        with self.assertRaisesRegex(ValueError, message):
            make_coverage(first_observed_on=None)

    def test_rejects_range_that_ends_before_it_starts(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be after"):
            make_coverage(
                first_observed_on=date(2026, 2, 1),
                last_observed_on=date(2026, 1, 31),
            )


class ProviderCoverageIssueCountTests(unittest.TestCase):
    def test_copies_issue_counts_into_read_only_mapping(self) -> None:
        source: dict[IssueReason, int] = {IssueReason.INVALID_NUMBER: 2}
        coverage = make_coverage(issue_counts=source)
        source[IssueReason.INVALID_NUMBER] = 99

        self.assertIsInstance(coverage.issue_counts, MappingProxyType)
        self.assertEqual({IssueReason.INVALID_NUMBER: 2}, dict(coverage.issue_counts))
        with self.assertRaises(TypeError):
            coverage.issue_counts[IssueReason.MISSING] = 1  # type: ignore[index]

    def test_accepts_any_mapping_of_reasons(self) -> None:
        counts = MappingProxyType({IssueReason.UNSUPPORTED: 4})
        coverage = make_coverage(issue_counts=counts)

        self.assertEqual({IssueReason.UNSUPPORTED: 4}, dict(coverage.issue_counts))


class CountIssuesTests(unittest.TestCase):
    def test_empty_input_yields_zero_for_every_reason_in_definition_order(self) -> None:
        counts = count_issues([])

        self.assertIsInstance(counts, MappingProxyType)
        self.assertEqual(list(IssueReason), list(counts))
        self.assertEqual({reason: 0 for reason in IssueReason}, dict(counts))

    def test_tallies_reasons_and_discards_field_names_and_record_refs(self) -> None:
        issues = (
            MappingIssue("fake-activity-1", "avg_hr", IssueReason.OUT_OF_RANGE),
            MappingIssue(None, "name", IssueReason.MISSING),
            MappingIssue("fake-activity-2", "load", IssueReason.OUT_OF_RANGE),
        )

        counts = count_issues(issues)

        self.assertEqual(list(IssueReason), list(counts))
        self.assertEqual(2, counts[IssueReason.OUT_OF_RANGE])
        self.assertEqual(1, counts[IssueReason.MISSING])
        self.assertEqual(0, counts[IssueReason.UNSUPPORTED])
        rendered = repr(dict(counts))
        self.assertNotIn("fake-activity", rendered)
        self.assertNotIn("avg_hr", rendered)

    def test_accepts_one_shot_iterables(self) -> None:
        issues = (
            MappingIssue(None, "distance_m", IssueReason.INVALID_TYPE) for _ in range(3)
        )

        self.assertEqual(3, count_issues(issues)[IssueReason.INVALID_TYPE])

    def test_rejects_entries_that_are_not_mapping_issues(self) -> None:
        with self.assertRaisesRegex(TypeError, "issues must be a MappingIssue"):
            count_issues(untyped(["missing field"]))


if __name__ == "__main__":
    unittest.main()
