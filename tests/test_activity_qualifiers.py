"""Terrain, motor assistance and native type of activities across providers (#1670)."""

from __future__ import annotations

import dataclasses
import unittest
from datetime import UTC, date, datetime
from typing import Any

from backend.activities.activity_summary import activity_summary
from backend.activities.session_corrections import _entry
from backend.canonical.records import ActivityRecord
from backend.canonical.vocabulary import Assist, Environment, Sport, Terrain
from backend.db import canonical_store
from backend.performance.critical_power import critical_power_speed
from backend.performance.load import activity_rollup
from backend.providers.garmin_activity_mapping import (
    GARMIN_ACTIVITY_QUALIFIERS,
    GARMIN_ACTIVITY_TYPES,
    map_garmin_activities,
)
from backend.providers.intervals_activity_mapping import (
    INTERVALS_ACTIVITY_QUALIFIERS,
    INTERVALS_ACTIVITY_TYPES,
    intervals_analysis_sport,
    map_intervals_activities,
)
from backend.providers.wahoo_activity_mapping import (
    WAHOO_WORKOUT_QUALIFIERS,
    WAHOO_WORKOUT_TYPES,
    map_wahoo_activities,
)

FETCHED = datetime(2026, 11, 6, 8, 0, tzinfo=UTC)

type Classification = tuple[Sport, Environment, Terrain, Assist]


def intervals(type_name: str, **fields: Any) -> ActivityRecord:
    row = {"id": "i1", "start_date_local": "2026-11-01T07:00:00", "type": type_name}
    result = map_intervals_activities([row | fields], zone=UTC, retrieved_at=FETCHED)
    return result.records[0]


def garmin(type_key: str) -> ActivityRecord:
    row = {
        "activityId": 1,
        "activityName": "Synthetic",
        "activityType": {"typeKey": type_key},
        "startTimeLocal": "2026-11-01 07:00:00",
        "duration": 3600.0,
    }
    return map_garmin_activities([row], zone=UTC, retrieved_at=FETCHED).records[0]


def wahoo(type_id: int) -> ActivityRecord:
    row = {"id": 1, "starts": "2026-11-01T07:00:00Z", "workout_type_id": type_id}
    return map_wahoo_activities([row], zone=UTC, retrieved_at=FETCHED).records[0]


def classified(record: ActivityRecord) -> Classification:
    return record.sport, record.environment, record.terrain, record.assist


# The same real activity type in each provider table that has it.
EQUIVALENT_TYPES: dict[str, tuple[tuple[str, Any], ...]] = {
    "trail run": (("intervals", "TrailRun"), ("garmin", "trail_running"), ("wahoo", 4)),
    "treadmill run": (("garmin", "treadmill_running"), ("wahoo", 5)),
    "track run": (("garmin", "track_running"), ("wahoo", 3)),
    "virtual run": (
        ("intervals", "VirtualRun"),
        ("garmin", "virtual_run"),
        ("wahoo", 71),
    ),
    "virtual ride": (
        ("intervals", "VirtualRide"),
        ("garmin", "virtual_ride"),
        ("wahoo", 68),
    ),
    "indoor ride": (("garmin", "indoor_cycling"), ("wahoo", 12)),
    "road ride": (("garmin", "road_biking"), ("wahoo", 15)),
    "mountain bike": (
        ("intervals", "MountainBikeRide"),
        ("garmin", "mountain_biking"),
        ("wahoo", 13),
    ),
    "gravel ride": (("intervals", "GravelRide"), ("garmin", "gravel_cycling")),
    "track cycling": (("garmin", "track_cycling"), ("wahoo", 16)),
    "cyclocross": (("garmin", "cyclocross"), ("wahoo", 11)),
    "e-bike": (("intervals", "EBikeRide"), ("garmin", "e_bike_fitness"), ("wahoo", 64)),
    "e-mountain bike": (
        ("intervals", "EMountainBikeRide"),
        ("garmin", "e_bike_mountain"),
    ),
    "lap swim": (("garmin", "lap_swimming"), ("wahoo", 25)),
    "open water swim": (
        ("intervals", "OpenWaterSwim"),
        ("garmin", "open_water_swimming"),
        ("wahoo", 26),
    ),
    "treadmill walk": (("garmin", "treadmill_walking"), ("wahoo", 56)),
    "backcountry ski": (
        ("intervals", "BackcountrySki"),
        ("garmin", "backcountry_skiing_snowboarding_ws"),
    ),
    "skate ski": (("intervals", "NordicSki"), ("garmin", "skate_skiing_ws")),
    "yoga": (("intervals", "Yoga"), ("garmin", "yoga"), ("wahoo", 66)),
    "pilates": (("intervals", "Pilates"), ("garmin", "pilates")),
    "hiit": (("intervals", "HighIntensityIntervalTraining"), ("garmin", "hiit")),
}
MAPPERS = {"intervals": intervals, "garmin": garmin, "wahoo": wahoo}


class CrossProviderTableTests(unittest.TestCase):
    def test_equivalent_types_get_the_same_classification_from_every_provider(
        self,
    ) -> None:
        for name, entries in EQUIVALENT_TYPES.items():
            with self.subTest(name=name):
                results = {
                    (provider, key): classified(MAPPERS[provider](key))
                    for provider, key in entries
                }
                self.assertEqual(1, len(set(results.values())), results)

    def test_the_new_garmin_keys_get_a_concrete_sport(self) -> None:
        for key in ("cyclocross", "bmx", "track_cycling", "e_bike_mountain"):
            self.assertIs(Sport.RIDE, garmin(key).sport, key)
        self.assertIs(Sport.NORDIC_SKI, garmin("skate_skiing_ws").sport)
        self.assertIs(
            Sport.ALPINE_SKI, garmin("backcountry_skiing_snowboarding_ws").sport
        )
        self.assertEqual(
            (Sport.WALK, Environment.INDOOR), GARMIN_ACTIVITY_TYPES["indoor_walking"]
        )
        self.assertEqual(
            (Sport.OTHER, Environment.INDOOR), GARMIN_ACTIVITY_TYPES["indoor_cardio"]
        )

    def test_qualifier_tables_only_name_known_types(self) -> None:
        self.assertLessEqual(
            set(GARMIN_ACTIVITY_QUALIFIERS), set(GARMIN_ACTIVITY_TYPES)
        )
        self.assertLessEqual(
            set(INTERVALS_ACTIVITY_QUALIFIERS), set(INTERVALS_ACTIVITY_TYPES)
        )
        self.assertLessEqual(set(WAHOO_WORKOUT_QUALIFIERS), set(WAHOO_WORKOUT_TYPES))


class MapperQualifierTests(unittest.TestCase):
    def test_a_trail_run_from_each_provider_has_a_trail_terrain(self) -> None:
        for record in (intervals("TrailRun"), garmin("trail_running"), wahoo(4)):
            with self.subTest(provider=record.provenance.provider):
                self.assertIs(Terrain.TRAIL, record.terrain)

    def test_an_e_bike_ride_from_each_provider_is_electric(self) -> None:
        for record in (intervals("EBikeRide"), garmin("e_bike_fitness"), wahoo(64)):
            with self.subTest(provider=record.provenance.provider):
                self.assertIs(Sport.RIDE, record.sport)
                self.assertIs(Assist.ELECTRIC, record.assist)

    def test_a_known_type_without_assistance_is_none_and_an_unknown_one_unknown(
        self,
    ) -> None:
        self.assertIs(Assist.NONE, intervals("Ride").assist)
        self.assertIs(Assist.NONE, garmin("road_biking").assist)
        self.assertIs(Assist.NONE, wahoo(0).assist)
        self.assertIs(Assist.UNKNOWN, intervals("Workout").assist)
        self.assertIs(Assist.UNKNOWN, garmin("something_new").assist)
        self.assertIs(Terrain.UNKNOWN, garmin("something_new").terrain)

    def test_the_native_type_is_kept(self) -> None:
        self.assertEqual("GravelRide", intervals("GravelRide").native_type)
        self.assertEqual("gravel_cycling", garmin("gravel_cycling").native_type)
        self.assertEqual("13", wahoo(13).native_type)
        self.assertIs(Terrain.GRAVEL, intervals("GravelRide").terrain)
        self.assertIs(Terrain.MOUNTAIN, wahoo(13).terrain)

    def test_an_intervals_swim_is_a_pool_swim_only_with_a_pool_length(self) -> None:
        self.assertIs(Terrain.POOL, intervals("Swim", pool_length=25).terrain)
        self.assertIs(Terrain.UNKNOWN, intervals("Swim").terrain)
        self.assertIs(Terrain.UNKNOWN, intervals("Swim", pool_length=0).terrain)

    def test_the_raw_intervals_detail_classification_matches_the_mapper(self) -> None:
        analysed = intervals_analysis_sport({"type": "TrailRun"})
        self.assertEqual("trail", analysed["terrain"])
        self.assertTrue(analysed["trail"])
        self.assertEqual(
            "electric", intervals_analysis_sport({"type": "EBikeRide"})["assist"]
        )


class StorageTests(unittest.TestCase):
    def test_qualifiers_round_trip_through_the_details(self) -> None:
        record = intervals("EMountainBikeRide")
        values = canonical_store._activity_values(
            record, local_date=date(2026, 11, 1), mapper_version=10
        )
        stored = canonical_store.activity_summary_values(values["details"])
        self.assertEqual(Terrain.MOUNTAIN, stored["terrain"])
        self.assertEqual(Assist.ELECTRIC, stored["assist"])
        self.assertEqual("EMountainBikeRide", stored["native_type"])

    def test_invalid_stored_qualifiers_are_left_out(self) -> None:
        details = '{"terrain":"lava","assist":3,"native_type":""}'
        self.assertEqual({}, canonical_store.activity_qualifiers(details))

    def test_the_bundle_view_names_the_native_type(self) -> None:
        row = {
            "session_id": "act_1",
            "provider": "garmin",
            "recorded_by": "garmin",
            "sport": "run",
            "started_at": "2026-11-01T07:00:00+00:00",
            "duration_s": 3600.0,
            "distance_m": 10000.0,
            "name": "Synthetic",
            "details": '{"terrain":"trail","native_type":"trail_running"}',
        }
        entry = _entry(row)
        self.assertEqual("trail_running", entry["native_type"])
        self.assertEqual("trail", entry["terrain"])


class SessionAndAnalysisTests(unittest.TestCase):
    def test_the_session_takes_a_known_qualifier_from_another_record(self) -> None:
        primary = intervals("Workout", name="Ride")
        other = dataclasses.replace(garmin("e_bike_mountain"), sport=primary.sport)
        summary = activity_summary("act_1", [primary, other], UTC)
        self.assertEqual("mountain", summary["terrain"])
        self.assertEqual("electric", summary["assist"])
        plain = activity_summary("act_2", [intervals("Workout")], UTC)
        self.assertNotIn("terrain", plain)
        self.assertNotIn("assist", plain)

    def test_e_bike_hours_are_volume_with_their_own_label(self) -> None:
        rows = [
            {"started_at_local": "2026-11-01T07:00:00", "moving_duration_s": 3600},
            {
                "started_at_local": "2026-11-02T07:00:00",
                "moving_duration_s": 1800,
                "assist": "electric",
            },
        ]
        rollup = activity_rollup(rows, 7, date(2026, 11, 3))
        self.assertEqual(1.5, rollup["duration_hours"])
        self.assertEqual(0.5, rollup["electric_assist_hours"])
        self.assertNotIn(
            "electric_assist_hours", activity_rollup(rows[:1], 7, date(2026, 11, 3))
        )

    def test_trail_runs_stay_out_of_the_critical_speed_fit(self) -> None:
        today = date(2026, 11, 6)

        def run(activity_id: str, terrain: str | None, speed: float) -> dict[str, Any]:
            return {
                "sport": "run",
                "environment": "outdoor",
                "terrain": terrain,
                "activity_id": activity_id,
                "date": "2026-11-01",
                "running_profile": {
                    "speed": [
                        {
                            "duration_seconds": seconds,
                            "speed_mps": speed,
                            "start_seconds": 0,
                        }
                        for seconds in (180, 300, 600, 1200)
                    ]
                },
            }

        trail = critical_power_speed(
            [run("t", "trail", 9.0)], today, input_fingerprint="x"
        )
        road = critical_power_speed([run("r", None, 4.0)], today, input_fingerprint="x")
        run_fit = next(f for f in trail["fits"] if f["sport"] == "run")
        road_fit = next(f for f in road["fits"] if f["sport"] == "run")
        self.assertEqual([], run_fit["efforts"])
        self.assertTrue(road_fit["efforts"])


if __name__ == "__main__":
    unittest.main()
