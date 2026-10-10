"""Characterization tests for body and chart history sources.

These tests pin today's behavior as the parity reference for the provider-neutral
refactor. Deliberately pinned quirks are marked with "Quirk:" comments.
"""

import math
import unittest
from datetime import date
from typing import Any

from backend.performance.body import body_history
from backend.performance.chart_history import analysis_history

TODAY = date(2026, 5, 4)
GARMIN = "Garmin Connect"
INTERVALS = "Intervals.icu"
INTERVALS_WELLNESS = "Intervals.icu Wellness"
ANALYSIS_METRIC_KEYS = (
    "cycling_ftp_watts",
    "cycling_eftp_watts",
    "run_threshold_pace_seconds_per_km",
    "cycling_vo2max_ml_kg_min",
    "running_vo2max_ml_kg_min",
    "run_5k_seconds",
    "run_10k_seconds",
    "run_half_marathon_seconds",
    "run_marathon_seconds",
)


def _wellness(
    day: str,
    weight: float | None = None,
    eftp: float | None = None,
    **extra: Any,
) -> dict[str, Any]:
    row: dict[str, Any] = {"id": day, **extra}
    if weight is not None:
        row["weight"] = weight
    if eftp is not None:
        row["sportInfo"] = [{"types": ["Ride"], "mmp_model": {"ftp": eftp}}]
    return row


def _garmin_weight(day: str, kg: float) -> dict[str, Any]:
    return {"date": day, "weightKg": kg}


def _performance_ftp(day: str, watts: float) -> dict[str, Any]:
    return {"date": day, "metrics": {"cycling_ftp_watts": watts}}


def _body_series(
    result: dict[str, Any], window: str, metric: str, source: str
) -> dict[str, Any]:
    matches = [
        item
        for item in result["windows"][window]["metrics"][metric]
        if item["source"] == source
    ]
    if not matches:
        raise AssertionError(f"no {window} {metric} series for {source}")
    return matches[0]


def _point(series: dict[str, Any], day: str) -> dict[str, Any]:
    matches = [point for point in series["points"] if point["date"] == day]
    if not matches:
        raise AssertionError(f"no point for {day}")
    return matches[0]


def _analysis_points(result: dict[str, Any], key: str) -> list[dict[str, Any]]:
    return result["metrics"][key][0]["points"]


def _point_value(points: list[dict[str, Any]], day: str) -> Any:
    return _point({"points": points}, day)["value"]


class BodyHistoryCharacterizationTests(unittest.TestCase):
    def test_same_day_weight_tie_prefers_garmin_for_both_ftp_sources(self) -> None:
        snapshot = {
            "synced_at": "intervals-sync",
            "recent_wellness": [_wellness("2026-05-04", weight=70, eftp=280)],
        }
        garmin = {
            "weight": [_garmin_weight("2026-05-04", 72)],
            "performance_history": [_performance_ftp("2026-05-04", 300)],
        }
        result = body_history(snapshot, garmin, TODAY)
        for source, watts in ((GARMIN, 300), (INTERVALS, 280)):
            with self.subTest(source=source):
                point = _point(
                    _body_series(result, "14d", "cycling_w_per_kg", source),
                    "2026-05-04",
                )
                self.assertEqual(point["weight_source"], GARMIN)
                self.assertEqual(point["weight_kg"], 72)
                self.assertEqual(point["weight_age_days"], 0)
                self.assertEqual(point["value"], round(watts / 72, 3))

    def test_newer_intervals_weight_beats_older_garmin_weight_for_w_per_kg(
        self,
    ) -> None:
        snapshot = {
            "recent_wellness": [
                _wellness("2026-05-03", weight=70),
                _wellness("2026-05-04", eftp=280),
            ]
        }
        garmin = {
            "weight": [_garmin_weight("2026-05-02", 72)],
            "performance_history": [_performance_ftp("2026-05-04", 300)],
        }
        result = body_history(snapshot, garmin, TODAY)
        garmin_point = _point(
            _body_series(result, "14d", "cycling_w_per_kg", GARMIN), "2026-05-04"
        )
        self.assertEqual(garmin_point["weight_source"], INTERVALS_WELLNESS)
        self.assertEqual(garmin_point["weight_kg"], 70)
        self.assertEqual(garmin_point["weight_age_days"], 1)
        self.assertEqual(garmin_point["value"], round(300 / 70, 3))
        # Quirk: the weight_source label is the weight provider name
        # ("Intervals.icu Wellness"), while the W/kg series source is "Intervals.icu".
        intervals_point = _point(
            _body_series(result, "14d", "cycling_w_per_kg", INTERVALS), "2026-05-04"
        )
        self.assertEqual(intervals_point["weight_source"], INTERVALS_WELLNESS)
        self.assertEqual(intervals_point["value"], round(280 / 70, 3))

    def test_w_per_kg_weight_window_is_seven_days_inclusive_and_never_looks_forward(
        self,
    ) -> None:
        def garmin_point(garmin: dict[str, Any], day: str) -> dict[str, Any]:
            result = body_history({}, garmin, TODAY)
            return _point(_body_series(result, "14d", "cycling_w_per_kg", GARMIN), day)

        seven_days_old = garmin_point(
            {
                "weight": [_garmin_weight("2026-04-27", 70)],
                "performance_history": [_performance_ftp("2026-05-04", 300)],
            },
            "2026-05-04",
        )
        self.assertEqual(seven_days_old["weight_age_days"], 7)
        self.assertEqual(seven_days_old["value"], round(300 / 70, 3))

        eight_days_old = garmin_point(
            {
                "weight": [_garmin_weight("2026-04-26", 70)],
                "performance_history": [_performance_ftp("2026-05-04", 300)],
            },
            "2026-05-04",
        )
        self.assertIsNone(eight_days_old["value"])
        self.assertNotIn("weight_kg", eight_days_old)

        # A weight recorded after the FTP day never explains that day's W/kg.
        future_weight = garmin_point(
            {
                "weight": [_garmin_weight("2026-05-03", 70)],
                "performance_history": [_performance_ftp("2026-05-02", 300)],
            },
            "2026-05-02",
        )
        self.assertEqual(future_weight["ftp_watts"], 300)
        self.assertIsNone(future_weight["value"])
        self.assertNotIn("weight_kg", future_weight)

    def test_local_profile_weight_is_never_used_for_w_per_kg(self) -> None:
        snapshot = {
            "synced_at": "sync",
            "profile": {"weight_kg": 70, "body_fat_pct": 15},
            "athlete": {"weight": 70, "weight_kg": 70},
            "recent_wellness": [_wellness("2026-05-04", eftp=280)],
        }
        garmin = {
            "profile": {"weight_kg": 70},
            "performance_history": [_performance_ftp("2026-05-04", 300)],
        }
        result = body_history(snapshot, garmin, TODAY)
        for window in ("14d", "12w"):
            for metric in ("weight_kg", "body_fat_pct"):
                for series in result["windows"][window]["metrics"][metric]:
                    self.assertTrue(all(p["value"] is None for p in series["points"]))
        for source in (GARMIN, INTERVALS):
            with self.subTest(source=source):
                series = _body_series(result, "14d", "cycling_w_per_kg", source)
                point = _point(series, "2026-05-04")
                self.assertIsNone(point["value"])
                self.assertNotIn("weight_kg", point)
        self.assertEqual(
            _point(
                _body_series(result, "14d", "cycling_w_per_kg", GARMIN), "2026-05-04"
            )["ftp_watts"],
            300,
        )

    def test_compact_wellness_row_overrides_raw_but_missing_compact_weight_keeps_raw(
        self,
    ) -> None:
        snapshot = {
            "synced_at": "sync",
            "raw_provider_data": {
                "wellness": [
                    _wellness("2026-05-03", weight=70),
                    _wellness("2026-05-04", weight=71),
                ]
            },
            "recent_wellness": [
                _wellness("2026-05-03", weight=69),
                {"id": "2026-05-04", "bodyFat": 18},
            ],
        }
        result = body_history(snapshot, {}, TODAY)
        weights = _body_series(result, "14d", "weight_kg", INTERVALS_WELLNESS)
        self.assertEqual(_point(weights, "2026-05-03")["value"], 69)
        self.assertEqual(_point(weights, "2026-05-03")["synced_at"], "sync")
        # Quirk: "last valid value wins" per day, so a compact row without a
        # weight does not clear the raw weight for the same date.
        self.assertEqual(_point(weights, "2026-05-04")["value"], 71)
        body_fat = _body_series(result, "14d", "body_fat_pct", INTERVALS_WELLNESS)
        self.assertEqual(_point(body_fat, "2026-05-04")["value"], 18)

    def test_future_measurements_never_reach_any_body_output(self) -> None:
        # Output series end at today and W/kg only looks backward, so the future
        # guards are not observable in the output. This pins that no future
        # weight, body fat, eFTP or FTP value leaks into any series.
        snapshot = {
            "synced_at": "sync",
            "recent_wellness": [
                _wellness("2026-05-05", weight=90, eftp=320, bodyFat=30),
            ],
        }
        garmin = {
            "weight": [{"date": "2026-05-05", "weightKg": 91, "bodyFat": 25}],
            "performance_history": [_performance_ftp("2026-05-05", 330)],
            "cycling_ftp_history": [
                {"date": "2026-05-05", "functionalThresholdPower": 310}
            ],
        }
        result = body_history(snapshot, garmin, TODAY)
        for window in ("14d", "12w"):
            for metric in ("weight_kg", "body_fat_pct", "cycling_w_per_kg"):
                for series in result["windows"][window]["metrics"][metric]:
                    with self.subTest(
                        window=window, metric=metric, source=series["source"]
                    ):
                        self.assertTrue(
                            all(point["value"] is None for point in series["points"])
                        )
                        self.assertFalse(
                            any("ftp_watts" in point for point in series["points"])
                        )

    def test_ftp_same_day_precedence_is_direct_then_performance_then_history(
        self,
    ) -> None:
        history = [{"date": "2026-05-04", "functionalThresholdPower": 260}]
        performance = [_performance_ftp("2026-05-04", 280)]
        direct = {"calendarDate": "2026-05-04", "functionalThresholdPower": 300}
        base: dict[str, Any] = {
            "weight": [_garmin_weight("2026-05-04", 70)],
            "source_freshness": {
                "weight": {"fetched_at": "weight-fetch"},
                "cycling_ftp_history": {"fetched_at": "history-fetch"},
                "cycling_ftp": {"fetched_at": "direct-fetch"},
            },
        }
        cases: tuple[tuple[str, dict[str, Any], int, str], ...] = (
            (
                "direct",
                {
                    "cycling_ftp_history": history,
                    "performance_history": performance,
                    "cycling_ftp": direct,
                },
                300,
                "direct-fetch",
            ),
            (
                "performance",
                {"cycling_ftp_history": history, "performance_history": performance},
                280,
                "history-fetch",
            ),
            ("history", {"cycling_ftp_history": history}, 260, "history-fetch"),
        )
        for winner, extra, expected_watts, expected_sync in cases:
            with self.subTest(winner=winner):
                result = body_history({}, {**base, **extra}, TODAY)
                point = _point(
                    _body_series(result, "14d", "cycling_w_per_kg", GARMIN),
                    "2026-05-04",
                )
                self.assertEqual(point["ftp_watts"], expected_watts)
                self.assertEqual(point["ftp_synced_at"], expected_sync)
                self.assertEqual(point["value"], round(expected_watts / 70, 3))

    def test_direct_ftp_without_date_uses_freshness_day_and_bare_scalar_is_ignored(
        self,
    ) -> None:
        bare_scalar = body_history(
            {},
            {
                "cycling_ftp": 300,
                "weight": [_garmin_weight("2026-05-04", 70)],
                "source_freshness": {"cycling_ftp": {"observed_at": "2026-05-03"}},
            },
            TODAY,
        )
        # Quirk: a bare scalar cycling_ftp has no date and is never recorded.
        self.assertFalse(
            any(
                "ftp_watts" in point
                for point in _body_series(
                    bare_scalar, "14d", "cycling_w_per_kg", GARMIN
                )["points"]
            )
        )

        dated_by_freshness = body_history(
            {},
            {
                "cycling_ftp": {"functionalThresholdPower": 300},
                "weight": [_garmin_weight("2026-05-04", 70)],
                "source_freshness": {"cycling_ftp": {"observed_at": "2026-05-03"}},
            },
            TODAY,
        )
        series = _body_series(dated_by_freshness, "14d", "cycling_w_per_kg", GARMIN)
        point = _point(series, "2026-05-03")
        self.assertEqual(point["ftp_watts"], 300)
        self.assertEqual(point["observed_at"], "2026-05-03")
        # The weight recorded on the following day does not explain 2026-05-03.
        self.assertIsNone(point["value"])

    def test_intervals_eftp_window_is_eighty_four_days_inclusive(self) -> None:
        snapshot = {
            "synced_at": "sync",
            "recent_wellness": [
                _wellness("2026-02-09", eftp=250),
                _wellness("2026-02-10", weight=70, eftp=260),
            ],
        }
        result = body_history(snapshot, {}, TODAY)
        series = _body_series(result, "12w", "cycling_w_per_kg", INTERVALS)
        points = series["points"]
        self.assertEqual(len(points), 84)
        self.assertEqual(points[0]["date"], "2026-02-10")
        self.assertEqual(series["weekly"][0]["week_start"], "2026-02-10")
        self.assertEqual(points[0]["ftp_watts"], 260)
        self.assertEqual(points[0]["value"], round(260 / 70, 3))
        self.assertFalse(any(point.get("ftp_watts") == 250 for point in points))


class AnalysisHistoryCharacterizationTests(unittest.TestCase):
    def test_source_labels_window_shape_and_metric_keys(self) -> None:
        snapshot = {
            "synced_at": "sync",
            "recent_wellness": [_wellness("2026-05-04", weight=70, eftp=270)],
        }
        garmin = {
            "training_status": [
                {"calendarDate": "2026-05-04", "acuteTrainingLoad": 300}
            ],
            "performance_history": [_performance_ftp("2026-05-04", 300)],
        }
        result = analysis_history(snapshot, garmin, TODAY)
        self.assertEqual(result["start"], "2026-02-04")
        self.assertEqual(result["end"], "2026-05-04")
        self.assertEqual(result["days"], 90)
        self.assertEqual(
            (result["load"]["source"], result["load"]["start"], result["load"]["end"]),
            (GARMIN, "2026-02-04", "2026-05-04"),
        )
        self.assertEqual(len(result["load"]["points"]), 90)
        self.assertEqual(result["training_time"]["source"], INTERVALS)
        self.assertEqual(len(result["training_time"]["points"]), 90)
        self.assertEqual(set(result["metrics"]), set(ANALYSIS_METRIC_KEYS))
        for key in ANALYSIS_METRIC_KEYS:
            with self.subTest(metric=key):
                sources = result["metrics"][key]
                self.assertEqual(len(sources), 1)
                expected = INTERVALS if key == "cycling_eftp_watts" else GARMIN
                self.assertEqual(sources[0]["source"], expected)
                self.assertEqual(len(sources[0]["points"]), 90)
        body_sources = {
            metric: sorted(
                item["source"]
                for item in result["body"]["windows"]["12w"]["metrics"][metric]
            )
            for metric in ("weight_kg", "cycling_w_per_kg")
        }
        self.assertEqual(
            body_sources,
            {
                "weight_kg": sorted([INTERVALS_WELLNESS, GARMIN]),
                "cycling_w_per_kg": sorted([INTERVALS, GARMIN]),
            },
        )

    def test_body_section_is_identical_to_direct_body_history(self) -> None:
        snapshot = {
            "synced_at": "sync",
            "recent_wellness": [
                _wellness("2026-05-03", weight=70),
                _wellness("2026-05-04", eftp=280),
            ],
        }
        garmin = {
            "weight": [_garmin_weight("2026-05-02", 72)],
            "performance_history": [_performance_ftp("2026-05-04", 300)],
        }
        self.assertEqual(
            analysis_history(snapshot, garmin, TODAY)["body"],
            body_history(snapshot, garmin, TODAY),
        )

    def test_training_time_counts_duplicate_ids_once_and_first_occurrence_wins(
        self,
    ) -> None:
        snapshot = {
            "raw_provider_data": {
                "activities": [
                    {
                        "id": "a1",
                        "start_date_local": "2026-05-03T07:00:00",
                        "moving_time": 3600,
                    }
                ]
            },
            "recent_activities": [
                {
                    "id": "a1",
                    "start_date_local": "2026-05-03T07:00:00",
                    "moving_time": 7200,
                },
                {
                    "id": "a2",
                    "start_date_local": "2026-05-03T18:00:00",
                    "moving_time": 1800,
                },
            ],
        }
        result = analysis_history(snapshot, {}, TODAY)
        # Raw rows come first, so the raw moving_time of a1 is the one counted.
        self.assertEqual(
            _point_value(result["training_time"]["points"], "2026-05-03"), 1.5
        )

    def test_training_time_value_bounds_and_missing_fields(self) -> None:
        snapshot = {
            "recent_activities": [
                {
                    "id": "z0",
                    "start_date_local": "2026-05-01T07:00:00",
                    "moving_time": 0,
                },
                {
                    "id": "z1",
                    "start_date_local": "2026-05-01T08:00:00",
                    "moving_time": 1800.5,
                },
                {
                    "id": "z2",
                    "start_date_local": "2026-05-02T07:00:00",
                    "moving_time": 86400,
                },
                {
                    "id": "z3",
                    "start_date_local": "2026-05-03T07:00:00",
                    "moving_time": 86401,
                },
                {
                    "id": "z4",
                    "start_date_local": "2026-05-03T08:00:00",
                    "moving_time": True,
                },
                {
                    "id": "z5",
                    "start_date_local": "2026-05-03T09:00:00",
                    "moving_time": "3600",
                },
                # Only start_date_local is trusted; start_date alone is ignored.
                {"id": "z6", "start_date": "2026-05-04T07:00:00", "moving_time": 3600},
                {"id": "z7", "start_date_local": "not a date", "moving_time": 3600},
                # Quirk: activities without an id are never deduplicated.
                {"start_date_local": "2026-05-02T08:00:00", "moving_time": 1800},
                {"start_date_local": "2026-05-02T09:00:00", "moving_time": 1800},
            ]
        }
        points = analysis_history(snapshot, {}, TODAY)["training_time"]["points"]
        self.assertEqual(_point_value(points, "2026-05-01"), 0.5)
        self.assertEqual(_point_value(points, "2026-05-02"), 25.0)
        self.assertIsNone(_point_value(points, "2026-05-03"))
        self.assertIsNone(_point_value(points, "2026-05-04"))

    def test_training_load_last_row_per_day_wins_even_when_it_has_no_value(
        self,
    ) -> None:
        acute = {"calendarDate": "2026-05-03", "acuteTrainingLoad": 475}
        without_acute = {"calendarDate": "2026-05-03", "dailyTrainingLoad": 100}
        # Quirk: a later row without acute load overwrites an earlier valid value.
        points = analysis_history(
            None, {"training_status": [acute, without_acute]}, TODAY
        )["load"]["points"]
        self.assertIsNone(_point_value(points, "2026-05-03"))
        reversed_points = analysis_history(
            None, {"training_status": [without_acute, acute]}, TODAY
        )["load"]["points"]
        self.assertEqual(_point_value(reversed_points, "2026-05-03"), 475)

    def test_garmin_metric_keeps_last_valid_value_and_starts_at_eighty_nine_days(
        self,
    ) -> None:
        garmin = {
            "performance_history": [
                {"date": "2026-02-03", "metrics": {"cycling_vo2max_ml_kg_min": 50}},
                {"date": "2026-02-04", "metrics": {"cycling_vo2max_ml_kg_min": 51}},
                {"date": "2026-05-03", "metrics": {"cycling_vo2max_ml_kg_min": 55}},
                {"date": "2026-05-03", "metrics": {"cycling_vo2max_ml_kg_min": 57}},
                {
                    "date": "2026-05-03",
                    "metrics": {"cycling_vo2max_ml_kg_min": math.nan},
                },
            ]
        }
        points = _analysis_points(
            analysis_history(None, garmin, TODAY), "cycling_vo2max_ml_kg_min"
        )
        self.assertEqual(points[0], {"date": "2026-02-04", "value": 51})
        # Quirk: for Garmin metric series the last valid value wins and an invalid
        # later row is ignored (contrast with training load below).
        self.assertEqual(_point_value(points, "2026-05-03"), 57)
        self.assertEqual(sum(point["value"] is not None for point in points), 2)

    def test_eftp_same_day_wellness_beats_activity_and_latest_activity_wins(
        self,
    ) -> None:
        # The latest 2026-05-03 activity is listed last so that a first-occurrence
        # rule would be distinguishable from the observed latest-start rule.
        activities = [
            {
                "start_date_local": "2026-05-02T08:00:00",
                "type": "Ride",
                "icu_eftp": 240,
            },
            {
                "start_date_local": "2026-05-03T08:00:00",
                "type": "Ride",
                "icu_eftp": 250,
            },
            {
                "start_date_local": "2026-05-03T16:00:00",
                "type": "Ride",
                "icu_eftp": 260,
            },
        ]
        activities_only = _analysis_points(
            analysis_history({"recent_activities": activities}, {}, TODAY),
            "cycling_eftp_watts",
        )
        self.assertEqual(_point_value(activities_only, "2026-05-03"), 260)
        self.assertEqual(_point_value(activities_only, "2026-05-02"), 240)

        with_wellness = _analysis_points(
            analysis_history(
                {
                    "recent_activities": activities,
                    "recent_wellness": [_wellness("2026-05-03", eftp=270)],
                },
                {},
                TODAY,
            ),
            "cycling_eftp_watts",
        )
        self.assertEqual(_point_value(with_wellness, "2026-05-03"), 270)

    def test_eftp_chart_window_is_ninety_days_while_body_eftp_is_eighty_four(
        self,
    ) -> None:
        # Quirk: the chart eFTP series uses the 90-day analysis window while body
        # eFTP uses an 84-day window. The divergence is intentional for now and
        # is pinned here so a refactor cannot silently merge the two windows.
        snapshot = {
            "recent_wellness": [
                _wellness("2026-02-03", eftp=240),
                _wellness("2026-02-04", eftp=250),
            ]
        }
        result = analysis_history(snapshot, {}, TODAY)
        points = _analysis_points(result, "cycling_eftp_watts")
        self.assertEqual(points[0], {"date": "2026-02-04", "value": 250})
        self.assertFalse(any(point["value"] == 240 for point in points))
        body_points = _body_series(
            result["body"], "12w", "cycling_w_per_kg", INTERVALS
        )["points"]
        self.assertFalse(
            any(point.get("ftp_watts") in (240, 250) for point in body_points)
        )

    def test_compact_wellness_row_replaces_raw_row_for_chart_eftp_but_not_body(
        self,
    ) -> None:
        snapshot = {
            "raw_provider_data": {
                "wellness": [_wellness("2026-05-03", eftp=270)],
            },
            "recent_wellness": [{"id": "2026-05-03", "ctl": 40}],
        }
        result = analysis_history(snapshot, {}, TODAY)
        # Quirk: chart history keys wellness rows by day, so the compact row
        # replaces the raw row wholesale and its eFTP is lost. Body history
        # keeps both rows and still reports 270.
        self.assertIsNone(
            _point_value(_analysis_points(result, "cycling_eftp_watts"), "2026-05-03")
        )
        body_point = _point(
            _body_series(result["body"], "12w", "cycling_w_per_kg", INTERVALS),
            "2026-05-03",
        )
        self.assertEqual(body_point["ftp_watts"], 270)

    def test_provider_metrics_pass_through_or_fall_back_to_unavailable_projection(
        self,
    ) -> None:
        supplied = {"endurance_score": {"status": "current"}}
        self.assertEqual(
            analysis_history(None, {"provider_metrics": supplied}, TODAY)[
                "provider_metrics"
            ],
            supplied,
        )
        projected = analysis_history(
            None,
            {
                "endurance_score": [
                    {"calendarDate": "2026-05-03", "overallScore": 70},
                ],
                "running_tolerance": [{"calendarDate": "2026-05-04", "value": 12}],
            },
            TODAY,
        )["provider_metrics"]
        self.assertEqual(projected["endurance_score"]["status"], "current")
        self.assertEqual(projected["endurance_score"]["observed_at"], "2026-05-03")
        self.assertEqual(
            projected["endurance_score"]["points"],
            [
                {
                    "date": "2026-05-03",
                    "values": {"overallScore": 70.0},
                    "source": GARMIN,
                }
            ],
        )
        self.assertEqual(projected["running_tolerance"]["observed_at"], "2026-05-04")

        fallback = analysis_history(None, {}, TODAY)["provider_metrics"]
        self.assertEqual(set(fallback), {"endurance_score", "running_tolerance"})
        self.assertEqual(fallback["endurance_score"]["status"], "unavailable")
        self.assertEqual(fallback["endurance_score"]["source"], GARMIN)
        self.assertEqual(fallback["endurance_score"]["points"], [])


if __name__ == "__main__":
    unittest.main()
