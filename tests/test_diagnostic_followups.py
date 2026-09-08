"""Synthetic regressions for the September diagnostic findings."""
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import test_coach_dialogue as dialogue

server = dialogue.server


class DiagnosticFollowupTests(unittest.TestCase):
    setUp = dialogue.CoachDialogueTests.setUp
    request = dialogue.CoachDialogueTests.request
    call = dialogue.CoachDialogueTests.call
    turn = dialogue.CoachDialogueTests.turn

    def test_morning_catches_up_after_11_but_not_before_5(self):
        for hour in (4, 5, 10, 13, 23):
            with self.subTest(hour=hour), patch.object(server, "local_now", return_value=datetime(2026, 9, 7, hour, tzinfo=timezone.utc)):
                self.assertEqual(server.morning_checkin_date(), None if hour == 4 else "2026-09-07")

    def test_yesterdays_ready_status_is_not_todays_success(self):
        server.set_kv("morning_checkin_status", "ready")
        server.set_kv("morning_checkin_date", "2026-09-06")
        result = server.public_bootstrap()["morning_checkin"]
        self.assertEqual(result["status"], "waiting")
        self.assertFalse(result["current_for_today"])
        self.assertEqual(server.diagnostic_report()["morning_checkin"], result)

    def test_morning_retry_waits_then_uses_a_new_command_and_stops_after_success(self):
        def thread(*, target, **kwargs):
            return Mock(start=target)
        with patch.object(server.threading, "Thread", side_effect=thread), \
                patch.object(server, "sync_intervals", return_value={"status": "ok"}), \
                patch.object(server, "sync_garmin"), patch.object(server, "refresh_morning_body_battery"), \
                patch.object(server, "chat_with_coach", side_effect=[{"status": "failed"}, {"status": "completed", "message": {"id": 1}}]) as chat:
            server.schedule_morning_checkin()
            self.assertEqual(server.get_kv("morning_checkin_status"), "error")
            server.schedule_morning_checkin()
            self.assertEqual(chat.call_count, 1)
            server.set_kv("morning_checkin_attempted_at", (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat())
            server.schedule_morning_checkin()
            self.assertEqual(server.get_kv("morning_checkin_date"), "2026-09-07")
            self.assertEqual([call.kwargs["client_turn_id"] for call in chat.call_args_list], ["morning:2026-09-07", "morning:2026-09-07:attempt:2"])
            server.schedule_morning_checkin()
            self.assertEqual(chat.call_count, 2)
        self.assertFalse(server.MORNING_CHECKIN_LOCK.locked())

    def test_morning_retry_limit_and_manual_pending_checkin_prevent_duplicate_work(self):
        server.set_kv("morning_checkin_attempted", "2026-09-07")
        server.set_kv("morning_checkin_attempt_count", "3")
        with patch.object(server.threading, "Thread") as thread:
            server.schedule_morning_checkin()
            thread.assert_not_called()
            server.set_kv("morning_checkin_attempt_count", "0")
            server.enqueue_background_coach_job("Synthetic check-in", "manual-morning", "synthetic-session", request_kind="morning_checkin")
            server.schedule_morning_checkin()
            thread.assert_not_called()
        self.assertFalse(server.MORNING_CHECKIN_LOCK.locked())

    def test_interrupted_morning_run_is_eligible_after_restart(self):
        server.set_kv("morning_checkin_status", "working")
        server.set_kv("morning_checkin_attempted", "2026-09-07")
        server.initialise_database()
        self.assertEqual(server.get_kv("morning_checkin_attempted"), "")
        self.assertEqual(server.morning_checkin_state()["status"], "waiting")

    def test_missing_body_battery_can_recover_after_cooldown_and_success_is_cached(self):
        day = server.local_now().date()
        with patch.object(server, "garmin_fixture_path", return_value=Path("synthetic.json")), \
                patch.object(server, "load_garmin_fixture", return_value={}) as fetch:
            first = server.sync_garmin_morning_body_battery(day)
            self.assertEqual(first["status"], "not_available_today")
            self.assertEqual(server.sync_garmin_morning_body_battery(day)["status"], "retry_wait")
            self.assertEqual(fetch.call_count, 1)
            snapshot = server.garmin_snapshot()
            snapshot["morning_body_battery"]["attempted_at"] = (datetime.now(timezone.utc) - timedelta(minutes=16)).isoformat()
            server.set_kv("garmin_snapshot", json.dumps(snapshot))
            ready = {"sleep_date": day.isoformat(), "status": "ready", "attempted_at": server.utc_now(), "morning": {"value": 78}, "before_sleep": {"value": 30}}
            with patch.object(server, "_morning_body_battery_record", return_value=ready):
                self.assertEqual(server.sync_garmin_morning_body_battery(day)["status"], "ready")
            self.assertEqual(server.garmin_snapshot()["morning_body_battery"]["attempts"], 2)
            self.assertEqual(server.sync_garmin_morning_body_battery(day)["status"], "already_loaded")
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
                record = server._morning_body_battery_record(day, sleep,
                    [{"bodyBatteryValuesArray": samples}], attempted_at="2026-09-07T14:00:00Z")
                self.assertEqual((record["morning"] or {}).get("value"), expected)
                self.assertEqual(record["status"], "ready" if expected else "not_available_today")

    def test_body_battery_lock_contention_does_not_replace_saved_recovery(self):
        snapshot = {"morning_body_battery": {"sleep_date": "2026-09-06", "status": "ready", "morning": {"value": 70}}}
        server.set_kv("garmin_snapshot", json.dumps(snapshot))
        with patch.object(server, "GARMIN_LOCK", Mock(acquire=Mock(return_value=False))):
            self.assertEqual(server.sync_garmin_morning_body_battery(server.local_now().date())["status"], "already_running")
        self.assertEqual(server.garmin_snapshot(), snapshot)

    def test_regular_garmin_jobs_refresh_recovery_but_historical_jobs_do_not(self):
        with patch.object(server, "sync_garmin", return_value={"status": "partial"}), patch.object(server, "refresh_morning_body_battery") as recovery:
            server._execute_sync_job(server.enqueue_sync_job("garmin", "refresh", {"days": 30}))
            recovery.assert_called_once_with()
            recovery.reset_mock()
            server._execute_sync_job(server.enqueue_sync_job("garmin", "historical_backfill", {"days": 30, "end_date": "2026-08-01"}))
            recovery.assert_not_called()

    def test_new_fetch_of_old_weight_exposes_observation_age_without_altering_raw_data(self):
        snapshot = {"synced_at": server.utc_now(), "weight": {"calendarDate": "2026-08-12", "weight": 72}, "errors": []}
        server.merge_garmin_sources(snapshot, {})
        original = json.dumps(snapshot, sort_keys=True)
        server.set_kv("garmin_snapshot", original)
        metric = server.garmin_performance_metrics(snapshot)["weight_kg"]
        self.assertEqual(metric["freshness"], "current")
        self.assertEqual(metric["measurement_status"], "earlier")
        self.assertEqual(metric["measurement_age_days"], 26)
        self.assertIn("keine neue Messung", metric["note"])
        self.assertEqual(server.garmin_public_state()["source_freshness"]["weight"]["measurement_age_days"], 26)
        self.assertEqual(server.garmin_coach_context()["source_freshness"]["weight"]["measurement_status"], "earlier")
        self.assertEqual(json.dumps(snapshot, sort_keys=True), original)
        self.assertEqual(server.get_kv("garmin_snapshot"), original)

    def test_feedback_answer_after_plain_text_morning_question_is_saved_once(self):
        server.save_snapshot({"synced_at": server.utc_now(), "recent_activities": [{"id": "synthetic-ride", "name": "Synthetic recovery ride", "type": "Ride", "start_date_local": "2026-09-06T10:00:00"}]})
        self.turn("Morgen-Check-in", [{"output_text": "Wie haben sich deine Beine bei der gestrigen Fahrt angefühlt?"}])
        result, _ = self.turn("Beine fühlten sich gut an, die geringe Leistung war aber zäh und langweilig.", [
            lambda _: self.call("inspect_activity_duplicates"),
            lambda _: self.call("save_activity_feedback", {"payload": {"activity_id": "synthetic-ride", "notes": "Beine gut; geringe Leistung fühlte sich zäh und langweilig an."}}, ["activity_feedback"]),
            {"output_text": "Deine Rückmeldung zur Fahrt ist gespeichert."},
        ])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(server.list_activity_feedback()), 1)
        self.assertEqual(server.list_activity_feedback()[0]["activity_id"], "synthetic-ride")

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
                metric = server.garmin_performance_metrics(snapshot)["cycling_max_hr_bpm"]
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
        server.save_snapshot({"synced_at": server.utc_now(), "recent_activities": activities})
        before = server.latest_snapshot()
        with patch.object(server, "IntervalsClient") as provider:
            result, model = self.turn("Analysiere die letzte Fahrt.", [
                lambda _: self.call("inspect_activity_duplicates"),
                {"output_text": "Die Fahrt wurde doppelt aufgezeichnet. Die Wahoo-Aufzeichnung bleibt maßgeblich."},
            ])
        self.assertEqual(result["status"], "completed")
        provider.assert_not_called()
        self.assertEqual(server.latest_snapshot(), before)
        output = json.loads(model.call_args.args[0]["input"][0]["output"])
        self.assertTrue(output["ok"])
        self.assertEqual(output["duplicate"]["canonical_id"], "synthetic-wahoo")
        self.assertEqual(output["duplicate"]["duplicate_id"], "synthetic-garmin")
        self.assertEqual(output["status"], "preview")
        self.assertEqual(result["proposed_actions"][0]["action_type"], "delete_duplicate_intervals_activity")

    def test_failed_tool_is_diagnosable_without_detail_capture_and_without_content(self):
        private = "synthetic-private-content-never-export"
        with patch.object(server, "save_coach_activity_feedback", side_effect=RuntimeError(private)):
            result, _ = self.turn(private, [lambda _: self.call("save_activity_feedback", {"payload": {"activity_id": "synthetic", "notes": private}}, ["activity_feedback"])])
        self.assertEqual(result["status"], "failed")
        history = server.diagnostic_report()["coach_commands"]
        self.assertEqual(history[0]["error"]["type"], "RuntimeError")
        self.assertTrue(history[0]["error"]["frames"])
        self.assertNotIn(private, json.dumps(history))
        self.assertNotIn("synthetic-session", json.dumps(history))
        self.assertFalse(server.diagnostic_capture_status()["active"])

    def test_rejected_tool_and_incomplete_reply_keep_classified_diagnostics(self):
        result, _ = self.turn("Synthetic missing activity feedback", [
            lambda _: self.call("save_activity_feedback", {"payload": {"activity_id": "missing", "notes": "Synthetic note"}}, ["activity_feedback"]),
            {"status": "incomplete", "output_text": "Synthetic unfinished answer"},
        ])
        self.assertEqual(result["status"], "partial")
        history = server.coach_diagnostic_history()
        self.assertEqual(history[0]["response_status"], "incomplete")
        self.assertEqual(history[0]["steps"][0]["error"]["status"], 404)
        self.assertEqual(history[0]["steps"][0]["tool"], "save_activity_feedback")
        self.assertNotIn("Synthetic note", json.dumps(history))
