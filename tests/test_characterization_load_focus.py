"""Characterization of load rollups, the load context and training focus.

These tests pin the current behaviour of the load context, the activity
rollups, the training-focus projection and the
Wahoo/Garmin canonical row selection. They are the parity reference for a later
refactor, so deliberate quirks are pinned as they are and marked "Quirk:".
"""

import math
import unittest
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

from performance_day_support import (
    garmin_activity_summaries,
    garmin_sync_status,
)

from backend.performance.canonical_inputs import EMPTY_PERFORMANCE_INPUTS
from backend.performance.load import activity_rollup
from backend.performance.load_context import (
    performance_load_context as _performance_load_context,
)
from backend.performance.training_focus import training_focus

TODAY = date(2026, 5, 4)
RETENTION = math.exp(-1.0 / 7.0)
DECAY = 1.0 - RETENTION


def performance_load_context(
    activities: list[Any], today: date, **inputs: Any
) -> dict[str, Any]:
    return _performance_load_context(
        activities,
        today,
        canonical=replace(EMPTY_PERFORMANCE_INPUTS, **inputs),
        timezone="UTC",
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
            {
                "days": 1,
                "sessions": 2,
                "duration_hours": 1.5,
                "training_load": 12.5,
                # #1672: a structured load is no TSS-scale number.
                "load_missing_sessions": 1,
            },
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
        # #1672: the unsummed load is reported as missing, not dropped silently.
        self.assertEqual(result["load_missing_sessions"], 1)

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


class CharacterizationLoadContextTests(unittest.TestCase):
    def test_result_contract_keys_are_stable(self) -> None:
        result = performance_load_context([], TODAY)
        self.assertEqual(
            set(result),
            {
                "load",
                "last_7",
                "previous_7",
                "last_30",
                "previous_30",
                "base_30_before_7",
            },
        )

    def test_without_local_load_the_load_block_is_empty_and_local(self) -> None:
        load = performance_load_context([], TODAY)["load"]
        self.assertEqual(
            {key: load[key] for key in ("id", "ctl", "atl", "tsb", "source")},
            {
                "id": None,
                "ctl": None,
                "atl": None,
                "tsb": None,
                "source": "Lokal berechnet (M7)",
            },
        )
        self.assertEqual(
            (load["status"], load["reason"]), ("insufficient_data", "no_load")
        )
        self.assertNotIn("ramp_rate", load)

    def test_load_block_is_the_latest_local_day_with_its_averages(self) -> None:
        days = {
            (TODAY - timedelta(days=offset)).isoformat(): 60.0
            for offset in range(1, 120)
        }
        load = performance_load_context([], TODAY, local_load_days=days)["load"]
        self.assertEqual(load["method_id"], "local-fitness-fatigue")
        self.assertEqual(load["status"], "estimate")
        # Today is open without a session and the sync time is unknown: the
        # latest valued day is today itself (complete_before = today).
        self.assertIsNotNone(load["ctl"])
        self.assertAlmostEqual(load["tsb"], round(load["ctl"] - load["atl"], 1), 1)
        self.assertIsNotNone(load["averages_7d"]["ctl"])

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
        result = performance_load_context(activities, TODAY)
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
