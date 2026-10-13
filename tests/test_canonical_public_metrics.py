from __future__ import annotations

import unittest

from backend.canonical.public_metrics import (
    neutral_activity_metrics,
    neutral_activity_records,
    neutral_calendar_entries,
)


class NeutralPublicMetricsTests(unittest.TestCase):
    def test_renames_stored_metric_keys_without_mutating_the_record(self) -> None:
        record = {"name": "Ride", "icu_training_load": 42, "icu_rpe": 3}

        translated = neutral_activity_metrics(record)

        self.assertEqual(
            {"name": "Ride", "training_load": 42, "rpe": 3},
            translated,
        )
        self.assertEqual(
            {"name": "Ride", "icu_training_load": 42, "icu_rpe": 3}, record
        )

    def test_records_without_stored_metrics_are_unchanged(self) -> None:
        record = {"name": "Rest", "moving_time": 600}

        self.assertEqual(record, neutral_activity_metrics(record))

    def test_existing_neutral_value_wins_over_the_stored_key(self) -> None:
        record = {
            "training_load": 7,
            "icu_training_load": 42,
            "rpe": None,
            "icu_rpe": 3,
        }

        self.assertEqual(
            {"training_load": 7, "rpe": 3}, neutral_activity_metrics(record)
        )

    def test_calendar_entries_translate_the_matched_activity(self) -> None:
        entries = [
            {
                "name": "Plan",
                "icu_training_load": 25,
                "icu_intensity": 0.7,
                "compliance": {
                    "status": "completed",
                    "actual_activity": {"icu_training_load": 34, "icu_rpe": 5},
                },
            },
            {"name": "Done", "icu_training_load": 10},
            "not-a-mapping",
        ]

        translated = neutral_calendar_entries(entries)

        self.assertEqual(
            [
                {
                    "name": "Plan",
                    "training_load": 25,
                    "intensity": 0.7,
                    "compliance": {
                        "status": "completed",
                        "actual_activity": {"training_load": 34, "rpe": 5},
                    },
                },
                {"name": "Done", "training_load": 10},
                "not-a-mapping",
            ],
            translated,
        )

    def test_activity_laps_and_rows_are_translated(self) -> None:
        lap = {"icu_intensity": 0.8}
        rows = [
            {
                "id": "a1",
                "icu_training_load": 50,
                "laps": [lap, "not-a-mapping"],
            },
            "not-a-mapping",
        ]

        self.assertEqual(
            [
                {
                    "id": "a1",
                    "training_load": 50,
                    "laps": [{"intensity": 0.8}, "not-a-mapping"],
                },
                "not-a-mapping",
            ],
            neutral_activity_records(rows),
        )
        self.assertEqual({"icu_intensity": 0.8}, lap)


if __name__ == "__main__":
    unittest.main()
