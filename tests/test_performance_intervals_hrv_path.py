import unittest
from datetime import date, timedelta
from typing import Any

from canonical_recovery_support import recovery_only_inputs
from intervals_compaction import compact_snapshot

from backend.performance.context import current_performance_context
from backend.performance.freshness import GarminSyncStatus

TODAY = date(2026, 5, 4)
SYNCED_AT = "2026-05-04T08:00:00+00:00"


def _wellness_rows(count: int, *, with_sdnn: bool = True) -> list[dict[str, Any]]:
    """Raw Intervals.icu wellness rows on consecutive days ending today."""
    rows: list[dict[str, Any]] = []
    for index in range(count):
        day = TODAY - timedelta(days=count - 1 - index)
        row: dict[str, Any] = {
            "id": day.isoformat(),
            "restingHR": 50 + index % 3,
            "sleepSecs": 7 * 3600 + index * 60,
            "hrv": 40 + index % 5,
            "unrelatedField": "not a training input",
        }
        if with_sdnn:
            row["hrvSDNN"] = 55 + index % 4
        rows.append(row)
    return rows


class IntervalsHrvPathTests(unittest.TestCase):
    def _context(
        self, rows: list[dict[str, Any]]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        snapshot = compact_snapshot(
            {},
            [],
            rows,
            [],
            history_days=-1,
            all_sync_days=-1,
            synced_at=SYNCED_AT,
        )
        context = current_performance_context(
            GarminSyncStatus.from_state({}),
            {},
            TODAY,
            canonical=recovery_only_inputs(None, rows),
        )
        return snapshot, context

    def test_hrv_sdnn_survives_compaction_and_unrelated_fields_do_not(self) -> None:
        snapshot, _ = self._context(_wellness_rows(20))

        latest = snapshot["recent_wellness"][-1]
        self.assertEqual(TODAY.isoformat(), latest["id"])
        self.assertEqual(55 + 19 % 4, latest["hrvSDNN"])
        self.assertEqual(40 + 19 % 5, latest["hrv"])
        self.assertNotIn("unrelatedField", latest)


if __name__ == "__main__":
    unittest.main()
