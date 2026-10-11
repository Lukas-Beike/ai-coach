import unittest
from datetime import date, timedelta
from typing import Any

from backend.performance.context import current_performance_context
from backend.planning.context import compact_snapshot

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


def _intervals_hrv_baselines(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        row["measurement"]: row
        for row in context["personal_recovery"]["baselines"]
        if row["source"] == "Intervals.icu" and row["metric"] == "hrv"
    }


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
        context = current_performance_context(snapshot, {}, {}, TODAY)
        return snapshot, context

    def test_rmssd_and_sdnn_form_separate_intervals_baselines(self) -> None:
        snapshot, context = self._context(_wellness_rows(20))

        baselines = _intervals_hrv_baselines(context)
        self.assertEqual({"RMSSD", "SDNN"}, set(baselines))
        for measurement in ("RMSSD", "SDNN"):
            with self.subTest(measurement=measurement):
                self.assertEqual("provisional", baselines[measurement]["status"])
                self.assertEqual(19, baselines[measurement]["nights"])
                self.assertEqual("ms", baselines[measurement]["unit"])

        rmssd_values = {
            point["date"]: point["value"] for point in baselines["RMSSD"]["history"]
        }
        sdnn_values = {
            point["date"]: point["value"] for point in baselines["SDNN"]["history"]
        }
        for row in snapshot["recent_wellness"]:
            self.assertEqual(row["hrv"], rmssd_values[row["id"]])
            self.assertEqual(row["hrvSDNN"], sdnn_values[row["id"]])

    def test_hrv_sdnn_survives_compaction_and_unrelated_fields_do_not(self) -> None:
        snapshot, _ = self._context(_wellness_rows(20))

        latest = snapshot["recent_wellness"][-1]
        self.assertEqual(TODAY.isoformat(), latest["id"])
        self.assertEqual(55 + 19 % 4, latest["hrvSDNN"])
        self.assertEqual(40 + 19 % 5, latest["hrv"])
        self.assertNotIn("unrelatedField", latest)

    def test_rows_with_only_rmssd_produce_no_sdnn_series(self) -> None:
        snapshot, context = self._context(_wellness_rows(20, with_sdnn=False))

        self.assertNotIn("hrvSDNN", snapshot["recent_wellness"][-1])
        baselines = _intervals_hrv_baselines(context)
        self.assertEqual({"RMSSD"}, set(baselines))
        self.assertEqual("provisional", baselines["RMSSD"]["status"])


if __name__ == "__main__":
    unittest.main()
