"""Garmin activity summaries map to canonical ActivityRecord values without raising."""

from __future__ import annotations

import json
import math
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.canonical.local_time import local_date
from backend.canonical.mapping import IssueReason, MappingIssue, MappingResult
from backend.canonical.records import ActivityRecord
from backend.canonical.sports import classify_sport_text
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.providers.garmin_activity_mapping import (
    GARMIN_ACTIVITY_TYPES,
    MAPPER_VERSION,
    MAX_ACTIVITY_ID_LENGTH,
    MAX_NAME_LENGTH,
    map_garmin_activities,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "providers"
    / "garmin"
    / "activities.json"
)
BERLIN = ZoneInfo("Europe/Berlin")
RETRIEVED = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
SECRET_MARKER = "SYNTHETIC-SENTINEL-VALUE"
CEST = timedelta(hours=2)
CET = timedelta(hours=1)


def untyped(value: object) -> Any:
    """Pass deliberately wrong types through static checks."""
    return value


def _row(**overrides: object) -> dict[str, Any]:
    """A valid synthetic summary. Overriding a key with None makes it absent."""
    row: dict[str, Any] = {
        "activityId": 910009,
        "activityName": "Synthetic ride",
        "activityType": {"typeKey": "cycling"},
        "startTimeLocal": "2026-10-08 07:15:00",
        "distance": 20000.0,
        "duration": 3600.0,
        "averageHR": 140,
        "activityTrainingLoad": 50.0,
    }
    row.update(overrides)
    return row


def _map(*rows: object) -> MappingResult[ActivityRecord]:
    return map_garmin_activities(list(rows), zone=BERLIN, retrieved_at=RETRIEVED)


def _one(**overrides: object) -> tuple[ActivityRecord | None, tuple[MappingIssue, ...]]:
    result = _map(_row(**overrides))
    return (result.records[0] if result.records else None, result.issues)


def _fixture_rows() -> list[Any]:
    rows: list[Any] = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return rows


class VersionAndFixtureTests(unittest.TestCase):
    def test_mapper_version_is_one(self) -> None:
        self.assertEqual(1, MAPPER_VERSION)

    def test_fixture_maps_every_record_without_issues(self) -> None:
        result = _map(*_fixture_rows())

        self.assertEqual((), result.issues)
        self.assertEqual(
            ("910001", "910002"), tuple(r.activity_id for r in result.records)
        )

    def test_fixture_records_carry_canonical_units_and_values(self) -> None:
        first, second = _map(*_fixture_rows()).records

        self.assertIs(Sport.RIDE, first.sport)
        self.assertIs(Environment.UNKNOWN, first.environment)
        self.assertEqual(5400.0, first.duration_s)
        self.assertEqual(88500.0, first.distance_m)
        self.assertEqual(72.0, first.load)
        self.assertIs(LoadModel.GARMIN_TRAINING_LOAD, first.load_model)
        self.assertEqual(142.0, first.avg_hr)
        self.assertIsNone(first.avg_power)
        self.assertEqual("Synthetic morning ride", first.name)
        self.assertIs(Sport.RUN, second.sport)
        self.assertEqual(2400.0, second.duration_s)
        self.assertEqual(7600.0, second.distance_m)

    def test_fixture_local_times_are_read_in_the_athlete_zone(self) -> None:
        first, second = _map(*_fixture_rows()).records

        # October 2026 is still CEST in Berlin, two hours ahead of UTC.
        self.assertEqual(datetime(2026, 10, 8, 5, 15, tzinfo=UTC), first.started_at)
        self.assertEqual(datetime(2026, 10, 9, 16, 5, tzinfo=UTC), second.started_at)
        self.assertEqual(date(2026, 10, 8), local_date(first.started_at, BERLIN))

    def test_provenance_names_garmin_as_provider_reported(self) -> None:
        provenance = _map(*_fixture_rows()).records[0].provenance

        self.assertIs(ProviderId.GARMIN, provenance.provider)
        self.assertIs(SourceKind.PROVIDER_REPORTED, provenance.source_kind)
        self.assertEqual("910001", provenance.source_record_id)
        self.assertIs(RecordingOrigin.GARMIN, provenance.recorded_by)
        self.assertEqual(RETRIEVED, provenance.retrieved_at)
        self.assertEqual("Garmin Connect", provenance.label)


class StartTimeTests(unittest.TestCase):
    def test_naive_gmt_is_read_as_utc_and_preferred_over_local(self) -> None:
        record, issues = _one(
            startTimeGMT="2026-10-08T05:15:00.0", startTimeLocal="2026-10-08 09:00:00"
        )

        assert record is not None
        self.assertEqual(datetime(2026, 10, 8, 5, 15, tzinfo=UTC), record.started_at)
        self.assertEqual((), issues)

    def test_aware_gmt_keeps_its_offset(self) -> None:
        record, _ = _one(startTimeGMT="2026-10-08T07:15:00+02:00")

        assert record is not None
        self.assertEqual(CEST, record.started_at.utcoffset())
        self.assertEqual(datetime(2026, 10, 8, 5, 15, tzinfo=UTC), record.started_at)

    def test_gmt_with_z_suffix_is_accepted(self) -> None:
        record, _ = _one(startTimeGMT="2026-10-08T05:15:00Z")

        assert record is not None
        self.assertEqual(datetime(2026, 10, 8, 5, 15, tzinfo=UTC), record.started_at)

    def test_invalid_gmt_falls_back_to_local_with_issue(self) -> None:
        record, issues = _one(startTimeGMT="not a time")

        assert record is not None
        self.assertEqual(datetime(2026, 10, 8, 5, 15, tzinfo=UTC), record.started_at)
        self.assertEqual(
            (MappingIssue("910009", "startTimeGMT", IssueReason.INVALID_TYPE),),
            issues,
        )

    def test_gmt_unrepresentable_in_the_athlete_zone_falls_back(self) -> None:
        # Parsed in UTC this instant is valid, but Berlin is ahead of UTC and the
        # conversion would overflow datetime's range, so local_date could not read it.
        record, issues = _one(startTimeGMT="9999-12-31T23:59:59")

        assert record is not None
        self.assertEqual(datetime(2026, 10, 8, 5, 15, tzinfo=UTC), record.started_at)
        self.assertEqual(
            (MappingIssue("910009", "startTimeGMT", IssueReason.INVALID_TYPE),),
            issues,
        )

    def test_naive_local_time_uses_the_athlete_zone(self) -> None:
        record, issues = _one(startTimeLocal="2026-10-08 07:15:00")

        assert record is not None
        self.assertEqual(datetime(2026, 10, 8, 5, 15, tzinfo=UTC), record.started_at)
        self.assertEqual((), issues)

    def test_spring_gap_moves_forward_under_the_pre_transition_offset(self) -> None:
        # 2026-03-29: 02:30 does not exist in Berlin; it is read as 03:30 CEST.
        record, _ = _one(startTimeLocal="2026-03-29 02:30:00")

        assert record is not None
        self.assertEqual(datetime(2026, 3, 29, 1, 30, tzinfo=UTC), record.started_at)

    def test_autumn_overlap_takes_the_first_occurrence(self) -> None:
        # 2026-10-25: 02:30 happens twice; the first occurrence is CEST.
        record, _ = _one(startTimeLocal="2026-10-25 02:30:00")

        assert record is not None
        # Python never compares an ambiguous zone-aware value equal across zones,
        # so the instant is checked in UTC.
        self.assertEqual(
            datetime(2026, 10, 25, 0, 30, tzinfo=UTC),
            record.started_at.astimezone(UTC),
        )
        self.assertEqual(CEST, record.started_at.utcoffset())

    def test_time_after_the_autumn_overlap_is_standard_time(self) -> None:
        record, _ = _one(startTimeLocal="2026-10-25 03:30:00")

        assert record is not None
        self.assertEqual(datetime(2026, 10, 25, 2, 30, tzinfo=UTC), record.started_at)
        self.assertEqual(CET, record.started_at.astimezone(BERLIN).utcoffset())
        self.assertEqual(date(2026, 10, 25), local_date(record.started_at, BERLIN))

    def test_malformed_local_text_drops_the_record(self) -> None:
        record, issues = _one(startTimeLocal="2026-13-40 99:99:99")

        self.assertIsNone(record)
        self.assertEqual(
            (MappingIssue("910009", "startTimeLocal", IssueReason.INVALID_TYPE),),
            issues,
        )

    def test_date_only_text_is_not_a_provider_timestamp(self) -> None:
        record, issues = _one(startTimeLocal="2026-10-08")

        self.assertIsNone(record)
        self.assertEqual(IssueReason.INVALID_TYPE, issues[0].reason)

    def test_non_text_start_is_invalid(self) -> None:
        record, issues = _one(startTimeLocal=1_234_567_890)

        self.assertIsNone(record)
        self.assertEqual(IssueReason.INVALID_TYPE, issues[0].reason)

    def test_missing_start_drops_the_record_with_missing_issue(self) -> None:
        record, issues = _one(startTimeLocal=None)

        self.assertIsNone(record)
        self.assertEqual(
            (MappingIssue("910009", "startTime", IssueReason.MISSING),), issues
        )

    def test_both_invalid_start_fields_are_reported(self) -> None:
        record, issues = _one(startTimeGMT="bad", startTimeLocal="worse")

        self.assertIsNone(record)
        self.assertEqual(
            (
                MappingIssue("910009", "startTimeGMT", IssueReason.INVALID_TYPE),
                MappingIssue("910009", "startTimeLocal", IssueReason.INVALID_TYPE),
            ),
            issues,
        )

    def test_invalid_gmt_without_local_drops_without_missing_issue(self) -> None:
        record, issues = _one(startTimeGMT="bad", startTimeLocal=None)

        self.assertIsNone(record)
        self.assertEqual(
            (MappingIssue("910009", "startTimeGMT", IssueReason.INVALID_TYPE),),
            issues,
        )


class ActivityIdTests(unittest.TestCase):
    def test_integer_id_becomes_text(self) -> None:
        record, issues = _one(activityId=910001)

        assert record is not None
        self.assertEqual("910001", record.activity_id)
        self.assertEqual("910001", record.provenance.source_record_id)
        self.assertEqual((), issues)

    def test_text_id_is_stripped(self) -> None:
        record, _ = _one(activityId=" 910003 ")

        assert record is not None
        self.assertEqual("910003", record.activity_id)

    def test_missing_id_drops_the_record(self) -> None:
        record, issues = _one(activityId=None)

        self.assertIsNone(record)
        self.assertEqual(
            (MappingIssue(None, "activityId", IssueReason.MISSING),), issues
        )

    def test_blank_text_id_is_missing(self) -> None:
        record, issues = _one(activityId="   ")

        self.assertIsNone(record)
        self.assertEqual(IssueReason.MISSING, issues[0].reason)

    def test_boolean_and_fractional_ids_are_invalid(self) -> None:
        result = _map(_row(activityId=True), _row(activityId=1.5))

        self.assertEqual((), result.records)
        self.assertEqual(
            (
                MappingIssue(None, "activityId", IssueReason.INVALID_TYPE),
                MappingIssue(None, "activityId", IssueReason.INVALID_TYPE),
            ),
            result.issues,
        )

    def test_oversized_text_id_is_invalid(self) -> None:
        record, issues = _one(activityId="9" * (MAX_ACTIVITY_ID_LENGTH + 1))

        self.assertIsNone(record)
        self.assertEqual(
            (MappingIssue(None, "activityId", IssueReason.INVALID_TYPE),), issues
        )

    def test_free_text_is_not_an_identifier(self) -> None:
        for value in ("Felt tired after work FTP 240", "910 011", "a/b", "-7"):
            with self.subTest(value=value):
                record, issues = _one(activityId=value)

                self.assertIsNone(record)
                self.assertEqual(
                    (MappingIssue(None, "activityId", IssueReason.INVALID_TYPE),),
                    issues,
                )

    def test_text_id_may_use_letters_digits_underscore_and_hyphen(self) -> None:
        record, issues = _one(activityId="garmin_A1-2")

        assert record is not None
        self.assertEqual("garmin_A1-2", record.activity_id)
        self.assertEqual((), issues)

    def test_integer_beyond_the_text_digit_limit_is_invalid_not_raised(self) -> None:
        record, issues = _one(activityId=10**5000)

        self.assertIsNone(record)
        self.assertEqual(
            (MappingIssue(None, "activityId", IssueReason.INVALID_TYPE),), issues
        )

    def test_longest_valid_id_is_kept_and_used_as_the_issue_ref(self) -> None:
        long_id = "9" * MAX_ACTIVITY_ID_LENGTH

        record, issues = _one(activityId=long_id, distance="not a number")

        assert record is not None
        self.assertEqual(long_id, record.activity_id)
        self.assertEqual(
            (MappingIssue(long_id, "distance", IssueReason.INVALID_NUMBER),), issues
        )


class ActivityTypeTests(unittest.TestCase):
    def test_every_table_entry_maps_to_its_sport_and_environment(self) -> None:
        for key, (sport, environment) in GARMIN_ACTIVITY_TYPES.items():
            with self.subTest(type_key=key):
                record, issues = _one(
                    activityType={"typeKey": key}, activityName="Synthetic activity"
                )

                assert record is not None
                self.assertEqual(sport, record.sport)
                self.assertEqual(environment, record.environment)
                self.assertEqual((), issues)

    def test_table_keys_are_normalised_text_with_canonical_members(self) -> None:
        for key, (sport, environment) in GARMIN_ACTIVITY_TYPES.items():
            with self.subTest(type_key=key):
                self.assertEqual(key, key.strip().casefold())
                self.assertIsInstance(sport, Sport)
                self.assertIsInstance(environment, Environment)

    def test_legacy_text_classifier_misses_keys_the_table_covers(self) -> None:
        # Why the table exists: these keys classify as OTHER from text alone.
        for key in ("road_biking", "mountain_biking", "hiking"):
            with self.subTest(type_key=key):
                self.assertIs(Sport.OTHER, classify_sport_text(key))

        record, _ = _one(activityType={"typeKey": "road_biking"})
        assert record is not None
        self.assertIs(Sport.RIDE, record.sport)

    def test_type_key_is_case_and_space_insensitive(self) -> None:
        record, _ = _one(activityType={"typeKey": "  Road_Biking "})

        assert record is not None
        self.assertIs(Sport.RIDE, record.sport)

    def test_plain_text_activity_type_is_accepted(self) -> None:
        record, issues = _one(activityType="running")

        assert record is not None
        self.assertIs(Sport.RUN, record.sport)
        self.assertEqual((), issues)

    def test_unknown_key_falls_back_to_name_text(self) -> None:
        record, _ = _one(
            activityType={"typeKey": "fitness_equipment"},
            activityName="Synthetic morning ride",
        )

        assert record is not None
        self.assertIs(Sport.RIDE, record.sport)
        self.assertIs(Environment.UNKNOWN, record.environment)

    def test_unknown_key_takes_environment_from_name_text(self) -> None:
        record, _ = _one(
            activityType={"typeKey": "fitness_equipment"},
            activityName="Synthetic Zwift session",
        )

        assert record is not None
        self.assertIs(Sport.OTHER, record.sport)
        self.assertIs(Environment.VIRTUAL, record.environment)

    def test_unknown_key_without_terms_is_other_and_unknown(self) -> None:
        record, issues = _one(
            activityType={"typeKey": "fitness_equipment"},
            activityName="Synthetic session",
        )

        assert record is not None
        self.assertIs(Sport.OTHER, record.sport)
        self.assertIs(Environment.UNKNOWN, record.environment)
        self.assertEqual((), issues)

    def test_known_key_environment_is_refined_by_name_when_unknown(self) -> None:
        record, _ = _one(
            activityType={"typeKey": "running"},
            activityName="Synthetic treadmill run",
        )

        assert record is not None
        self.assertIs(Sport.RUN, record.sport)
        self.assertIs(Environment.INDOOR, record.environment)

    def test_known_indoor_key_is_not_overridden_by_name(self) -> None:
        record, _ = _one(
            activityType={"typeKey": "indoor_cycling"},
            activityName="Synthetic Zwift ride",
        )

        assert record is not None
        self.assertIs(Environment.INDOOR, record.environment)

    def test_name_classifies_the_activity_when_type_is_absent(self) -> None:
        record, issues = _one(activityType=None, activityName="Synthetic morning ride")

        assert record is not None
        self.assertIs(Sport.RIDE, record.sport)
        self.assertEqual((), issues)

    def test_absent_type_and_name_are_other_without_issue(self) -> None:
        record, issues = _one(activityType=None, activityName=None)

        assert record is not None
        self.assertIs(Sport.OTHER, record.sport)
        self.assertIs(Environment.UNKNOWN, record.environment)
        self.assertEqual((), issues)

    def test_empty_or_keyless_type_is_treated_as_absent(self) -> None:
        for activity_type in ({"typeKey": ""}, {"other": 1}, "  ", {"typeKey": None}):
            with self.subTest(activity_type=activity_type):
                record, issues = _one(activityType=activity_type)

                assert record is not None
                self.assertEqual((), issues)

    def test_non_text_type_key_is_invalid(self) -> None:
        record, issues = _one(activityType={"typeKey": 5})

        assert record is not None
        self.assertIs(Sport.RIDE, record.sport)
        self.assertEqual(
            (MappingIssue("910009", "activityType.typeKey", IssueReason.INVALID_TYPE),),
            issues,
        )

    def test_non_text_legacy_type_is_invalid(self) -> None:
        record, issues = _one(activityType=["running"])

        assert record is not None
        self.assertEqual(
            (MappingIssue("910009", "activityType", IssueReason.INVALID_TYPE),),
            issues,
        )


class DurationAndDistanceTests(unittest.TestCase):
    def test_duration_aliases_are_read_in_precedence_order(self) -> None:
        cases = (
            (
                {"duration": 3600.0, "movingDuration": 3000.0},
                3600.0,
            ),
            ({"duration": 3600.0, "movingTime": 3000.0}, 3600.0),
            ({"duration": None, "movingTime": 3200}, 3200.0),
            ({"duration": None, "movingTime": None}, None),
        )
        for overrides, expected in cases:
            with self.subTest(overrides=overrides):
                record, _ = _one(**overrides)

                assert record is not None
                self.assertEqual(expected, record.duration_s)

    def test_present_invalid_duration_does_not_fall_back_to_an_alias(self) -> None:
        record, issues = _one(duration="abc", movingTime=3000.0)

        assert record is not None
        self.assertIsNone(record.duration_s)
        self.assertEqual(
            (MappingIssue("910009", "duration", IssueReason.INVALID_NUMBER),),
            issues,
        )

    def test_zero_duration_is_a_measured_zero_not_missing(self) -> None:
        record, issues = _one(duration=0)

        assert record is not None
        self.assertEqual(0.0, record.duration_s)
        self.assertEqual((), issues)

    def test_numeric_text_is_accepted(self) -> None:
        record, issues = _one(distance="7600.5")

        assert record is not None
        self.assertEqual(7600.5, record.distance_m)
        self.assertEqual((), issues)

    def test_comma_decimal_and_non_finite_text_are_invalid_numbers(self) -> None:
        for value in ("7600,5", "nan", "inf", "1_000", "9" * 100):
            with self.subTest(value=value):
                record, issues = _one(distance=value)

                assert record is not None
                self.assertIsNone(record.distance_m)
                self.assertEqual(
                    (MappingIssue("910009", "distance", IssueReason.INVALID_NUMBER),),
                    issues,
                )

    def test_booleans_lists_and_nan_are_invalid_numbers(self) -> None:
        for value in (True, [20000], math.nan):
            with self.subTest(value=value):
                record, issues = _one(distance=value)

                assert record is not None
                self.assertIsNone(record.distance_m)
                self.assertEqual(IssueReason.INVALID_NUMBER, issues[0].reason)

    def test_null_and_blank_values_are_missing_without_issue(self) -> None:
        record, issues = _one(distance=None, averageHR="", activityTrainingLoad="   ")

        assert record is not None
        self.assertIsNone(record.distance_m)
        self.assertIsNone(record.avg_hr)
        self.assertIsNone(record.load)
        self.assertEqual((), issues)

    def test_out_of_range_values_become_none_with_issue(self) -> None:
        cases = (
            ({"duration": -1}, "duration"),
            ({"distance": 2_000_001}, "distance"),
            ({"averageHR": 0}, "averageHR"),
            ({"averageHR": 300}, "averageHR"),
            ({"activityTrainingLoad": 10_001}, "activityTrainingLoad"),
        )
        for overrides, field in cases:
            with self.subTest(overrides=overrides):
                record, issues = _one(**overrides)

                assert record is not None
                self.assertEqual(
                    (MappingIssue("910009", field, IssueReason.OUT_OF_RANGE),),
                    issues,
                )

    def test_valid_units_are_metres_seconds_and_bpm(self) -> None:
        record, _ = _one(distance=20000, duration=3600, averageHR=140)

        assert record is not None
        self.assertEqual(20000.0, record.distance_m)
        self.assertEqual(3600.0, record.duration_s)
        self.assertEqual(140.0, record.avg_hr)

    def test_heart_rate_bounds_are_inclusive(self) -> None:
        low, _ = _one(averageHR=20)
        high, _ = _one(averageHR=250)

        assert low is not None and high is not None
        self.assertEqual(20.0, low.avg_hr)
        self.assertEqual(250.0, high.avg_hr)


class TrainingLoadAndPowerTests(unittest.TestCase):
    def test_training_load_selects_the_garmin_model(self) -> None:
        record, _ = _one(activityTrainingLoad=72)

        assert record is not None
        self.assertEqual(72.0, record.load)
        self.assertIs(LoadModel.GARMIN_TRAINING_LOAD, record.load_model)

    def test_absent_training_load_leaves_the_model_unknown(self) -> None:
        record, issues = _one(activityTrainingLoad=None)

        assert record is not None
        self.assertIsNone(record.load)
        self.assertIs(LoadModel.UNKNOWN, record.load_model)
        self.assertEqual((), issues)

    def test_invalid_training_load_leaves_the_model_unknown(self) -> None:
        record, issues = _one(activityTrainingLoad="x")

        assert record is not None
        self.assertIsNone(record.load)
        self.assertIs(LoadModel.UNKNOWN, record.load_model)
        self.assertEqual(IssueReason.INVALID_NUMBER, issues[0].reason)

    def test_power_alias_prefers_avg_power_over_average_power(self) -> None:
        both, _ = _one(avgPower=250, averagePower=260)
        alias_only, _ = _one(avgPower=None, averagePower=260)

        assert both is not None and alias_only is not None
        self.assertEqual(250.0, both.avg_power)
        self.assertEqual(260.0, alias_only.avg_power)

    def test_out_of_range_power_becomes_none_with_issue(self) -> None:
        for value in (-5, 6000):
            with self.subTest(value=value):
                record, issues = _one(avgPower=value)

                assert record is not None
                self.assertIsNone(record.avg_power)
                self.assertEqual(
                    (MappingIssue("910009", "avgPower", IssueReason.OUT_OF_RANGE),),
                    issues,
                )


class NameTests(unittest.TestCase):
    def test_name_is_stripped(self) -> None:
        record, _ = _one(activityName="  Synthetic ride  ")

        assert record is not None
        self.assertEqual("Synthetic ride", record.name)

    def test_long_name_is_truncated_to_the_canonical_limit(self) -> None:
        record, _ = _one(activityName="A" * 250)

        assert record is not None
        self.assertEqual(MAX_NAME_LENGTH, len(record.name or ""))

    def test_blank_or_null_name_is_none_without_issue(self) -> None:
        for value in ("   ", None):
            with self.subTest(value=value):
                record, issues = _one(activityName=value)

                assert record is not None
                self.assertIsNone(record.name)
                self.assertEqual((), issues)

    def test_non_text_name_is_invalid(self) -> None:
        record, issues = _one(activityName=42)

        assert record is not None
        self.assertIsNone(record.name)
        self.assertEqual(
            (MappingIssue("910009", "activityName", IssueReason.INVALID_TYPE),),
            issues,
        )


class GarbageInputTests(unittest.TestCase):
    def test_non_list_rows_yield_no_records_and_one_issue(self) -> None:
        for rows in ({"activityId": 1}, None, "text", 5, (), _row()):
            with self.subTest(rows=type(rows).__name__):
                result = map_garmin_activities(
                    rows, zone=BERLIN, retrieved_at=RETRIEVED
                )

                self.assertEqual((), result.records)
                self.assertEqual(
                    (MappingIssue(None, "rows", IssueReason.INVALID_TYPE),),
                    result.issues,
                )

    def test_non_dict_rows_are_dropped_with_issue(self) -> None:
        result = _map(None, 5, "text", [], True, 1.5)

        self.assertEqual((), result.records)
        self.assertEqual(6, len(result.issues))
        for issue in result.issues:
            self.assertEqual(
                MappingIssue(None, "activity", IssueReason.INVALID_TYPE), issue
            )

    def test_hostile_rows_never_raise(self) -> None:
        hostile = (
            {
                "activityId": [1],
                "startTimeLocal": {},
                "activityType": 5,
                "duration": {"x": 1},
                "distance": "1e400",
                "averageHR": "1_000",
                "activityName": b"bytes",
                "avgPower": float("inf"),
            },
            {"activityId": {"nested": True}, "startTimeGMT": [], "avgPower": "-0"},
            {"activityId": 1, "startTimeLocal": "2026-10-08 07:15:00", "load": "x"},
        )

        result = _map(*hostile)

        self.assertIsInstance(result, MappingResult)
        self.assertEqual(("1",), tuple(r.activity_id for r in result.records))

    def test_issues_and_records_never_echo_provider_values(self) -> None:
        result = _map(
            _row(distance=SECRET_MARKER, duration=SECRET_MARKER),
            _row(activityId=910010, startTimeLocal=SECRET_MARKER),
            _row(activityType={"typeKey": 5, "other": SECRET_MARKER}),
        )

        self.assertNotIn(SECRET_MARKER, repr(result.issues))
        self.assertNotIn(SECRET_MARKER, repr(result.records))

    def test_unknown_provider_fields_are_not_passed_through(self) -> None:
        record, _ = _one(calories=SECRET_MARKER, ownerEmail=SECRET_MARKER)

        assert record is not None
        self.assertNotIn(SECRET_MARKER, repr(record))

    def test_mixed_batch_keeps_valid_rows_and_reports_the_rest(self) -> None:
        result = _map(
            _row(activityId=1),
            None,
            _row(activityId="2", startTimeLocal=None),
        )

        self.assertEqual(("1",), tuple(r.activity_id for r in result.records))
        self.assertEqual(
            (
                MappingIssue(None, "activity", IssueReason.INVALID_TYPE),
                MappingIssue("2", "startTime", IssueReason.MISSING),
            ),
            result.issues,
        )


class RetrievedAtTests(unittest.TestCase):
    def test_naive_retrieved_at_is_a_programming_error(self) -> None:
        naive = datetime.fromisoformat("2026-10-11T08:00:00")

        with self.assertRaisesRegex(ValueError, "retrieved_at"):
            map_garmin_activities([], zone=BERLIN, retrieved_at=naive)

    def test_non_datetime_retrieved_at_is_a_type_error(self) -> None:
        with self.assertRaisesRegex(TypeError, "retrieved_at"):
            map_garmin_activities(
                [], zone=BERLIN, retrieved_at=untyped("2026-10-11T08:00:00")
            )

    def test_zone_must_be_a_tzinfo(self) -> None:
        with self.assertRaisesRegex(TypeError, "zone"):
            map_garmin_activities([], zone=untyped(None), retrieved_at=RETRIEVED)


if __name__ == "__main__":
    unittest.main()
