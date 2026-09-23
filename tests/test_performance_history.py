import copy
import unittest
from datetime import date, timedelta

from backend.performance.history import append_garmin_performance_history


def current_source(observed_at="2026-08-31"):
    return {
        "freshness": "current",
        "observed_at": observed_at,
        "fetched_at": "2026-09-01",
    }


class PerformanceHistoryTests(unittest.TestCase):
    def test_merges_previous_and_payload_history_with_later_metrics_overwriting(self):
        payload = {
            "performance_history": [
                {"date": "2026-08-30", "metrics": {"weight_kg": 72, "old": 1}},
                {"date": "2026-08-30", "metrics": {"weight_kg": 71}},
            ],
            "source_freshness": {},
        }
        previous = {
            "performance_history": [
                {"date": "2026-08-30", "metrics": {"weight_kg": 73, "previous": 1}},
                {"date": "malformed", "metrics": {"keep": 1}},
                {"date": "2026-08-29", "metrics": "invalid"},
            ]
        }
        append_garmin_performance_history(payload, previous, date(2026, 9, 1))
        self.assertEqual(
            payload["performance_history"],
            [
                {
                    "date": "2026-08-30",
                    "metrics": {"weight_kg": 71, "previous": 1, "old": 1},
                },
                {"date": "malformed", "metrics": {"keep": 1}},
            ],
        )

    def test_current_metrics_and_readiness_filter_by_current_freshness(self):
        payload = {
            "weight": [{"date": "2026-08-31", "weightKg": 72}],
            "readiness": [{"date": "2026-08-31", "readiness": 85}],
            "source_freshness": {
                "weight": current_source(),
                "readiness": current_source(),
            },
        }
        append_garmin_performance_history(payload, None, date(2026, 9, 1))
        self.assertEqual(
            payload["performance_history"],
            [{"date": "2026-08-31", "metrics": {"weight_kg": 72.0, "readiness": 85}}],
        )

    def test_missing_stale_and_undated_values_are_not_added(self):
        payload = {
            "weight": [{"date": "2026-08-31", "weightKg": 72}],
            "readiness": [{"date": "2026-08-31", "readiness": 85}],
            "source_freshness": {
                "weight": {"freshness": "stale", "observed_at": "2026-08-31"},
                "readiness": {"freshness": "current"},
            },
            "performance_history": [
                {"date": "2026-08-30", "metrics": {"existing": 1}},
            ],
        }
        append_garmin_performance_history(payload, None, date(2026, 9, 1))
        self.assertEqual(
            payload["performance_history"],
            [{"date": "2026-08-30", "metrics": {"existing": 1}}],
        )

    def test_retains_sorted_last_90_dates_and_uses_explicit_current_date(self):
        end = date(2026, 9, 1)
        old = [
            {
                "date": (end - timedelta(days=offset)).isoformat(),
                "metrics": {"value": offset},
            }
            for offset in range(100, -1, -1)
        ]
        payload = {"performance_history": old, "source_freshness": {}}
        before = copy.deepcopy(payload)
        append_garmin_performance_history(payload, None, end)
        dates = [item["date"] for item in payload["performance_history"]]
        self.assertEqual(len(dates), 90)
        self.assertEqual(dates, sorted(dates))
        self.assertEqual(dates[0], (end - timedelta(days=89)).isoformat())
        self.assertEqual(dates[-1], end.isoformat())
        self.assertNotEqual(payload, before)

    def test_previous_input_and_non_target_payload_data_are_not_mutated(self):
        previous = {
            "performance_history": [{"date": "2026-08-30", "metrics": {"value": 1}}],
            "other": {"keep": True},
        }
        payload = {"performance_history": [], "other": {"keep": True}}
        previous_before = copy.deepcopy(previous)
        other_before = copy.deepcopy(payload["other"])
        append_garmin_performance_history(payload, previous, date(2026, 9, 1))
        self.assertEqual(previous, previous_before)
        self.assertEqual(payload["other"], other_before)
        self.assertEqual(payload["performance_history"][0]["metrics"], {"value": 1})


if __name__ == "__main__":
    unittest.main()
