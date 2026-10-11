"""Parity between the Garmin health mapper and the legacy performance readers.

The legacy readers in ``backend/performance`` still serve the Coach context. These
tests check that the mapper yields the same values, dates and per-day choices for
the same snapshots. Named deviation tests record where the mapper is intentionally
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

from backend.canonical.mapping import IssueReason, MappingResult
from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, Sport
from backend.performance import garmin_metrics, garmin_weight, recovery_context
from backend.providers.garmin_health_mapping import map_garmin_health

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
)


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


class WeightParityTests(unittest.TestCase):
    def test_fixture_weight_matches_legacy_daily_records(self) -> None:
        snapshot = _fixture_snapshot()

        mapped = _latest_by_day(_map(snapshot), MetricKind.WEIGHT)
        legacy = dict(garmin_weight.garmin_weight_daily_records(snapshot))

        self.assertEqual(mapped, legacy)
        self.assertEqual(mapped, {"2026-10-08": 72.1, "2026-10-10": 71.5})

    def test_latest_weight_matches_legacy_metric(self) -> None:
        snapshot = _fixture_snapshot()

        _, mapped_value = _latest_value(_map(snapshot), MetricKind.WEIGHT)
        legacy = garmin_weight.garmin_weight_metric(snapshot)

        self.assertEqual(mapped_value, legacy["value"])

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
        legacy = dict(garmin_weight.garmin_weight_daily_records(snapshot))

        self.assertEqual(mapped, legacy)
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
        legacy = dict(garmin_weight.garmin_weight_daily_records(snapshot))

        self.assertEqual(mapped, legacy)
        self.assertEqual(mapped, {DAY: 71.6})

    def test_weigh_in_section_alias_is_used_when_weight_is_empty(self) -> None:
        snapshot: dict[str, Any] = {
            "weight": [],
            "weighIns": [{"calendarDate": DAY, "weight": 70.5, "unitKey": "kg"}],
        }

        mapped = _latest_by_day(_map(snapshot), MetricKind.WEIGHT)
        legacy = dict(garmin_weight.garmin_weight_daily_records(snapshot))

        self.assertEqual(mapped, legacy)
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
        legacy = dict(garmin_weight.garmin_weight_daily_records(snapshot))

        self.assertEqual(mapped, legacy)
        self.assertEqual(mapped, {DAY: 72.0})

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
        legacy = dict(garmin_weight.garmin_weight_daily_records(snapshot))

        self.assertEqual(mapped, legacy)
        self.assertEqual(mapped, {"2026-10-09": 71.0})

    def test_epoch_timestamp_day_is_the_utc_day_like_legacy(self) -> None:
        # 1728540000000 ms is 2024-10-10 06:00 UTC; the legacy reader dates it by UTC.
        snapshot: dict[str, Any] = {
            "weight": [{"timestampGMT": 1728540000000, "weight": 72.0, "unitKey": "kg"}]
        }

        mapped = _latest_by_day(_map(snapshot), MetricKind.WEIGHT)
        legacy = dict(garmin_weight.garmin_weight_daily_records(snapshot))

        self.assertEqual(mapped, legacy)
        self.assertEqual(mapped, {"2024-10-10": 72.0})


class BodyFatParityTests(unittest.TestCase):
    def test_body_fat_units_and_comma_decimals_match_legacy(self) -> None:
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
        legacy = dict(garmin_weight.garmin_body_fat_daily_records(snapshot))

        self.assertEqual(mapped, legacy)
        self.assertEqual(mapped, {DAY: 18.4, "2026-10-11": 18.5})

    def test_body_fat_without_unit_is_taken_as_percent_like_legacy(self) -> None:
        snapshot: dict[str, Any] = {
            "weight": {"calendarDate": DAY, "bodyFatPercentage": 21.25}
        }

        mapped = _latest_by_day(_map(snapshot), MetricKind.BODY_FAT)
        legacy = dict(garmin_weight.garmin_body_fat_daily_records(snapshot))

        self.assertEqual(mapped, legacy)
        self.assertEqual(mapped, {DAY: 21.25})


class RecoveryAndPerformanceParityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = _fixture_snapshot()
        self.result = _map(self.snapshot)
        self.context = recovery_context.performance_recovery_context(
            self.snapshot, {}, [], TODAY
        )
        self.metrics = garmin_metrics.garmin_performance_metrics(self.snapshot, TODAY)

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

    def test_readiness_matches_legacy(self) -> None:
        _, value = _latest_value(self.result, MetricKind.READINESS)

        self.assertEqual(value, self.context["readiness"])

    def test_vo2max_matches_legacy_per_sport(self) -> None:
        _, cycling = _latest_value(self.result, MetricKind.VO2MAX, Sport.RIDE)
        _, running = _latest_value(self.result, MetricKind.VO2MAX, Sport.RUN)

        self.assertEqual(cycling, self.metrics["cycling_vo2max_ml_kg_min"]["value"])
        self.assertEqual(running, self.metrics["running_vo2max_ml_kg_min"]["value"])

    def test_cycling_ftp_matches_legacy_latest_value(self) -> None:
        daily = _latest_by_day(self.result, MetricKind.FTP, Sport.RIDE)

        self.assertEqual(daily, {"2026-10-05": 258.0, DAY: 260.0})
        self.assertEqual(
            daily[DAY],
            self.metrics["cycling_ftp_watts"]["value"],
        )

    def test_running_threshold_heart_rates_match_legacy(self) -> None:
        _, run_hr = _latest_value(self.result, MetricKind.THRESHOLD_HR, Sport.RUN)
        _, ride_hr = _latest_value(self.result, MetricKind.THRESHOLD_HR, Sport.RIDE)

        self.assertEqual(run_hr, self.metrics["run_threshold_hr_bpm"]["value"])
        self.assertEqual(ride_hr, self.metrics["bike_threshold_hr_bpm"]["value"])

    def test_threshold_pace_converts_to_legacy_seconds_per_kilometre(self) -> None:
        # The mapper keeps Garmin's m/s speed. The legacy reader shows s/km.
        _, speed = _latest_value(self.result, MetricKind.THRESHOLD_PACE, Sport.RUN)

        self.assertEqual(
            round(1000 / speed),
            self.metrics["run_threshold_pace_seconds_per_km"]["value"],
        )


class NamedDeviationTests(unittest.TestCase):
    """Places where the mapper intentionally differs from a legacy reader."""

    def test_declared_kilograms_above_the_range_are_not_reinterpreted(self) -> None:
        snapshot: dict[str, Any] = {
            "weight": {"calendarDate": DAY, "weight": 72100, "unitKey": "kg"}
        }

        legacy = dict(garmin_weight.garmin_weight_daily_records(snapshot))
        result = _map(snapshot)

        self.assertEqual(legacy, {DAY: 72.1})
        self.assertEqual(result.records, ())
        self.assertEqual(
            [(i.record_ref, i.field, i.reason) for i in result.issues],
            [("weight[0]", "weight", IssueReason.OUT_OF_RANGE)],
        )

    def test_declared_grams_below_300_are_converted_not_kept(self) -> None:
        snapshot: dict[str, Any] = {
            "weight": {"calendarDate": DAY, "weight": 250, "unitKey": "gram"}
        }

        legacy = dict(garmin_weight.garmin_weight_daily_records(snapshot))
        result = _map(snapshot)

        self.assertEqual(legacy, {DAY: 250.0})
        self.assertEqual(result.records, ())
        self.assertEqual(
            [(i.record_ref, i.field, i.reason) for i in result.issues],
            [("weight[0]", "weight", IssueReason.OUT_OF_RANGE)],
        )

    def test_unreadable_date_is_not_kept_as_a_day_key(self) -> None:
        snapshot: dict[str, Any] = {
            "weight": {"calendarDate": "soon", "weight": 72.0, "unitKey": "kg"}
        }

        legacy_days = [day for day, _ in garmin_weight.garmin_weight_records(snapshot)]
        result = _map(snapshot)

        self.assertEqual(legacy_days, ["soon"])
        self.assertEqual(result.records, ())
        self.assertEqual(
            [(i.record_ref, i.field, i.reason) for i in result.issues],
            [("weight[0]", "calendarDate", IssueReason.INVALID_TYPE)],
        )

    def test_weekly_hrv_average_is_used_by_legacy_but_not_mapped(self) -> None:
        snapshot: dict[str, Any] = {
            "hrv": {"calendarDate": DAY, "weeklyAvg": 58},
        }

        context = recovery_context.performance_recovery_context(snapshot, {}, [], TODAY)
        result = _map(snapshot)

        self.assertEqual(context["hrv"], 58)
        self.assertEqual(result.records, ())

    def test_running_threshold_power_is_unsupported_not_running_watts(self) -> None:
        snapshot = _fixture_snapshot()
        metrics = garmin_metrics.garmin_performance_metrics(snapshot, TODAY)
        result = _map(snapshot)

        self.assertEqual(metrics["run_threshold_watts"]["value"], 290)
        self.assertFalse(
            [
                obs
                for obs in result.records
                if obs.kind is MetricKind.FTP and obs.sport is Sport.RUN
            ]
        )
        self.assertIn(
            (
                "running_threshold[0]",
                "power.functionalThresholdPower",
                IssueReason.UNSUPPORTED,
            ),
            [(i.record_ref, i.field, i.reason) for i in result.issues],
        )


if __name__ == "__main__":
    unittest.main()
