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

from performance_day_support import (
    current_days,
    garmin_activity_summaries,
    garmin_sync_status,
)

from backend.canonical.vocabulary import MetricKind
from backend.performance.canonical_inputs import EMPTY_PERFORMANCE_INPUTS
from backend.performance.load import activity_rollup
from backend.performance.load import actual_atl_series as _actual_atl_series
from backend.performance.load_context import (
    performance_load_context as _performance_load_context,
)
from backend.performance.training_focus import training_focus
from backend.performance.wellness_days import series

TODAY = date(2026, 5, 4)
RETENTION = math.exp(-1.0 / 7.0)
DECAY = 1.0 - RETENTION


def actual_atl_series(
    rows: list[Any], activities: list[Any], end_date: date
) -> dict[date, float]:
    return _actual_atl_series(
        series(
            current_days([row for row in rows if isinstance(row, dict)]), MetricKind.ATL
        ),
        activities,
        end_date,
    )


def performance_load_context(
    activities: list[Any], rows: list[Any], _latest: dict[str, Any], today: date
) -> dict[str, Any]:
    return _performance_load_context(
        activities,
        current_days([row for row in rows if isinstance(row, dict)]),
        today,
        canonical=EMPTY_PERFORMANCE_INPUTS,
    )


def _day(offset: int) -> str:
    return (TODAY + timedelta(days=offset)).isoformat()


def _activity(day: str, **fields: Any) -> dict[str, Any]:
    return {"started_at_local": day, "moving_duration_s": 3600, **fields}


def _wellness(day: str, atl: Any, **fields: Any) -> dict[str, Any]:
    return {"id": day, "atl": atl, **fields}


def _ride(
    activity_id: str, start: str = "2026-05-04T08:00:00", **fields: Any
) -> dict[str, Any]:
    return {
        "id": activity_id,
        "sport": "ride",
        "started_at_local": start,
        "moving_duration_s": 3600,
        "distance_m": 30000,
        **fields,
    }


def _raw_ride(
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


def _hr(seconds: int) -> list[dict[str, Any]]:
    return [{"id": "Z1", "secs": seconds}]


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
                    "started_at": "2026-05-04T08:00:00Z",
                    "moving_duration_s": 60,
                    "training_load": 5,
                }
            ],
            1,
            TODAY,
        )
        self.assertEqual(
            result,
            {"days": 1, "sessions": 0, "duration_hours": 0.0, "training_load": 0.0},
        )

    def test_rollup_falls_back_to_the_elapsed_duration(self) -> None:
        result = activity_rollup(
            [
                {
                    "started_at_local": "2026-05-04",
                    "elapsed_duration_s": 3600,
                    "training_load": 50,
                }
            ],
            1,
            TODAY,
        )
        self.assertEqual(result["sessions"], 1)
        self.assertEqual(result["duration_hours"], 1.0)
        self.assertEqual(result["training_load"], 50.0)

    def test_rollup_parses_numeric_strings_and_zeroes_structured_values(self) -> None:
        result = activity_rollup(
            [
                {
                    "started_at_local": "2026-05-04",
                    "moving_duration_s": "5400",
                    "training_load": "12.5",
                },
                {
                    "started_at_local": "2026-05-04",
                    "moving_duration_s": ["3600"],
                    "training_load": {"value": 9},
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
                    "started_at_local": "2026-05-04",
                    "moving_duration_s": "1800",
                    "training_load": "42,5",
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
                {"started_at_local": "2026-05-04", "training_load": 20},
                {"started_at_local": "2026-05-04", "training_load": -5},
            ],
            1,
            TODAY,
        )
        self.assertEqual(result["training_load"], 15.0)

    def test_rollup_rounds_hours_and_load_to_one_decimal(self) -> None:
        result = activity_rollup(
            [
                {
                    "started_at_local": "2026-05-04",
                    "moving_duration_s": 1000,
                    "training_load": 10.06,
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
                {"started_at_local": "2026-05-04T23:59:59", "moving_duration_s": 60},
                {"started_at_local": _day(1), "moving_duration_s": 60},
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
            [_activity("2026-05-03", training_load=70)],
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

    def test_activity_load_on_a_day_without_wellness_row_is_applied(self) -> None:
        # Loads on days without a wellness row decay the running ATL and add their
        # load, so the next wellness day reflects the completed activity.
        wellness = [_wellness("2026-05-01", 10), _wellness("2026-05-04", 10)]
        with_gap_load = actual_atl_series(
            wellness, [_activity("2026-05-02", training_load=100)], TODAY
        )
        self.assertEqual(
            with_gap_load,
            {
                date(2026, 5, 1): 10.0,
                date(2026, 5, 4): round(
                    (10 * RETENTION + 100 * DECAY) * RETENTION**2, 2
                ),
            },
        )
        self.assertNotEqual(with_gap_load, actual_atl_series(wellness, [], TODAY))

    def test_activity_load_before_first_wellness_row_is_ignored(self) -> None:
        series = actual_atl_series(
            [_wellness("2026-05-04", 10)],
            [_activity("2026-04-30", training_load=70)],
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
            [_activity("2026-05-05", training_load=999)],
            TODAY,
        )
        self.assertEqual(
            series,
            {date(2026, 5, 4): 10.0, date(2026, 5, 6): round(10 * RETENTION**2, 2)},
        )

    def test_duplicate_wellness_dates_make_one_observed_day(self) -> None:
        series = actual_atl_series(
            [_wellness("2026-05-04", 10), _wellness("2026-05-04", 10)],
            [_activity("2026-05-04", training_load=70)],
            TODAY,
        )
        self.assertEqual(series, {date(2026, 5, 4): 10.0})

    def test_decimal_comma_activity_load_is_accepted_by_atl(self) -> None:
        series = actual_atl_series(
            [_wellness("2026-05-03", 10), _wellness("2026-05-04", 10)],
            [_activity("2026-05-04", training_load="42,5")],
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
                _activity("2026-05-04", training_load="n/a"),
                {"started_at_local": None, "training_load": 50},
            ],
            TODAY,
        )
        self.assertEqual(series[date(2026, 5, 4)], round(10 * RETENTION, 2))

    def test_invalid_ids_do_not_create_canonical_days(
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
        self.assertEqual(series, {})

    def test_atl_alias_is_mapped_before_reconstruction(self) -> None:
        self.assertEqual(
            actual_atl_series([{"id": "2026-05-04", "atlLoad": 10}], [], TODAY),
            {TODAY: 10.0},
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
            {
                "id": None,
                "ctl": None,
                "atl": None,
                "tsb": None,
                "ramp_rate": None,
                "ramp_rate_source": None,
            },
        )

    def test_load_block_does_not_read_snapshot_aliases_without_canonical_inputs(
        self,
    ) -> None:
        # Quirk: ctl and atl come from the latest Intervals row (with aliases) and
        # raw values are passed through. Form and ramp rate no longer come from the
        # row (#1412): without canonical inputs they are unknown.
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
                "id": None,
                "ctl": None,
                "atl": None,
                "tsb": None,
                "ramp_rate": None,
                "ramp_rate_source": None,
            },
        )

    def test_load_block_skips_empty_strings_but_keeps_zero(self) -> None:
        result = performance_load_context(
            [], [], {"ctl": "", "ctLoad": 55, "atl": 0}, TODAY
        )
        self.assertIsNone(result["load"]["ctl"])
        self.assertIsNone(result["load"]["atl"])

    def test_carrier_form_fields_are_not_read_without_canonical_inputs(self) -> None:
        # Intended difference (#1412): the row's tsb/form/freshness and a derived
        # CTL minus ATL are gone; form is read from canonical observations only.
        for row in (
            {"ctl": 50, "atl": 60, "tsb": ""},
            {"ctl": 50, "atl": 60, "freshness": 4},
            {"ctl": 50, "atl": 60, "tsb": 3, "form": 2},
        ):
            with self.subTest(row=row):
                self.assertIsNone(
                    performance_load_context([], [], row, TODAY)["load"]["tsb"]
                )

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
        # context does not drop duplicates and both copies of one ride count.
        activities = [
            _ride(
                "w",
                source="WAHOO ELEMNT",
                training_load=40,
            ),
            _ride("g", source="garmin", training_load=40),
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
                    heart_rate_zone_times=_hr(600),
                    power_zone_times=[{"id": "Z1", "secs": 300}],
                    pace_zone_times=[{"id": "Z1", "secs": 900}],
                ),
                {
                    "id": "s",
                    "sport": "strength",
                    "started_at_local": "2026-05-04T08:00:00",
                    "moving_duration_s": 3600,
                    "heart_rate_zone_times": _hr(1800),
                },
            ]
        }
        result = training_focus(
            garmin_sync_status({}), TODAY, activities=snapshot["recent_activities"]
        )
        self.assertEqual(
            sorted({row["sensor"] for row in result["zones"]}),
            ["heart_rate", "power"],
        )
        zones = {row["sensor"]: row["seconds"] for row in result["zones"]}
        self.assertEqual(zones["heart_rate"], {"Z1": 600.0})
        self.assertEqual(zones["power"], {"Z1": 300.0})

    def test_zone_window_includes_today_minus_27_and_today_only(self) -> None:
        snapshot = {
            "recent_activities": [
                _ride(
                    "before",
                    start=f"{_day(-28)}T08:00:00",
                    heart_rate_zone_times=_hr(900),
                ),
                _ride(
                    "first",
                    start=f"{_day(-27)}T08:00:00",
                    heart_rate_zone_times=_hr(300),
                ),
                _ride(
                    "today", start=f"{_day(0)}T08:00:00", heart_rate_zone_times=_hr(300)
                ),
                _ride(
                    "after", start=f"{_day(1)}T08:00:00", heart_rate_zone_times=_hr(900)
                ),
            ]
        }
        result = training_focus(
            garmin_sync_status({}), TODAY, activities=snapshot["recent_activities"]
        )
        self.assertEqual(result["zones"][0]["seconds"], {"Z1": 600.0})
        self.assertEqual(result["zones"][0]["training_seconds"], 7200)

    def test_days_argument_sets_the_window_start(self) -> None:
        snapshot = {
            "recent_activities": [
                _ride(
                    "before",
                    start=f"{_day(-14)}T08:00:00",
                    heart_rate_zone_times=_hr(900),
                ),
                _ride(
                    "first",
                    start=f"{_day(-13)}T08:00:00",
                    heart_rate_zone_times=_hr(300),
                ),
            ]
        }
        result = training_focus(
            garmin_sync_status({}),
            TODAY,
            activities=snapshot["recent_activities"],
            days=14,
        )
        self.assertEqual(result["start"], _day(-13))
        self.assertEqual(result["zones"][0]["seconds"], {"Z1": 300.0})

    def test_zone_timezone_moves_absolute_start_into_the_requested_day(self) -> None:
        ride = _ride(
            "r",
            start="2026-05-04T22:30:00",
            started_at="2026-05-04T22:30:00+00:00",
            heart_rate_zone_times=_hr(600),
        )
        utc = training_focus(garmin_sync_status({}), TODAY, "UTC", activities=[ride])
        berlin = training_focus(
            garmin_sync_status({}), TODAY, "Europe/Berlin", activities=[ride]
        )
        self.assertEqual(utc["zones"][0]["seconds"], {"Z1": 600.0})
        # 22:30 UTC is 00:30 on 2026-05-05 in Berlin, after the window end.
        self.assertEqual(berlin["zones"], [])

    def test_invalid_timezone_name_falls_back_to_local_start_date(self) -> None:
        ride = _ride(
            "r",
            start="2026-05-04T22:30:00",
            started_at="2026-05-04T22:30:00+00:00",
            heart_rate_zone_times=_hr(600),
        )
        result = training_focus(
            garmin_sync_status({}), TODAY, "Mars/Olympus", activities=[ride]
        )
        self.assertEqual(result["zones"][0]["seconds"], {"Z1": 600.0})

    def test_categories_and_zones_date_a_session_in_the_profile_zone(self) -> None:
        # Canonical reads (#1416): categories and zones date a session in the same
        # profile zone, so a near-midnight session moves day for both.
        garmin = {
            "activities": [
                {
                    **_garmin("a", "TEMPO", 40, start="2026-05-04T23:30:00"),
                    "activityType": {"typeKey": "running"},
                }
            ]
        }
        summaries = [
            {**summary, "heart_rate_zone_times": _hr(600)}
            for summary in garmin_activity_summaries(garmin)
        ]
        for timezone, sessions in (("UTC", 1), ("Europe/Berlin", 0)):
            with self.subTest(timezone=timezone):
                result = training_focus(
                    garmin_sync_status(garmin), TODAY, timezone, activities=summaries
                )
                self.assertEqual(result["coverage"]["known_sessions"], sessions)
                self.assertEqual(len(result["zones"]), sessions)
                self.assertEqual(
                    result["coverage"]["observed_end"],
                    "2026-05-04" if sessions else None,
                )

    def test_activity_id_zero_is_a_valid_identity(self) -> None:
        # Canonical reads (#1416): the mapper keeps the activity id 0, so the
        # session is classified; the old falsy-id quirk is gone.
        result = training_focus(
            garmin_sync_status(
                {
                    "activities": [
                        {
                            "activityId": 0,
                            "startTimeLocal": "2026-05-04T08:00:00",
                            "trainingEffectLabel": "TEMPO",
                            "activityTrainingLoad": 40,
                        }
                    ]
                }
            ),
            TODAY,
            activities=garmin_activity_summaries(
                {
                    "activities": [
                        {
                            "activityId": 0,
                            "startTimeLocal": "2026-05-04T08:00:00",
                            "trainingEffectLabel": "TEMPO",
                            "activityTrainingLoad": 40,
                        }
                    ]
                }
            ),
        )
        self.assertEqual(result["coverage"]["known_sessions"], 1)
        self.assertEqual(result["classified_sessions"], 1)
        self.assertEqual(result["unclassified_sessions"], 0)
        self.assertEqual(result["categories"]["high_aerobic"]["sessions"], 1)

    def test_garmin_load_bounds_and_parsing_edges_are_pinned(self) -> None:
        # Canonical reads (#1416): the mapper bounds the activity load to
        # 0..10000 at ingest and does not read decimal-comma text, so only the
        # zero load classifies.
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
        result = training_focus(
            garmin_sync_status(garmin),
            TODAY,
            activities=garmin_activity_summaries(garmin),
        )
        self.assertEqual(result["classified_sessions"], 1)
        self.assertEqual(result["unclassified_sessions"], 5)
        self.assertEqual(
            result["categories"]["high_aerobic"], {"load": 0.0, "sessions": 1}
        )

    def test_category_labels_are_case_insensitive_aliased_and_trimmed(
        self,
    ) -> None:
        # Canonical reads (#1416): the mapper strips and upper-cases the label, so
        # a padded label is classified too.
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
        result = training_focus(
            garmin_sync_status(garmin),
            TODAY,
            activities=garmin_activity_summaries(garmin),
        )
        categories = result["categories"]
        self.assertEqual(categories["high_aerobic"], {"load": 25.0, "sessions": 5})
        self.assertEqual(categories["low_aerobic"], {"load": 5.0, "sessions": 1})
        self.assertEqual(categories["anaerobic"], {"load": 10.0, "sessions": 2})
        self.assertEqual(result["unclassified_sessions"], 2)

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
                    garmin_sync_status({"activities": [_garmin("a", label, 5)]}),
                    TODAY,
                    activities=garmin_activity_summaries(
                        {"activities": [_garmin("a", label, 5)]}
                    ),
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
        result = training_focus(
            garmin_sync_status(garmin),
            TODAY,
            activities=garmin_activity_summaries(garmin),
        )
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
        result = training_focus(
            garmin_sync_status(garmin),
            TODAY,
            activities=garmin_activity_summaries(garmin),
        )
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
        result = training_focus(
            garmin_sync_status(garmin),
            TODAY,
            activities=garmin_activity_summaries(garmin),
        )
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
        result = training_focus(
            garmin_sync_status({"activities": [_garmin("a", "TEMPO", 40)]}),
            TODAY,
            activities=garmin_activity_summaries(
                {"activities": [_garmin("a", "TEMPO", 40)]}
            ),
        )
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
                _ride("r", training_load=99, start="2026-05-04T08:00:00")
            ]
        }
        result = training_focus(
            garmin_sync_status({}), TODAY, activities=snapshot["recent_activities"]
        )
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

    def test_every_canonical_garmin_session_is_considered(self) -> None:
        # Canonical reads (#1416): the sessions of the read window are bounded by
        # the activity read, so the old first-1000-rows cap is gone.
        garmin = {
            "activities": [_garmin(str(index), "TEMPO", 1) for index in range(1002)]
        }
        result = training_focus(
            garmin_sync_status(garmin),
            TODAY,
            activities=garmin_activity_summaries(garmin),
        )
        self.assertEqual(result["coverage"]["known_sessions"], 1002)
        self.assertEqual(result["categories"]["high_aerobic"]["sessions"], 1002)


if __name__ == "__main__":
    unittest.main()
