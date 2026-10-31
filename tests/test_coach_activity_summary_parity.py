"""The Coach reads activity summaries and reports the values it reported for raw rows."""

import unittest
from datetime import UTC, date, datetime

from activity_row_support import summaries_of_rows

from backend.activities.activity_summary import activity_summary
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.coach.context import (
    COACH_ACTIVITY_FIELDS,
    CoachIntervalsContextService,
    compact_coach_activity,
)
from backend.planning import context as planning_context

TODAY = date(2026, 9, 23)

# An Intervals.icu-only ride as the activity summary reader reports it.
RIDE_SUMMARY = {
    "id": "i1001",
    "started_at": "2026-09-22T06:30:00+00:00",
    "started_at_local": "2026-09-22T08:30:00",
    "name": "Endurance",
    "sport": "ride",
    "environment": "outdoor",
    "recorded_by": "garmin",
    "source": "Intervals.icu",
    "sources": {"moving_duration_s": "Intervals.icu"},
    "record_ids": {"intervals": "i1001"},
    "moving_duration_s": 5400,
    "elapsed_duration_s": 5600,
    "distance_m": 42000.0,
    "elevation_gain_m": 410.0,
    "avg_hr": 138.0,
    "max_hr": 171.0,
    "avg_power": 190.0,
    "avg_speed_mps": 7.8,
    "normalized_power": 205.0,
    "weighted_avg_speed_mps": 7.9,
    "pace_mps": 7.7,
    "intensity": 71.0,
    "training_load": 82.0,
    "load_model": "intervals_training_load",
    "rpe": 6.0,
    "feel": 3,
    "planned_event_id": "evt-1",
}
RUN_SUMMARY = {
    "id": "i1002",
    "started_at_local": "2026-09-20T07:00:00",
    "name": "Easy run",
    "sport": "run",
    "environment": "outdoor",
    "source": "Intervals.icu",
    "moving_duration_s": 1800,
    "distance_m": 5000.0,
    "training_load": 30.0,
    "load_model": "intervals_training_load",
}


class CoachActivitySummaryParityTests(unittest.TestCase):
    def test_coach_activity_carries_the_summary_values_without_private_fields(self):
        row = compact_coach_activity(RIDE_SUMMARY, select=planning_context.selected)
        self.assertEqual(
            row,
            {
                "id": "i1001",
                "started_at_local": "2026-09-22T08:30:00",
                "name": "Endurance",
                "sport": "ride",
                "environment": "outdoor",
                "moving_duration_s": 5400,
                "distance_m": 42000.0,
                "elevation_gain_m": 410.0,
                "training_load": 82.0,
                "load_model": "intervals_training_load",
                "intensity": 71.0,
                "avg_hr": 138.0,
                "max_hr": 171.0,
                "avg_power": 190.0,
                "normalized_power": 205.0,
                "avg_speed_mps": 7.8,
                "weighted_avg_speed_mps": 7.9,
                "pace_mps": 7.7,
                "rpe": 6.0,
                "feel": 3,
                "source": "Intervals.icu",
            },
        )
        self.assertEqual(set(row), set(COACH_ACTIVITY_FIELDS))

    def test_projection_groups_and_rolls_up_with_unchanged_labels_and_numbers(self):
        result = CoachIntervalsContextService().project(
            [], TODAY, [RIDE_SUMMARY, RUN_SUMMARY], synced_at="2026-09-23T05:00:00"
        )

        self.assertEqual(
            result["source"],
            {
                "provider": "intervals",
                "label": "Intervals.icu",
                "synced_at": "2026-09-23T05:00:00",
                "applies_to": [
                    "recent_activities_by_sport",
                    "activity_rollups_by_sport",
                ],
            },
        )
        self.assertEqual(
            sorted(result["recent_activities_by_sport"]), ["Laufen", "Radfahren"]
        )
        ride = result["recent_activities_by_sport"]["Radfahren"][0]
        self.assertEqual((ride["id"], ride["training_load"]), ("i1001", 82.0))
        self.assertEqual(
            result["activity_rollups_by_sport"],
            {
                "Laufen": {
                    "last_7_days": {
                        "days": 7,
                        "sessions": 1,
                        "duration_hours": 0.5,
                        "training_load": 30.0,
                    },
                    "last_30_days": {
                        "days": 30,
                        "sessions": 1,
                        "duration_hours": 0.5,
                        "training_load": 30.0,
                    },
                },
                "Radfahren": {
                    "last_7_days": {
                        "days": 7,
                        "sessions": 1,
                        "duration_hours": 1.5,
                        "training_load": 82.0,
                    },
                    "last_30_days": {
                        "days": 30,
                        "sessions": 1,
                        "duration_hours": 1.5,
                        "training_load": 82.0,
                    },
                },
            },
        )


# A raw Intervals.icu row with the keys the former compact Coach rows copied.
RAW_RIDE = {
    "id": "i2001",
    "start_date_local": "2026-09-22T08:30:00",
    "name": "Tempo",
    "type": "VirtualRide",
    "moving_time": 3600,
    "elapsed_time": 3700,
    "distance": 36000.0,
    "total_elevation_gain": 120.0,
    "icu_training_load": 75,
    "icu_intensity": 82.5,
    "average_heartrate": 150,
    "max_heartrate": 172,
    "average_watts": 215,
    "icu_weighted_avg_watts": 228,
    "average_speed": 10.0,
    "icu_weighted_avg_speed": 10.2,
    "icu_pace": 10.1,
    "icu_rpe": 7,
    "feel": 2,
}


class CoachRawRowParityTests(unittest.TestCase):
    def test_mapped_summary_keeps_every_value_the_raw_coach_row_carried(self) -> None:
        summary = summaries_of_rows([RAW_RIDE])[0]

        row = compact_coach_activity(summary, select=planning_context.selected)

        self.assertEqual(
            {
                "started_at_local": "2026-09-22T08:30:00",
                "name": "Tempo",
                "sport": "ride",
                "environment": "virtual",
                "moving_duration_s": 3600.0,
                "distance_m": 36000.0,
                "elevation_gain_m": 120.0,
                "training_load": 75.0,
                "load_model": "intervals_training_load",
                "intensity": 82.5,
                "avg_hr": 150.0,
                "max_hr": 172.0,
                "avg_power": 215.0,
                "normalized_power": 228.0,
                "avg_speed_mps": 10.0,
                "weighted_avg_speed_mps": 10.2,
                "pace_mps": 10.1,
                "rpe": 7.0,
                "feel": 2.0,
                "source": "Intervals.icu",
            },
            {key: value for key, value in row.items() if key != "id"},
        )
        self.assertTrue(row["id"])

    def test_garmin_only_session_appears_without_training_load(self) -> None:
        record = ActivityRecord(
            activity_id="g1",
            provenance=Provenance(
                provider=ProviderId.GARMIN,
                source_kind=SourceKind.PROVIDER_REPORTED,
                source_record_id="g1",
                recorded_by=RecordingOrigin.GARMIN,
                retrieved_at=datetime(2026, 9, 22, 12, tzinfo=UTC),
                label="Garmin Connect",
            ),
            sport=Sport.RUN,
            environment=Environment.UNKNOWN,
            started_at=datetime(2026, 9, 21, 6, tzinfo=UTC),
            duration_s=2400.0,
            moving_duration_s=2400.0,
            distance_m=6000.0,
            load=55.0,
            load_model=LoadModel.GARMIN_TRAINING_LOAD,
            avg_hr=140.0,
            avg_power=None,
            name="Garmin run",
        )
        summary = activity_summary("act_g1", [record], UTC)

        result = CoachIntervalsContextService().project(
            [], TODAY, [summary], synced_at=None
        )

        run = result["recent_activities_by_sport"]["Laufen"][0]
        self.assertEqual(("act_g1", "Garmin Connect"), (run["id"], run["source"]))
        self.assertNotIn("training_load", run)
        self.assertEqual(
            {"days": 7, "sessions": 1, "duration_hours": 0.7, "training_load": 0.0},
            result["activity_rollups_by_sport"]["Laufen"]["last_7_days"],
        )


class CoachMergedSourceTests(unittest.TestCase):
    def test_values_from_another_provider_name_their_source(self) -> None:
        summary = {
            **RUN_SUMMARY,
            "source": "Garmin Connect",
            "sources": {
                "moving_duration_s": "Garmin Connect",
                "training_load": "Intervals.icu",
                "planned_event_id": "Intervals.icu",
            },
        }

        row = compact_coach_activity(summary, select=planning_context.selected)

        self.assertEqual({"training_load": "Intervals.icu"}, row["sources"])
        self.assertNotIn(
            "sources",
            compact_coach_activity(RIDE_SUMMARY, select=planning_context.selected),
        )


if __name__ == "__main__":
    unittest.main()
