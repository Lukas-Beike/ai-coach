"""Characterize how provider data and source labels reach the Coach context.

These tests pin current composition and provenance as the parity reference for
the provider-neutral refactor. Observed quirks are commented with "Quirk:".
Intervals HRV baselines are out of scope; recovery id and fallback precedence
are pinned here as current behaviour.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import Mock

from backend.coach.context import (
    CoachIntervalsContextService,
    CoachPerformanceContextReader,
    CoachPlanningContextReader,
    CoachStructuredContextService,
)
from backend.coach.context_selection import CoachContextSelection
from backend.performance.context import current_performance_context
from backend.sync.garmin_projection_service import GarminProjectionService

TODAY = date(2026, 5, 4)
GARMIN_SOURCE = "Garmin Connect"
INTERVALS_SOURCE = "Intervals.icu"
WELLNESS_SOURCE = "Intervals.icu Wellness"
GENERIC_LTHR_SOURCE = "Intervals.icu (allgemein)"
VENDOR_SENTINEL = "synthetic-vendor-blob"


def _garmin_payload() -> dict[str, Any]:
    """Synthetic Garmin snapshot with one vendor field that must not leak."""
    current = {"freshness": "current", "fetched_at": "2026-05-04T06:00:00Z"}
    return {
        "synced_at": "2026-05-04T06:00:00Z",
        "start": "2026-04-27",
        "end": "2026-05-04",
        "source_freshness": {
            "sleep": {**current, "observed_at": "2026-05-04"},
            "resting_hr": {**current, "observed_at": "2026-05-04"},
            "hrv": {**current, "observed_at": "2026-05-04"},
            "cycling_ftp": {
                "freshness": "partial",
                "fetched_at": "2026-05-04T06:00:00Z",
                "observed_at": "2026-05-01",
            },
            "training_load_balance": {**current, "observed_at": "2026-05-04"},
        },
        "sleep": [
            {
                "calendarDate": "2026-05-03",
                "sleepTimeSeconds": 25200,
                "sleepScore": 79,
                "vendorBlob": VENDOR_SENTINEL,
            },
            {
                "calendarDate": "2026-05-04",
                "sleepTimeSeconds": 27000,
                "sleepScore": 84,
                "vendorBlob": VENDOR_SENTINEL,
            },
        ],
        "resting_hr": [{"calendarDate": "2026-05-04", "restingHeartRate": 49}],
        "hrv": [{"calendarDate": "2026-05-04", "lastNightAvg": 58}],
        "cycling_ftp": {"calendarDate": "2026-05-01", "functionalThresholdPower": 265},
        "training_load_balance": {
            "metricsTrainingLoadBalanceDTOMap": {
                "device-1": {
                    "calendarDate": "2026-05-04",
                    "primaryTrainingDevice": True,
                    "monthlyLoadAerobicLow": 400,
                }
            }
        },
    }


def _intervals_snapshot(**overrides: Any) -> dict[str, Any]:
    snapshot: dict[str, Any] = {
        "synced_at": "2026-05-04T05:00:00Z",
        "athlete": {
            "icu_ftp": 250,
            "icu_w_prime": 20000,
            "max_hr": 190,
            "lthr": 171,
            "weight": 71.5,
        },
        "recent_wellness": [{"id": "2026-05-04", "ctl": 60, "atl": 66, "tsb": -6}],
        "recent_activities": [
            {
                "id": "ride-1",
                "type": "Ride",
                "start_date_local": "2026-05-03T07:00:00",
                "moving_time": 3600,
                "icu_training_load": 90,
            }
        ],
    }
    snapshot.update(overrides)
    return snapshot


def _performance_reader(
    garmin_payload: dict[str, Any],
) -> tuple[CoachPerformanceContextReader, Mock]:
    profile_service = Mock()
    profile_service.get.return_value = {"name": "Athlete", "timezone": "UTC"}
    payload_service = Mock()
    payload_service.snapshot.return_value = garmin_payload
    garmin_projection = Mock()
    garmin_projection.coach_context.return_value = {"recovery": {}}
    reader = CoachPerformanceContextReader(
        profile_service, payload_service, garmin_projection, lambda: TODAY
    )
    return reader, garmin_projection


def _structured_service(
    latest_snapshot: dict[str, Any] | None,
    garmin_payload: dict[str, Any],
) -> tuple[CoachStructuredContextService, Mock]:
    sync_state_repository = Mock()
    sync_state_repository.latest_snapshot.return_value = latest_snapshot
    checkin_service = Mock()
    checkin_service.context.return_value = {"recent": []}
    weather_service = Mock()
    weather_service.state.return_value = {"days": []}
    activity_feedback_service = Mock()
    activity_feedback_service.context.return_value = {"recent": []}
    planned_unit_service = Mock()
    planned_unit_service.list.return_value = []
    daily_planning_context_service = Mock()
    daily_planning_context_service.build.return_value = []
    external_calendar_reader = Mock()
    external_calendar_reader.list_events.return_value = []
    competition_service = Mock()
    competition_service.list.return_value = []
    training_plan_service = Mock()
    training_plan_service.list.return_value = []
    adaptive_preview_service = Mock()
    adaptive_preview_service.latest_preview.return_value = {"status": "none"}
    adaptive_preview_service.status.return_value = {"available": False}
    performance_reader, garmin_projection = _performance_reader(garmin_payload)
    service = CoachStructuredContextService(
        sync_state_repository,
        checkin_service,
        weather_service,
        activity_feedback_service,
        CoachPlanningContextReader(
            planned_unit_service,
            daily_planning_context_service,
            external_calendar_reader,
            competition_service,
            training_plan_service,
            adaptive_preview_service,
            lambda: TODAY,
        ),
        performance_reader,
    )
    return service, garmin_projection


def _garmin_projection_service(snapshot: dict[str, Any]) -> GarminProjectionService:
    payload_service = Mock()
    payload_service.snapshot.return_value = snapshot
    battery_service = Mock()
    battery_service.current.return_value = None
    redactor = Mock()
    redactor.redact_text.side_effect = lambda text: text
    return GarminProjectionService(
        config=Mock(),
        garmin_payload_service=payload_service,
        garmin_sync_service=Mock(),
        garmin_sync_state_service=Mock(),
        sync_state_repository=Mock(),
        morning_body_battery_service=battery_service,
        garmin_client_factory=Mock(),
        database_manager=Mock(),
        key_value_repository=Mock(),
        redactor=redactor,
        local_now=lambda: datetime(2026, 5, 4, 8, tzinfo=UTC),
    )


class CurrentPerformanceProvenanceTests(unittest.TestCase):
    def test_unavailable_projection_garmin_balance_follows_freshness_and_presence(
        self,
    ) -> None:
        result = current_performance_context(None, _garmin_payload(), {}, TODAY)

        self.assertFalse(result["available"])
        self.assertEqual(result["source"], INTERVALS_SOURCE)
        balance = result["garmin_training_load"]["four_week_balance"]
        self.assertEqual(balance["source"], GARMIN_SOURCE)
        self.assertEqual(balance["freshness"], "current")
        self.assertEqual(balance["date"], "2026-05-04")
        self.assertEqual(balance["monthlyLoadAerobicLow"], 400)

        stale = _garmin_payload()
        stale["source_freshness"]["training_load_balance"]["freshness"] = "stale"
        stale_result = current_performance_context(None, stale, {}, TODAY)
        # Quirk: a stale balance keeps its source and date but drops every metric.
        stale_balance = stale_result["garmin_training_load"]["four_week_balance"]
        self.assertEqual(stale_balance["source"], GARMIN_SOURCE)
        self.assertEqual(stale_balance["date"], "2026-05-04")
        self.assertNotIn("monthlyLoadAerobicLow", stale_balance)

        without_balance = _garmin_payload()
        del without_balance["training_load_balance"]
        self.assertNotIn(
            "garmin_training_load",
            current_performance_context(None, without_balance, {}, TODAY),
        )

    def test_available_projection_always_has_garmin_training_load_key(self) -> None:
        # Quirk: unlike the unavailable projection, the key is always present here.
        result = current_performance_context(_intervals_snapshot(), {}, {}, TODAY)

        self.assertEqual(result["garmin_training_load"], {})

    def test_available_projection_top_level_keys_are_pinned(self) -> None:
        result = current_performance_context(_intervals_snapshot(), {}, {}, TODAY)

        self.assertEqual(
            set(result),
            {
                "available",
                "personal_recovery",
                "garmin_training_load",
                "training_focus",
                "source",
                "as_of",
                "metrics",
                "thresholds",
                "current_load",
                "actual_load",
                "recovery",
                "rolling_training",
                "comparisons",
                "activity_validation",
            },
        )
        self.assertEqual(result["as_of"], "2026-05-04T05:00:00Z")
        self.assertEqual(
            set(result["thresholds"]),
            {"icu_ftp", "icu_w_prime", "max_hr", "lthr", "weight"},
        )

    def test_athlete_icu_ftp_is_the_labelled_intervals_fallback(self) -> None:
        result = current_performance_context(_intervals_snapshot(), {}, {}, TODAY)

        self.assertEqual(result["metrics"]["cycling_ftp_watts"]["value"], 250)
        self.assertEqual(
            result["metrics"]["cycling_ftp_watts"]["source"], INTERVALS_SOURCE
        )
        self.assertEqual(result["thresholds"]["icu_ftp"], 250)

    def test_generic_lthr_is_labelled_as_allgemein_not_as_intervals(self) -> None:
        result = current_performance_context(_intervals_snapshot(), {}, {}, TODAY)

        self.assertEqual(result["metrics"]["bike_threshold_hr_bpm"]["value"], 171)
        self.assertEqual(
            result["metrics"]["bike_threshold_hr_bpm"]["source"], GENERIC_LTHR_SOURCE
        )
        self.assertEqual(result["metrics"]["weight_kg"]["source"], INTERVALS_SOURCE)

    def test_garmin_cycling_ftp_wins_and_thresholds_drop_the_source_label(
        self,
    ) -> None:
        result = current_performance_context(
            _intervals_snapshot(), _garmin_payload(), {}, TODAY
        )

        ftp = result["metrics"]["cycling_ftp_watts"]
        self.assertEqual(ftp["value"], 265)
        self.assertEqual(ftp["source"], GARMIN_SOURCE)
        self.assertEqual(ftp["freshness"], "partial")
        self.assertEqual(ftp["measurement_age_days"], 3)
        # Quirk: thresholds carry bare values; provenance lives in metrics only.
        self.assertEqual(result["thresholds"]["icu_ftp"], 265)
        self.assertNotIsInstance(result["thresholds"]["icu_ftp"], dict)

    def test_recovery_id_follows_resting_hr_then_hrv_then_wellness(self) -> None:
        # Quirk: the dated sleepTimeSeconds record (2026-05-04) supplies
        # recovery.sleep_hours, but its date never becomes recovery.id, which
        # follows the resting HR date.
        sleep_only = [{"calendarDate": "2026-05-04", "sleepTimeSeconds": 27000}]
        resting_hr = [{"calendarDate": "2026-05-03", "restingHeartRate": 49}]
        hrv = [{"calendarDate": "2026-05-02", "lastNightAvg": 58}]
        wellness = [{"id": "2026-05-04", "ctl": 60}]

        full = current_performance_context(
            _intervals_snapshot(recent_wellness=wellness),
            {"sleep": sleep_only, "resting_hr": resting_hr, "hrv": hrv},
            {},
            TODAY,
        )
        self.assertEqual(full["recovery"]["sleep_hours"], 7.5)
        self.assertEqual(full["recovery"]["id"], "2026-05-03")

        no_resting = current_performance_context(
            _intervals_snapshot(recent_wellness=wellness),
            {"sleep": sleep_only, "hrv": hrv},
            {},
            TODAY,
        )
        self.assertEqual(no_resting["recovery"]["id"], "2026-05-02")

        wellness_only = current_performance_context(
            _intervals_snapshot(recent_wellness=wellness),
            {"sleep": sleep_only},
            {},
            TODAY,
        )
        self.assertEqual(wellness_only["recovery"]["id"], "2026-05-04")

        no_rows = current_performance_context(
            _intervals_snapshot(recent_wellness=[]), {"sleep": sleep_only}, {}, TODAY
        )
        self.assertIsNone(no_rows["recovery"]["id"])

    def test_recovery_source_freshness_lists_only_garmin_sourced_values(self) -> None:
        result = current_performance_context(
            _intervals_snapshot(), _garmin_payload(), {}, TODAY
        )

        recovery = result["recovery"]
        self.assertEqual(recovery["restingHR_source"], GARMIN_SOURCE)
        self.assertEqual(recovery["sleepScore"], 84)
        self.assertEqual(recovery["sleepScore_source"], GARMIN_SOURCE)
        self.assertEqual(recovery["sleep_hours"], 7.5)
        self.assertEqual(recovery["sleep_source"], GARMIN_SOURCE)
        self.assertEqual(
            set(recovery["source_freshness"]),
            {"restingHR", "hrv", "sleepScore", "sleep_hours"},
        )
        self.assertEqual(
            recovery["source_freshness"]["restingHR"]["freshness"], "current"
        )
        self.assertEqual(
            recovery["source_freshness"]["restingHR"]["measurement_status"], "today"
        )

    def test_intervals_wellness_fallback_is_labelled_without_garmin_freshness(
        self,
    ) -> None:
        wellness = [
            {
                "id": "2026-05-04",
                "restingHR": 52,
                "sleepScore": 66,
                "sleepSecs": 23400,
            }
        ]

        result = current_performance_context(
            _intervals_snapshot(recent_wellness=wellness), {}, {}, TODAY
        )

        recovery = result["recovery"]
        self.assertEqual(recovery["restingHR"], 52)
        self.assertEqual(recovery["restingHR_source"], WELLNESS_SOURCE)
        self.assertEqual(recovery["sleepScore_source"], WELLNESS_SOURCE)
        self.assertEqual(recovery["sleep_hours"], 6.5)
        self.assertEqual(recovery["sleep_source"], WELLNESS_SOURCE)
        self.assertEqual(recovery["source_freshness"], {})


class CoachPerformanceReaderProvenanceTests(unittest.TestCase):
    def test_realistic_garmin_payload_keeps_source_labels_in_current_performance(
        self,
    ) -> None:
        reader, _ = _performance_reader(_garmin_payload())

        result = reader.current_performance(_intervals_snapshot())

        self.assertEqual(
            result["metrics"]["cycling_ftp_watts"]["source"], GARMIN_SOURCE
        )
        self.assertEqual(result["metrics"]["weight_kg"]["source"], INTERVALS_SOURCE)
        self.assertEqual(
            result["metrics"]["bike_threshold_hr_bpm"]["source"], GENERIC_LTHR_SOURCE
        )
        self.assertEqual(result["recovery"]["restingHR_source"], GARMIN_SOURCE)
        self.assertEqual(result["recovery"]["hrv_source"], GARMIN_SOURCE)
        self.assertEqual(result["recovery"]["sleepScore_source"], GARMIN_SOURCE)
        self.assertEqual(
            result["garmin_training_load"]["four_week_balance"]["source"],
            GARMIN_SOURCE,
        )

    def test_garmin_vendor_fields_do_not_reach_current_performance(self) -> None:
        reader, _ = _performance_reader(_garmin_payload())

        result = reader.current_performance(_intervals_snapshot())

        self.assertNotIn(VENDOR_SENTINEL, json.dumps(result, ensure_ascii=False))

    def test_garmin_context_requests_performance_only_without_intervals_snapshot(
        self,
    ) -> None:
        reader, garmin_projection = _performance_reader(_garmin_payload())

        unavailable = reader.current_performance(None)
        garmin_context = reader.garmin(None)
        reader.garmin(_intervals_snapshot())

        self.assertFalse(unavailable["available"])
        self.assertEqual(
            unavailable["garmin_training_load"]["four_week_balance"]["source"],
            GARMIN_SOURCE,
        )
        self.assertEqual(garmin_context, {"recovery": {}})
        # The Garmin fallback performance block is only requested when no
        # Intervals.icu snapshot exists.
        self.assertEqual(
            garmin_projection.coach_context.call_args_list[0].kwargs,
            {"include_performance": True},
        )
        self.assertEqual(
            garmin_projection.coach_context.call_args_list[1].kwargs,
            {"include_performance": False},
        )


class CoachIntervalsProjectionTests(unittest.TestCase):
    def test_activity_projection_is_allowlisted_and_truncates_text(self) -> None:
        activity = {
            "id": "ride-9",
            "type": "Ride",
            "name": "N" * 250,
            "start_date_local": "2026-05-03T07:00:00",
            "moving_time": 3600,
            "distance": None,
            "icu_eftp": 265,
            "max_speed": 12.5,
            "description": "private coach note",
            "feel": "F" * 200,
            "icu_rpe": 6,
        }

        result = CoachIntervalsContextService().project(
            {"recent_activities": [activity]}, [], TODAY
        )

        row = result["recent_activities_by_sport"]["Radfahren"][0]
        # Fields outside COACH_ACTIVITY_FIELDS (icu_eftp, max_speed, description)
        # and None-valued fields are dropped.
        self.assertEqual(
            set(row),
            {
                "id",
                "start_date_local",
                "name",
                "type",
                "moving_time",
                "feel",
                "icu_rpe",
            },
        )
        self.assertEqual(len(row["name"]), 200)
        self.assertEqual(len(row["feel"]), 120)

    def test_activity_without_id_loses_its_id_when_only_activity_id_exists(
        self,
    ) -> None:
        # Quirk: sorting falls back to activityId, but the projection selects only
        # `id`, so the row is kept without an identifier.
        activity = {
            "activityId": "legacy-7",
            "type": "Run",
            "name": "Legacy",
            "start_date_local": "2026-05-03T07:00:00",
        }

        result = CoachIntervalsContextService().project(
            {"recent_activities": [activity]}, [], TODAY
        )

        rows = result["recent_activities_by_sport"]["Laufen"]
        self.assertEqual(len(rows), 1)
        self.assertNotIn("id", rows[0])
        self.assertEqual(rows[0]["name"], "Legacy")

    def test_planned_projection_drops_date_key_and_filters_on_start_date_first(
        self,
    ) -> None:
        # Quirk: a planned item is accepted through its `date` key, but the
        # projection drops that key and keeps no date at all. Date filtering
        # prefers start_date_local, so a past start with a future `date` is excluded.
        events = [
            {
                "id": "date-only",
                "date": "2026-05-05",
                "name": "Date only",
                "type": "Run",
                "description": "private",
                "target": "T" * 1200,
            },
            {
                "id": "start-wins",
                "start_date_local": "2026-05-01T06:00:00",
                "date": "2026-05-06",
                "name": "Start wins",
            },
        ]

        planned = CoachIntervalsContextService().project({}, events, TODAY)[
            "planned_workouts"
        ]

        self.assertEqual([row["id"] for row in planned], ["date-only"])
        self.assertNotIn("date", planned[0])
        self.assertNotIn("description", planned[0])
        self.assertEqual(len(planned[0]["target"]), 1000)

    def test_synced_at_is_passed_through_and_missing_planned_units_are_empty(
        self,
    ) -> None:
        result = CoachIntervalsContextService().project(
            _intervals_snapshot(), None, TODAY
        )

        self.assertEqual(result["synced_at"], "2026-05-04T05:00:00Z")
        self.assertEqual(result["planned_workouts"], [])


class CoachStructuredContextSwitchTests(unittest.TestCase):
    def test_missing_intervals_snapshot_switches_garmin_to_performance_fallback(
        self,
    ) -> None:
        service, garmin_projection = _structured_service(None, _garmin_payload())

        result = service.build()

        garmin_projection.coach_context.assert_called_once_with(
            include_performance=True
        )
        self.assertFalse(result["current_performance"]["available"])
        self.assertEqual(result["current_performance"]["source"], INTERVALS_SOURCE)
        self.assertEqual(
            result["current_performance"]["garmin_training_load"]["four_week_balance"][
                "source"
            ],
            GARMIN_SOURCE,
        )
        self.assertIsNone(result["intervals"]["synced_at"])
        self.assertEqual(result["garmin"], {"recovery": {}})

    def test_selection_without_garmin_never_calls_garmin_projection(self) -> None:
        service, garmin_projection = _structured_service(None, _garmin_payload())
        selection = CoachContextSelection(
            "focused", frozenset({"intervals", "current_performance"})
        )

        result = service.build(_intervals_snapshot(), selection=selection)

        garmin_projection.coach_context.assert_not_called()
        self.assertEqual(set(result), {"intervals", "current_performance"})
        self.assertTrue(result["current_performance"]["available"])


class GarminCoachContextFallbackProvenanceTests(unittest.TestCase):
    def test_missing_categories_are_empty_mappings_and_no_performance_block(
        self,
    ) -> None:
        result = _garmin_projection_service({}).coach_context()

        self.assertIsNone(result["synced_at"])
        self.assertIsNone(result["start"])
        self.assertIsNone(result["end"])
        self.assertEqual(result["source_freshness"], {})
        self.assertEqual(
            result["recovery"],
            {
                "sleep": {},
                "hrv": {},
                "resting_hr": {},
                "readiness": {},
                "body_battery": {},
            },
        )
        self.assertEqual(result["errors"], [])
        self.assertNotIn("performance", result)

    def test_vendor_fields_are_dropped_from_garmin_coach_context(self) -> None:
        result = _garmin_projection_service(_garmin_payload()).coach_context()

        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["recovery"]["sleep"]["sleepScore"], 84)
        self.assertNotIn(VENDOR_SENTINEL, serialized)
        self.assertNotIn("vendorBlob", serialized)

    def test_scalar_recovery_values_are_wrapped_with_value_key(self) -> None:
        result = _garmin_projection_service(
            {"hrv": 57, "resting_hr": 48}
        ).coach_context()

        self.assertEqual(result["recovery"]["hrv"], {"value": 57})
        self.assertEqual(result["recovery"]["resting_hr"], {"value": 48})

    def test_source_freshness_gets_measurement_age_and_drops_non_mappings(
        self,
    ) -> None:
        snapshot = {
            "start": "2026-04-27",
            "end": "2026-05-04",
            "source_freshness": {
                "sleep": {
                    "freshness": "current",
                    "observed_at": "2026-05-03",
                    "fetched_at": "2026-05-04T06:00:00Z",
                },
                "hrv": "not-a-mapping",
            },
        }

        result = _garmin_projection_service(snapshot).coach_context()

        self.assertEqual(result["start"], "2026-04-27")
        self.assertEqual(result["end"], "2026-05-04")
        self.assertEqual(set(result["source_freshness"]), {"sleep"})
        sleep = result["source_freshness"]["sleep"]
        self.assertEqual(sleep["freshness"], "current")
        self.assertEqual(sleep["fetched_at"], "2026-05-04T06:00:00Z")
        self.assertEqual(sleep["measurement_status"], "earlier")
        self.assertEqual(sleep["measurement_age_days"], 1)

    def test_performance_fallback_keeps_garmin_source_and_note(self) -> None:
        snapshot = {
            "source_freshness": {
                "cycling_ftp": {"freshness": "current", "observed_at": "2026-05-04"}
            },
            "cycling_ftp": {
                "calendarDate": "2026-05-04",
                "functionalThresholdPower": 265,
            },
        }

        result = _garmin_projection_service(snapshot).coach_context(
            include_performance=True
        )

        self.assertEqual(result["performance"]["source"], GARMIN_SOURCE)
        ftp = result["performance"]["thresholds"]["cycling_ftp_watts"]
        self.assertEqual(ftp["value"], 265)
        self.assertEqual(ftp["source"], GARMIN_SOURCE)
        self.assertEqual(ftp["note"], "Garmin Connect FTP")
        self.assertEqual(ftp["freshness"], "current")
        self.assertEqual(ftp["measurement_status"], "today")
        self.assertIn("Kein Intervals.icu-Snapshot", result["scope"])


if __name__ == "__main__":
    unittest.main()
