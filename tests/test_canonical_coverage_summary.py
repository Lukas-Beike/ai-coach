"""Counts-only canonical coverage summary for the diagnostics report.

The projection is built from in-memory fakes over the read-only wire fixtures.
"""

from __future__ import annotations

import unittest
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from support import garmin_payload_fixture, intervals_snapshot_fixture

from backend.canonical.coverage import ProviderCoverage
from backend.canonical.mapping import IssueReason
from backend.canonical.vocabulary import ProviderId
from backend.diagnostics.canonical_coverage import summarize_canonical_coverage
from backend.sync.canonical_projection import CanonicalSnapshotProjection

CLOCK_AT = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
FAKE_DB: Any = object()
SUMMARY_VOCABULARY = {
    "status",
    "available",
    "providers",
    "provider",
    "sync_time_stored",
    "activities",
    "observations",
    "issues",
    *(str(reason) for reason in IssueReason),
    *(str(provider) for provider in ProviderId),
}


def fixture_projection(
    *,
    snapshot: dict[str, Any] | None = None,
    payload: dict[str, Any] | None = None,
) -> CanonicalSnapshotProjection:
    stored_snapshot = intervals_snapshot_fixture() if snapshot is None else snapshot
    stored_payload = garmin_payload_fixture() if payload is None else payload
    return CanonicalSnapshotProjection(
        intervals_snapshot=lambda db: stored_snapshot,
        intervals_version=lambda db: "row-1",
        garmin_payload=lambda db: stored_payload,
        zone=lambda db: ZoneInfo("Europe/Berlin"),
        clock=lambda: CLOCK_AT,
    )


def providers_by_name(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {entry["provider"]: entry for entry in summary["providers"]}


def long_leaves(value: Any) -> set[str]:
    """Collect string leaves long enough to be fixture content, not vocabulary."""
    if isinstance(value, dict):
        return set().union(*(long_leaves(item) for item in value.values()), set())
    if isinstance(value, list | tuple):
        return set().union(*(long_leaves(item) for item in value), set())
    if isinstance(value, str) and len(value) >= 8:
        return {value}
    return set()


class FailingCoverage:
    def coverage(self, db: Any) -> tuple[ProviderCoverage, ...]:
        raise RuntimeError("private athlete text in the error message")


class CanonicalCoverageSummaryTests(unittest.TestCase):
    def test_summary_reports_counts_and_flags_per_provider(self) -> None:
        summary = summarize_canonical_coverage(fixture_projection(), FAKE_DB)

        self.assertEqual(summary["status"], "available")
        providers = providers_by_name(summary)
        intervals = providers[str(ProviderId.INTERVALS)]
        garmin = providers[str(ProviderId.GARMIN)]
        self.assertEqual(intervals["sync_time_stored"], True)
        self.assertEqual(intervals["activities"], 5)
        self.assertEqual(intervals["observations"], 31)
        self.assertEqual(intervals["issues"][str(IssueReason.UNSUPPORTED)], 0)
        self.assertEqual(garmin["sync_time_stored"], True)
        self.assertEqual(garmin["activities"], 2)
        self.assertEqual(garmin["observations"], 18)
        self.assertEqual(garmin["issues"][str(IssueReason.UNSUPPORTED)], 3)

    def test_every_issue_reason_is_reported_with_an_explicit_count(self) -> None:
        coverage = ProviderCoverage(
            provider=ProviderId.GARMIN,
            retrieved_at=None,
            activity_count=4,
            observation_count=9,
            issue_counts={IssueReason.MISSING: 2},
            first_observed_on=None,
            last_observed_on=None,
        )

        class Reader:
            def coverage(self, db: Any) -> tuple[ProviderCoverage, ...]:
                return (coverage,)

        summary = summarize_canonical_coverage(Reader(), FAKE_DB)

        self.assertEqual(
            summary,
            {
                "status": "available",
                "providers": [
                    {
                        "provider": str(ProviderId.GARMIN),
                        "sync_time_stored": False,
                        "activities": 4,
                        "observations": 9,
                        "issues": {
                            str(reason): 2 if reason is IssueReason.MISSING else 0
                            for reason in IssueReason
                        },
                    }
                ],
            },
        )

    def test_missing_stored_sync_time_is_reported_as_a_flag_only(self) -> None:
        snapshot = intervals_snapshot_fixture()
        snapshot.pop("synced_at", None)
        summary = summarize_canonical_coverage(
            fixture_projection(snapshot=snapshot), FAKE_DB
        )

        providers = providers_by_name(summary)
        self.assertFalse(providers[str(ProviderId.INTERVALS)]["sync_time_stored"])
        self.assertTrue(providers[str(ProviderId.GARMIN)]["sync_time_stored"])

    def test_summary_carries_no_dates_or_fixture_content(self) -> None:
        projection = fixture_projection()
        summary = summarize_canonical_coverage(projection, FAKE_DB)
        serialized = repr(summary)

        for item in projection.coverage(FAKE_DB):
            self.assertIsNotNone(item.first_observed_on)
            for day in (item.first_observed_on, item.last_observed_on):
                if isinstance(day, date):
                    self.assertNotIn(day.isoformat(), serialized)
        fixture_text = long_leaves(intervals_snapshot_fixture()) | long_leaves(
            garmin_payload_fixture()
        )
        for leaf in fixture_text - SUMMARY_VOCABULARY:
            self.assertNotIn(leaf, serialized)

    def test_projection_failure_yields_an_unavailable_marker_without_detail(
        self,
    ) -> None:
        summary = summarize_canonical_coverage(FailingCoverage(), FAKE_DB)

        self.assertEqual(summary, {"status": "unavailable"})
        self.assertNotIn("private athlete", repr(summary))


if __name__ == "__main__":
    unittest.main()
