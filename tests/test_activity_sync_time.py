"""The activity sync time is the oldest current fetch of the active providers."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from backend.activities.sync_time import activities_synced_at
from backend.canonical.vocabulary import ProviderId


class _Coverage:
    def __init__(self, *rows: Any) -> None:
        self._rows = rows

    def coverage(self, _db: Any) -> tuple[Any, ...]:
        return self._rows

    def metric_windows(self, _db: Any) -> tuple[Any, ...]:
        return ()


def _row(provider: ProviderId, day: int | None) -> Any:
    fetched = None if day is None else datetime(2026, 11, day, 8, tzinfo=UTC)
    return SimpleNamespace(provider=provider, activities_retrieved_at=fetched)


class ActivitySyncTimeTests(unittest.TestCase):
    def test_garmin_synced_today_bounds_the_days_without_intervals(self) -> None:
        coverage = _Coverage(_row(ProviderId.INTERVALS, 1), _row(ProviderId.GARMIN, 7))

        self.assertEqual(
            activities_synced_at(coverage, None), "2026-11-07T08:00:00+00:00"
        )

    def test_the_oldest_active_provider_holds_the_boundary(self) -> None:
        coverage = _Coverage(_row(ProviderId.GARMIN, 7), _row(ProviderId.WAHOO, 5))

        self.assertEqual(
            activities_synced_at(coverage, None), "2026-11-05T08:00:00+00:00"
        )

    def test_a_stalled_provider_no_longer_holds_it_back(self) -> None:
        coverage = _Coverage(
            _row(ProviderId.GARMIN, 30),
            SimpleNamespace(
                provider=ProviderId.WAHOO,
                activities_retrieved_at=datetime(2026, 10, 1, 8, tzinfo=UTC),
            ),
        )

        self.assertEqual(
            activities_synced_at(coverage, None), "2026-11-30T08:00:00+00:00"
        )

    def test_without_a_current_fetch_the_time_is_unknown(self) -> None:
        self.assertIsNone(activities_synced_at(_Coverage(), None))
        self.assertIsNone(activities_synced_at(None, None))
        self.assertIsNone(
            activities_synced_at(_Coverage(_row(ProviderId.INTERVALS, 5)), None)
        )


if __name__ == "__main__":
    unittest.main()
