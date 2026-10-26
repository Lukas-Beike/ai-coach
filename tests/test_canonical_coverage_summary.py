"""Counts-only canonical coverage summary for the diagnostics report.

The projection is built from in-memory fakes over the read-only wire fixtures.
"""

from __future__ import annotations

import json
import re
import unittest
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from support import garmin_payload_fixture, intervals_snapshot_fixture

from backend.canonical.coverage import MetricWindow, ProviderCoverage
from backend.canonical.mapping import IssueReason
from backend.canonical.vocabulary import ProviderId
from backend.diagnostics.canonical_coverage import summarize_canonical_coverage
from backend.sync.canonical_projection import CanonicalSnapshotProjection

CLOCK_AT = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
NEWEST = date(2026, 10, 11)
FAKE_DB: Any = object()
SUMMARY_VOCABULARY = {
    "status",
    "available",
    "providers",
    "provider",
    "sync_time_stored",
    "activity_sync_time_stored",
    "observation_sync_time_stored",
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

    def metric_windows(self, db: Any) -> tuple[MetricWindow, ...]:
        return ()


class CanonicalCoverageSummaryTests(unittest.TestCase):
    def test_summary_reports_counts_and_flags_per_provider(self) -> None:
        summary = summarize_canonical_coverage(fixture_projection(), FAKE_DB)

        self.assertEqual(summary["status"], "available")
        providers = providers_by_name(summary)
        intervals = providers[str(ProviderId.INTERVALS)]
        garmin = providers[str(ProviderId.GARMIN)]
        self.assertEqual(intervals["sync_time_stored"], True)
        self.assertEqual(intervals["activity_sync_time_stored"], True)
        self.assertEqual(intervals["observation_sync_time_stored"], True)
        self.assertEqual(intervals["activities"], 5)
        self.assertEqual(intervals["observations"], 51)
        self.assertEqual(intervals["issues"][str(IssueReason.UNSUPPORTED)], 0)
        self.assertEqual(garmin["sync_time_stored"], True)
        self.assertEqual(garmin["activity_sync_time_stored"], True)
        self.assertEqual(garmin["observation_sync_time_stored"], True)
        self.assertEqual(garmin["activities"], 2)
        self.assertEqual(garmin["observations"], 32)
        self.assertEqual(garmin["issues"][str(IssueReason.UNSUPPORTED)], 0)

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

            def metric_windows(self, db: Any) -> tuple[MetricWindow, ...]:
                return ()

        summary = summarize_canonical_coverage(Reader(), FAKE_DB)

        self.assertEqual(
            summary,
            {
                "status": "available",
                "providers": [
                    {
                        "provider": str(ProviderId.GARMIN),
                        "sync_time_stored": False,
                        "activity_sync_time_stored": False,
                        "observation_sync_time_stored": False,
                        "activities": 4,
                        "observations": 9,
                        "issues": {
                            str(reason): 2 if reason is IssueReason.MISSING else 0
                            for reason in IssueReason
                        },
                        "metrics": [],
                        "stalled_metrics": 0,
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


class FixedCoverage:
    def __init__(
        self, *providers: ProviderId, windows: tuple[MetricWindow, ...] = ()
    ) -> None:
        self._providers = providers
        self._windows = windows

    def coverage(self, db: Any) -> tuple[ProviderCoverage, ...]:
        return tuple(
            ProviderCoverage(
                provider=provider,
                retrieved_at=None,
                activity_count=0,
                observation_count=0,
                issue_counts={},
                first_observed_on=None,
                last_observed_on=None,
            )
            for provider in self._providers
        )

    def metric_windows(self, db: Any) -> tuple[MetricWindow, ...]:
        return self._windows


def window(
    provider: ProviderId,
    metric: str,
    observations: int,
    newest: date,
    oldest: date | None = None,
) -> MetricWindow:
    """Daily observations ending on ``newest``, unless the test passes ``oldest``."""
    return MetricWindow(
        provider=provider,
        metric=metric,
        observations=observations,
        oldest_observed_on=(
            newest - timedelta(days=observations - 1) if oldest is None else oldest
        ),
        newest_observed_on=newest,
    )


def weekly_window(
    provider: ProviderId, metric: str, observations: int, newest: date
) -> MetricWindow:
    """Observations spaced seven days apart, ending on ``newest``."""
    return window(
        provider,
        metric,
        observations,
        newest,
        oldest=newest - timedelta(days=7 * (observations - 1)),
    )


class MetricWindowTests(unittest.TestCase):
    """Per-metric lag and stall flags, fed from fake metric windows."""

    def summary(
        self,
        *windows: MetricWindow,
        providers: tuple[ProviderId, ...] = (ProviderId.INTERVALS,),
    ) -> dict[str, Any]:
        return summarize_canonical_coverage(
            FixedCoverage(*providers, windows=windows), FAKE_DB
        )

    def intervals_metrics(self, *windows: MetricWindow) -> dict[str, dict[str, Any]]:
        entry = providers_by_name(self.summary(*windows))[str(ProviderId.INTERVALS)]
        return {metric["metric"]: metric for metric in entry["metrics"]}

    def test_metric_stopped_ten_days_before_the_provider_is_stalled(self) -> None:
        windows = (
            window(ProviderId.INTERVALS, "ctl", 10, NEWEST - timedelta(days=10)),
            window(ProviderId.INTERVALS, "weight", 10, NEWEST),
        )

        metrics = self.intervals_metrics(*windows)

        self.assertEqual(
            metrics["ctl"],
            {"metric": "ctl", "observations": 10, "lag_days": 10, "stalled": True},
        )
        self.assertEqual(
            metrics["weight"],
            {"metric": "weight", "observations": 10, "lag_days": 0, "stalled": False},
        )
        self.assertEqual(
            providers_by_name(self.summary(*windows))[str(ProviderId.INTERVALS)][
                "stalled_metrics"
            ],
            1,
        )

    def test_metric_with_too_few_observations_is_not_stalled(self) -> None:
        metrics = self.intervals_metrics(
            window(ProviderId.INTERVALS, "ctl", 3, NEWEST - timedelta(days=10)),
            window(ProviderId.INTERVALS, "weight", 1, NEWEST),
        )

        self.assertEqual(metrics["ctl"]["lag_days"], 10)
        self.assertFalse(metrics["ctl"]["stalled"])

    def test_lag_below_a_week_is_not_stalled(self) -> None:
        metrics = self.intervals_metrics(
            window(ProviderId.INTERVALS, "ctl", 10, NEWEST - timedelta(days=6)),
            window(ProviderId.INTERVALS, "weight", 1, NEWEST),
        )

        self.assertEqual(metrics["ctl"]["lag_days"], 6)
        self.assertFalse(metrics["ctl"]["stalled"])

    def test_weekly_metric_within_its_cadence_is_not_stalled(self) -> None:
        metrics = self.intervals_metrics(
            weekly_window(
                ProviderId.INTERVALS, "weight", 10, NEWEST - timedelta(days=10)
            ),
            window(ProviderId.INTERVALS, "ctl", 1, NEWEST),
        )

        self.assertEqual(
            metrics["weight"],
            {"metric": "weight", "observations": 10, "lag_days": 10, "stalled": False},
        )

    def test_weekly_metric_lagging_three_cadences_is_stalled(self) -> None:
        metrics = self.intervals_metrics(
            weekly_window(
                ProviderId.INTERVALS, "weight", 10, NEWEST - timedelta(days=21)
            ),
            window(ProviderId.INTERVALS, "ctl", 1, NEWEST),
        )

        self.assertEqual(
            metrics["weight"],
            {"metric": "weight", "observations": 10, "lag_days": 21, "stalled": True},
        )

    def test_dense_metric_lagging_a_week_is_stalled(self) -> None:
        metrics = self.intervals_metrics(
            window(ProviderId.INTERVALS, "ctl", 10, NEWEST - timedelta(days=7)),
            window(ProviderId.INTERVALS, "weight", 1, NEWEST),
        )

        self.assertEqual(metrics["ctl"]["lag_days"], 7)
        self.assertTrue(metrics["ctl"]["stalled"])

    def test_event_driven_metric_is_never_stalled_by_its_lag(self) -> None:
        metrics = self.intervals_metrics(
            window(ProviderId.INTERVALS, "ftp", 10, NEWEST - timedelta(days=60)),
            window(ProviderId.INTERVALS, "ctl", 1, NEWEST),
        )

        self.assertEqual(
            metrics["ftp"],
            {"metric": "ftp", "observations": 10, "lag_days": 60, "stalled": False},
        )

    def test_non_event_daily_metric_with_a_long_lag_is_stalled(self) -> None:
        metrics = self.intervals_metrics(
            window(ProviderId.INTERVALS, "steps", 10, NEWEST - timedelta(days=10)),
            window(ProviderId.INTERVALS, "ctl", 1, NEWEST),
        )

        self.assertEqual(metrics["steps"]["lag_days"], 10)
        self.assertTrue(metrics["steps"]["stalled"])

    def test_metric_window_rejects_an_oldest_day_after_the_newest(self) -> None:
        with self.assertRaises(ValueError):
            MetricWindow(
                provider=ProviderId.INTERVALS,
                metric="ctl",
                observations=2,
                oldest_observed_on=NEWEST + timedelta(days=1),
                newest_observed_on=NEWEST,
            )

    def test_empty_metric_windows_report_no_metrics(self) -> None:
        entry = providers_by_name(self.summary())[str(ProviderId.INTERVALS)]

        self.assertEqual(entry["metrics"], [])
        self.assertEqual(entry["stalled_metrics"], 0)

    def test_metrics_of_providers_outside_the_coverage_are_not_added(self) -> None:
        summary = self.summary(
            window(ProviderId.INTERVALS, "ctl", 10, NEWEST - timedelta(days=10)),
            providers=(ProviderId.GARMIN,),
        )

        self.assertEqual(
            [entry["provider"] for entry in summary["providers"]], ["garmin"]
        )
        self.assertEqual(summary["providers"][0]["metrics"], [])

    def test_metric_summary_carries_no_dates(self) -> None:
        serialized = json.dumps(
            self.summary(
                window(ProviderId.INTERVALS, "ctl", 10, NEWEST - timedelta(days=10)),
                window(ProviderId.INTERVALS, "weight", 10, NEWEST),
            )
        )

        self.assertIsNone(re.search(r"\d{4}-\d{2}-\d{2}", serialized))


if __name__ == "__main__":
    unittest.main()
