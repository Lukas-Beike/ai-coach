from __future__ import annotations

import unittest

from backend.canonical.public_metrics import (
    neutral_activity,
    neutral_activity_metrics,
    neutral_activity_records,
    neutral_calendar_entries,
    neutral_calendar_entry,
    neutral_calendar_state,
)
from backend.providers.intervals_activity_fields import ACTIVITY_FIELDS

# Keys of the compact activity row that are already generic and stay.
GENERIC_ACTIVITY_KEYS = frozenset(
    {
        "id",
        "name",
        "type",
        "feel",
        "source",
        "device_name",
        "external_id",
        "file_type",
        "paired_event_id",
        "normalized_power",
        "vo2max",
    }
)

FULL_ROW = {
    "id": "a1",
    "start_date_local": "2026-10-11T07:00:00",
    "start_date": "2026-10-11T05:00:00Z",
    "name": "Ride",
    "type": "Ride",
    "moving_time": 3600,
    "elapsed_time": 3700,
    "distance": 30000.0,
    "total_elevation_gain": 250.0,
    "icu_training_load": 60,
    "icu_intensity": 0.8,
    "icu_ctl": 55.0,
    "icu_atl": 61.0,
    "icu_ftp": 280,
    "icu_eftp": 275.5,
    "average_heartrate": 140,
    "max_heartrate": 172,
    "average_watts": 200,
    "weighted_average_watts": 215,
    "icu_weighted_avg_watts": 212,
    "average_speed": 8.3,
    "max_speed": 14.2,
    "icu_weighted_avg_speed": 8.4,
    "icu_pace": 4.1,
    "vO2MaxValue": 58,
    "icu_vo2max": 57,
    "feel": 3,
    "icu_rpe": 6,
    "source": "GARMIN_CONNECT",
}


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

    def test_renames_recorded_zone_times(self) -> None:
        record = {
            "icu_hr_zone_times": [600, 300],
            "icu_zone_times": [{"id": "Z1", "secs": 300}],
            "icu_weighted_avg_watts": 205,
        }

        self.assertEqual(
            {
                "heart_rate_zone_times": [600, 300],
                "power_zone_times": [{"id": "Z1", "secs": 300}],
                "normalized_power": 205,
            },
            neutral_activity_metrics(record),
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

    def test_activity_rows_get_every_neutral_activity_key(self) -> None:
        self.assertEqual(
            {
                "id": "a1",
                "started_at_local": "2026-10-11T07:00:00",
                "started_at": "2026-10-11T05:00:00Z",
                "name": "Ride",
                "type": "Ride",
                "moving_duration_s": 3600,
                "elapsed_duration_s": 3700,
                "distance_m": 30000.0,
                "elevation_gain_m": 250.0,
                "training_load": 60,
                "intensity": 0.8,
                "ctl": 55.0,
                "atl": 61.0,
                "ftp_w": 280,
                "eftp_w": 275.5,
                "avg_hr": 140,
                "max_hr": 172,
                "avg_power": 200,
                "weighted_avg_power": 215,
                "normalized_power": 212,
                "avg_speed_mps": 8.3,
                "max_speed_mps": 14.2,
                "weighted_avg_speed_mps": 8.4,
                "pace_mps": 4.1,
                "vo2max": 58,
                "feel": 3,
                "rpe": 6,
                "source": "GARMIN_CONNECT",
            },
            neutral_activity(FULL_ROW),
        )

    def test_no_stored_activity_key_survives_the_translation(self) -> None:
        row = {key: index + 1 for index, key in enumerate(ACTIVITY_FIELDS)}
        (translated,) = neutral_activity_records([row])
        self.assertEqual(
            set(),
            (set(translated) & set(ACTIVITY_FIELDS)) - GENERIC_ACTIVITY_KEYS,
        )

    def test_vo2max_aliases_collapse_and_the_first_present_wins(self) -> None:
        self.assertEqual(
            {"vo2max": 52}, neutral_activity({"vo2_max": 52, "icu_vo2max": 50})
        )
        self.assertEqual({"vo2max": 50}, neutral_activity({"icu_vo2max": 50}))

    def test_planned_units_keep_their_neutral_planning_keys(self) -> None:
        planned = {
            "id": "planned-1",
            "starts_at_local": "2026-10-12T07:00:00",
            "planned_duration_s": 3600,
            "icu_training_load": 40,
            "compliance": {
                "status": "completed",
                "actual_activity": {
                    "start_date_local": "2026-10-12T07:05:00",
                    "moving_time": 3500,
                    "icu_training_load": 38,
                    "is_completed_activity": True,
                },
            },
        }
        completed = {
            "id": "a2",
            "is_completed_activity": True,
            "start_date_local": "2026-10-12T17:00:00",
            "moving_time": 1800,
            "average_heartrate": 130,
        }

        self.assertEqual(
            [
                {
                    "id": "planned-1",
                    "starts_at_local": "2026-10-12T07:00:00",
                    "planned_duration_s": 3600,
                    "training_load": 40,
                    "compliance": {
                        "status": "completed",
                        "actual_activity": {
                            "started_at_local": "2026-10-12T07:05:00",
                            "moving_duration_s": 3500,
                            "training_load": 38,
                            "is_completed_activity": True,
                        },
                    },
                },
                {
                    "id": "a2",
                    "is_completed_activity": True,
                    "started_at_local": "2026-10-12T17:00:00",
                    "moving_duration_s": 1800,
                    "avg_hr": 130,
                },
            ],
            neutral_calendar_entries([planned, completed]),
        )

    def test_calendar_state_translates_every_calendar_list(self) -> None:
        actual = {"moving_time": 3500, "is_completed_activity": True}
        entry = {"planned_duration_s": 3600, "compliance": {"actual_activity": actual}}
        state = {
            "training_calendar": [dict(entry)],
            "planned": [dict(entry)],
            "calendar": [dict(entry)],
            "planning_view": {"source": "local", "items": [dict(entry)]},
            "plans": [{"moving_time": 1}],
        }

        translated = neutral_calendar_state(state)

        expected = {
            "planned_duration_s": 3600,
            "compliance": {
                "actual_activity": {
                    "moving_duration_s": 3500,
                    "is_completed_activity": True,
                }
            },
        }
        for key in ("training_calendar", "planned", "calendar"):
            self.assertEqual([expected], translated[key])
        self.assertEqual(
            {"source": "local", "items": [expected]}, translated["planning_view"]
        )
        self.assertEqual([{"moving_time": 1}], translated["plans"])


class ActivitySummaryTranslationTests(unittest.TestCase):
    def test_translating_a_summary_changes_nothing(self):
        summary = {
            "id": "act_1",
            "started_at": "2026-09-22T06:30:00+00:00",
            "started_at_local": "2026-09-22T08:30:00",
            "sport": "ride",
            "environment": "indoor",
            "moving_duration_s": 3600,
            "distance_m": 30000.0,
            "avg_power": 180.0,
            "normalized_power": 200.0,
            "training_load": 70.0,
            "intensity": 70.0,
            "rpe": 5.0,
            "power_zone_times": [{"id": "Z1", "secs": 600.0}],
            "heart_rate_zone_times": [{"id": "Z2", "secs": 300.0}],
            "record_ids": {"intervals": "i1"},
            "sources": {"training_load": "Intervals.icu"},
        }
        self.assertEqual(neutral_activity(summary), summary)
        self.assertEqual(neutral_activity_records([summary]), [summary])
        entry = {"is_completed_activity": True, **summary}
        self.assertEqual(neutral_calendar_entry(entry), entry)


if __name__ == "__main__":
    unittest.main()
