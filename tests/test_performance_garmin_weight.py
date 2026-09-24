import copy
import unittest
from datetime import date, datetime, timezone

from backend.performance.garmin_weight import (
    garmin_weight_average,
    garmin_weight_metric,
    garmin_weight_records,
)


class GarminWeightTests(unittest.TestCase):
    def test_nested_records_inherit_dates_and_dedupe_in_first_order(self):
        snapshot = {
            "weight": {
                "calendarDate": "2026-08-30",
                "entries": [
                    {"weightKg": 70},
                    {"weight_kg": 70},
                    {"date": "2026-08-31", "weight": 71},
                ],
            }
        }
        self.assertEqual(
            garmin_weight_records(snapshot),
            [("2026-08-30", 70.0), ("2026-08-31", 71.0)],
        )

    def test_list_cap_and_excluded_summary_keys(self):
        entries = [
            {"date": "2026-08-30", "weightKg": 70 + index / 100} for index in range(501)
        ]
        snapshot = {
            "weight": {
                "records": entries,
                "minWeight": {"date": "2026-08-30", "weightKg": 999},
                "max-weight": {"date": "2026-08-30", "weightKg": 999},
                "weightDelta": {"date": "2026-08-30", "weightKg": 999},
            }
        }
        records = garmin_weight_records(snapshot)
        self.assertEqual(len(records), 500)
        self.assertEqual(records[0], ("2026-08-30", 70.0))
        self.assertEqual(records[-1], ("2026-08-30", 74.99))

    def test_kg_lb_grams_and_inclusive_bounds(self):
        snapshot = {
            "weight": [
                {"weightKg": 30},
                {"weight_kg": 300},
                {"weight": 154.323583, "unit": "lb"},
                {"weight": 71000},
                {"weight": 29.99},
                {"weight": 300.01},
            ]
        }
        self.assertEqual(
            garmin_weight_records(snapshot),
            [(None, 30.0), (None, 300.0), (None, 70.0), (None, 71.0)],
        )

    def test_millisecond_timestamp_is_normalized_to_utc_date(self):
        timestamp = (
            datetime(2026, 8, 30, 23, 30, tzinfo=timezone.utc).timestamp() * 1000
        )
        self.assertEqual(
            garmin_weight_records(
                {"weight": [{"timestamp": timestamp, "weightKg": 72}]}
            ),
            [("2026-08-30", 72.0)],
        )

    def test_metric_shape_source_note_and_empty_value(self):
        self.assertEqual(
            garmin_weight_metric({"weight": [{"date": "2026-08-30", "weightKg": 72}]}),
            {
                "value": 72.0,
                "unit": "kg",
                "source": "Garmin Connect",
                "note": "Garmin Connect Körpergewicht",
            },
        )
        self.assertEqual(
            garmin_weight_metric({}),
            {"value": None, "unit": "kg", "source": None, "note": ""},
        )

    def test_average_uses_inclusive_window_and_ignores_invalid_dates(self):
        snapshot = {
            "weight": [
                {"date": "2026-08-29", "weightKg": 60},
                {"date": "2026-08-30", "weightKg": 70},
                {"date": "2026-08-31", "weightKg": 72},
                {"date": "2026-09-01", "weightKg": 74},
                {"date": "invalid", "weightKg": 100},
            ]
        }
        self.assertEqual(garmin_weight_average(snapshot, 2, date(2026, 8, 31)), 71.0)

    def test_inputs_are_not_mutated(self):
        snapshot = {"weight": [{"calendarDate": "2026-08-30", "weightKg": 72}]}
        before = copy.deepcopy(snapshot)
        garmin_weight_records(snapshot)
        garmin_weight_metric(snapshot)
        garmin_weight_average(snapshot, 30, date(2026, 8, 31))
        self.assertEqual(snapshot, before)


if __name__ == "__main__":
    unittest.main()
