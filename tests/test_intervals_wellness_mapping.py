"""Intervals.icu wellness and athlete threshold mappers, using synthetic fixtures."""

from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from backend.canonical.mapping import IssueReason, MappingResult
from backend.canonical.records import Observation
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.providers.intervals_wellness_mapping import (
    MAPPER_VERSION,
    map_intervals_athlete_thresholds,
    map_intervals_wellness,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "providers" / "intervals"
RETRIEVED_AT = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
OBSERVED_ON = date(2026, 10, 11)
ROW_DAY = "2026-10-08"
ATHLETE_ID = "i-synthetic-001"
TOLERANCE = 1e-9


def untyped(value: object) -> Any:
    """Pass deliberately wrong types through static checks."""
    return value


def naive(text: str) -> datetime:
    return datetime.fromisoformat(text)


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def wellness(rows: object) -> MappingResult[Observation]:
    return map_intervals_wellness(rows, retrieved_at=RETRIEVED_AT)


def thresholds(athlete: object) -> MappingResult[Observation]:
    return map_intervals_athlete_thresholds(
        athlete, observed_on=OBSERVED_ON, retrieved_at=RETRIEVED_AT
    )


def row(**fields: object) -> dict[str, object]:
    return {"id": ROW_DAY, **fields}


def issue_tuples(
    result: MappingResult[Observation],
) -> list[tuple[str | None, str, IssueReason]]:
    return [(issue.record_ref, issue.field, issue.reason) for issue in result.issues]


def kinds(result: MappingResult[Observation]) -> dict[MetricKind, float]:
    return {record.kind: record.value.value for record in result.records}


def only_value(result: MappingResult[Observation]) -> float:
    """Return the value of the single observation, asserting there is exactly one."""
    if len(result.records) != 1:
        raise AssertionError(f"expected one record, got {len(result.records)}")
    return result.records[0].value.value


def sport_records(
    result: MappingResult[Observation],
) -> set[tuple[MetricKind, Sport | None, float]]:
    return {
        (record.kind, record.sport, record.value.value) for record in result.records
    }


class ModuleContractTests(unittest.TestCase):
    def test_mapper_version_is_pinned(self) -> None:
        self.assertEqual(MAPPER_VERSION, 1)

    def test_naive_retrieved_at_is_a_programming_error_for_both_mappers(self) -> None:
        naive_time = naive("2026-10-11T08:00:00")
        with self.assertRaises(ValueError):
            map_intervals_wellness([], retrieved_at=naive_time)
        with self.assertRaises(ValueError):
            map_intervals_athlete_thresholds(
                {}, observed_on=OBSERVED_ON, retrieved_at=naive_time
            )

    def test_empty_inputs_yield_no_records_and_no_issues(self) -> None:
        empty_wellness = wellness([])
        self.assertEqual(empty_wellness.records, ())
        self.assertEqual(empty_wellness.issues, ())
        empty_athlete = thresholds({})
        self.assertEqual(empty_athlete.records, ())
        self.assertEqual(empty_athlete.issues, ())


class WellnessFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = wellness(load_fixture("wellness.json"))

    def test_fixture_maps_without_issues(self) -> None:
        self.assertEqual(self.result.issues, ())

    def test_each_fixture_row_yields_eight_observations(self) -> None:
        # Per row: weight, restingHR, hrv, sleepSecs, sleepScore, readiness,
        # ctl (ctLoad duplicates it) and atl (atlLoad duplicates it).
        self.assertEqual(len(self.result.records), 3 * 8)
        for day in ("2026-10-08", "2026-10-09", "2026-10-10"):
            day_kinds = {
                record.kind
                for record in self.result.records
                if record.observed_on == date.fromisoformat(day)
            }
            self.assertEqual(
                day_kinds,
                {
                    MetricKind.WEIGHT,
                    MetricKind.RESTING_HR,
                    MetricKind.HRV_RMSSD,
                    MetricKind.SLEEP_DURATION,
                    MetricKind.SLEEP_SCORE,
                    MetricKind.READINESS,
                    MetricKind.CTL,
                    MetricKind.ATL,
                },
            )

    def test_first_fixture_row_values_and_canonical_units(self) -> None:
        first = [
            record
            for record in self.result.records
            if record.observed_on == date(2026, 10, 8)
        ]
        values = {record.kind: record.value for record in first}
        self.assertAlmostEqual(values[MetricKind.WEIGHT].value, 70.4, places=9)
        self.assertEqual(values[MetricKind.WEIGHT].unit, "kg")
        self.assertEqual(values[MetricKind.RESTING_HR].value, 49)
        self.assertEqual(values[MetricKind.RESTING_HR].unit, "bpm")
        self.assertEqual(values[MetricKind.HRV_RMSSD].value, 64.0)
        self.assertEqual(values[MetricKind.HRV_RMSSD].unit, "ms")
        self.assertEqual(values[MetricKind.SLEEP_DURATION].value, 26400)
        self.assertEqual(values[MetricKind.SLEEP_DURATION].unit, "s")
        self.assertEqual(values[MetricKind.SLEEP_SCORE].value, 82)
        self.assertEqual(values[MetricKind.SLEEP_SCORE].unit, "score")
        self.assertEqual(values[MetricKind.READINESS].value, 74)
        self.assertEqual(values[MetricKind.READINESS].unit, "score")
        self.assertEqual(values[MetricKind.CTL].value, 52.1)
        self.assertEqual(values[MetricKind.CTL].unit, "load")
        self.assertEqual(values[MetricKind.ATL].value, 60.4)
        self.assertEqual(values[MetricKind.ATL].unit, "load")

    def test_sport_info_and_unlisted_keys_are_ignored_without_issues(self) -> None:
        kinds_seen = {record.kind for record in self.result.records}
        self.assertNotIn(MetricKind.FTP, kinds_seen)
        self.assertNotIn(MetricKind.TRAINING_LOAD, kinds_seen)
        for record in self.result.records:
            self.assertIsNone(record.sport)
            self.assertIsNone(record.observed_at)

    def test_provenance_names_the_intervals_row(self) -> None:
        record = self.result.records[0]
        provenance = record.provenance
        self.assertEqual(provenance.provider, ProviderId.INTERVALS)
        self.assertEqual(provenance.source_kind, SourceKind.PROVIDER_REPORTED)
        self.assertEqual(provenance.source_record_id, ROW_DAY)
        self.assertEqual(provenance.recorded_by, RecordingOrigin.UNKNOWN)
        self.assertEqual(provenance.retrieved_at, RETRIEVED_AT)
        self.assertEqual(provenance.label, "Intervals.icu")
        self.assertEqual(record.observed_on, date(2026, 10, 8))


class WellnessFieldTests(unittest.TestCase):
    def test_hrv_sdnn_maps_to_sdnn_in_milliseconds(self) -> None:
        result = wellness([row(hrvSDNN=45.5)])
        self.assertEqual(result.issues, ())
        self.assertEqual(len(result.records), 1)
        record = result.records[0]
        self.assertEqual(record.kind, MetricKind.HRV_SDNN)
        self.assertEqual(record.value.unit, "ms")
        self.assertAlmostEqual(record.value.value, 45.5, places=9)

    def test_body_fat_maps_to_percent(self) -> None:
        result = wellness([row(bodyFat=12.5)])
        self.assertEqual(result.issues, ())
        self.assertEqual(result.records[0].kind, MetricKind.BODY_FAT)
        self.assertEqual(result.records[0].value.unit, "%")
        self.assertEqual(result.records[0].value.value, 12.5)

    def test_vo2max_maps_to_ml_per_kg_min(self) -> None:
        result = wellness([row(vo2max=55)])
        self.assertEqual(result.records[0].kind, MetricKind.VO2MAX)
        self.assertEqual(result.records[0].value.unit, "ml/kg/min")

    def test_missing_fields_do_not_become_zero_observations(self) -> None:
        result = wellness([row(weight=None, ctl="", hrv=None)])
        self.assertEqual(result.records, ())
        self.assertEqual(result.issues, ())

    def test_row_without_mapped_fields_is_kept_empty_not_dropped_with_issue(
        self,
    ) -> None:
        result = wellness([row(tsb=-8.3, rampRate=1.2, sportInfo=[])])
        self.assertEqual(result.records, ())
        self.assertEqual(result.issues, ())

    def test_numeric_text_with_dot_decimal_is_accepted(self) -> None:
        result = wellness([row(weight=" 70.4 ")])
        self.assertEqual(only_value(result), 70.4)


class WellnessAliasPrecedenceTests(unittest.TestCase):
    def test_ctl_wins_over_ctload_when_both_differ(self) -> None:
        result = wellness([row(ctl=50, ctLoad=99)])
        self.assertEqual(kinds(result)[MetricKind.CTL], 50)
        self.assertEqual(len(result.records), 1)

    def test_ctload_is_used_when_ctl_is_none_or_empty(self) -> None:
        self.assertEqual(
            kinds(wellness([row(ctl=None, ctLoad=99)]))[MetricKind.CTL], 99
        )
        self.assertEqual(kinds(wellness([row(ctl="", ctLoad=98)]))[MetricKind.CTL], 98)

    def test_atl_wins_over_atlload_and_atlload_is_the_fallback(self) -> None:
        self.assertEqual(kinds(wellness([row(atl=40, atlLoad=99)]))[MetricKind.ATL], 40)
        self.assertEqual(
            kinds(wellness([row(atlLoad=77)]))[MetricKind.ATL],
            77,
        )

    def test_invalid_first_alias_is_not_replaced_by_the_later_alias(self) -> None:
        result = wellness([row(ctl="n/a", ctLoad=99)])
        self.assertNotIn(MetricKind.CTL, kinds(result))
        self.assertEqual(
            issue_tuples(result),
            [(ROW_DAY, "ctl", IssueReason.INVALID_NUMBER)],
        )

    def test_hrv_wins_over_hrv_ms(self) -> None:
        self.assertEqual(
            kinds(wellness([row(hrv=60, hrv_ms=70)]))[MetricKind.HRV_RMSSD], 60
        )
        self.assertEqual(kinds(wellness([row(hrv_ms=70)]))[MetricKind.HRV_RMSSD], 70)

    def test_body_fat_alias_order_is_bodyfat_then_body_fat_then_pct(self) -> None:
        self.assertEqual(
            kinds(wellness([row(bodyFat=10, body_fat=12, body_fat_pct=15)]))[
                MetricKind.BODY_FAT
            ],
            10,
        )
        self.assertEqual(
            kinds(wellness([row(body_fat=12, body_fat_pct=15)]))[MetricKind.BODY_FAT],
            12,
        )
        self.assertEqual(
            kinds(wellness([row(body_fat_pct=15)]))[MetricKind.BODY_FAT],
            15,
        )

    def test_resting_hr_accepts_snake_case_alias_when_camel_case_is_absent(
        self,
    ) -> None:
        self.assertEqual(
            kinds(wellness([row(resting_hr=47)]))[MetricKind.RESTING_HR], 47
        )
        self.assertEqual(
            kinds(wellness([row(restingHR=49, resting_hr=47)]))[MetricKind.RESTING_HR],
            49,
        )

    def test_sleep_seconds_is_the_fallback_for_sleep_secs(self) -> None:
        self.assertEqual(
            kinds(wellness([row(sleepSecs=None, sleep_seconds=21600)]))[
                MetricKind.SLEEP_DURATION
            ],
            21600,
        )

    def test_readiness_alias_chain_skips_empty_and_none_values(self) -> None:
        result = wellness(
            [
                row(
                    readiness=None,
                    readinessScore="",
                    readiness_score=None,
                    training_readiness=66,
                )
            ]
        )
        self.assertEqual(kinds(result)[MetricKind.READINESS], 66)

    def test_readiness_score_precedes_training_readiness(self) -> None:
        result = wellness([row(readinessScore=71, trainingReadiness=60)])
        self.assertEqual(kinds(result)[MetricKind.READINESS], 71)

    def test_vo2_max_snake_case_alias_is_accepted(self) -> None:
        self.assertEqual(kinds(wellness([row(vo2_max=52)]))[MetricKind.VO2MAX], 52)


class WellnessGarbageTests(unittest.TestCase):
    def test_non_list_top_level_input_yields_one_issue(self) -> None:
        for garbage in (None, {"id": ROW_DAY}, "rows", 3):
            with self.subTest(garbage=type(garbage).__name__):
                result = wellness(garbage)
                self.assertEqual(result.records, ())
                self.assertEqual(
                    issue_tuples(result),
                    [(None, "rows", IssueReason.INVALID_TYPE)],
                )

    def test_non_dict_rows_are_reported_as_row_issues(self) -> None:
        result = wellness([None, 5, "2026-10-08", [ROW_DAY], row(weight=70)])
        self.assertEqual(
            issue_tuples(result),
            [
                (None, "row", IssueReason.INVALID_TYPE),
                (None, "row", IssueReason.INVALID_TYPE),
                (None, "row", IssueReason.INVALID_TYPE),
                (None, "row", IssueReason.INVALID_TYPE),
            ],
        )
        self.assertEqual(only_value(result), 70)

    def test_row_identifier_problems_drop_the_row_with_an_issue(self) -> None:
        cases: list[tuple[dict[str, object], IssueReason]] = [
            ({"weight": 70}, IssueReason.MISSING),
            ({"id": None, "weight": 70}, IssueReason.MISSING),
            ({"id": "", "weight": 70}, IssueReason.MISSING),
            ({"id": 20261008, "weight": 70}, IssueReason.INVALID_TYPE),
            ({"id": True, "weight": 70}, IssueReason.INVALID_TYPE),
            ({"id": "2026-02-30", "weight": 70}, IssueReason.UNKNOWN_VALUE),
            ({"id": "2026-W41-3", "weight": 70}, IssueReason.UNKNOWN_VALUE),
            ({"id": "20261008", "weight": 70}, IssueReason.UNKNOWN_VALUE),
            ({"id": "2026-10-08T00:00:00", "weight": 70}, IssueReason.UNKNOWN_VALUE),
            ({"id": "２０２６-10-08", "weight": 70}, IssueReason.UNKNOWN_VALUE),
        ]
        for payload, reason in cases:
            with self.subTest(payload=payload):
                result = wellness([payload])
                self.assertEqual(result.records, ())
                self.assertEqual(issue_tuples(result), [(None, "id", reason)])

    def test_untrusted_identifier_text_is_never_echoed_in_issues(self) -> None:
        result = wellness([{"id": "secret-row-token <b>", "weight": 70}])
        self.assertEqual(result.records, ())
        self.assertEqual(
            issue_tuples(result), [(None, "id", IssueReason.UNKNOWN_VALUE)]
        )
        self.assertNotIn("secret-row-token", repr(result.issues))

    def test_wrong_value_types_are_reported_per_field(self) -> None:
        cases: list[tuple[object, IssueReason]] = [
            (True, IssueReason.INVALID_TYPE),
            ([70], IssueReason.INVALID_TYPE),
            ({"value": 70}, IssueReason.INVALID_TYPE),
            ("70,4", IssueReason.INVALID_NUMBER),
            ("abc", IssueReason.INVALID_NUMBER),
            (float("nan"), IssueReason.INVALID_NUMBER),
            (float("inf"), IssueReason.INVALID_NUMBER),
            (10**400, IssueReason.INVALID_NUMBER),
            (0, IssueReason.OUT_OF_RANGE),
            (1000, IssueReason.OUT_OF_RANGE),
        ]
        for value, reason in cases:
            with self.subTest(value=repr(value)[:40]):
                result = wellness([row(weight=untyped(value))])
                self.assertEqual(result.records, ())
                self.assertEqual(issue_tuples(result), [(ROW_DAY, "weight", reason)])

    def test_bad_value_does_not_drop_other_fields_of_the_row(self) -> None:
        result = wellness([row(weight="bad", restingHR=49, ctl=52.1)])
        self.assertEqual(
            issue_tuples(result),
            [(ROW_DAY, "weight", IssueReason.INVALID_NUMBER)],
        )
        self.assertEqual(
            kinds(result),
            {MetricKind.RESTING_HR: 49, MetricKind.CTL: 52.1},
        )

    def test_out_of_bounds_values_are_rejected_for_each_bounded_kind(self) -> None:
        result = wellness(
            [
                row(
                    bodyFat=0.5,
                    restingHR=300,
                    hrv=-1,
                    readiness=101,
                    sleepScore=-5,
                    vo2max=2,
                    ctl=20000,
                )
            ]
        )
        self.assertEqual(result.records, ())
        self.assertEqual(
            {(field, reason) for _, field, reason in issue_tuples(result)},
            {
                ("bodyFat", IssueReason.OUT_OF_RANGE),
                ("restingHR", IssueReason.OUT_OF_RANGE),
                ("hrv", IssueReason.OUT_OF_RANGE),
                ("readiness", IssueReason.OUT_OF_RANGE),
                ("sleepScore", IssueReason.OUT_OF_RANGE),
                ("vo2max", IssueReason.OUT_OF_RANGE),
                ("ctl", IssueReason.OUT_OF_RANGE),
            },
        )

    def test_nan_text_and_infinite_text_are_rejected(self) -> None:
        result = wellness([row(weight="nan", restingHR="inf")])
        self.assertEqual(result.records, ())
        self.assertEqual(
            {reason for _, _, reason in issue_tuples(result)},
            {IssueReason.INVALID_NUMBER},
        )

    def test_issues_never_carry_raw_values(self) -> None:
        result = wellness([row(weight="secret-weight-value")])
        self.assertNotIn("secret-weight-value", repr(result.issues))

    def test_non_finite_floats_are_not_observations(self) -> None:
        result = wellness([row(hrv=float("nan"))])
        self.assertEqual(result.records, ())


class WellnessProvenanceTests(unittest.TestCase):
    def test_observation_is_day_scoped_with_provider_provenance(self) -> None:
        result = wellness([row(weight=70.4)])
        record = result.records[0]
        self.assertEqual(record.observed_on, date(2026, 10, 8))
        self.assertIsNone(record.observed_at)
        self.assertIsNone(record.sport)
        self.assertEqual(record.provenance.provider, ProviderId.INTERVALS)
        self.assertEqual(record.provenance.source_kind, SourceKind.PROVIDER_REPORTED)
        self.assertEqual(record.provenance.source_record_id, ROW_DAY)
        self.assertEqual(record.provenance.recorded_by, RecordingOrigin.UNKNOWN)
        self.assertEqual(record.provenance.retrieved_at, RETRIEVED_AT)
        self.assertEqual(record.provenance.label, "Intervals.icu")

    def test_each_row_keeps_its_own_day_and_identifier(self) -> None:
        result = wellness([row(weight=70), {"id": "2026-10-09", "weight": 71}])
        self.assertEqual(
            [
                (record.observed_on, record.provenance.source_record_id)
                for record in result.records
            ],
            [
                (date(2026, 10, 8), ROW_DAY),
                (date(2026, 10, 9), "2026-10-09"),
            ],
        )


class AthleteFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.result = thresholds(load_fixture("athlete.json"))

    def test_fixture_maps_without_issues(self) -> None:
        self.assertEqual(self.result.issues, ())

    def test_sport_settings_map_thresholds_per_sport(self) -> None:
        self.assertEqual(
            sport_records(self.result),
            {
                (MetricKind.FTP, Sport.RIDE, 260),
                (MetricKind.THRESHOLD_HR, Sport.RIDE, 168),
                (MetricKind.MAX_HR, Sport.RIDE, 190),
                (MetricKind.FTP, Sport.RUN, 290),
                (MetricKind.THRESHOLD_HR, Sport.RUN, 172),
                (MetricKind.MAX_HR, Sport.RUN, 192),
                (MetricKind.THRESHOLD_PACE, Sport.RUN, 4.2),
            },
        )

    def test_top_level_icu_ftp_is_not_used_when_ride_ftp_is_mapped(self) -> None:
        ride_ftp = [
            record
            for record in self.result.records
            if record.kind is MetricKind.FTP and record.sport is Sport.RIDE
        ]
        self.assertEqual(len(ride_ftp), 1)

    def test_threshold_pace_already_in_metres_per_second_keeps_its_value(self) -> None:
        pace = [
            record
            for record in self.result.records
            if record.kind is MetricKind.THRESHOLD_PACE
        ]
        self.assertEqual(pace[0].value.unit, "m/s")
        self.assertAlmostEqual(pace[0].value.value, 4.2, places=9)

    def test_unmapped_settings_are_not_observations(self) -> None:
        kinds_seen = {record.kind for record in self.result.records}
        self.assertEqual(
            kinds_seen,
            {
                MetricKind.FTP,
                MetricKind.THRESHOLD_HR,
                MetricKind.MAX_HR,
                MetricKind.THRESHOLD_PACE,
            },
        )

    def test_provenance_names_the_athlete_record(self) -> None:
        for record in self.result.records:
            self.assertEqual(record.observed_on, OBSERVED_ON)
            self.assertIsNone(record.observed_at)
            self.assertEqual(record.provenance.provider, ProviderId.INTERVALS)
            self.assertEqual(
                record.provenance.source_kind, SourceKind.PROVIDER_REPORTED
            )
            self.assertEqual(record.provenance.source_record_id, ATHLETE_ID)
            self.assertEqual(record.provenance.recorded_by, RecordingOrigin.UNKNOWN)
            self.assertEqual(record.provenance.retrieved_at, RETRIEVED_AT)
            self.assertEqual(record.provenance.label, "Intervals.icu")


class AthleteFallbackTests(unittest.TestCase):
    def test_icu_ftp_is_a_ride_ftp_when_no_sport_setting_provides_one(self) -> None:
        result = thresholds({"id": "a1", "icu_ftp": 260})
        self.assertEqual(sport_records(result), {(MetricKind.FTP, Sport.RIDE, 260)})
        self.assertEqual(result.issues, ())

    def test_icu_ftp_is_used_when_ride_setting_has_no_ftp(self) -> None:
        result = thresholds(
            {
                "icu_ftp": 255,
                "sportSettings": [{"types": ["Ride"], "lthr": 160}],
            }
        )
        self.assertIn((MetricKind.FTP, Sport.RIDE, 255), sport_records(result))
        self.assertIn((MetricKind.THRESHOLD_HR, Sport.RIDE, 160), sport_records(result))

    def test_icu_ftp_is_used_when_ride_ftp_was_rejected(self) -> None:
        result = thresholds(
            {
                "icu_ftp": 255,
                "sportSettings": [{"types": ["Ride"], "ftp": "n/a"}],
            }
        )
        self.assertEqual(
            issue_tuples(result),
            [(None, "ftp", IssueReason.INVALID_NUMBER)],
        )
        self.assertEqual(sport_records(result), {(MetricKind.FTP, Sport.RIDE, 255)})

    def test_run_ftp_does_not_suppress_the_ride_fallback(self) -> None:
        result = thresholds(
            {
                "icu_ftp": 260,
                "sportSettings": [{"types": ["Run"], "ftp": 290}],
            }
        )
        self.assertEqual(
            sport_records(result),
            {(MetricKind.FTP, Sport.RUN, 290), (MetricKind.FTP, Sport.RIDE, 260)},
        )

    def test_invalid_icu_ftp_is_reported_under_its_own_name(self) -> None:
        result = thresholds({"icu_ftp": 5000})
        self.assertEqual(result.records, ())
        self.assertEqual(
            issue_tuples(result),
            [(None, "icu_ftp", IssueReason.OUT_OF_RANGE)],
        )

    def test_missing_icu_ftp_yields_nothing(self) -> None:
        result = thresholds({"id": "a1", "icu_ftp": None})
        self.assertEqual(result.records, ())
        self.assertEqual(result.issues, ())

    def test_indoor_ftp_is_the_fallback_for_ftp_within_a_setting(self) -> None:
        only_indoor = thresholds(
            {"sportSettings": [{"types": ["Ride"], "indoor_ftp": 240}]}
        )
        self.assertEqual(
            sport_records(only_indoor), {(MetricKind.FTP, Sport.RIDE, 240)}
        )
        both = thresholds(
            {
                "sportSettings": [
                    {"types": ["Ride"], "ftp": 260, "indoor_ftp": 240},
                ]
            }
        )
        self.assertEqual(sport_records(both), {(MetricKind.FTP, Sport.RIDE, 260)})


class ThresholdPaceTests(unittest.TestCase):
    def pace_result(self, value: object) -> MappingResult[Observation]:
        return thresholds(
            {"sportSettings": [{"types": ["Run"], "threshold_pace": untyped(value)}]}
        )

    def test_seconds_per_kilometre_convert_to_metres_per_second(self) -> None:
        self.assertAlmostEqual(only_value(self.pace_result(240)), 1000 / 240, places=9)

    def test_numeric_text_seconds_per_kilometre_convert_the_same_way(self) -> None:
        self.assertAlmostEqual(
            only_value(self.pace_result("240")), 1000 / 240, places=9
        )

    def test_values_below_twenty_are_already_metres_per_second(self) -> None:
        self.assertEqual(only_value(self.pace_result(4.2)), 4.2)
        self.assertEqual(only_value(self.pace_result(15)), 15)

    def test_metres_per_second_above_the_canonical_bound_are_rejected(self) -> None:
        result = self.pace_result(16)
        self.assertEqual(result.records, ())
        self.assertEqual(
            issue_tuples(result),
            [(None, "threshold_pace", IssueReason.OUT_OF_RANGE)],
        )

    def test_seconds_per_kilometre_below_the_bound_are_rejected(self) -> None:
        self.assertEqual(
            issue_tuples(self.pace_result(60)),
            [(None, "threshold_pace", IssueReason.OUT_OF_RANGE)],
        )

    def test_twenty_is_seconds_per_kilometre_and_therefore_out_of_range(self) -> None:
        self.assertEqual(
            issue_tuples(self.pace_result(20)),
            [(None, "threshold_pace", IssueReason.OUT_OF_RANGE)],
        )

    def test_zero_pace_means_unset_and_yields_nothing(self) -> None:
        for value in (0, "0", 0.0):
            with self.subTest(value=value):
                result = self.pace_result(value)
                self.assertEqual(result.records, ())
                self.assertEqual(result.issues, ())

    def test_negative_pace_is_rejected_without_dividing(self) -> None:
        self.assertEqual(
            issue_tuples(self.pace_result(-4)),
            [(None, "threshold_pace", IssueReason.OUT_OF_RANGE)],
        )

    def test_zero_pace_does_not_fall_through_to_another_alias(self) -> None:
        result = thresholds(
            {"sportSettings": [{"types": ["Run"], "threshold_pace": 0}]}
        )
        self.assertEqual(result.records, ())
        self.assertEqual(result.issues, ())

    def test_threshold_pace_is_mapped_for_run_entries_only(self) -> None:
        result = thresholds(
            {"sportSettings": [{"types": ["Swim"], "threshold_pace": 240}]}
        )
        self.assertEqual(result.records, ())
        self.assertEqual(result.issues, ())

    def test_malformed_pace_values_are_reported(self) -> None:
        self.assertEqual(
            issue_tuples(self.pace_result("fast")),
            [(None, "threshold_pace", IssueReason.INVALID_NUMBER)],
        )
        self.assertEqual(
            issue_tuples(self.pace_result(True)),
            [(None, "threshold_pace", IssueReason.INVALID_TYPE)],
        )


class SportSettingsAliasTests(unittest.TestCase):
    def test_snake_case_sport_settings_is_read_when_camel_case_is_absent(self) -> None:
        result = thresholds({"sport_settings": [{"types": ["Ride"], "ftp": 200}]})
        self.assertEqual(sport_records(result), {(MetricKind.FTP, Sport.RIDE, 200)})

    def test_camel_case_sport_settings_wins_when_both_are_present(self) -> None:
        result = thresholds(
            {
                "sportSettings": [{"types": ["Ride"], "ftp": 300}],
                "sport_settings": [{"types": ["Ride"], "ftp": 200}],
            }
        )
        self.assertEqual(sport_records(result), {(MetricKind.FTP, Sport.RIDE, 300)})

    def test_empty_camel_case_list_falls_back_to_snake_case(self) -> None:
        result = thresholds(
            {
                "sportSettings": [],
                "sport_settings": [{"types": ["Ride"], "ftp": 200}],
            }
        )
        self.assertEqual(sport_records(result), {(MetricKind.FTP, Sport.RIDE, 200)})

    def test_absent_or_empty_settings_yield_nothing_without_issues(self) -> None:
        empty_athletes: list[dict[str, object]] = [
            {},
            {"sportSettings": None},
            {"sportSettings": {}},
        ]
        for athlete in empty_athletes:
            with self.subTest(athlete=athlete):
                result = thresholds(athlete)
                self.assertEqual(result.records, ())
                self.assertEqual(result.issues, ())

    def test_non_list_settings_are_one_issue_and_no_records(self) -> None:
        result = thresholds({"id": ATHLETE_ID, "sportSettings": "invalid"})
        self.assertEqual(result.records, ())
        self.assertEqual(
            issue_tuples(result),
            [(ATHLETE_ID, "sportSettings", IssueReason.INVALID_TYPE)],
        )


class SportSettingEntryTests(unittest.TestCase):
    def test_first_types_text_selects_the_sport(self) -> None:
        cases = {
            "VirtualRide": Sport.RIDE,
            "WeightTraining": Sport.STRENGTH,
            "Rad": Sport.RIDE,
            "Workout": Sport.OTHER,
        }
        for types_text, sport in cases.items():
            with self.subTest(types=types_text):
                result = thresholds(
                    {"sportSettings": [{"types": [types_text], "ftp": 100}]}
                )
                self.assertEqual(sport_records(result), {(MetricKind.FTP, sport, 100)})

    def test_only_the_first_types_entry_classifies_the_sport(self) -> None:
        result = thresholds({"sportSettings": [{"types": ["Ride", "Run"], "ftp": 250}]})
        self.assertEqual(sport_records(result), {(MetricKind.FTP, Sport.RIDE, 250)})

    def test_missing_or_empty_types_skip_the_entry_with_an_issue(self) -> None:
        for entry in (
            {"ftp": 250},
            {"types": None, "ftp": 250},
            {"types": [], "ftp": 250},
        ):
            with self.subTest(entry=entry):
                result = thresholds({"id": ATHLETE_ID, "sportSettings": [entry]})
                self.assertEqual(result.records, ())
                self.assertEqual(
                    issue_tuples(result),
                    [(ATHLETE_ID, "types", IssueReason.MISSING)],
                )

    def test_malformed_types_skip_the_entry_with_an_issue(self) -> None:
        for types_value in ("Ride", 5, [5], [None]):
            with self.subTest(types=types_value):
                result = thresholds(
                    {"sportSettings": [{"types": untyped(types_value), "ftp": 250}]}
                )
                self.assertEqual(result.records, ())
                self.assertEqual(
                    issue_tuples(result),
                    [(None, "types", IssueReason.INVALID_TYPE)],
                )

    def test_non_dict_entry_is_one_issue_and_other_entries_still_map(self) -> None:
        result = thresholds(
            {
                "id": ATHLETE_ID,
                "sportSettings": [5, {"types": ["Run"], "lthr": 170}],
            }
        )
        self.assertEqual(
            issue_tuples(result),
            [(ATHLETE_ID, "sportSettings", IssueReason.INVALID_TYPE)],
        )
        self.assertEqual(
            sport_records(result), {(MetricKind.THRESHOLD_HR, Sport.RUN, 170)}
        )

    def test_max_hr_aliases_follow_the_reader_order(self) -> None:
        self.assertEqual(
            sport_records(
                thresholds(
                    {
                        "sportSettings": [
                            {"types": ["Ride"], "max_hr": 190, "maxHR": 180}
                        ]
                    }
                )
            ),
            {(MetricKind.MAX_HR, Sport.RIDE, 190)},
        )
        self.assertEqual(
            sport_records(
                thresholds(
                    {"sportSettings": [{"types": ["Ride"], "maxHeartRate": 185}]}
                )
            ),
            {(MetricKind.MAX_HR, Sport.RIDE, 185)},
        )


class SportSettingValueTests(unittest.TestCase):
    def test_malformed_threshold_values_are_reported_without_dropping_siblings(
        self,
    ) -> None:
        result = thresholds(
            {
                "id": ATHLETE_ID,
                "sportSettings": [
                    {
                        "types": ["Ride"],
                        "ftp": "260,5",
                        "lthr": True,
                        "max_hr": 300,
                        "indoor_ftp": None,
                    },
                ],
            }
        )
        self.assertEqual(result.records, ())
        self.assertEqual(
            {(field, reason) for _, field, reason in issue_tuples(result)},
            {
                ("ftp", IssueReason.INVALID_NUMBER),
                ("lthr", IssueReason.INVALID_TYPE),
                ("max_hr", IssueReason.OUT_OF_RANGE),
            },
        )

    def test_zero_ftp_is_unset_and_does_not_read_indoor_ftp(self) -> None:
        result = thresholds(
            {
                "icu_ftp": 260,
                "sportSettings": [
                    {"types": ["Ride"], "ftp": 0, "indoor_ftp": 240},
                ],
            }
        )
        self.assertEqual(sport_records(result), {(MetricKind.FTP, Sport.RIDE, 260)})
        self.assertEqual(result.issues, ())

    def test_zero_lthr_and_max_hr_are_unset_without_issues(self) -> None:
        for field in ("lthr", "max_hr"):
            with self.subTest(field=field):
                result = thresholds({"sportSettings": [{"types": ["Ride"], field: 0}]})
                self.assertEqual(result.records, ())
                self.assertEqual(result.issues, ())

    def test_duplicate_sport_entries_both_map_in_input_order(self) -> None:
        result = thresholds(
            {
                "sportSettings": [
                    {"types": ["Ride"], "ftp": 260},
                    {"types": ["Ride"], "ftp": 250},
                ]
            }
        )
        self.assertEqual(
            [
                (record.kind, record.sport, record.value.value)
                for record in result.records
            ],
            [
                (MetricKind.FTP, Sport.RIDE, 260),
                (MetricKind.FTP, Sport.RIDE, 250),
            ],
        )

    def test_secret_threshold_text_is_never_echoed(self) -> None:
        result = thresholds(
            {"sportSettings": [{"types": ["Ride"], "ftp": "secret-ftp-value"}]}
        )
        self.assertNotIn("secret-ftp-value", repr(result.issues))


class AthleteRecordIdentityTests(unittest.TestCase):
    def test_athlete_id_is_the_source_record_id_when_text(self) -> None:
        result = thresholds({"id": "i-1", "icu_ftp": 260})
        self.assertEqual(result.records[0].provenance.source_record_id, "i-1")

    def test_missing_or_unusable_athlete_id_is_recorded_as_none(self) -> None:
        for athlete in (
            {"icu_ftp": 260},
            {"id": 42, "icu_ftp": 260},
            {"id": "   ", "icu_ftp": 260},
            {"id": "x" * 300, "icu_ftp": 260},
            {"id": "x" * 201, "icu_ftp": 260},
            {"id": "secret id <b>", "icu_ftp": 260},
        ):
            with self.subTest(athlete=repr(athlete)[:30]):
                result = thresholds(athlete)
                self.assertEqual(len(result.records), 1)
                self.assertIsNone(result.records[0].provenance.source_record_id)

    def test_issues_reference_only_a_usable_athlete_id(self) -> None:
        result = thresholds({"id": 42, "icu_ftp": 5000})
        self.assertEqual(
            issue_tuples(result), [(None, "icu_ftp", IssueReason.OUT_OF_RANGE)]
        )

    def test_overlong_athlete_id_never_breaks_a_sport_setting_issue(self) -> None:
        result = thresholds({"id": "x" * 220, "sportSettings": "bad"})
        self.assertEqual(result.records, ())
        self.assertEqual(
            issue_tuples(result),
            [(None, "sportSettings", IssueReason.INVALID_TYPE)],
        )


class AthleteGarbageTests(unittest.TestCase):
    def test_non_dict_athlete_yields_one_issue(self) -> None:
        garbage_values: list[object] = [None, [], "athlete", 7]
        for garbage in garbage_values:
            with self.subTest(garbage=type(garbage).__name__):
                result = thresholds(garbage)
                self.assertEqual(result.records, ())
                self.assertEqual(
                    issue_tuples(result),
                    [(None, "athlete", IssueReason.INVALID_TYPE)],
                )


if __name__ == "__main__":
    unittest.main()
