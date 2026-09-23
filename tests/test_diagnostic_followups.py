"""Synthetic regressions for the September diagnostic findings."""
import json
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import test_coach_dialogue as dialogue

from backend.performance import garmin_metrics as performance_garmin_metrics
from backend.performance import morning_battery as performance_morning_battery
from backend.sync import garmin as garmin_sync
from backend.sync import observation as sync_observation
from backend.sync.garmin_service import GarminSyncService

server = dialogue.server


class DiagnosticFollowupTests(unittest.TestCase):
    setUp = dialogue.CoachDialogueTests.setUp
    request = dialogue.CoachDialogueTests.request
    call = dialogue.CoachDialogueTests.call
    turn = dialogue.CoachDialogueTests.turn

    def test_yesterdays_ready_status_is_not_todays_success(self):
        server.set_kv("morning_checkin_status", "ready")
        server.set_kv("morning_checkin_date", "2026-09-06")
        result = server.public_bootstrap()["morning_checkin"]
        self.assertEqual(result["status"], "waiting")
        self.assertFalse(result["current_for_today"])
        self.assertEqual(server.diagnostic_report_service().report()["morning_checkin"], result)

    def test_static_garmin_fixture_sleep_is_normalized_to_simulated_today(self):
        with tempfile.TemporaryDirectory() as temp_root:
            fixture = Path(temp_root) / "garmin.json"
            fixture.write_text(json.dumps({"sleep": [{"calendarDate": "2026-08-29", "sleepScore": 82}]}), encoding="utf-8")
            config = replace(server.CONFIG, garmin_fixture_path=str(fixture))
            with patch.object(server, "CONFIG", config):
                payload = server.garmin_fixture_loader().load(2)
        self.assertEqual(payload["sleep"][0]["calendarDate"], server.local_now().date().isoformat())

    def test_static_garmin_fixture_preserves_relative_sleep_dates(self):
        with tempfile.TemporaryDirectory() as temp_root:
            fixture = Path(temp_root) / "garmin.json"
            fixture.write_text(json.dumps({"sleep": [
                {"calendarDate": "2026-08-28", "sleepScore": 79},
                {"calendarDate": "2026-08-29", "sleepScore": 82},
            ]}), encoding="utf-8")
            config = replace(server.CONFIG, garmin_fixture_path=str(fixture))
            with patch.object(server, "CONFIG", config):
                payload = server.garmin_fixture_loader().load(2)
        today = server.local_now().date()
        self.assertEqual([record["calendarDate"] for record in payload["sleep"]], [
            (today - timedelta(days=1)).isoformat(),
            today.isoformat(),
        ])

    def test_missing_body_battery_can_recover_after_cooldown_and_success_is_cached(self):
        day = server.local_now().date()
        with patch.object(garmin_sync.GarminFixtureLoader, "path", return_value=Path("synthetic.json")), \
                patch.object(garmin_sync.GarminFixtureLoader, "load", return_value={}) as fetch:
            service = server.morning_body_battery_service()
            first = service.sync(day)
            self.assertEqual(first["status"], "not_available_today")
            self.assertEqual(service.sync(day)["status"], "retry_wait")
            self.assertEqual(fetch.call_count, 1)
            snapshot = server.garmin_payload_service().snapshot()
            snapshot["morning_body_battery"]["attempted_at"] = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
            server.set_kv("garmin_snapshot", json.dumps(snapshot))
            ready = {"sleep_date": day.isoformat(), "status": "ready", "attempted_at": server.utc_now(), "morning": {"value": 78}, "before_sleep": {"value": 30}}
            with patch.object(performance_morning_battery, "morning_body_battery_record", return_value=ready):
                self.assertEqual(service.sync(day)["status"], "ready")
            self.assertEqual(server.garmin_payload_service().snapshot()["morning_body_battery"]["attempts"], 2)
            self.assertEqual(service.sync(day)["status"], "already_loaded")
            self.assertEqual(fetch.call_count, 2)

    def test_late_checkin_uses_wake_up_body_battery_and_rejects_afternoon_only_values(self):
        day = server.local_now().date()
        sleep = {"dailySleepDTO": {"sleepStartTimestampGMT": "2026-09-06T21:30:00Z",
                                   "sleepEndTimestampGMT": "2026-09-07T05:45:00Z"}}
        before = ["2026-09-06T21:25:00Z", 30]
        wake_up = ["2026-09-07T05:45:00Z", 78]
        afternoon = ["2026-09-07T13:00:00Z", 40]
        for samples, expected in (([before, wake_up, afternoon], 78), ([before, afternoon], None)):
            with self.subTest(expected=expected):
                record = performance_morning_battery.morning_body_battery_record(
                    day, sleep, [{"bodyBatteryValuesArray": samples}],
                    attempted_at="2026-09-07T14:00:00Z",
                )
                self.assertEqual((record["morning"] or {}).get("value"), expected)
                self.assertEqual(record["status"], "ready" if expected else "not_available_today")

    def test_body_battery_lock_contention_does_not_replace_saved_recovery(self):
        snapshot = {"morning_body_battery": {"sleep_date": "2026-09-06", "status": "ready", "morning": {"value": 70}}}
        server.set_kv("garmin_snapshot", json.dumps(snapshot))
        service = server.morning_body_battery_service()
        with patch.object(
            service._execution_gate,
            "_lock",
            Mock(acquire=Mock(return_value=False)),
        ):
            self.assertEqual(service.sync(server.local_now().date())["status"], "already_running")
        self.assertEqual(server.garmin_payload_service().snapshot(), snapshot)

    def test_morning_remote_calls_use_the_current_operation_context(self):
        day = server.local_now().date()
        context = {"operation_id": "morning-context", "trigger": "checkin"}

        def fetch(_client, _checkin_date, **kwargs):
            kwargs["external_call"]("garmin", "synthetic", lambda: None, {})
            return {}, []

        with patch.object(server.GarminClientFactory, "create", return_value=object()), \
                patch.object(server, "fetch_morning_body_battery", side_effect=fetch), \
                patch.object(server.provider_http, "external_call", return_value=None) as external_call:
            token = sync_observation.OPERATION_CONTEXT.set(context)
            try:
                server.morning_body_battery_service().source.fetch_remote(day)
            finally:
                sync_observation.OPERATION_CONTEXT.reset(token)

        self.assertEqual(external_call.call_args.kwargs["operation_context"], context)

    def test_regular_garmin_jobs_refresh_recovery_but_historical_jobs_do_not(self):
        with patch.object(GarminSyncService, "sync", return_value={"status": "partial"}), patch.object(server.morning_body_battery_service(), "refresh") as recovery:
            server.sync_job_executor().execute(
                server.sync_job_queue_service().enqueue(
                    "garmin", "refresh", {"days": 30}
                )
            )
            recovery.assert_called_once_with()
            recovery.reset_mock()
            server.sync_job_executor().execute(
                server.sync_job_queue_service().enqueue(
                    "garmin",
                    "historical_backfill",
                    {"days": 30, "end_date": "2026-08-01"},
                )
            )
            recovery.assert_not_called()

    def test_new_fetch_of_old_weight_exposes_observation_age_without_altering_raw_data(self):
        snapshot = {"synced_at": server.utc_now(), "weight": {"calendarDate": "2026-08-12", "weight": 72}, "errors": []}
        garmin_sync.merge_sources(snapshot, {})
        original = json.dumps(snapshot, sort_keys=True)
        server.set_kv("garmin_snapshot", original)
        metric = performance_garmin_metrics.garmin_performance_metrics(
            snapshot, server.local_now().date()
        )["weight_kg"]
        self.assertEqual(metric["freshness"], "current")
        self.assertEqual(metric["measurement_status"], "earlier")
        self.assertEqual(metric["measurement_age_days"], 26)
        self.assertIn("keine neue Messung", metric["note"])
        self.assertEqual(server.garmin_projection_service().public_state()["source_freshness"]["weight"]["measurement_age_days"], 26)
        self.assertEqual(server.garmin_projection_service().coach_context()["source_freshness"]["weight"]["measurement_status"], "earlier")
        self.assertEqual(json.dumps(snapshot, sort_keys=True), original)
        self.assertEqual(server.get_kv("garmin_snapshot"), original)

    def test_feedback_answer_after_plain_text_morning_question_is_saved_once(self):
        server.sync_state_repository().save_snapshot({"synced_at": server.utc_now(), "recent_activities": [{"id": "synthetic-ride", "name": "Synthetic recovery ride", "type": "Ride", "start_date_local": "2026-09-06T10:00:00"}]})
        self.turn("Morgen-Check-in", [{"output_text": "Wie haben sich deine Beine bei der gestrigen Fahrt angefühlt?"}])
        result, _ = self.turn("Beine fühlten sich gut an, die geringe Leistung war aber zäh und langweilig.", [
            lambda _: self.call("inspect_activity_duplicates"),
            lambda _: self.call("save_activity_feedback", {"payload": {"activity_id": "synthetic-ride", "notes": "Beine gut; geringe Leistung fühlte sich zäh und langweilig an."}}, ["activity_feedback"]),
            {"output_text": "Deine Rückmeldung zur Fahrt ist gespeichert."},
        ])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(server.activity_feedback_service().list()), 1)
        self.assertEqual(
            server.activity_feedback_service().list()[0]["activity_id"],
            "synthetic-ride",
        )

    def test_activity_max_hr_age_uses_the_selected_measurement_not_latest_sync_activity(self):
        for stored_maximum, expected_age, expected_status in ((None, 6, "earlier"), (200, None, "unknown")):
            with self.subTest(stored_maximum=stored_maximum):
                snapshot = {"activities": [
                    {"type": "Ride", "startTimeLocal": "2026-09-01T10:00:00", "maxHR": 190},
                    {"type": "Ride", "startTimeLocal": "2026-09-07T10:00:00", "maxHR": 150},
                ], "source_freshness": {"activities": {"freshness": "current",
                    "observed_at": "2026-09-07", "fetched_at": "2026-09-07T11:00:00Z"}}}
                if stored_maximum:
                    snapshot["sport_max_hr"] = {"cycling": stored_maximum}
                original = json.dumps(snapshot, sort_keys=True)
                metric = performance_garmin_metrics.garmin_performance_metrics(
                    snapshot, server.local_now().date()
                )["cycling_max_hr_bpm"]
                self.assertEqual(metric["value"], stored_maximum or 190)
                self.assertEqual(metric["observed_at"], None if stored_maximum else "2026-09-01")
                self.assertEqual(metric["measurement_status"], expected_status)
                self.assertEqual(metric["measurement_age_days"], expected_age)
                self.assertEqual(metric["freshness"], "current")
                self.assertEqual(metric["fetched_at"], "2026-09-07T11:00:00Z")
                if expected_age is not None:
                    self.assertIn("6 Tage alt", metric["note"])
                self.assertEqual(json.dumps(snapshot, sort_keys=True), original)

    def test_duplicate_inspection_returns_confirmation_preview_without_remote_deletion(self):
        activities = [{"id": "synthetic-wahoo", "source": "Wahoo", "type": "Ride",
                       "start_date_local": "2026-09-06T10:00:00", "moving_time": 3600, "distance": 30000},
                      {"id": "synthetic-garmin", "source": "Garmin", "type": "Ride",
                       "start_date_local": "2026-09-06T10:01:00", "moving_time": 3610, "distance": 30100}]
        server.sync_state_repository().save_snapshot({"synced_at": server.utc_now(), "recent_activities": activities})
        before = server.sync_state_repository().latest_snapshot()
        with patch.object(server, "IntervalsClient") as provider:
            result, model = self.turn("Analysiere die letzte Fahrt.", [
                lambda _: self.call("inspect_activity_duplicates"),
                {"output_text": "Die Fahrt wurde doppelt aufgezeichnet. Die Wahoo-Aufzeichnung bleibt maßgeblich."},
            ])
        self.assertEqual(result["status"], "completed")
        provider.assert_not_called()
        self.assertEqual(server.sync_state_repository().latest_snapshot(), before)
        output = json.loads(model.call_args.args[0]["input"][0]["output"])
        self.assertTrue(output["ok"])
        self.assertEqual(output["duplicate"]["canonical_id"], "synthetic-wahoo")
        self.assertEqual(output["duplicate"]["duplicate_id"], "synthetic-garmin")
        self.assertEqual(output["status"], "preview")
        self.assertEqual(result["proposed_actions"][0]["action_type"], "delete_duplicate_intervals_activity")

    def test_failed_tool_is_diagnosable_without_detail_capture_and_without_content(self):
        private = "synthetic-private-content-never-export"
        with patch.object(
            server.ActivityFeedbackService,
            "save_coach",
            side_effect=RuntimeError(private),
        ):
            result, _ = self.turn(private, [lambda _: self.call("save_activity_feedback", {"payload": {"activity_id": "synthetic", "notes": private}}, ["activity_feedback"])])
        self.assertEqual(result["status"], "failed")
        history = server.diagnostic_report_service().report()["coach_commands"]
        self.assertEqual(history[0]["error"]["type"], "RuntimeError")
        self.assertTrue(history[0]["error"]["frames"])
        self.assertNotIn(private, json.dumps(history))
        self.assertNotIn("synthetic-session", json.dumps(history))
        self.assertFalse(server.DIAGNOSTIC_CAPTURE.status()["active"])

    def test_rejected_tool_and_incomplete_reply_keep_classified_diagnostics(self):
        result, _ = self.turn("Synthetic missing activity feedback", [
            lambda _: self.call("save_activity_feedback", {"payload": {"activity_id": "missing", "notes": "Synthetic note"}}, ["activity_feedback"]),
            {"status": "incomplete", "output_text": "Synthetic unfinished answer"},
        ])
        self.assertEqual(result["status"], "partial")
        history = server.coach_diagnostic_history_service().history()
        self.assertEqual(history[0]["response_status"], "incomplete")
        self.assertEqual(history[0]["steps"][0]["error"]["status"], 404)
        self.assertEqual(history[0]["steps"][0]["tool"], "save_activity_feedback")
        self.assertNotIn("Synthetic note", json.dumps(history))
