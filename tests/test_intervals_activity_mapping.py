"""Intervals.icu activity rows mapped to canonical activity records."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime, timedelta, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.identity import activity_kind
from backend.canonical.mapping import IssueReason, MappingIssue, MappingResult
from backend.canonical.records import ActivityRecord
from backend.canonical.sports import legacy_activity_family
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.planning.workouts import INTERVALS_WORKOUT_TYPES
from backend.providers.intervals_activity_fields import intervals_activity_device_source
from backend.providers.intervals_activity_mapping import (
    INTERVALS_ACTIVITY_TYPES,
    INTERVALS_LABEL,
    MAPPER_VERSION,
    MAX_ACTIVITY_ID_LENGTH,
    MAX_NAME_LENGTH,
    map_intervals_activities,
)

BERLIN = ZoneInfo("Europe/Berlin")
RETRIEVED_AT = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
CET = timedelta(hours=1)
CEST = timedelta(hours=2)
FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "providers"
    / "intervals"
    / "activities.json"
)
GENERIC_TYPES = frozenset({"Workout", "Other"})


def row(**fields: object) -> dict[str, object]:
    """Return a minimal valid Berlin-time ride, overridden by ``fields``."""
    base: dict[str, object] = {
        "id": "i-test",
        "start_date_local": "2026-06-01T07:00:00",
        "type": "Ride",
    }
    base.update(fields)
    return base


def map_rows(rows: object, zone: tzinfo = BERLIN) -> MappingResult[ActivityRecord]:
    return map_intervals_activities(rows, zone=zone, retrieved_at=RETRIEVED_AT)


def map_one(**fields: object) -> ActivityRecord:
    result = map_rows([row(**fields)])
    if len(result.records) != 1:
        raise AssertionError(f"expected one record, got {result.issues!r}")
    return result.records[0]


def load_fixture_rows() -> list[dict[str, Any]]:
    with FIXTURE.open(encoding="utf-8") as handle:
        loaded: list[dict[str, Any]] = json.load(handle)
    return loaded


class ModuleContractTests(unittest.TestCase):
    def test_mapper_version_is_one(self) -> None:
        self.assertEqual(1, MAPPER_VERSION)

    def test_retrieved_at_must_be_timezone_aware(self) -> None:
        with self.assertRaises(ValueError):
            map_intervals_activities(
                [row()], zone=BERLIN, retrieved_at=RETRIEVED_AT.replace(tzinfo=None)
            )

    def test_non_list_rows_yield_empty_result_and_one_issue(self) -> None:
        for value in (None, "rows", {"id": "i-1"}, (row(),)):
            with self.subTest(value=type(value).__name__):
                result = map_rows(value)
                self.assertEqual((), result.records)
                self.assertEqual(
                    (MappingIssue(None, "rows", IssueReason.INVALID_TYPE),),
                    result.issues,
                )

    def test_empty_list_yields_empty_result(self) -> None:
        self.assertEqual(MappingResult((), ()), map_rows([]))


class FixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = map_rows(load_fixture_rows())
        self.by_id = {record.activity_id: record for record in self.result.records}

    def test_every_fixture_row_maps_without_issues(self) -> None:
        self.assertEqual((), self.result.issues)
        self.assertEqual(
            [
                "i-act-001",
                "i-act-002",
                "i-act-003",
                "i-act-004",
                "i-act-005",
            ],
            [record.activity_id for record in self.result.records],
        )

    def test_full_ride_record(self) -> None:
        record = self.by_id["i-act-001"]

        self.assertEqual(Sport.RIDE, record.sport)
        self.assertEqual(Environment.UNKNOWN, record.environment)
        self.assertEqual("Synthetic endurance ride", record.name)
        self.assertEqual(5400.0, record.duration_s)
        self.assertEqual(88500.0, record.distance_m)
        self.assertEqual(72.0, record.load)
        self.assertEqual(LoadModel.INTERVALS_TRAINING_LOAD, record.load_model)
        self.assertEqual(142.0, record.avg_hr)
        self.assertEqual(198.0, record.avg_power)

    def test_run_without_elapsed_or_power_uses_moving_time(self) -> None:
        record = self.by_id["i-act-002"]

        self.assertEqual(Sport.RUN, record.sport)
        self.assertEqual(2400.0, record.duration_s)
        self.assertEqual(150.0, record.avg_hr)
        self.assertIsNone(record.avg_power)

    def test_naive_wall_times_across_dst_transitions_are_localised(self) -> None:
        # Spring change 2026-03-29: 02:00 CET jumps to 03:00 CEST.
        # Autumn change 2026-10-25: 03:00 CEST falls back to 02:00 CET.
        cases = (
            ("i-act-002", "2026-03-29T01:59:00", CET),
            ("i-act-003", "2026-03-29T03:01:00", CEST),
            ("i-act-004", "2026-10-25T01:59:00", CEST),
            ("i-act-005", "2026-10-25T03:01:00", CET),
        )
        for activity_id, wall, offset in cases:
            with self.subTest(activity_id=activity_id):
                started_at = self.by_id[activity_id].started_at
                self.assertEqual(offset, started_at.utcoffset())
                self.assertEqual(wall, started_at.replace(tzinfo=None).isoformat())

    def test_fixture_provenance_is_provider_reported(self) -> None:
        record = self.by_id["i-act-001"]
        provenance = record.provenance

        self.assertIsInstance(provenance.provider, ProviderId)
        self.assertEqual(ProviderId.INTERVALS, provenance.provider)
        self.assertEqual(SourceKind.PROVIDER_REPORTED, provenance.source_kind)
        self.assertEqual("i-act-001", provenance.source_record_id)
        self.assertEqual(RecordingOrigin.UNKNOWN, provenance.recorded_by)
        self.assertEqual(RETRIEVED_AT, provenance.retrieved_at)
        self.assertEqual(INTERVALS_LABEL, provenance.label)
        self.assertEqual("Intervals.icu", provenance.label)

    def test_private_free_text_is_not_carried_into_records(self) -> None:
        private = "synthetic free text that is not a compacted field"

        for record in self.result.records:
            with self.subTest(activity_id=record.activity_id):
                self.assertNotIn(private, repr(record))


class DaylightSavingTests(unittest.TestCase):
    def test_spring_gap_moves_forward_under_the_pre_transition_offset(self) -> None:
        record = map_one(start_date_local="2026-03-29T02:30:00")

        self.assertEqual(CEST, record.started_at.utcoffset())
        self.assertEqual(
            "2026-03-29T03:30:00", record.started_at.replace(tzinfo=None).isoformat()
        )

    def test_autumn_overlap_takes_the_first_occurrence(self) -> None:
        record = map_one(start_date_local="2026-10-25T02:30:00")

        self.assertEqual(CEST, record.started_at.utcoffset())
        # Compare instants in UTC: PEP 495 makes an ambiguous zone-aware time
        # unequal to the same instant in another zone.
        self.assertEqual(
            datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
            record.started_at.astimezone(UTC),
        )


class StartAndIdentityTests(unittest.TestCase):
    def test_aware_start_date_wins_over_local_wall_time(self) -> None:
        record = map_one(
            start_date="2026-06-01T05:00:00Z",
            start_date_local="2026-06-01T07:00:00",
        )

        self.assertEqual(datetime(2026, 6, 1, 5, tzinfo=UTC), record.started_at)

    def test_aware_start_date_with_offset_keeps_its_instant(self) -> None:
        record = map_one(start_date="2026-06-01T07:00:00+02:00", start_date_local=None)

        self.assertEqual(timedelta(hours=2), record.started_at.utcoffset())

    def test_negative_offset_start_date_keeps_its_instant(self) -> None:
        record = map_one(start_date="2026-06-01T02:00:00-05:00", start_date_local=None)

        self.assertEqual(
            datetime(2026, 6, 1, 7, tzinfo=UTC), record.started_at.astimezone(UTC)
        )

    def test_naive_start_date_is_not_read_as_an_instant(self) -> None:
        # Read as Berlin wall time, 05:00 would be 03:00 UTC. The fallback wins.
        result = map_rows(
            [
                row(
                    start_date="2026-06-01T05:00:00",
                    start_date_local="2026-06-01T07:00:00",
                )
            ]
        )

        self.assertEqual(
            datetime(2026, 6, 1, 5, tzinfo=UTC),
            result.records[0].started_at.astimezone(UTC),
        )
        self.assertEqual(
            (MappingIssue("i-test", "start_date", IssueReason.INVALID_TYPE),),
            result.issues,
        )

    def test_naive_start_date_alone_drops_the_record(self) -> None:
        result = map_rows(
            [row(start_date="2026-06-01T05:00:00", start_date_local=None)]
        )

        self.assertEqual((), result.records)
        self.assertEqual(
            (MappingIssue("i-test", "start_date", IssueReason.INVALID_TYPE),),
            result.issues,
        )

    def test_invalid_start_date_falls_back_to_local_wall_time(self) -> None:
        result = map_rows(
            [row(start_date="not a time", start_date_local="2026-06-01T07:00:00")]
        )

        self.assertEqual(1, len(result.records))
        self.assertEqual(
            (MappingIssue("i-test", "start_date", IssueReason.INVALID_TYPE),),
            result.issues,
        )
        self.assertEqual(CEST, result.records[0].started_at.utcoffset())

    def test_non_text_start_date_is_reported_and_falls_back(self) -> None:
        result = map_rows([row(start_date=12, start_date_local="2026-06-01T07:00:00")])

        self.assertEqual(1, len(result.records))
        self.assertEqual(
            (MappingIssue("i-test", "start_date", IssueReason.INVALID_TYPE),),
            result.issues,
        )

    def test_missing_start_drops_the_record(self) -> None:
        result = map_rows([row(start_date_local=None)])

        self.assertEqual((), result.records)
        self.assertEqual(
            (MappingIssue("i-test", "start_date", IssueReason.MISSING),),
            result.issues,
        )

    def test_unparseable_start_drops_the_record(self) -> None:
        bad_starts = ("2026-06-01", "2026-02-30T07:00:00", "yesterday", 12345)
        for start in bad_starts:
            with self.subTest(start=type(start).__name__):
                result = map_rows([row(start_date_local=start)])

                self.assertEqual((), result.records)
                self.assertEqual(
                    (
                        MappingIssue(
                            "i-test", "start_date_local", IssueReason.INVALID_TYPE
                        ),
                    ),
                    result.issues,
                )

    def test_numeric_id_becomes_text(self) -> None:
        self.assertEqual("42", map_one(id=42).activity_id)

    def test_integer_id_too_wide_to_render_is_out_of_range_without_raising(
        self,
    ) -> None:
        # str() of an integer this wide raises ValueError under the digit limit.
        result = map_rows([row(id=10**5000)])

        self.assertEqual((), result.records)
        self.assertEqual(
            (MappingIssue(None, "id", IssueReason.OUT_OF_RANGE),), result.issues
        )

    def test_id_is_stripped(self) -> None:
        record = map_one(id="  i-42  ")

        self.assertEqual("i-42", record.activity_id)
        self.assertEqual("i-42", record.provenance.source_record_id)

    def test_missing_or_blank_id_drops_the_record(self) -> None:
        absent = row()
        del absent["id"]
        for fields in (absent, row(id=None), row(id="   ")):
            with self.subTest(fields=fields):
                result = map_rows([fields])

                self.assertEqual((), result.records)
                self.assertEqual(
                    (MappingIssue(None, "id", IssueReason.MISSING),), result.issues
                )

    def test_wrong_type_id_drops_the_record(self) -> None:
        for id_value in (True, 1.5, ["i-1"]):
            with self.subTest(id=type(id_value).__name__):
                result = map_rows([row(id=id_value)])

                self.assertEqual((), result.records)
                self.assertEqual(
                    (MappingIssue(None, "id", IssueReason.INVALID_TYPE),),
                    result.issues,
                )

    def test_overlong_id_is_out_of_range_without_a_record_reference(self) -> None:
        result = map_rows([row(id="x" * (MAX_ACTIVITY_ID_LENGTH + 1))])

        self.assertEqual((), result.records)
        self.assertEqual(
            (MappingIssue(None, "id", IssueReason.OUT_OF_RANGE),), result.issues
        )


class AliasTests(unittest.TestCase):
    def test_moving_time_precedes_elapsed_time(self) -> None:
        self.assertEqual(
            3000.0, map_one(moving_time=3000, elapsed_time=3600).duration_s
        )

    def test_elapsed_time_is_used_when_moving_time_is_absent(self) -> None:
        self.assertEqual(3600.0, map_one(elapsed_time=3600).duration_s)

    def test_zero_moving_time_is_out_of_range_and_elapsed_time_is_used(self) -> None:
        result = map_rows([row(moving_time=0, elapsed_time=3600)])

        self.assertEqual(3600.0, result.records[0].duration_s)
        self.assertEqual(
            (MappingIssue("i-test", "moving_time", IssueReason.OUT_OF_RANGE),),
            result.issues,
        )

    def test_zero_moving_time_alone_leaves_duration_none(self) -> None:
        self.assertIsNone(map_one(moving_time=0).duration_s)

    def test_one_second_is_the_smallest_accepted_duration(self) -> None:
        self.assertEqual(1.0, map_one(moving_time=1).duration_s)

    def test_invalid_moving_time_is_reported_and_elapsed_time_is_used(self) -> None:
        result = map_rows([row(moving_time="abc", elapsed_time=3600)])

        self.assertEqual(3600.0, result.records[0].duration_s)
        self.assertEqual(
            (MappingIssue("i-test", "moving_time", IssueReason.INVALID_NUMBER),),
            result.issues,
        )

    def test_average_watts_precedes_average_power(self) -> None:
        self.assertEqual(
            200.0,
            map_one(average_watts=200, average_power=150).avg_power,
        )
        self.assertEqual(150.0, map_one(average_power=150).avg_power)

    def test_legacy_average_heart_rate_alias_is_accepted(self) -> None:
        self.assertEqual(140.0, map_one(averageHR=140).avg_hr)

    def test_average_heart_rate_precedes_legacy_alias(self) -> None:
        self.assertEqual(142.0, map_one(average_heartrate=142, averageHR=140).avg_hr)

    def test_numeric_text_is_accepted(self) -> None:
        self.assertEqual(5400.0, map_one(moving_time=" 5400 ").duration_s)

    def test_zero_load_is_kept_with_the_intervals_model(self) -> None:
        record = map_one(icu_training_load=0)

        self.assertEqual(0.0, record.load)
        self.assertEqual(LoadModel.INTERVALS_TRAINING_LOAD, record.load_model)

    def test_missing_load_has_unknown_model(self) -> None:
        record = map_one()

        self.assertIsNone(record.load)
        self.assertEqual(LoadModel.UNKNOWN, record.load_model)

    def test_absent_optional_fields_are_none_not_zero_and_not_issues(self) -> None:
        result = map_rows([{"id": "i-bare", "start_date_local": "2026-06-01T07:00:00"}])
        record = result.records[0]

        self.assertEqual((), result.issues)
        self.assertEqual(
            (None, None, None, None, None, None),
            (
                record.duration_s,
                record.distance_m,
                record.load,
                record.avg_hr,
                record.avg_power,
                record.name,
            ),
        )
        self.assertEqual(Sport.OTHER, record.sport)
        self.assertEqual(Environment.UNKNOWN, record.environment)

    def test_blank_optional_values_are_missing_not_invalid(self) -> None:
        result = map_rows([row(distance="   ", name="")])

        self.assertEqual((), result.issues)
        self.assertIsNone(result.records[0].distance_m)
        self.assertIsNone(result.records[0].name)


class TypeClassificationTests(unittest.TestCase):
    def test_type_table_covers_every_known_workout_type_except_generic_ones(
        self,
    ) -> None:
        known = set(INTERVALS_WORKOUT_TYPES) - GENERIC_TYPES

        self.assertEqual(known, set(INTERVALS_ACTIVITY_TYPES))
        self.assertTrue(GENERIC_TYPES.isdisjoint(INTERVALS_ACTIVITY_TYPES))

    def test_every_table_type_maps_to_its_declared_sport_and_environment(self) -> None:
        for type_name, (sport, environment) in INTERVALS_ACTIVITY_TYPES.items():
            with self.subTest(type=type_name):
                record = map_one(type=type_name, name=None)

                self.assertEqual(sport, record.sport)
                self.assertEqual(environment, record.environment)

    def test_virtual_types_are_virtual(self) -> None:
        ride = map_one(type="VirtualRide")

        self.assertEqual(
            (Sport.RIDE, Environment.VIRTUAL), (ride.sport, ride.environment)
        )
        self.assertEqual(Environment.VIRTUAL, map_one(type="VirtualRun").environment)
        self.assertEqual(Environment.VIRTUAL, map_one(type="VirtualRow").environment)

    def test_outdoor_types_name_their_setting(self) -> None:
        for type_name in ("TrailRun", "OpenWaterSwim", "Hike", "BackcountrySki"):
            with self.subTest(type=type_name):
                self.assertEqual(
                    Environment.OUTDOOR, map_one(type=type_name).environment
                )

    def test_named_sports_map_to_canonical_sports(self) -> None:
        cases = (
            ("WeightTraining", Sport.STRENGTH),
            ("Rowing", Sport.ROW),
            ("Yoga", Sport.YOGA),
            ("Walk", Sport.WALK),
            ("NordicSki", Sport.NORDIC_SKI),
            ("RollerSki", Sport.NORDIC_SKI),
            ("AlpineSki", Sport.ALPINE_SKI),
            ("EBikeRide", Sport.RIDE),
            ("Snowshoe", Sport.OTHER),
        )
        for type_name, sport in cases:
            with self.subTest(type=type_name):
                self.assertEqual(sport, map_one(type=type_name).sport)

    def test_indoor_is_taken_from_text_for_known_types(self) -> None:
        self.assertEqual(
            Environment.INDOOR, map_one(type="Rowing", name="Indoor row").environment
        )
        self.assertEqual(
            Environment.VIRTUAL, map_one(type="Ride", name="Zwift race").environment
        )

    def test_type_table_environment_is_not_overridden_by_text(self) -> None:
        record = map_one(type="VirtualRide", name="Indoor session")

        self.assertEqual(Environment.VIRTUAL, record.environment)

    def test_unknown_type_uses_legacy_text_rules(self) -> None:
        record = map_one(type="Mystery", name="Zwift Tempo Run")

        self.assertEqual(
            (Sport.RUN, Environment.VIRTUAL), (record.sport, record.environment)
        )

    def test_unknown_type_with_treadmill_text_is_indoor(self) -> None:
        record = map_one(type="Mystery", name="Treadmill intervals")

        self.assertEqual(
            (Sport.OTHER, Environment.INDOOR), (record.sport, record.environment)
        )

    def test_generic_type_text_matches_legacy_activity_family(self) -> None:
        cases = (
            ("Workout", "Morning run"),
            ("Other", "Morning swim"),
            ("Workout", "Krafttraining"),
            ("Other", "Kraftrunde"),
            ("Workout", "Strength session"),
            ("Other", "Crowd"),
            ("Other", "brunch"),
            ("Other", "Easy spin"),
            ("Workout", "Bike commute"),
        )
        for type_name, name in cases:
            with self.subTest(type=type_name, name=name):
                fields = row(type=type_name, name=name)
                record = map_rows([fields]).records[0]

                self.assertEqual(
                    activity_kind(fields), legacy_activity_family(record.sport)
                )

    def test_missing_type_uses_the_name(self) -> None:
        fields = row(name="Morning ride")
        del fields["type"]
        record = map_rows([fields]).records[0]

        self.assertEqual(Sport.RIDE, record.sport)

    def test_activity_type_and_name_fields_classify_like_the_legacy_reader(
        self,
    ) -> None:
        zwift_run = map_one(type="Mystery", name=None, activityType="Zwift Run")
        swim = map_one(type="Mystery", name=None, activityName="Morning swim")

        self.assertEqual(
            (Sport.RUN, Environment.VIRTUAL),
            (zwift_run.sport, zwift_run.environment),
        )
        self.assertEqual(
            activity_kind({"type": "Mystery", "activityName": "Morning swim"}),
            legacy_activity_family(swim.sport),
        )

    def test_non_text_type_is_reported_and_falls_back_to_text(self) -> None:
        result = map_rows([row(type=7, name="Morning run")])

        self.assertEqual(Sport.RUN, result.records[0].sport)
        self.assertEqual(
            (MappingIssue("i-test", "type", IssueReason.INVALID_TYPE),),
            result.issues,
        )


class RecordingOriginTests(unittest.TestCase):
    def test_recording_origin_from_device_and_source_text(self) -> None:
        cases = (
            ({"source": "WAHOO"}, RecordingOrigin.WAHOO),
            ({"device_name": "ELEMNT BOLT"}, RecordingOrigin.WAHOO),
            ({"source": "GARMIN_CONNECT"}, RecordingOrigin.GARMIN),
            ({"device_name": "Garmin Edge"}, RecordingOrigin.GARMIN),
            ({"source": "ZWIFT"}, RecordingOrigin.ZWIFT),
            ({"source": "STRAVA"}, RecordingOrigin.STRAVA),
            ({"source": "MANUAL"}, RecordingOrigin.MANUAL),
            ({"source": "UPLOAD"}, RecordingOrigin.UPLOAD),
            ({"device_name": "Import file"}, RecordingOrigin.UPLOAD),
            ({"device_name": "Profile head unit"}, RecordingOrigin.UNKNOWN),
            (
                {"source": "SYNTHETIC", "external_id": "synthetic-ext-001"},
                RecordingOrigin.UNKNOWN,
            ),
        )
        for fields, expected in cases:
            with self.subTest(fields=fields):
                self.assertEqual(expected, map_one(**fields).provenance.recorded_by)

    def test_recording_device_wins_over_sync_source(self) -> None:
        record = map_one(source="STRAVA", device_name="Garmin Edge")

        self.assertEqual(RecordingOrigin.GARMIN, record.provenance.recorded_by)

    def test_wahoo_and_garmin_agree_with_the_legacy_device_source(self) -> None:
        cases = (
            {"source": "WAHOO"},
            {"device_name": "ELEMNT BOLT"},
            {"external_id": "garmin-1"},
            {"source": "STRAVA", "device_name": "Garmin Edge"},
            {"source": "GARMIN", "device_name": "Wahoo"},
            {"source": "SYNTHETIC"},
        )
        for fields in cases:
            with self.subTest(fields=fields):
                legacy = intervals_activity_device_source(fields)
                origin = map_one(**fields).provenance.recorded_by

                if legacy == "wahoo":
                    self.assertEqual(RecordingOrigin.WAHOO, origin)
                elif legacy == "garmin":
                    self.assertEqual(RecordingOrigin.GARMIN, origin)
                else:
                    self.assertNotIn(
                        origin, {RecordingOrigin.WAHOO, RecordingOrigin.GARMIN}
                    )

    def test_non_text_provenance_is_reported_and_unknown(self) -> None:
        result = map_rows([row(source=7)])

        self.assertEqual(
            RecordingOrigin.UNKNOWN, result.records[0].provenance.recorded_by
        )
        self.assertEqual(
            (MappingIssue("i-test", "source", IssueReason.INVALID_TYPE),),
            result.issues,
        )


class ProvenanceTests(unittest.TestCase):
    def test_provenance_names_the_intervals_source_record(self) -> None:
        record = map_one(id="i-prov")
        provenance = record.provenance

        self.assertEqual(ProviderId.INTERVALS, provenance.provider)
        self.assertEqual(SourceKind.PROVIDER_REPORTED, provenance.source_kind)
        self.assertEqual("i-prov", provenance.source_record_id)
        self.assertEqual(RETRIEVED_AT, provenance.retrieved_at)
        self.assertEqual("Intervals.icu", provenance.label)


class MalformedInputTests(unittest.TestCase):
    def test_non_dict_rows_are_dropped_with_one_row_issue_each(self) -> None:
        result = map_rows([None, 5, "text", ["id"], True, 1.5])

        self.assertEqual((), result.records)
        self.assertEqual(6, len(result.issues))
        for issue in result.issues:
            self.assertEqual(MappingIssue(None, "row", IssueReason.INVALID_TYPE), issue)

    def test_bad_numbers_become_none_and_the_record_is_kept(self) -> None:
        cases = (
            ({"distance": "1,5"}, "distance", IssueReason.INVALID_NUMBER),
            (
                {"icu_training_load": "nan"},
                "icu_training_load",
                IssueReason.INVALID_NUMBER,
            ),
            (
                {"average_heartrate": True},
                "average_heartrate",
                IssueReason.INVALID_NUMBER,
            ),
            ({"moving_time": float("inf")}, "moving_time", IssueReason.INVALID_NUMBER),
            ({"average_watts": -5}, "average_watts", IssueReason.OUT_OF_RANGE),
            ({"distance": 2_000_001}, "distance", IssueReason.OUT_OF_RANGE),
            ({"average_heartrate": 300}, "average_heartrate", IssueReason.OUT_OF_RANGE),
            (
                {"icu_training_load": 10_001},
                "icu_training_load",
                IssueReason.OUT_OF_RANGE,
            ),
            ({"moving_time": 604_801}, "moving_time", IssueReason.OUT_OF_RANGE),
            ({"moving_time": 0}, "moving_time", IssueReason.OUT_OF_RANGE),
        )
        for fields, field, reason in cases:
            with self.subTest(field=field, reason=reason):
                result = map_rows([row(name="Kept", **fields)])

                self.assertEqual(1, len(result.records))
                self.assertEqual("Kept", result.records[0].name)
                self.assertEqual(
                    (MappingIssue("i-test", field, reason),), result.issues
                )

    def test_bad_numbers_are_none_on_the_record(self) -> None:
        record = map_one(distance=[1], average_watts="200,5", moving_time=-1)

        self.assertIsNone(record.distance_m)
        self.assertIsNone(record.avg_power)
        self.assertIsNone(record.duration_s)

    def test_bounds_are_inclusive(self) -> None:
        record = map_one(
            moving_time=604_800,
            distance=2_000_000,
            icu_training_load=10_000,
            average_heartrate=250,
            average_watts=5_000,
        )

        self.assertEqual(604_800.0, record.duration_s)
        self.assertEqual(2_000_000.0, record.distance_m)
        self.assertEqual(10_000.0, record.load)
        self.assertEqual(250.0, record.avg_hr)
        self.assertEqual(5_000.0, record.avg_power)

    def test_name_is_stripped_and_truncated(self) -> None:
        self.assertEqual("Morning", map_one(name="  Morning  ").name)
        self.assertEqual("x" * MAX_NAME_LENGTH, map_one(name="x" * 250).name)

    def test_non_text_name_is_reported_and_none(self) -> None:
        result = map_rows([row(name=5)])

        self.assertIsNone(result.records[0].name)
        self.assertEqual(
            (MappingIssue("i-test", "name", IssueReason.INVALID_TYPE),), result.issues
        )

    def test_issues_never_carry_the_provider_value(self) -> None:
        secret = "SECRET-VALUE-123"
        result = map_rows(
            [
                # A short id is set as record_ref before later fields are read.
                row(id="i-leak", distance=secret, name=5, source=secret),
                # An over-long id is rejected before record_ref is set.
                row(id=secret * 20, start_date_local=secret),
            ]
        )

        self.assertIn(
            MappingIssue("i-leak", "distance", IssueReason.INVALID_NUMBER),
            result.issues,
        )
        self.assertIn(
            MappingIssue("i-leak", "name", IssueReason.INVALID_TYPE), result.issues
        )
        self.assertIn(MappingIssue(None, "id", IssueReason.OUT_OF_RANGE), result.issues)
        for issue in result.issues:
            self.assertNotIn(secret, repr(issue))

    def test_unknown_fields_are_never_passed_through(self) -> None:
        record = map_one(private_comment="SECRET-COMMENT", raw_blob={"x": 1})

        self.assertNotIn("SECRET-COMMENT", repr(record))
        self.assertNotIn("raw_blob", repr(record))

    def test_mixed_batch_keeps_good_rows_and_reports_bad_ones(self) -> None:
        result = map_rows(
            [
                row(id="i-good"),
                "garbage",
                row(id=None),
                row(id="i-good-2", distance="far"),
            ]
        )

        self.assertEqual(
            ["i-good", "i-good-2"], [r.activity_id for r in result.records]
        )
        self.assertEqual(
            (
                MappingIssue(None, "row", IssueReason.INVALID_TYPE),
                MappingIssue(None, "id", IssueReason.MISSING),
                MappingIssue("i-good-2", "distance", IssueReason.INVALID_NUMBER),
            ),
            result.issues,
        )


if __name__ == "__main__":
    unittest.main()
