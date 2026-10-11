"""Characterization of load rollups, ATL reconstruction and training focus.

These tests pin the current behaviour of the load context, the activity
rollups, the reconstructed ATL series, the training-focus projection and the
Wahoo/Garmin canonical row selection. They are the parity reference for a later
refactor, so deliberate quirks are pinned as they are and marked "Quirk:".
"""

import math
import unittest
from datetime import date, timedelta
from typing import Any

from backend.performance.load import activity_rollup, actual_atl_series
from backend.performance.load_context import performance_load_context
from backend.performance.training_focus import training_focus
from backend.performance.training_report import canonical_rows

TODAY = date(2026, 5, 4)
RETENTION = math.exp(-1.0 / 7.0)
DECAY = 1.0 - RETENTION


def _day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _activity(day: str, **fields: Any) -> dict[str, Any]:
    return {"start_date_local": day, "moving_time": 3600, **fields}


def _wellness(day: str, atl: Any, **fields: Any) -> dict[str, Any]:
    return {"id": day, "atl": atl, **fields}


def _ride(
    activity_id: str, start: str = "2026-05-04T08:00:00", **fields: Any
) -> dict[str, Any]:
    return {
        "id": activity_id,
        "type": "Ride",
        "start_date_local": start,
        "moving_time": 3600,
        "distance": 30000,
        **fields,
    }


def _garmin(
    activity_id: str,
    label: str | None,
    load: Any,
    start: str = "2026-05-04T08:00:00",
) -> dict[str, Any]:
    return {
        "activityId": activity_id,
        "startTimeLocal": start,
        "trainingEffectLabel": label,
        "activityTrainingLoad": load,
    }


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    return [str(row["id"]) for row in rows]


class CharacterizationLoadRollupTests(unittest.TestCase):
    def test_rollup_reads_only_local_start_date_and_ignores_absolute_start(
        self,
    ) -> None:
        # Quirk: an absolute start_date is never consulted by the rollup.
        result = activity_rollup(
            [
                {
                    "start_date": "2026-05-04T08:00:00Z",
                    "moving_time": 60,
                    "icu_training_load": 5,
                }
            ],
            1,
            TODAY,
        )
        self.assertEqual(
            result,
            {"days": 1, "sessions": 0, "duration_hours": 0.0, "training_load": 0.0},
        )

    def test_rollup_ignores_alias_keys_for_duration_and_load(self) -> None:
        # Quirk: only moving_time and icu_training_load are read; elapsed_time and
        # training_load are not aliases here, although the row still counts.
        result = activity_rollup(
            [
                {
                    "start_date_local": "2026-05-04",
                    "elapsed_time": 3600,
                    "training_load": 50,
                }
            ],
            1,
            TODAY,
        )
        self.assertEqual(result["sessions"], 1)
        self.assertEqual(result["duration_hours"], 0.0)
        self.assertEqual(result["training_load"], 0.0)

    def test_rollup_parses_numeric_strings_and_zeroes_structured_values(self) -> None:
        result = activity_rollup(
            [
                {
                    "start_date_local": "2026-05-04",
                    "moving_time": "5400",
                    "icu_training_load": "12.5",
                },
                {
                    "start_date_local": "2026-05-04",
                    "moving_time": ["3600"],
                    "icu_training_load": {"value": 9},
                },
            ],
            1,
            TODAY,
        )
        self.assertEqual(
            result,
            {"days": 1, "sessions": 2, "duration_hours": 1.5, "training_load": 12.5},
        )

    def test_rollup_decimal_comma_load_is_zero_while_atl_accepts_it(self) -> None:
        # Quirk: activity_rollup parses with plain float(), so "42,5" becomes 0.
        # The ATL reconstruction normalises commas and keeps the value (see below).
        result = activity_rollup(
            [
                {
                    "start_date_local": "2026-05-04",
                    "moving_time": "1800",
                    "icu_training_load": "42,5",
                }
            ],
            1,
            TODAY,
        )
        self.assertEqual(result["sessions"], 1)
        self.assertEqual(result["duration_hours"], 0.5)
        self.assertEqual(result["training_load"], 0.0)

    def test_rollup_sums_negative_loads_without_bounds(self) -> None:
        # Quirk: the rollup has no lower bound, so negative loads reduce totals.
        result = activity_rollup(
            [
                {"start_date_local": "2026-05-04", "icu_training_load": 20},
                {"start_date_local": "2026-05-04", "icu_training_load": -5},
            ],
            1,
            TODAY,
        )
        self.assertEqual(result["training_load"], 15.0)

    def test_rollup_rounds_hours_and_load_to_one_decimal(self) -> None:
        result = activity_rollup(
            [
                {
                    "start_date_local": "2026-05-04",
                    "moving_time": 1000,
                    "icu_training_load": 10.06,
                }
            ],
            1,
            TODAY,
        )
        self.assertEqual(result["duration_hours"], 0.3)
        self.assertEqual(result["training_load"], 10.1)

    def test_rollup_window_excludes_dates_after_end_and_keeps_timestamps_on_end(
        self,
    ) -> None:
        result = activity_rollup(
            [
                {"start_date_local": "2026-05-04T23:59:59", "moving_time": 60},
                {"start_date_local": _day(1), "moving_time": 60},
            ],
            1,
            TODAY,
        )
        self.assertEqual(result["sessions"], 1)


class CharacterizationAtlSeriesTests(unittest.TestCase):
    def test_first_day_load_is_backed_out_and_has_no_effect_on_the_series(
        self,
    ) -> None:
        # The first wellness ATL is reproduced exactly: its own day load is backed
        # out before the recurrence starts, so the series matches one without it.
        wellness = [_wellness("2026-05-03", 10), _wellness("2026-05-04", 20)]
        with_load = actual_atl_series(
            wellness,
            [_activity("2026-05-03", icu_training_load=70)],
            TODAY,
        )
        without_load = actual_atl_series(wellness, [], TODAY)
        self.assertEqual(with_load, without_load)
        self.assertEqual(with_load[date(2026, 5, 3)], 10.0)

    def test_only_the_first_wellness_atl_anchors_the_series(self) -> None:
        # Quirk: later wellness ATL values are not read; only their presence
        # matters, and the value is reconstructed from the first row's ATL.
        series = actual_atl_series(
            [_wellness("2026-05-01", 10), _wellness("2026-05-02", 999)], [], TODAY
        )
        self.assertEqual(
            series,
            {date(2026, 5, 1): 10.0, date(2026, 5, 2): round(10 * RETENTION, 2)},
        )

    def test_activity_load_on_a_day_without_wellness_row_is_dropped(self) -> None:
        # Quirk: loads on days without a wellness row only decay the anchor. They are
        # never added, so the series is identical with or without the activity.
        wellness = [_wellness("2026-05-01", 10), _wellness("2026-05-04", 10)]
        with_gap_load = actual_atl_series(
            wellness, [_activity("2026-05-02", icu_training_load=100)], TODAY
        )
        self.assertEqual(
            with_gap_load,
            {
                date(2026, 5, 1): 10.0,
                date(2026, 5, 4): round(10 * RETENTION**3, 2),
            },
        )
        self.assertEqual(with_gap_load, actual_atl_series(wellness, [], TODAY))

    def test_activity_load_before_first_wellness_row_is_ignored(self) -> None:
        series = actual_atl_series(
            [_wellness("2026-05-04", 10)],
            [_activity("2026-04-30", icu_training_load=70)],
            TODAY,
        )
        self.assertEqual(series, {date(2026, 5, 4): 10.0})

    def test_activity_load_after_anchor_is_ignored_but_future_wellness_is_kept(
        self,
    ) -> None:
        # Quirk: the series itself contains wellness rows after the anchor date;
        # only the context layer filters them out (see the context tests).
        series = actual_atl_series(
            [_wellness("2026-05-04", 10), _wellness("2026-05-06", 10)],
            [_activity("2026-05-05", icu_training_load=999)],
            TODAY,
        )
        self.assertEqual(
            series,
            {date(2026, 5, 4): 10.0, date(2026, 5, 6): round(10 * RETENTION**2, 2)},
        )

    def test_duplicate_wellness_dates_apply_the_day_load_twice(self) -> None:
        # Quirk: each wellness row applies its day's load, so duplicate dates apply
        # the load twice, and the last row written for that date wins.
        series = actual_atl_series(
            [_wellness("2026-05-04", 10), _wellness("2026-05-04", 10)],
            [_activity("2026-05-04", icu_training_load=70)],
            TODAY,
        )
        self.assertEqual(
            series, {date(2026, 5, 4): round(10 * RETENTION + 70 * DECAY, 2)}
        )

    def test_decimal_comma_activity_load_is_accepted_by_atl(self) -> None:
        series = actual_atl_series(
            [_wellness("2026-05-03", 10), _wellness("2026-05-04", 10)],
            [_activity("2026-05-04", icu_training_load="42,5")],
            TODAY,
        )
        self.assertEqual(
            series[date(2026, 5, 4)], round(10 * RETENTION + 42.5 * DECAY, 2)
        )

    def test_non_numeric_loads_and_malformed_activities_contribute_nothing(
        self,
    ) -> None:
        series = actual_atl_series(
            [_wellness("2026-05-03", 10), _wellness("2026-05-04", 10)],
            [
                "junk",
                _activity("2026-05-04", icu_training_load="n/a"),
                {"start_date_local": None, "icu_training_load": 50},
            ],
            TODAY,
        )
        self.assertEqual(series[date(2026, 5, 4)], round(10 * RETENTION, 2))

    def test_row_date_prefers_id_and_does_not_fall_back_when_id_is_invalid(
        self,
    ) -> None:
        # Quirk: an invalid id is not replaced by the date field, so that row drops.
        series = actual_atl_series(
            [
                {"id": "2026-05-03T07:00:00", "atl": 10},
                {"id": "bad", "date": "2026-05-04", "atl": 10},
                {"date": "2026-05-05", "atl": 20},
            ],
            [],
            TODAY,
        )
        self.assertEqual(
            series,
            {date(2026, 5, 3): 10.0, date(2026, 5, 5): round(10 * RETENTION**2, 2)},
        )

    def test_only_the_plain_atl_key_is_read_from_wellness_rows(self) -> None:
        # Quirk: the atlLoad alias is ignored by the reconstruction.
        self.assertEqual(
            actual_atl_series([{"id": "2026-05-04", "atlLoad": 10}], [], TODAY), {}
        )
        self.assertEqual(
            actual_atl_series(
                [{"id": "2026-05-04", "atl": 10, "atlLoad": 99}], [], TODAY
            ),
            {date(2026, 5, 4): 10.0},
        )


class CharacterizationLoadContextTests(unittest.TestCase):
    def test_result_contract_keys_are_stable(self) -> None:
        result = performance_load_context([], [], {}, TODAY)
        self.assertEqual(
            set(result),
            {
                "load",
                "last_7",
                "previous_7",
                "last_30",
                "previous_30",
                "actual_atl_current",
                "actual_atl_date",
                "actual_atl_average",
            },
        )

    def test_missing_latest_wellness_yields_null_load_block(self) -> None:
        self.assertEqual(
            performance_load_context([], [], {}, TODAY)["load"],
            {"id": None, "ctl": None, "atl": None, "tsb": None, "rampRate": None},
        )

    def test_load_block_takes_ctl_and_atl_from_aliases_without_normalising(
        self,
    ) -> None:
        # Quirk: ctl and atl come from the latest Intervals row (with aliases), raw
        # values are passed through, and TSB is derived only from the plain keys.
        result = performance_load_context(
            [],
            [],
            {
                "id": TODAY.isoformat(),
                "ctLoad": "55",
                "atlLoad": 65,
                "rampRate": "1,5",
            },
            TODAY,
        )
        self.assertEqual(
            result["load"],
            {
                "id": TODAY.isoformat(),
                "ctl": "55",
                "atl": 65,
                "tsb": None,
                "rampRate": "1,5",
            },
        )

    def test_load_block_skips_empty_strings_but_keeps_zero(self) -> None:
        result = performance_load_context(
            [], [], {"ctl": "", "ctLoad": 55, "atl": 0}, TODAY
        )
        self.assertEqual(result["load"]["ctl"], 55)
        self.assertEqual(result["load"]["atl"], 0)

    def test_tsb_prefers_direct_fields_then_derives_from_plain_ctl_and_atl(
        self,
    ) -> None:
        derived = performance_load_context(
            [], [], {"ctl": 50, "atl": 60, "tsb": ""}, TODAY
        )
        direct = performance_load_context(
            [], [], {"ctl": 50, "atl": 60, "freshness": 4}, TODAY
        )
        self.assertEqual(derived["load"]["tsb"], -10.0)
        self.assertEqual(direct["load"]["tsb"], 4)

    def test_actual_atl_current_falls_back_to_a_stale_row_while_average_is_empty(
        self,
    ) -> None:
        # Quirk: the current value is the last row on or before today, however old,
        # while the average needs a row inside the last seven days.
        result = performance_load_context([], [_wellness("2026-04-20", 30)], {}, TODAY)
        self.assertEqual(result["actual_atl_current"], 30.0)
        self.assertEqual(result["actual_atl_date"], date(2026, 4, 20))
        self.assertIsNone(result["actual_atl_average"])

    def test_actual_atl_average_uses_only_the_seven_day_window(self) -> None:
        # Quirk: the series decays from the first row (100 on 2026-04-27), so the
        # later ATL values 10 and 20 do not change the result. Only the rows dated
        # 2026-05-01 and 2026-05-04 fall in the window: (100 * R**4 + 100 * R**7) / 2
        # with R = exp(-1/7).
        rows = [
            _wellness("2026-04-27", 100),
            _wellness("2026-05-01", 10),
            _wellness("2026-05-04", 20),
        ]
        result = performance_load_context([], rows, {}, TODAY)
        self.assertEqual(result["actual_atl_average"], 46.63)

    def test_future_wellness_is_excluded_from_current_and_average(self) -> None:
        rows = [_wellness("2026-05-04", 20), _wellness("2026-05-05", 999)]
        result = performance_load_context([], rows, {}, TODAY)
        self.assertEqual(result["actual_atl_current"], 20.0)
        self.assertEqual(result["actual_atl_date"], TODAY)
        self.assertEqual(result["actual_atl_average"], 20.0)
        self.assertIn(date(2026, 5, 5), actual_atl_series(rows, [], TODAY))

    def test_context_rollups_count_garmin_and_wahoo_copies_twice(self) -> None:
        # Quirk: the production caller passes raw recent_activities, so the load
        # context does not apply canonical_rows and both copies of one ride count.
        activities = [
            _ride(
                "w",
                source="WAHOO ELEMNT",
                icu_training_load=40,
            ),
            _ride("g", source="garmin", icu_training_load=40),
        ]
        result = performance_load_context(activities, [], {}, TODAY)
        self.assertEqual(result["last_7"]["sessions"], 2)
        self.assertEqual(result["last_7"]["training_load"], 80.0)
        self.assertEqual(result["last_7"]["duration_hours"], 2.0)


class CharacterizationTrainingFocusTests(unittest.TestCase):
    def test_zones_keep_only_heart_rate_and_power_and_drop_pace_and_strength(
        self,
    ) -> None:
        snapshot = {
            "recent_activities": [
                _ride(
                    "r",
                    icu_hr_zone_times=[600],
                    icu_zone_times=[{"id": "Z1", "secs": 300}],
                    pace_zone_times=[{"id": "Z1", "secs": 900}],
                ),
                {
                    "id": "s",
                    "type": "WeightTraining",
                    "start_date_local": "2026-05-04T08:00:00",
                    "moving_time": 3600,
                    "icu_hr_zone_times": [1800],
                },
            ]
        }
        result = training_focus(snapshot, {}, TODAY)
        self.assertEqual(
            sorted({row["sensor"] for row in result["zones"]}),
            ["heart_rate", "power"],
        )
        zones = {row["sensor"]: row["seconds"] for row in result["zones"]}
        self.assertEqual(zones["heart_rate"], {"Z1": 600.0})
        self.assertEqual(zones["power"], {"Z1": 300.0})

    def test_zones_are_built_from_canonical_rows_so_garmin_copies_are_excluded(
        self,
    ) -> None:
        snapshot = {
            "recent_activities": [
                _ride("w", source="wahoo", icu_hr_zone_times=[600]),
                _ride("g", source="garmin", icu_hr_zone_times=[600]),
            ]
        }
        result = training_focus(snapshot, {}, TODAY)
        self.assertEqual(result["zones"][0]["seconds"], {"Z1": 600.0})

    def test_zones_prefer_raw_provider_activities_even_when_that_list_is_empty(
        self,
    ) -> None:
        # Quirk: an empty raw_provider_data.activities list wins over recent_activities.
        snapshot = {
            "raw_provider_data": {"activities": []},
            "recent_activities": [_ride("r", icu_hr_zone_times=[600])],
        }
        self.assertEqual(training_focus(snapshot, {}, TODAY)["zones"], [])

    def test_zone_window_includes_today_minus_27_and_today_only(self) -> None:
        snapshot = {
            "recent_activities": [
                _ride("before", start=f"{_day(-28)}T08:00:00", icu_hr_zone_times=[900]),
                _ride("first", start=f"{_day(-27)}T08:00:00", icu_hr_zone_times=[300]),
                _ride("today", start=f"{_day(0)}T08:00:00", icu_hr_zone_times=[300]),
                _ride("after", start=f"{_day(1)}T08:00:00", icu_hr_zone_times=[900]),
            ]
        }
        result = training_focus(snapshot, {}, TODAY)
        self.assertEqual(result["zones"][0]["seconds"], {"Z1": 600.0})
        self.assertEqual(result["zones"][0]["training_seconds"], 7200)

    def test_zone_timezone_moves_absolute_start_into_the_requested_day(self) -> None:
        ride = _ride(
            "r",
            start="2026-05-04T22:30:00",
            start_date="2026-05-04T22:30:00Z",
            icu_hr_zone_times=[600],
        )
        utc = training_focus({"recent_activities": [ride]}, {}, TODAY, "UTC")
        berlin = training_focus(
            {"recent_activities": [ride]}, {}, TODAY, "Europe/Berlin"
        )
        self.assertEqual(utc["zones"][0]["seconds"], {"Z1": 600.0})
        # 22:30 UTC is 00:30 on 2026-05-05 in Berlin, after the window end.
        self.assertEqual(berlin["zones"], [])

    def test_invalid_timezone_name_falls_back_to_local_start_date(self) -> None:
        ride = _ride(
            "r",
            start="2026-05-04T22:30:00",
            start_date="2026-05-04T22:30:00Z",
            icu_hr_zone_times=[600],
        )
        result = training_focus(
            {"recent_activities": [ride]}, {}, TODAY, "Mars/Olympus"
        )
        self.assertEqual(result["zones"][0]["seconds"], {"Z1": 600.0})

    def test_garmin_coverage_uses_local_start_time_and_ignores_timezone(self) -> None:
        # Quirk: Garmin rows only carry a local timestamp, so the timezone argument
        # never moves them to another day.
        garmin = {
            "activities": [
                _garmin("a", "TEMPO", 40, start="2026-05-04T23:30:00"),
                _garmin("b", "TEMPO", 40, start="2026-05-05T00:30:00"),
            ]
        }
        for timezone in ("UTC", "Europe/Berlin"):
            with self.subTest(timezone=timezone):
                result = training_focus({}, garmin, TODAY, timezone)
                self.assertEqual(result["coverage"]["known_sessions"], 1)
                self.assertEqual(result["coverage"]["observed_end"], "2026-05-04")

    def test_activity_id_zero_is_treated_as_missing_identity(self) -> None:
        # Quirk: a numeric activityId of 0 is falsy, so the row is unclassified.
        result = training_focus(
            {},
            {
                "activities": [
                    {
                        "activityId": 0,
                        "startTimeLocal": "2026-05-04T08:00:00",
                        "trainingEffectLabel": "TEMPO",
                        "activityTrainingLoad": 40,
                    }
                ]
            },
            TODAY,
        )
        self.assertEqual(result["coverage"]["known_sessions"], 1)
        self.assertEqual(result["classified_sessions"], 0)
        self.assertEqual(result["unclassified_sessions"], 1)
        self.assertEqual(result["categories"]["high_aerobic"]["sessions"], 0)

    def test_garmin_load_bounds_and_parsing_edges_are_pinned(self) -> None:
        # Inclusive bounds 0..100000; "12,5" parses as 12.5; an oversized numeric
        # string is rejected.
        garmin = {
            "activities": [
                _garmin("a", "TEMPO", 0),
                _garmin("b", "TEMPO", 100000),
                _garmin("c", "TEMPO", 100001),
                _garmin("d", "TEMPO", -1),
                _garmin("e", "TEMPO", "12,5"),
                _garmin("f", "TEMPO", "9" * 33),
            ]
        }
        result = training_focus({}, garmin, TODAY)
        self.assertEqual(result["classified_sessions"], 3)
        self.assertEqual(result["unclassified_sessions"], 3)
        self.assertEqual(
            result["categories"]["high_aerobic"], {"load": 100012.5, "sessions": 3}
        )

    def test_category_labels_are_case_insensitive_aliased_and_not_trimmed(
        self,
    ) -> None:
        # Quirk: labels are upper-cased but not stripped, so padded labels are unknown.
        garmin = {
            "activities": [
                _garmin("a", "tempo", 5),
                _garmin("b", "LACTATE_THRESHOLD", 5),
                _garmin("c", "VO2MAX", 5),
                _garmin("d", "SPEED", 5),
                _garmin("e", "ANAEROBIC", 5),
                _garmin("f", " TEMPO ", 5),
                _garmin("g", "RECOVERY", 5),
                _garmin("h", "HIGH_AEROBIC", 5),
                _garmin("i", "OTHER", 5),
                _garmin("j", None, 5),
            ]
        }
        result = training_focus({}, garmin, TODAY)
        categories = result["categories"]
        self.assertEqual(categories["high_aerobic"], {"load": 20.0, "sessions": 4})
        self.assertEqual(categories["low_aerobic"], {"load": 5.0, "sessions": 1})
        self.assertEqual(categories["anaerobic"], {"load": 10.0, "sessions": 2})
        self.assertEqual(result["unclassified_sessions"], 3)

    def test_every_mapped_training_effect_label_lands_in_its_category(self) -> None:
        expected = {
            "RECOVERY": "low_aerobic",
            "AEROBIC_BASE": "low_aerobic",
            "LOW_AEROBIC": "low_aerobic",
            "TEMPO": "high_aerobic",
            "THRESHOLD": "high_aerobic",
            "LACTATE_THRESHOLD": "high_aerobic",
            "VO2_MAX": "high_aerobic",
            "VO2MAX": "high_aerobic",
            "HIGH_AEROBIC": "high_aerobic",
            "ANAEROBIC_CAPACITY": "anaerobic",
            "SPEED": "anaerobic",
            "ANAEROBIC": "anaerobic",
        }
        for label, category in expected.items():
            with self.subTest(label=label):
                result = training_focus(
                    {}, {"activities": [_garmin("a", label, 5)]}, TODAY
                )
                self.assertEqual(result["categories"][category]["sessions"], 1)
                self.assertEqual(result["classified_sessions"], 1)

    def test_dedicated_load_fields_override_per_key_so_null_load_keeps_base(
        self,
    ) -> None:
        garmin = {
            "activities": [_garmin("a", "TEMPO", 40)],
            "training_load_activities": [
                {
                    "activityId": "a",
                    "trainingEffectLabel": "ANAEROBIC_CAPACITY",
                    "activityTrainingLoad": None,
                }
            ],
        }
        result = training_focus({}, garmin, TODAY)
        self.assertEqual(
            result["categories"]["anaerobic"], {"load": 40.0, "sessions": 1}
        )
        self.assertEqual(result["categories"]["high_aerobic"]["sessions"], 0)
        self.assertEqual(
            result["category_source_key"], "training_load_activities+activities"
        )

    def test_empty_dedicated_load_list_keeps_activities_only_source(self) -> None:
        garmin = {
            "activities": [_garmin("a", "TEMPO", 40)],
            "training_load_activities": [],
            "source_freshness": {
                "training_load_activities": {"freshness": "current"},
            },
        }
        result = training_focus({}, garmin, TODAY)
        self.assertEqual(result["category_source_key"], "activities")
        self.assertEqual(set(result["category_freshness"]), {"activities"})

    def test_category_freshness_reports_measurement_age_and_unknown_defaults(
        self,
    ) -> None:
        garmin = {
            "activities": [_garmin("a", "TEMPO", 40)],
            "training_load_activities": [
                {"activityId": "a", "activityTrainingLoad": 40}
            ],
            "source_freshness": {
                "activities": {
                    "freshness": "current",
                    "observed_at": "2026-05-03",
                    "fetched_at": "2026-05-04T06:00:00",
                }
            },
        }
        result = training_focus({}, garmin, TODAY)
        self.assertEqual(
            result["category_freshness"]["activities"],
            {
                "freshness": "current",
                "observed_at": "2026-05-03",
                "fetched_at": "2026-05-04T06:00:00",
                "measurement_status": "earlier",
                "measurement_age_days": 1,
            },
        )
        self.assertEqual(
            result["category_freshness"]["training_load_activities"],
            {
                "freshness": "unknown",
                "observed_at": None,
                "fetched_at": None,
                "measurement_status": "unknown",
                "measurement_age_days": None,
            },
        )

    def test_missing_source_freshness_defaults_the_activities_source(self) -> None:
        result = training_focus({}, {"activities": [_garmin("a", "TEMPO", 40)]}, TODAY)
        self.assertEqual(
            result["category_freshness"],
            {
                "activities": {
                    "freshness": "unknown",
                    "observed_at": None,
                    "fetched_at": None,
                    "measurement_status": "unknown",
                    "measurement_age_days": None,
                }
            },
        )

    def test_snapshot_ride_loads_never_feed_training_focus_categories(
        self,
    ) -> None:
        snapshot = {
            "recent_activities": [
                _ride("r", icu_training_load=99, start="2026-05-04T08:00:00")
            ]
        }
        result = training_focus(snapshot, {}, TODAY)
        self.assertEqual(result["classified_sessions"], 0)
        self.assertEqual(result["unclassified_sessions"], 0)
        self.assertEqual(
            result["categories"],
            {
                "low_aerobic": {"load": 0.0, "sessions": 0},
                "high_aerobic": {"load": 0.0, "sessions": 0},
                "anaerobic": {"load": 0.0, "sessions": 0},
            },
        )

    def test_garmin_activity_rows_are_capped_at_the_first_thousand(self) -> None:
        # Quirk: only the first 1000 Garmin activity rows are considered.
        garmin = {
            "activities": [_garmin(str(index), "TEMPO", 1) for index in range(1002)]
        }
        result = training_focus({}, garmin, TODAY)
        self.assertEqual(result["coverage"]["known_sessions"], 1000)
        self.assertEqual(result["categories"]["high_aerobic"]["sessions"], 1000)


class CharacterizationCanonicalRowsTests(unittest.TestCase):
    def test_wahoo_provenance_is_read_from_each_source_field_alone(self) -> None:
        # Each provenance field marks the ride as Wahoo on its own, so the Garmin
        # copy is removed when only that single field is present.
        for field, value in (
            ("source", "WAHOO ELEMNT"),
            ("device_name", "ELEMNT BOLT"),
            ("external_id", "wahoo-123"),
        ):
            with self.subTest(field=field):
                rows, duplicates = canonical_rows(
                    {
                        "recent_activities": [
                            _ride("w", **{field: value}),
                            _ride("g", source="garmin"),
                        ]
                    }
                )
                self.assertEqual(_ids(rows), ["w"])
                self.assertEqual(duplicates, 1)

    def test_garmin_ride_is_removed_at_exactly_thirty_minutes_not_thirty_one(
        self,
    ) -> None:
        wahoo = _ride("w", source="wahoo")
        at_limit = canonical_rows(
            {
                "recent_activities": [
                    wahoo,
                    _ride("g", start="2026-05-04T08:30:00", source="garmin"),
                ]
            }
        )
        past_limit = canonical_rows(
            {
                "recent_activities": [
                    wahoo,
                    _ride("g", start="2026-05-04T08:31:00", source="garmin"),
                ]
            }
        )
        self.assertEqual(_ids(at_limit[0]), ["w"])
        self.assertEqual(_ids(past_limit[0]), ["w", "g"])

    def test_duration_and_distance_tolerances_use_the_larger_of_floor_and_ten_percent(
        self,
    ) -> None:
        # Duration passes within max(120 s, 10% of the longer ride); distance passes
        # within max(500 m, 10% of the longer ride). Both boundaries are inclusive.
        cases: list[tuple[dict[str, Any], dict[str, Any], bool]] = [
            ({"moving_time": 600}, {"moving_time": 720}, True),
            ({"moving_time": 600}, {"moving_time": 721}, False),
            ({"moving_time": 7200}, {"moving_time": 7000}, True),
            ({"moving_time": 7200}, {"moving_time": 6400}, False),
            ({"distance": 2000}, {"distance": 2500}, True),
            ({"distance": 2000}, {"distance": 2501}, False),
            ({"distance": 30000}, {"distance": 33000}, True),
            ({"distance": 30000}, {"distance": 33500}, False),
        ]
        for wahoo_fields, garmin_fields, matches in cases:
            with self.subTest(wahoo=wahoo_fields, garmin=garmin_fields):
                rows, duplicates = canonical_rows(
                    {
                        "recent_activities": [
                            _ride("w", source="wahoo", **wahoo_fields),
                            _ride("g", source="garmin", **garmin_fields),
                        ]
                    }
                )
                self.assertEqual(_ids(rows), ["w"] if matches else ["w", "g"])
                self.assertEqual(duplicates, 1 if matches else 0)

    def test_garmin_run_is_kept_and_untyped_garmin_ride_is_matched_by_name(
        self,
    ) -> None:
        # Quirk: a Garmin row without a type is treated as cycling from its name
        # ("Morning Ride") and removed; a Garmin Run copy is not matched at all.
        wahoo = _ride("w", source="wahoo")
        run_copy = canonical_rows(
            {
                "recent_activities": [
                    wahoo,
                    _ride("g", source="garmin", type="Run"),
                ]
            }
        )
        name_only = canonical_rows(
            {
                "recent_activities": [
                    wahoo,
                    {
                        "id": "g",
                        "name": "Morning Ride",
                        "source": "garmin",
                        "start_date_local": "2026-05-04T08:00:00",
                        "moving_time": 3600,
                        "distance": 30000,
                    },
                ]
            }
        )
        self.assertEqual(_ids(run_copy[0]), ["w", "g"])
        self.assertEqual(_ids(name_only[0]), ["w"])

    def test_missing_or_zero_wahoo_distance_keeps_the_garmin_copy(self) -> None:
        for distance in (None, 0):
            with self.subTest(distance=distance):
                rows, duplicates = canonical_rows(
                    {
                        "recent_activities": [
                            _ride("w", source="wahoo", distance=distance),
                            _ride("g", source="garmin"),
                        ]
                    }
                )
                self.assertEqual(_ids(rows), ["w", "g"])
                self.assertEqual(duplicates, 0)

    def test_string_garmin_distance_still_matches_for_removal(self) -> None:
        # Quirk: the duplicate matcher parses decimal strings, unlike training totals.
        rows, duplicates = canonical_rows(
            {
                "recent_activities": [
                    _ride("w", source="wahoo"),
                    _ride("g", source="garmin", distance="30000"),
                ]
            }
        )
        self.assertEqual(_ids(rows), ["w"])
        self.assertEqual(duplicates, 1)

    def test_garmin_only_and_wahoo_only_pairs_are_not_collapsed(self) -> None:
        garmin_pair = canonical_rows(
            {
                "recent_activities": [
                    _ride("g1", source="garmin"),
                    _ride("g2", source="garmin"),
                ]
            }
        )
        wahoo_pair = canonical_rows(
            {
                "recent_activities": [
                    _ride("w1", source="wahoo"),
                    _ride("w2", source="wahoo"),
                ]
            }
        )
        self.assertEqual((_ids(garmin_pair[0]), garmin_pair[1]), (["g1", "g2"], 0))
        self.assertEqual((_ids(wahoo_pair[0]), wahoo_pair[1]), (["w1", "w2"], 0))

    def test_identical_id_duplicates_are_dropped_but_not_counted(self) -> None:
        # Quirk: excluded_duplicates only counts Wahoo/Garmin removals, because the
        # identical-id duplicates are dropped before the count is taken.
        wahoo = _ride("w", source="wahoo")
        rows, duplicates = canonical_rows({"recent_activities": [wahoo, dict(wahoo)]})
        self.assertEqual(_ids(rows), ["w"])
        self.assertEqual(duplicates, 0)

    def test_numeric_and_string_ids_are_the_same_identity(self) -> None:
        rows, duplicates = canonical_rows(
            {"recent_activities": [_ride(5), _ride("5")]}  # type: ignore[arg-type]
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(duplicates, 0)

    def test_non_dict_records_are_dropped_and_not_counted(self) -> None:
        rows, duplicates = canonical_rows(
            {"recent_activities": ["junk", None, _ride("a")]}
        )
        self.assertEqual(_ids(rows), ["a"])
        self.assertEqual(duplicates, 0)

    def test_raw_provider_list_takes_precedence_even_when_empty(self) -> None:
        # Quirk: a list in raw_provider_data wins, even when it is empty.
        self.assertEqual(
            canonical_rows(
                {
                    "raw_provider_data": {"activities": []},
                    "recent_activities": [_ride("r")],
                }
            ),
            ([], 0),
        )
        rows, _ = canonical_rows(
            {
                "raw_provider_data": {"activities": {"not": "a list"}},
                "recent_activities": [_ride("r")],
            }
        )
        self.assertEqual(_ids(rows), ["r"])
        rows, _ = canonical_rows(
            {
                "raw_provider_data": {"activities": [_ride("raw")]},
                "recent_activities": [_ride("r")],
            }
        )
        self.assertEqual(_ids(rows), ["raw"])

    def test_missing_recent_activities_yield_no_rows(self) -> None:
        self.assertEqual(canonical_rows({"recent_activities": None}), ([], 0))
        self.assertEqual(canonical_rows({}), ([], 0))

    def test_output_keeps_input_order_and_first_occurrence(self) -> None:
        rows, _ = canonical_rows(
            {
                "recent_activities": [
                    _ride("b"),
                    _ride("a", moving_time=1),
                    _ride("a", moving_time=2),
                ]
            }
        )
        self.assertEqual(_ids(rows), ["b", "a"])
        self.assertEqual(rows[1]["moving_time"], 1)


if __name__ == "__main__":
    unittest.main()
