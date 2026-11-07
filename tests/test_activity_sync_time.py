"""The activity sync time follows the newest current fetch of any provider."""

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
    def test_a_garmin_fetch_after_the_last_intervals_fetch_wins(self) -> None:
        coverage = _Coverage(
            _row(ProviderId.INTERVALS, 5),
            _row(ProviderId.GARMIN, 7),
            _row(ProviderId.WAHOO, 6),
        )

        self.assertEqual(
            activities_synced_at(coverage, None), "2026-11-07T08:00:00+00:00"
        )

    def test_intervals_only_keeps_its_time(self) -> None:
        coverage = _Coverage(
            _row(ProviderId.INTERVALS, 5), _row(ProviderId.GARMIN, None)
        )

        self.assertEqual(
            activities_synced_at(coverage, None), "2026-11-05T08:00:00+00:00"
        )

    def test_no_current_fetch_is_unknown(self) -> None:
        self.assertIsNone(activities_synced_at(_Coverage(), None))
        self.assertIsNone(activities_synced_at(None, None))


if __name__ == "__main__":
    unittest.main()
