"""Parity between the Garmin health mapper and the retired legacy readers.

The legacy ingest parsers are gone. These tests pin the values, dates and per-day
choices they produced for the same snapshots as literals and check that the mapper
yields them. Named deviation tests record where the mapper is intentionally
different. Everything runs on tests/fixtures or inline data with the standard
library only; no provider, network, database or real data directory is involved.
"""

from __future__ import annotations

import json
import unittest
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from canonical_recovery_support import mapped_recovery_inputs

from backend.canonical.mapping import IssueReason, MappingResult
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, Sport
from backend.performance import recovery_context
from backend.providers.garmin_health_mapping import map_garmin_health
from backend.sync.garmin_performance_history import (
    append_garmin_performance_history,
    current_garmin_metrics,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "providers" / "garmin"
ZONE = ZoneInfo("Europe/Berlin")
RETRIEVED_AT = datetime(2026, 10, 11, 6, 0, tzinfo=ZONE)
TODAY = date(2026, 10, 11)
DAY = "2026-10-10"

FIXTURE_NAMES = (
    "weight",
    "resting_hr",
    "hrv",
    "sleep",
    "readiness",
    "max_metrics",
    "cycling_ftp",
    "cycling_ftp_history",
    "running_threshold",
    "heart_rate_zones",
    "race_predictions",
)
# What the retired legacy reader returned for the fixture snapshot.
LEGACY_FIXTURE_METRICS = {
    "cycling_vo2max_ml_kg_min": 59,
    "running_vo2max_ml_kg_min": 57.8,
    "cycling_ftp_watts": 260,
    "run_threshold_watts": 290,
    "run_threshold_pace_seconds_per_km": 278,
    "bike_threshold_hr_bpm": 160,
    "run_threshold_hr_bpm": 168,
    "run_5k_seconds": 1320,
    "run_10k_seconds": 2790,
    "run_half_marathon_seconds": 6150,
    "run_marathon_seconds": 13050,
}


def _fixture_snapshot() -> dict[str, Any]:
    return {
        name: json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
        for name in FIXTURE_NAMES
    }


def _map(snapshot: dict[str, Any]) -> MappingResult[Observation]:
    return map_garmin_health(snapshot, zone=ZONE, retrieved_at=RETRIEVED_AT)


def _latest_by_day(
    result: MappingResult[Observation],
    kind: MetricKind,
    sport: Sport | None = None,
) -> dict[str, float]:
    """Latest value per day, ordered as the legacy daily projection orders them.

    The key is (has timestamp, timestamp, traversal index), so a timestamped
    weigh-in beats an untimed one and later records win ties.
    """
    best: dict[str, tuple[tuple[bool, float, int], float]] = {}
    for obs in result.records:
        if obs.kind is not kind or obs.sport is not sport:
            continue
        suffix = (obs.provenance.source_record_id or "").rsplit(":", 1)[-1]
        index = int(suffix) if suffix.isdigit() else 0
        stamp = obs.observed_at.timestamp() if obs.observed_at is not None else 0.0
        key = (obs.observed_at is not None, stamp, index)
        day = obs.observed_on.isoformat()
        if day not in best or key >= best[day][0]:
            best[day] = (key, obs.value.value)
    return {day: value for day, (_, value) in best.items()}


def _latest_value(
    result: MappingResult[Observation],
    kind: MetricKind,
    sport: Sport | None = None,
) -> tuple[str, float]:
    """Value of the latest observed day for one kind."""
    daily = _latest_by_day(result, kind, sport)
    day = max(daily)
    return day, daily[day]


def _max_hr_by_category(result: MappingResult[Observation]) -> dict[str, float]:
    """Highest mapped max heart rate per legacy category, as the legacy reader keys it."""
    categories: dict[Sport | None, str] = {
        Sport.RIDE: "cycling",
        Sport.RUN: "running",
        None: "generic",
    }
    values: dict[str, float] = {}
    for obs in result.records:
        if obs.kind is not MetricKind.MAX_HR:
            continue
        category = categories[obs.sport]
        values[category] = max(values.get(category, obs.value.value), obs.value.value)
    return values


class WeightParityTests(unittest.TestCase):
    def test_fixture_weight_matches_legacy_daily_records(self) -> None:
        mapped = _latest_by_day(_map(_fixture_snapshot()), MetricKind.WEIGHT)

        self.assertEqual(mapped, {"2026-10-08": 72.1, "2026-10-10": 71.5})

    def test_latest_weight_matches_legacy_metric(self) -> None:
        _, mapped_value = _latest_value(_map(_fixture_snapshot()), MetricKind.WEIGHT)

        self.assertEqual(mapped_value, 71.5)

    def test_same_day_weigh_ins_pick_the_timestamped_latest_like_legacy(self) -> None:
        snapshot: dict[str, Any] = {
            "weight": [
                {
                    "calendarDate": DAY,
                    "weight": 72400,
                    "unitKey": "gram",
                    "timestampGMT": "2026-10-10T06:00:00Z",
                },
                {"calendarDate": DAY, "weight": 72.2, "unitKey": "kg"},
                {
                    "calendarDate": DAY,
                    "weight": 72.0,
                    "unitKey": "kg",
                    "timestampGMT": "2026-10-10T07:00:00Z",
                },
            ]
        }

        mapped = _latest_by_day(_map(snapshot), MetricKind.WEIGHT)

        self.assertEqual(mapped, {DAY: 72.0})

    def test_nested_weigh_ins_inherit_or_take_their_own_date_like_legacy(self) -> None:
        snapshot: dict[str, Any] = {
            "weight": {
                "calendarDate": DAY,
                "weight": 71.8,
                "unitKey": "kg",
                "weighIns": [
                    {
                        "weight": 71.6,
                        "unitKey": "kg",
                        "timestampGMT": "2026-10-10T06:00:00Z",
                    },
                    {"weight": 71.7, "unitKey": "kg"},
                ],
            }
        }

        mapped = _latest_by_day(_map(snapshot), MetricKind.WEIGHT)

        self.assertEqual(mapped, {DAY: 71.6})

    def test_weigh_in_section_alias_is_used_when_weight_is_empty(self) -> None:
        snapshot: dict[str, Any] = {
            "weight": [],
            "weighIns": [{"calendarDate": DAY, "weight": 70.5, "unitKey": "kg"}],
        }

        mapped = _latest_by_day(_map(snapshot), MetricKind.WEIGHT)

        self.assertEqual(mapped, {DAY: 70.5})

    def test_min_and_max_subtrees_are_not_weigh_ins_like_legacy(self) -> None:
        snapshot: dict[str, Any] = {
            "weight": {
                "calendarDate": DAY,
                "weight": 72.0,
                "unitKey": "kg",
                "minWeight": {"weight": 60.0, "unitKey": "kg"},
                "maxWeight": {"weight": 90.0, "unitKey": "kg"},
            }
        }

        mapped = _latest_by_day(_map(snapshot), MetricKind.WEIGHT)

        self.assertEqual(mapped, {DAY: 72.0})

    def test_undated_weigh_in_is_not_a_daily_record_like_legacy(self) -> None:
        snapshot: dict[str, Any] = {"weight": [{"weight": 72.0, "unitKey": "kg"}]}

        result = _map(snapshot)

        self.assertEqual(_latest_by_day(result, MetricKind.WEIGHT), {})
        self.assertEqual(
            [(i.record_ref, i.field, i.reason) for i in result.issues],
            [("weight[0]", "calendarDate", IssueReason.MISSING)],
        )

    def test_records_beyond_the_depth_limit_are_ignored_like_legacy(self) -> None:
        deep: dict[str, Any] = {"calendarDate": DAY, "weight": 72.0, "unitKey": "kg"}
        for _ in range(25):
            deep = {"child": deep}
        snapshot: dict[str, Any] = {
            "weight": [
                {"calendarDate": "2026-10-09", "weight": 71.0, "unitKey": "kg"},
                deep,
            ]
        }

        mapped = _latest_by_day(_map(snapshot), MetricKind.WEIGHT)

        self.assertEqual(mapped, {"2026-10-09": 71.0})

    def test_epoch_timestamp_day_is_the_utc_day_like_legacy(self) -> None:
        # 1728540000000 ms is 2024-10-10 06:00 UTC; the legacy reader dates it by UTC.
        snapshot: dict[str, Any] = {
            "weight": [{"timestampGMT": 1728540000000, "weight": 72.0, "unitKey": "kg"}]
        }

        mapped = _latest_by_day(_map(snapshot), MetricKind.WEIGHT)

        self.assertEqual(mapped, {"2024-10-10": 72.0})


class BodyFatParityTests(unittest.TestCase):
    def test_body_fat_units_and_comma_decimals_are_mapped(self) -> None:
        snapshot: dict[str, Any] = {
            "weight": [
                {
                    "calendarDate": DAY,
                    "weight": 72100,
                    "unitKey": "gram",
                    "bodyFat": {"value": 0.184, "unitKey": "fraction"},
                },
                {
                    "calendarDate": "2026-10-11",
                    "bodyFat": "18,5",
                    "bodyFatUnit": "%",
                },
            ]
        }

        mapped = _latest_by_day(_map(snapshot), MetricKind.BODY_FAT)

        self.assertEqual(mapped, {DAY: 18.4, "2026-10-11": 18.5})

    def test_body_fat_without_unit_is_taken_as_percent(self) -> None:
        snapshot: dict[str, Any] = {
            "weight": {"calendarDate": DAY, "bodyFatPercentage": 21.25}
        }

        mapped = _latest_by_day(_map(snapshot), MetricKind.BODY_FAT)

        self.assertEqual(mapped, {DAY: 21.25})


class RecoveryAndPerformanceParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = _fixture_snapshot()
        self.result = _map(self.snapshot)
        # Since #1411 the recovery context reads the mapped observations, so this
        # checks that the context shows the mapped value and day it selects.
        self.context = recovery_context.performance_recovery_context(
            mapped_recovery_inputs(self.snapshot), TODAY
        )

    def test_resting_heart_rate_matches_legacy_value_and_date(self) -> None:
        day, value = _latest_value(self.result, MetricKind.RESTING_HR)

        self.assertEqual(value, self.context["resting_hr"])
        self.assertEqual(day, self.context["resting_hr_date"])

    def test_hrv_matches_legacy_value_and_date(self) -> None:
        day, value = _latest_value(self.result, MetricKind.HRV_RMSSD)

        self.assertEqual(value, self.context["hrv"])
        self.assertEqual(day, self.context["hrv_date"])

    def test_sleep_matches_legacy_hours_and_score(self) -> None:
        day, seconds = _latest_value(self.result, MetricKind.SLEEP_DURATION)
        _, score = _latest_value(self.result, MetricKind.SLEEP_SCORE)

        self.assertEqual(round(seconds / 3600, 1), self.context["sleep_hours"])
        self.assertEqual(score, self.context["sleep_score"])
        self.assertEqual(day, DAY)

    def test_zero_sleep_score_matches_legacy(self) -> None:
        snapshot: dict[str, Any] = {
            "sleep": [{"calendarDate": DAY, "sleepScore": 0, "sleepTimeSeconds": 25200}]
        }

        context = recovery_context.performance_recovery_context(
            mapped_recovery_inputs(snapshot), TODAY
        )
        result = _map(snapshot)

        self.assertEqual(context["sleep_score"], 0)
        self.assertEqual(_latest_value(result, MetricKind.SLEEP_SCORE), (DAY, 0.0))

    def test_readiness_matches_legacy(self) -> None:
        _, value = _latest_value(self.result, MetricKind.READINESS)

        self.assertEqual(value, self.context["readiness"])

    def test_fixture_max_hr_matches_legacy_category(self) -> None:
        mapped = _max_hr_by_category(self.result)

        self.assertEqual(mapped, {"generic": 190.0})

    def test_max_hr_per_category_matches_legacy(self) -> None:
        snapshot: dict[str, Any] = {
            "heart_rate_zones": [
                {"calendarDate": DAY, "sport": "CYCLING", "maxHeartRateUsed": 181},
                {"sport": "RUNNING", "maxHeartRate": 194},
                {"activityType": "DEFAULT", "maxHR": 186},
                {"nested": [{"sport": "cycling", "maxHeartRateUsed": 188}]},
            ]
        }

        mapped = _max_hr_by_category(_map(snapshot))

        self.assertEqual(mapped, {"cycling": 188, "running": 194, "generic": 186})

    def test_vo2max_matches_legacy_per_sport(self) -> None:
        _, cycling = _latest_value(self.result, MetricKind.VO2MAX, Sport.RIDE)
        # Garmin's maxmet reports no running object; generic is the running value.
        _, running = _latest_value(self.result, MetricKind.VO2MAX)

        self.assertEqual(cycling, LEGACY_FIXTURE_METRICS["cycling_vo2max_ml_kg_min"])
        self.assertEqual(running, LEGACY_FIXTURE_METRICS["running_vo2max_ml_kg_min"])

    def test_cycling_ftp_matches_legacy_latest_value(self) -> None:
        daily = _latest_by_day(self.result, MetricKind.FTP, Sport.RIDE)

        self.assertEqual(daily, {"2026-10-05": 258.0, DAY: 260.0})
        self.assertEqual(
            daily[DAY],
            LEGACY_FIXTURE_METRICS["cycling_ftp_watts"],
        )

    def test_running_threshold_heart_rates_match_legacy(self) -> None:
        _, run_hr = _latest_value(self.result, MetricKind.THRESHOLD_HR, Sport.RUN)
        _, ride_hr = _latest_value(self.result, MetricKind.THRESHOLD_HR, Sport.RIDE)

        self.assertEqual(run_hr, LEGACY_FIXTURE_METRICS["run_threshold_hr_bpm"])
        self.assertEqual(ride_hr, LEGACY_FIXTURE_METRICS["bike_threshold_hr_bpm"])

    def test_running_threshold_power_matches_legacy_running_watts(self) -> None:
        _, watts = _latest_value(self.result, MetricKind.FTP, Sport.RUN)

        self.assertEqual(watts, LEGACY_FIXTURE_METRICS["run_threshold_watts"])

    def test_race_predictions_match_legacy_seconds(self) -> None:
        legacy = {
            MetricKind.RACE_PREDICTION_5K: "run_5k_seconds",
            MetricKind.RACE_PREDICTION_10K: "run_10k_seconds",
            MetricKind.RACE_PREDICTION_HALF: "run_half_marathon_seconds",
            MetricKind.RACE_PREDICTION_FULL: "run_marathon_seconds",
        }
        for kind, key in legacy.items():
            with self.subTest(kind=kind):
                _, seconds = _latest_value(self.result, kind, Sport.RUN)

                self.assertEqual(seconds, LEGACY_FIXTURE_METRICS[key])

    def test_threshold_pace_converts_to_legacy_seconds_per_kilometre(self) -> None:
        # The mapper keeps Garmin's m/s speed. The legacy reader shows s/km.
        _, speed = _latest_value(self.result, MetricKind.THRESHOLD_PACE, Sport.RUN)

        self.assertEqual(
            round(1000 / speed),
            LEGACY_FIXTURE_METRICS["run_threshold_pace_seconds_per_km"],
        )


class NamedDeviationTests(unittest.TestCase):
    """Places where the mapper intentionally differs from a legacy reader."""

    def test_declared_units_outside_the_plausible_range_are_flagged_not_reinterpreted(
        self,
    ) -> None:
        # The legacy reader read 72100 kg as 72.1 and kept 250 gram as 250.0.
        for raw, unit in ((72100, "kg"), (250, "gram")):
            with self.subTest(unit=unit):
                snapshot: dict[str, Any] = {
                    "weight": {"calendarDate": DAY, "weight": raw, "unitKey": unit}
                }

                result = _map(snapshot)

                self.assertEqual(result.records, ())
                self.assertEqual(
                    [(i.record_ref, i.field, i.reason) for i in result.issues],
                    [("weight[0]", "weight", IssueReason.OUT_OF_RANGE)],
                )

    def test_unreadable_date_is_not_kept_as_a_day_key(self) -> None:
        snapshot: dict[str, Any] = {
            "weight": {"calendarDate": "soon", "weight": 72.0, "unitKey": "kg"}
        }

        result = _map(snapshot)

        self.assertEqual(result.records, ())
        self.assertEqual(
            [(i.record_ref, i.field, i.reason) for i in result.issues],
            [("weight[0]", "calendarDate", IssueReason.INVALID_TYPE)],
        )

    def test_max_hr_above_the_canonical_bound_is_legacy_only(self) -> None:
        snapshot: dict[str, Any] = {
            "heart_rate_zones": [
                {"calendarDate": DAY, "sport": "CYCLING", "maxHeartRateUsed": 255}
            ]
        }

        result = _map(snapshot)

        self.assertEqual(_max_hr_by_category(result), {})
        self.assertEqual(
            [(i.record_ref, i.field, i.reason) for i in result.issues],
            [("heart_rate_zones[0]", "maxHeartRateUsed", IssueReason.OUT_OF_RANGE)],
        )

    def test_weekly_hrv_average_is_its_own_kind_and_a_labelled_fallback(self) -> None:
        # Legacy showed the weekly average as the HRV value under the plain Garmin
        # label. Since #1411 it is mapped as its own kind and labelled.
        snapshot: dict[str, Any] = {
            "hrv": {"calendarDate": DAY, "weeklyAvg": 58},
        }

        context = recovery_context.performance_recovery_context(
            mapped_recovery_inputs(snapshot), TODAY
        )
        result = _map(snapshot)

        self.assertEqual(context["hrv"], 58)
        self.assertEqual(context["hrv_source"], "Garmin Connect (Wochenmittel)")
        self.assertEqual(
            [(item.kind, item.value.value) for item in result.records],
            [(MetricKind.HRV_WEEKLY_AVERAGE, 58.0)],
        )

    def test_legacy_ingest_shapes_the_mapper_does_not_read(self) -> None:
        # #2081: the performance history reads the latest-value sections through
        # the mapper. The retired ingest parser also read these shapes, which the
        # garminconnect SDK does not deliver; ``legacy`` is its value on each input.
        # Undated sections (A) never added a history row, as a row needs an
        # observation day; dated ones (B) did.
        flat = {
            "calendarDate": DAY,
            "paceInSecondsPerKilometer": 274,
            "power": 310,
            "heartRate": 168,
            "heartRateCycling": 162,
        }
        zone_sets = [
            {"sport": "DEFAULT", "fetchedOn": "2026-11-01", "maxHeartRateUsed": 195},
            {"sport": "DEFAULT", "fetchedOn": "2026-11-05", "maxHeartRateUsed": 189},
        ]
        mixed_readiness = [
            {"calendarDate": "2026-10-09", "score": 61},
            {"date": DAY, "trainingReadiness": {"score": "72"}},
            {"id": "2026-10-08", "value": 40},
        ]
        nested_readiness = {
            "readinessScore": [
                {"date": "2026-10-09", "value": 55},
                {"date": DAY, "value": 66},
            ]
        }
        ftp_list = [
            {"calendarDate": DAY, "functionalThresholdPower": 302},
            {"calendarDate": "2026-10-09", "functionalThresholdPower": 300},
        ]
        cases = (
            (
                "A1",
                "max_metrics",
                [{"cycling": {"vo2MaxValue": 61.0}}],
                "cycling_vo2max_ml_kg_min",
                61,
                None,
            ),
            (
                "A2",
                "max_metrics",
                {"generic": {"vo2MaxValue": 51.0}},
                "running_vo2max_ml_kg_min",
                51,
                None,
            ),
            (
                "A3",
                "running_threshold",
                {"speedInMetersPerSecond": 4.0},
                "run_threshold_pace_seconds_per_km",
                250,
                None,
            ),
            (
                "A4",
                "running_threshold",
                {"power": {"power": 320}},
                "run_threshold_watts",
                320,
                None,
            ),
            ("A5", "readiness", {"score": "7,5"}, "readiness", 7.5, None),
            ("A6", "heart_rate_zones", zone_sets, "cycling_max_hr_bpm", 189, 195),
            ("B1a", "readiness", mixed_readiness, "readiness", 72, 61),
            ("B1b", "readiness", nested_readiness, "readiness", 66, None),
            (
                "B1c",
                "readiness",
                [{"date": DAY, "readiness": 85}],
                "readiness",
                85,
                None,
            ),
            (
                "B1d",
                "readiness",
                {"calendarDate": DAY, "score": "7,5"},
                "readiness",
                7.5,
                None,
            ),
            (
                "B2a",
                "running_threshold",
                {"calendarDate": DAY, "speedInMetersPerSecond": 3.8},
                "run_threshold_pace_seconds_per_km",
                263,
                None,
            ),
            (
                "B2b",
                "running_threshold",
                {"calendarDate": DAY, "thresholdPace": "4:27"},
                "run_threshold_pace_seconds_per_km",
                267,
                None,
            ),
            (
                "B2c",
                "running_threshold",
                flat,
                "run_threshold_pace_seconds_per_km",
                274,
                None,
            ),
            ("B2c", "running_threshold", flat, "run_threshold_watts", 310, None),
            ("B2c", "running_threshold", flat, "run_threshold_hr_bpm", 168, None),
            ("B2c", "running_threshold", flat, "bike_threshold_hr_bpm", 162, None),
            ("B3", "cycling_ftp", ftp_list, "cycling_ftp_watts", 300, 302),
        )
        for case, section, value, key, legacy, mapped in cases:
            with self.subTest(case=case, key=key, legacy=legacy):
                metrics = current_garmin_metrics({section: value}, TODAY)
                self.assertEqual(metrics[key]["value"], mapped)
        # B4: a range record that also names a calendarDate keeps its range day;
        # the legacy reader dropped the ambiguous record.
        payload: dict[str, Any] = {
            "cycling_ftp_history": [
                {"from": "2026-10-03", "calendarDate": "2026-10-04", "value": 280}
            ]
        }
        append_garmin_performance_history(payload, None, TODAY)
        self.assertEqual(
            payload["performance_history"],
            [{"date": "2026-10-03", "metrics": {"cycling_ftp_watts": 280.0}}],
        )


if __name__ == "__main__":
    unittest.main()
