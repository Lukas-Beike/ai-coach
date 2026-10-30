"""Parity between the Intervals.icu mappers and the legacy readers.

The legacy readers in ``backend.performance`` and ``backend.activities`` consume
compact snapshots. Each comparison therefore runs the synthetic Intervals.icu
fixtures through ``compact_snapshot`` and through the mappers, in both raw and
compact form, and checks that the mapped values agree with the legacy readers.

Known differences are named test cases with a comment explaining them. Pinned
expectations record what the compact form drops; they describe the compact form
and are not a reason to add fields to it. Everything here is synthetic and in
memory: no network, no DATA_DIR, no provider account.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from canonical_recovery_support import mapped_recovery_inputs
from performance_day_support import current_days, latest_day

from backend.activities.identity import activity_kind
from backend.athlete.local_date import iso_date_prefix
from backend.canonical.mapping import IssueReason, MappingResult
from backend.canonical.records import ActivityRecord, Observation
from backend.canonical.sports import legacy_activity_family
from backend.canonical.vocabulary import MetricKind, Sport
from backend.performance.canonical_inputs import CanonicalPerformanceInputs
from backend.performance.current_metrics import current_performance_metrics
from backend.performance.load import activity_rollup
from backend.performance.load_context import performance_load_context
from backend.performance.recovery_context import performance_recovery_context
from backend.planning.context import compact_snapshot
from backend.providers.intervals_activity_mapping import map_intervals_activities
from backend.providers.intervals_wellness_mapping import (
    map_intervals_athlete_thresholds,
    map_intervals_wellness,
)

FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures" / "providers" / "intervals"
BERLIN = ZoneInfo("Europe/Berlin")
RETRIEVED_AT = datetime(2026, 10, 11, 8, 0, tzinfo=UTC)
SYNCED_AT = "2026-10-10T06:00:00+00:00"
TODAY = date(2026, 10, 10)
LATEST_DAY = "2026-10-10"
# The fixtures include two October 25 activities, so the rollup window must reach them.
ROLLUP_END = date(2026, 10, 31)

GARMIN_METRIC_KEYS = (
    "weight_kg",
    "cycling_ftp_watts",
    "run_threshold_watts",
    "run_threshold_pace_seconds_per_km",
    "bike_threshold_hr_bpm",
    "run_threshold_hr_bpm",
    "cycling_vo2max_ml_kg_min",
    "running_vo2max_ml_kg_min",
    "cycling_max_hr_bpm",
    "running_max_hr_bpm",
    "run_5k_seconds",
    "run_10k_seconds",
    "run_half_marathon_seconds",
    "run_marathon_seconds",
)

# Every key the mappers read from one provider row, listed by hand so that a
# change to a mapper alias chain shows up in this file.
MAPPED_ACTIVITY_KEYS = frozenset(
    {
        "id",
        "start_date",
        "start_date_local",
        "moving_time",
        "elapsed_time",
        "distance",
        "icu_training_load",
        "average_heartrate",
        "averageHR",
        "average_watts",
        "average_power",
        "name",
        "type",
        "sport",
        "sport_type",
        "activityType",
        "activityName",
        "source",
        "device_name",
        "external_id",
    }
)
MAPPED_WELLNESS_KEYS = frozenset(
    {
        "id",
        "weight",
        "bodyFat",
        "body_fat",
        "body_fat_pct",
        "restingHR",
        "resting_hr",
        "hrv",
        "hrv_ms",
        "hrvSDNN",
        "sleepSecs",
        "sleep_seconds",
        "sleepScore",
        "readiness",
        "readinessScore",
        "readiness_score",
        "trainingReadiness",
        "training_readiness",
        "vo2max",
        "vo2_max",
        "ctl",
        "ctLoad",
        "atl",
        "atlLoad",
    }
)
MAPPED_SPORT_SETTING_KEYS = frozenset(
    {
        "types",
        "ftp",
        "indoor_ftp",
        "lthr",
        "max_hr",
        "maxHR",
        "maxHeartRate",
        "max_heartrate",
        "threshold_pace",
        "vo2max",
        "vo2_max",
        "cycling_vo2max",
        "running_vo2max",
    }
)


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text(encoding="utf-8"))


def compact_form(athlete: Any, activities: Any, wellness: Any) -> dict[str, Any]:
    return compact_snapshot(
        athlete, activities, wellness, [], all_sync_days=42, synced_at=SYNCED_AT
    )


def fixture_snapshot() -> dict[str, Any]:
    return compact_form(
        load_fixture("athlete"),
        load_fixture("activities"),
        load_fixture("wellness"),
    )


def empty_garmin_metrics() -> dict[str, dict[str, Any]]:
    return {
        key: {"value": None, "unit": "", "source": None, "note": ""}
        for key in GARMIN_METRIC_KEYS
    }


def legacy_metrics(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return current_performance_metrics(
        snapshot,
        {},
        empty_garmin_metrics(),
        latest_wellness=latest_day(snapshot.get("recent_wellness", [])),
    )


def map_activities(rows: object) -> MappingResult[ActivityRecord]:
    return map_intervals_activities(rows, zone=BERLIN, retrieved_at=RETRIEVED_AT)


def map_wellness(rows: object) -> MappingResult[Observation]:
    return map_intervals_wellness(rows, retrieved_at=RETRIEVED_AT)


def map_thresholds(athlete: object) -> MappingResult[Observation]:
    return map_intervals_athlete_thresholds(
        athlete, observed_on=TODAY, retrieved_at=RETRIEVED_AT
    )


def first_value(
    result: MappingResult[Observation],
    kind: MetricKind,
    *,
    day: str | None = None,
    sport: Sport | None = None,
) -> float | None:
    for observation in result.records:
        if observation.kind is not kind or observation.sport != sport:
            continue
        if day is not None and observation.observed_on.isoformat() != day:
            continue
        return observation.value.value
    return None


def expect_value(
    result: MappingResult[Observation],
    kind: MetricKind,
    *,
    day: str | None = None,
    sport: Sport | None = None,
) -> float:
    value = first_value(result, kind, day=day, sport=sport)
    if value is None:
        raise AssertionError(f"no {kind.value} observation for sport {sport}")
    return value


def records_by_id(result: MappingResult[ActivityRecord]) -> dict[str, ActivityRecord]:
    return {record.activity_id: record for record in result.records}


def wall_clock(record: ActivityRecord) -> datetime:
    return record.started_at.astimezone(BERLIN).replace(tzinfo=None)


class ActivityParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw = load_fixture("activities")
        self.compact = fixture_snapshot()["recent_activities"]

    def test_fixture_rows_map_without_issues_in_both_forms(self) -> None:
        for rows in (self.raw, self.compact):
            with self.subTest(form="raw" if rows is self.raw else "compact"):
                result = map_activities(rows)
                self.assertEqual(result.issues, ())
                self.assertEqual(len(result.records), len(self.raw))

    def test_starts_match_the_legacy_wall_clock_and_day(self) -> None:
        for rows in (self.raw, self.compact):
            records = records_by_id(map_activities(rows))
            for row in rows:
                with self.subTest(row=row["id"]):
                    record = records[row["id"]]
                    self.assertEqual(
                        wall_clock(record),
                        datetime.fromisoformat(row["start_date_local"]),
                    )
                    self.assertEqual(
                        record.started_at.astimezone(BERLIN).date().isoformat(),
                        iso_date_prefix(row["start_date_local"]),
                    )

    def test_duration_distance_and_load_match_the_legacy_fields(self) -> None:
        records = records_by_id(map_activities(self.raw))
        for row in self.raw:
            with self.subTest(row=row["id"]):
                record = records[row["id"]]
                self.assertEqual(record.duration_s, row["moving_time"])
                self.assertEqual(record.distance_m, row["distance"])
                self.assertEqual(record.load, row["icu_training_load"])

    def test_rollup_totals_match_the_mapped_records(self) -> None:
        records = map_activities(self.compact).records
        rollup = activity_rollup(self.compact, 400, ROLLUP_END)
        self.assertEqual(rollup["sessions"], len(records))
        self.assertEqual(
            rollup["duration_hours"],
            round(sum(record.duration_s or 0.0 for record in records) / 3600, 1),
        )
        self.assertEqual(
            rollup["training_load"],
            round(sum(record.load or 0.0 for record in records), 1),
        )

    def test_sport_family_matches_legacy_activity_kind(self) -> None:
        for rows in (self.raw, self.compact):
            records = records_by_id(map_activities(rows))
            for row in rows:
                with self.subTest(row=row["id"]):
                    self.assertEqual(
                        legacy_activity_family(records[row["id"]].sport),
                        activity_kind(row),
                    )

    def test_raw_and_compact_forms_map_to_identical_records(self) -> None:
        self.assertEqual(
            map_activities(self.raw).records,
            map_activities(self.compact).records,
        )

    def test_compact_form_drops_sport_identity_fields(self) -> None:
        # ``sport`` is not in the compact activity fields, so only ``type`` and
        # ``name`` reach the compact row. The legacy reader sees that same compact
        # row, so the mapper and activity_kind still agree on the compact form.
        row = {
            "id": "syn-act-901",
            "start_date_local": "2026-10-07T06:30:00",
            "type": "Other",
            "sport": "Run",
            "name": "Synthetic session",
        }
        compact_row = compact_form({}, [row], [])["recent_activities"][0]
        raw_record = records_by_id(map_activities([row]))["syn-act-901"]
        compact_record = records_by_id(map_activities([compact_row]))["syn-act-901"]
        self.assertEqual(raw_record.sport, Sport.RUN)
        self.assertEqual(compact_record.sport, Sport.OTHER)
        self.assertEqual(legacy_activity_family(raw_record.sport), activity_kind(row))
        self.assertEqual(
            legacy_activity_family(compact_record.sport),
            activity_kind(compact_row),
        )

    def test_compact_form_drops_exact_start_and_average_power(self) -> None:
        row = {
            "id": "syn-act-902",
            "start_date": "2026-10-07T05:00:00Z",
            "start_date_local": "2026-10-07T06:30:00",
            "type": "Ride",
            "average_power": 210,
        }
        compact_row = compact_form({}, [row], [])["recent_activities"][0]
        raw_record = records_by_id(map_activities([row]))["syn-act-902"]
        compact_record = records_by_id(map_activities([compact_row]))["syn-act-902"]
        self.assertEqual(raw_record.started_at, datetime(2026, 10, 7, 5, 0, tzinfo=UTC))
        self.assertEqual(raw_record.avg_power, 210)
        # 06:30 in Europe/Berlin summer time is 04:30 UTC.
        self.assertEqual(
            compact_record.started_at, datetime(2026, 10, 7, 4, 30, tzinfo=UTC)
        )
        self.assertIsNone(compact_record.avg_power)

    def test_pinned_activity_keys_missing_from_the_compact_form(self) -> None:
        row = {key: f"synthetic-{key}" for key in MAPPED_ACTIVITY_KEYS}
        compact_row = compact_form({}, [row], [])["recent_activities"][0]
        self.assertEqual(
            MAPPED_ACTIVITY_KEYS - set(compact_row),
            frozenset(
                {
                    "start_date",
                    "averageHR",
                    "average_power",
                    "sport",
                    "sport_type",
                    "activityType",
                    "activityName",
                }
            ),
        )

    # Known deviations, named so that each one stays visible.

    def test_start_precedence_prefers_the_exact_instant(self) -> None:
        # Deviation: the legacy readers bucket days by start_date_local, while the
        # mapper uses an aware start_date when one is sent. The rows are deliberately
        # inconsistent so that the two readings differ.
        row = {
            "id": "syn-act-903",
            "start_date": "2026-09-30T12:00:00Z",
            "start_date_local": "2026-10-07T06:30:00",
            "type": "Ride",
        }
        record = records_by_id(map_activities([row]))["syn-act-903"]
        self.assertEqual(record.started_at, datetime(2026, 9, 30, 12, 0, tzinfo=UTC))
        self.assertEqual(activity_rollup([row], 1, date(2026, 10, 7))["sessions"], 1)
        self.assertEqual(activity_rollup([row], 1, date(2026, 9, 30))["sessions"], 0)

    def test_type_table_wins_over_name_text_where_legacy_text_order_differs(
        self,
    ) -> None:
        # Deviation: a known Intervals type is classified from the type table.
        # activity_kind classifies the joined text in legacy term order, so a word
        # in the name can change its family. The mapper follows the type.
        cases = (
            ({"type": "Run", "name": "Synthetic bike check"}, Sport.RUN, "cycling"),
            ({"type": "Walk", "name": "Morning run"}, Sport.WALK, "running"),
        )
        for fields, sport, legacy_family in cases:
            row = {
                "id": "syn-act-904",
                "start_date_local": "2026-10-07T06:30:00",
                **fields,
            }
            with self.subTest(type=fields["type"]):
                record = records_by_id(map_activities([row]))["syn-act-904"]
                self.assertEqual(record.sport, sport)
                self.assertEqual(activity_kind(row), legacy_family)
                self.assertNotEqual(legacy_activity_family(sport), legacy_family)

    def test_elapsed_time_fills_duration_where_the_rollup_counts_zero(self) -> None:
        # Deviation: the mapper follows activity_validation and falls back to
        # elapsed_time, but the load rollup reads moving_time only.
        row = {
            "id": "syn-act-905",
            "start_date_local": "2026-10-07T06:30:00",
            "type": "Run",
            "elapsed_time": 1800,
        }
        record = records_by_id(map_activities([row]))["syn-act-905"]
        self.assertEqual(record.duration_s, 1800)
        rollup = activity_rollup([row], 7, date(2026, 10, 10))
        self.assertEqual(rollup["sessions"], 1)
        self.assertEqual(rollup["duration_hours"], 0.0)


class WellnessParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = fixture_snapshot()
        self.rows = self.snapshot["recent_wellness"]

    def test_load_alias_chains_match_the_legacy_load_context(self) -> None:
        result = map_wellness(self.rows)
        for row in self.rows:
            with self.subTest(day=row["id"]):
                day = date.fromisoformat(row["id"])
                ctl = expect_value(result, MetricKind.CTL, day=row["id"])
                atl = expect_value(result, MetricKind.ATL, day=row["id"])
                load = performance_load_context(
                    self.snapshot["recent_activities"],
                    current_days([row]),
                    TODAY,
                    canonical=CanonicalPerformanceInputs(
                        wellness_day=day, ctl=ctl, atl=atl
                    ),
                )["load"]
                self.assertEqual(
                    expect_value(result, MetricKind.CTL, day=row["id"]), load["ctl"]
                )
                self.assertEqual(
                    expect_value(result, MetricKind.ATL, day=row["id"]), load["atl"]
                )

    def test_recovery_values_match_the_recovery_context(self) -> None:
        # Since #1411 the recovery context reads these observations directly.
        result = map_wellness(self.rows)
        legacy = performance_recovery_context(
            mapped_recovery_inputs(None, self.rows), TODAY
        )
        sleep_seconds = expect_value(result, MetricKind.SLEEP_DURATION, day=LATEST_DAY)
        self.assertEqual(legacy["sleep_hours"], round(sleep_seconds / 3600, 1))
        self.assertEqual(
            legacy["sleep_score"],
            expect_value(result, MetricKind.SLEEP_SCORE, day=LATEST_DAY),
        )
        self.assertEqual(
            legacy["resting_hr"],
            expect_value(result, MetricKind.RESTING_HR, day=LATEST_DAY),
        )
        self.assertEqual(
            legacy["hrv"],
            expect_value(result, MetricKind.HRV_RMSSD, day=LATEST_DAY),
        )
        self.assertEqual(
            legacy["readiness"],
            expect_value(result, MetricKind.READINESS, day=LATEST_DAY),
        )

    def test_weight_matches_current_metrics(self) -> None:
        result = map_wellness(self.rows)
        legacy = legacy_metrics(self.snapshot)
        self.assertEqual(
            legacy["weight_kg"]["value"],
            expect_value(result, MetricKind.WEIGHT, day=LATEST_DAY),
        )

    def test_pinned_wellness_keys_missing_from_the_compact_form(self) -> None:
        row = {"id": LATEST_DAY, **{key: 1 for key in MAPPED_WELLNESS_KEYS - {"id"}}}
        compact_row = compact_form({}, [], [row])["recent_wellness"][0]
        self.assertEqual(
            MAPPED_WELLNESS_KEYS - set(compact_row),
            frozenset(
                {
                    "body_fat_pct",
                    "resting_hr",
                    "hrv_ms",
                    "sleep_seconds",
                    "vo2max",
                    "vo2_max",
                }
            ),
        )

    def test_compact_loss_of_resting_hr_is_seen_by_the_recovery_reader_too(
        self,
    ) -> None:
        # The compact wellness fields do not carry ``resting_hr``. Observations
        # mapped from the compact row lose it, so the recovery context does too.
        row = {"id": LATEST_DAY, "resting_hr": 47}
        compact_row = compact_form({}, [], [row])["recent_wellness"][0]
        self.assertEqual(
            expect_value(map_wellness([row]), MetricKind.RESTING_HR, day=LATEST_DAY),
            47,
        )
        self.assertIsNone(
            first_value(map_wellness([compact_row]), MetricKind.RESTING_HR)
        )
        self.assertEqual(
            performance_recovery_context(mapped_recovery_inputs(None, [row]), TODAY)[
                "resting_hr"
            ],
            47,
        )
        self.assertIsNone(
            performance_recovery_context(
                mapped_recovery_inputs(None, [compact_row]), TODAY
            )["resting_hr"]
        )

    def test_comma_decimal_weight_is_accepted_by_mapper_and_legacy(self) -> None:
        # Both the mapper and the legacy readers replace the comma with a dot.
        row = {"id": LATEST_DAY, "weight": "70,1"}
        result = map_wellness([row])
        self.assertEqual(first_value(result, MetricKind.WEIGHT), 70.1)
        self.assertEqual(result.issues, ())
        legacy = legacy_metrics(
            {"athlete": {}, "recent_wellness": [row], "recent_activities": []}
        )
        self.assertEqual(legacy["weight_kg"]["value"], 70.1)


class ThresholdParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.athlete = load_fixture("athlete")
        self.legacy = legacy_metrics(compact_form(self.athlete, [], []))

    def test_ftp_lthr_and_max_hr_match_current_metrics(self) -> None:
        result = map_thresholds(self.athlete)
        pairs = (
            ("cycling_ftp_watts", MetricKind.FTP, Sport.RIDE),
            ("run_threshold_watts", MetricKind.FTP, Sport.RUN),
            ("bike_threshold_hr_bpm", MetricKind.THRESHOLD_HR, Sport.RIDE),
            ("run_threshold_hr_bpm", MetricKind.THRESHOLD_HR, Sport.RUN),
            ("cycling_max_hr_bpm", MetricKind.MAX_HR, Sport.RIDE),
            ("running_max_hr_bpm", MetricKind.MAX_HR, Sport.RUN),
        )
        for name, kind, sport in pairs:
            with self.subTest(metric=name):
                self.assertEqual(
                    first_value(result, kind, sport=sport),
                    self.legacy[name]["value"],
                )

    def test_threshold_pace_is_metres_per_second_below_twenty(self) -> None:
        pace = expect_value(
            map_thresholds(self.athlete), MetricKind.THRESHOLD_PACE, sport=Sport.RUN
        )
        self.assertEqual(
            round(1000 / pace),
            self.legacy["run_threshold_pace_seconds_per_km"]["value"],
        )

    def test_threshold_pace_in_seconds_per_km_converts_to_metres_per_second(
        self,
    ) -> None:
        athlete = {"sportSettings": [{"types": ["Run"], "threshold_pace": 240}]}
        legacy = legacy_metrics(compact_form(athlete, [], []))
        pace = expect_value(
            map_thresholds(athlete), MetricKind.THRESHOLD_PACE, sport=Sport.RUN
        )
        self.assertEqual(legacy["run_threshold_pace_seconds_per_km"]["value"], 240)
        self.assertEqual(round(1000 / pace), 240)

    def test_compact_athlete_maps_like_the_raw_athlete(self) -> None:
        snapshot = compact_form(self.athlete, [], [])
        self.assertEqual(
            map_thresholds(snapshot["athlete"]).records,
            map_thresholds(self.athlete).records,
        )

    def test_pinned_sport_setting_keys_missing_from_the_compact_form(self) -> None:
        setting = {
            "id": 1,
            "types": ["Run"],
            "ftp": 200,
            "indoor_ftp": 190,
            "lthr": 160,
            "max_hr": 180,
            "maxHR": 181,
            "maxHeartRate": 182,
            "max_heartrate": 183,
            "threshold_pace": 4.0,
            "vo2max": 58,
            "vo2_max": 57,
            "cycling_vo2max": 56,
            "running_vo2max": 55,
        }
        compact_setting = compact_form({"sportSettings": [setting]}, [], [])["athlete"][
            "sport_settings"
        ][0]
        self.assertEqual(
            MAPPED_SPORT_SETTING_KEYS - set(compact_setting),
            frozenset({"max_heartrate"}),
        )

    def test_eftp_is_a_ride_observation_and_not_read_from_the_snapshot(self) -> None:
        # The snapshot reader of cycling_eftp_watts was removed (#1412): the value
        # is read from this observation, so the snapshot-only path reports none.
        result = map_thresholds(self.athlete)
        self.assertIsNone(self.legacy["cycling_eftp_watts"]["value"])
        self.assertEqual(first_value(result, MetricKind.EFTP, sport=Sport.RIDE), 258)

    def test_any_type_entry_classifies_a_sport_setting(self) -> None:
        athlete = {"sportSettings": [{"types": ["Workout", "Ride"], "ftp": 255}]}
        legacy = legacy_metrics(compact_form(athlete, [], []))
        result = map_thresholds(athlete)
        self.assertEqual(legacy["cycling_ftp_watts"]["value"], 255)
        self.assertEqual(first_value(result, MetricKind.FTP, sport=Sport.RIDE), 255)
        self.assertIsNone(first_value(result, MetricKind.FTP, sport=Sport.OTHER))

    def test_zero_values_mean_unset_in_both_readers(self) -> None:
        athlete = {
            "icu_ftp": 250,
            "sportSettings": [
                {"types": ["Ride"], "ftp": 0, "lthr": 0, "max_hr": 0},
                {"types": ["Run"], "threshold_pace": 0, "lthr": 0},
            ],
        }
        legacy = legacy_metrics(compact_form(athlete, [], []))
        result = map_thresholds(athlete)
        # The zero FTP falls through to the top-level icu_ftp in both readers.
        self.assertEqual(legacy["cycling_ftp_watts"]["value"], 250)
        self.assertEqual(first_value(result, MetricKind.FTP, sport=Sport.RIDE), 250)
        self.assertIsNone(legacy["bike_threshold_hr_bpm"]["value"])
        self.assertIsNone(
            first_value(result, MetricKind.THRESHOLD_HR, sport=Sport.RIDE)
        )
        self.assertIsNone(legacy["cycling_max_hr_bpm"]["value"])
        self.assertIsNone(first_value(result, MetricKind.MAX_HR, sport=Sport.RIDE))
        self.assertIsNone(legacy["run_threshold_pace_seconds_per_km"]["value"])
        self.assertIsNone(
            first_value(result, MetricKind.THRESHOLD_PACE, sport=Sport.RUN)
        )

    # Known deviations, named so that each one stays visible.

    def test_threshold_pace_bound_rejects_paces_the_legacy_reader_accepts(
        self,
    ) -> None:
        # Deviation: the canonical THRESHOLD_PACE bound is 15 m/s. The legacy
        # reader accepts any positive value. 16 is read as metres per second and
        # gives 62 s/km; 60 is read as seconds per kilometre.
        for threshold_pace, legacy_seconds in ((16, 62), (60, 60)):
            athlete = {
                "sportSettings": [{"types": ["Run"], "threshold_pace": threshold_pace}]
            }
            with self.subTest(threshold_pace=threshold_pace):
                legacy = legacy_metrics(compact_form(athlete, [], []))
                self.assertEqual(
                    legacy["run_threshold_pace_seconds_per_km"]["value"],
                    legacy_seconds,
                )
                result = map_thresholds(athlete)
                self.assertIsNone(
                    first_value(result, MetricKind.THRESHOLD_PACE, sport=Sport.RUN)
                )
                self.assertEqual(
                    [issue.reason for issue in result.issues],
                    [IssueReason.OUT_OF_RANGE],
                )

    def test_athlete_level_lthr_and_max_hr_match_the_legacy_fallback(self) -> None:
        # Parity: current_metrics falls back to the athlete-level lthr and max_hr
        # for both sports when no sport setting carries them. The mapper emits them
        # with sport None, and the consumer applies the per-sport fallback.
        athlete = {"id": "i-synthetic-001", "lthr": 165, "max_hr": 188}
        legacy = legacy_metrics(compact_form(athlete, [], []))
        result = map_thresholds(athlete)
        self.assertEqual(first_value(result, MetricKind.THRESHOLD_HR), 165)
        self.assertEqual(first_value(result, MetricKind.MAX_HR), 188)
        for name in ("bike_threshold_hr_bpm", "run_threshold_hr_bpm"):
            with self.subTest(metric=name):
                self.assertEqual(legacy[name]["value"], 165)
        for name in ("cycling_max_hr_bpm", "running_max_hr_bpm"):
            with self.subTest(metric=name):
                self.assertEqual(legacy[name]["value"], 188)

    def test_sport_setting_lthr_overrides_the_athlete_level_value(self) -> None:
        # The Ride setting wins for Ride; Run has no setting, so the athlete-level
        # value (sport None) is its fallback in both readers.
        athlete = {
            "lthr": 165,
            "sportSettings": [{"types": ["Ride"], "lthr": 168}],
        }
        legacy = legacy_metrics(compact_form(athlete, [], []))
        result = map_thresholds(athlete)
        self.assertEqual(legacy["bike_threshold_hr_bpm"]["value"], 168)
        self.assertEqual(
            first_value(result, MetricKind.THRESHOLD_HR, sport=Sport.RIDE), 168
        )
        self.assertEqual(legacy["run_threshold_hr_bpm"]["value"], 165)
        self.assertIsNone(first_value(result, MetricKind.THRESHOLD_HR, sport=Sport.RUN))
        self.assertEqual(first_value(result, MetricKind.THRESHOLD_HR), 165)

    def test_athlete_weight_matches_current_metrics(self) -> None:
        # The fixture athlete carries weight 70.0 and no wellness rows, so the
        # legacy weight chain reads the athlete record.
        result = map_thresholds(self.athlete)
        self.assertEqual(self.legacy["weight_kg"]["value"], 70.0)
        self.assertEqual(first_value(result, MetricKind.WEIGHT), 70.0)

    def test_sport_setting_vo2max_matches_current_metrics(self) -> None:
        athlete = {
            "sportSettings": [
                {"types": ["Ride"], "vo2max": 58},
                {"types": ["Run"], "running_vo2max": 52.5},
            ]
        }
        legacy = legacy_metrics(compact_form(athlete, [], []))
        result = map_thresholds(athlete)
        self.assertEqual(legacy["cycling_vo2max_ml_kg_min"]["value"], 58)
        self.assertEqual(first_value(result, MetricKind.VO2MAX, sport=Sport.RIDE), 58)
        self.assertEqual(legacy["running_vo2max_ml_kg_min"]["value"], 52.5)
        self.assertEqual(first_value(result, MetricKind.VO2MAX, sport=Sport.RUN), 52.5)

    def test_zero_sport_vo2max_is_unset_in_both_readers(self) -> None:
        # Both readers stop at the zero vo2max and do not fall through to vo2_max.
        athlete = {"sportSettings": [{"types": ["Ride"], "vo2max": 0, "vo2_max": 55}]}
        legacy = legacy_metrics(compact_form(athlete, [], []))
        result = map_thresholds(athlete)
        self.assertIsNone(legacy["cycling_vo2max_ml_kg_min"]["value"])
        self.assertIsNone(first_value(result, MetricKind.VO2MAX, sport=Sport.RIDE))

    # Known deviations for the athlete-level fallback, named so they stay visible.

    def test_zero_athlete_lthr_is_unset_where_legacy_reads_zero(self) -> None:
        # Deviation: the legacy generic lthr fallback reads 0 bpm. The mapper treats
        # a zero athlete-level lthr as unset, as it does for a zero sport setting.
        athlete = {"lthr": 0}
        legacy = legacy_metrics(compact_form(athlete, [], []))
        self.assertEqual(legacy["bike_threshold_hr_bpm"]["value"], 0)
        self.assertIsNone(first_value(map_thresholds(athlete), MetricKind.THRESHOLD_HR))

    def test_rejected_sport_lthr_lets_the_athlete_level_value_apply(self) -> None:
        # Deviation: a sport lthr that the mapper rejects leaves the sport unset, so
        # the athlete-level value is the only Ride candidate the mapper offers.
        athlete = {
            "lthr": 165,
            "sportSettings": [{"types": ["Ride"], "lthr": "not-a-number"}],
        }
        result = map_thresholds(athlete)
        self.assertIsNone(
            first_value(result, MetricKind.THRESHOLD_HR, sport=Sport.RIDE)
        )
        self.assertEqual(first_value(result, MetricKind.THRESHOLD_HR), 165)
        self.assertEqual(
            [issue.reason for issue in result.issues],
            [IssueReason.INVALID_NUMBER],
        )
