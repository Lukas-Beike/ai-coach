import math
import unittest
from datetime import date

from backend.performance.body import body_history
from backend.performance.garmin_weight import (
    garmin_body_fat_daily_records,
    garmin_body_fat_records,
    garmin_weight_daily_records,
)

TODAY = date(2026, 10, 6)


def _series(result, window, metric, source):
    return next(
        item
        for item in result["windows"][window]["metrics"][metric]
        if item["source"] == source
    )


class BodyHistoryTests(unittest.TestCase):
    def test_windows_gaps_and_last_valid_duplicate_per_provider(self):
        result = body_history(
            {
                "synced_at": "intervals-sync",
                "recent_wellness": [
                    {"id": "2026-10-05", "weight": 70, "bodyFat": 18},
                    {"id": "2026-10-05", "weight": 71},
                    {"id": "2026-10-06", "weight": math.nan, "bodyFat": 19},
                ],
            },
            {
                "synced_at": "garmin-sync",
                "weight": [{"date": "2026-10-04", "weightKg": 72}],
                "source_freshness": {"weight": {"fetched_at": "garmin-fetch"}},
            },
            TODAY,
        )
        self.assertEqual(result["windows"]["14d"]["days"], 14)
        self.assertEqual(result["windows"]["12w"]["days"], 84)
        intervals = _series(result, "14d", "weight_kg", "Intervals.icu Wellness")[
            "points"
        ]
        self.assertEqual(intervals[-2]["value"], 71)
        self.assertEqual(intervals[-2]["synced_at"], "intervals-sync")
        self.assertIsNone(intervals[-1]["value"])
        self.assertEqual(
            _series(result, "14d", "body_fat_pct", "Intervals.icu Wellness")["points"][
                -1
            ]["value"],
            19,
        )

    def test_ftp_sources_and_weight_age_limit(self):
        snapshot = {
            "synced_at": "intervals-sync",
            "recent_wellness": [
                {
                    "id": "2026-10-01",
                    "sportInfo": [{"types": ["Ride"], "mmp_model": {"ftp": 250}}],
                }
            ],
            "recent_activities": [],
        }
        garmin = {
            "weight": [{"date": "2026-09-29", "weightKg": 70}],
            "performance_history": [
                {"date": "2026-10-01", "metrics": {"cycling_ftp_watts": 280}},
                {"date": "2026-10-06", "metrics": {"cycling_ftp_watts": 300}},
            ],
            "source_freshness": {
                "weight": {"fetched_at": "weight-fetch"},
                "cycling_ftp": {"fetched_at": "ftp-fetch"},
            },
        }
        result = body_history(snapshot, garmin, TODAY)
        garmin_series = _series(result, "12w", "cycling_w_per_kg", "Garmin Connect")[
            "points"
        ]
        self.assertAlmostEqual(garmin_series[-1]["value"], 300 / 70, places=3)
        self.assertEqual(garmin_series[-1]["weight_age_days"], 7)
        intervals_series = _series(result, "12w", "cycling_w_per_kg", "Intervals.icu")[
            "points"
        ]
        self.assertAlmostEqual(intervals_series[-6]["value"], 250 / 70, places=3)
        self.assertEqual(intervals_series[-6]["ftp_synced_at"], "intervals-sync")
        self.assertEqual(
            _series(result, "12w", "cycling_w_per_kg", "Intervals.icu")["power_method"],
            "eFTP",
        )
        self.assertEqual(
            _series(result, "12w", "cycling_w_per_kg", "Garmin Connect")[
                "power_method"
            ],
            "FTP",
        )

        too_old = body_history(
            snapshot,
            {
                "weight": [{"date": "2026-09-28", "weightKg": 70}],
                "performance_history": garmin["performance_history"],
            },
            TODAY,
        )
        self.assertIsNone(
            _series(too_old, "12w", "cycling_w_per_kg", "Garmin Connect")["points"][-1][
                "value"
            ]
        )

    def test_manual_profile_values_are_not_historical_and_invalid_garmin_values_drop(
        self,
    ):
        result = body_history(
            {"synced_at": "sync", "profile": {"weight_kg": 80, "body_fat_pct": 20}},
            {"weight": [{"date": "2026-10-06", "weightKg": math.inf, "bodyFat": 80}]},
            TODAY,
        )
        self.assertTrue(
            all(
                point["value"] is None
                for point in _series(
                    result, "14d", "weight_kg", "Intervals.icu Wellness"
                )["points"]
            )
        )
        self.assertTrue(
            all(
                point["value"] is None
                for point in _series(result, "14d", "weight_kg", "Garmin Connect")[
                    "points"
                ]
            )
        )
        self.assertTrue(
            all(
                point["value"] is None
                for point in _series(result, "14d", "body_fat_pct", "Garmin Connect")[
                    "points"
                ]
            )
        )

    def test_garmin_body_fat_uses_dated_weigh_ins(self):
        self.assertEqual(
            garmin_body_fat_records(
                {"weigh_ins": [{"date": "2026-10-01", "bodyFatPercent": 18.5}]}
            ),
            [("2026-10-01", 18.5)],
        )

    def test_garmin_body_fat_unit_and_weigh_in_unit_do_not_conflict(self):
        rows = [
            {
                "date": "2026-10-01",
                "unitKey": "kg",
                "weight": 70,
                "bodyFat": 18.5,
            },
            {
                "date": "2026-10-02",
                "bodyFat": {"value": 0.185, "unitKey": "FRACTION"},
            },
        ]
        self.assertEqual(
            garmin_body_fat_records({"weight": rows}),
            [("2026-10-01", 18.5), ("2026-10-02", 18.5)],
        )

    def test_garmin_daily_record_uses_latest_timestamp_and_converts_pounds(self):
        snapshot = {
            "weight": [
                {
                    "timestampGMT": "2026-10-01T18:00:00Z",
                    "weight": 154.3,
                    "unit": "lb",
                    "bodyFat": 18,
                },
                {
                    "timestampGMT": "2026-10-01T07:00:00Z",
                    "weight": 160,
                    "unit": "lb",
                    "bodyFat": 20,
                },
            ]
        }
        self.assertEqual(garmin_weight_daily_records(snapshot), [("2026-10-01", 69.99)])
        self.assertEqual(
            garmin_body_fat_daily_records(snapshot), [("2026-10-01", 18.0)]
        )

    def test_weekly_quotient_median_counts_dates_and_chart_history_integration(self):
        from backend.performance.chart_history import analysis_history

        snapshot = {
            "recent_wellness": [
                {"id": "2026-10-05", "weight": 70},
                {"id": "2026-10-06", "weight": 70},
                {
                    "id": "2026-10-05",
                    "sportInfo": [{"types": ["Ride"], "mmp_model": {"ftp": 280}}],
                },
                {
                    "id": "2026-10-06",
                    "sportInfo": [{"types": ["Ride"], "mmp_model": {"ftp": 300}}],
                },
            ]
        }
        result = analysis_history(snapshot, {}, TODAY)
        self.assertIn("body", result)
        series = _series(result["body"], "12w", "cycling_w_per_kg", "Intervals.icu")
        self.assertEqual(len(series["weekly"]), 12)
        self.assertEqual(
            series["weekly"][-1],
            {
                "week_start": "2026-09-30",
                "week_end": "2026-10-06",
                "value": 4.14,
                "count": 2,
                "dates": ["2026-10-05", "2026-10-06"],
            },
        )
        self.assertEqual(series["weekly"][0]["count"], 0)
        self.assertIsNone(series["weekly"][0]["value"])

    def test_deeply_nested_garmin_ftp_is_bounded(self):
        nested: dict[str, object] = {"calendarDate": "2026-10-06"}
        current = nested
        for _ in range(25):
            child: dict[str, object] = {}
            current["nested"] = child
            current = child
        current["functionalThresholdPower"] = 300
        result = body_history(
            {},
            {"cycling_ftp": nested, "weight": [{"date": "2026-10-06", "weightKg": 70}]},
            TODAY,
        )
        series = _series(result, "14d", "cycling_w_per_kg", "Garmin Connect")
        self.assertIsNone(series["points"][-1]["value"])


if __name__ == "__main__":
    unittest.main()
