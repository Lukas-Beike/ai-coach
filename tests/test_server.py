import os
import sys
import tempfile
import unittest
import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="intervals-coach-test-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import server


class CoachTests(unittest.TestCase):
    def setUp(self):
        server.initialise_database()
        with server.DB_LOCK, server.database() as db:
            db.execute("DELETE FROM messages")
            db.execute("DELETE FROM snapshots")
            db.execute("DELETE FROM workout_drafts")
            db.execute("DELETE FROM workout_library")
            db.execute("DELETE FROM competitions")
            db.execute("DELETE FROM kv")
        server.save_profile({})

    def test_profile_only_accepts_known_fields_and_trims(self):
        profile = server.normalize_profile({"name": "  Ada  ", "goals": "Finish strong", "admin": True})
        self.assertEqual(profile["name"], "Ada")
        self.assertNotIn("admin", profile)

    def test_compact_snapshot_drops_unknown_and_sensitive_fields(self):
        result = server.compact_snapshot(
            {"id": "i1", "name": "Ada", "secret": "nope"},
            [{"id": "a1", "name": "Ride", "private_note": "nope"}],
            [{"id": "2026-01-01", "ctl": 42, "unknown": 99}],
            [{"id": 1, "name": "Tempo", "category": "WORKOUT", "raw": "nope"}],
        )
        self.assertEqual(result["athlete"]["name"], "Ada")
        self.assertNotIn("secret", result["athlete"])
        self.assertNotIn("private_note", result["recent_activities"][0])
        self.assertEqual(result["recent_wellness"][0]["ctl"], 42)

    def test_workout_payload_is_an_idempotent_calendar_event(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        payload = server.workout_event_payload("abc", {
            "date": tomorrow,
            "sport": "Ride",
            "name": "Tempo",
            "description": "- 10m 55%\n- 20m 85%\n- 10m 55%",
            "duration_minutes": 40,
            "target": "POWER",
        })
        self.assertEqual(payload["category"], "WORKOUT")
        self.assertEqual(payload["moving_time"], 2400)
        self.assertEqual(payload["external_id"], "intervals-coach-abc")
        self.assertTrue(payload["start_date_local"].endswith("T00:00:00"))

    def test_past_workout_is_rejected(self):
        old = (date.today() - timedelta(days=4)).isoformat()
        with self.assertRaises(server.AppError):
            server.workout_event_payload("abc", {"date": old, "duration_minutes": 60})

    def test_workout_draft_can_be_deleted_locally(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        draft = server.save_workout_drafts([{
            "date": tomorrow, "sport": "Ride", "name": "Bibliothek",
            "description": "Locker fahren", "duration_minutes": 45, "target": "AUTO",
        }])[0]
        self.assertEqual(server.delete_workout_draft(draft["id"])["status"], "deleted")
        self.assertEqual(server.list_workout_drafts(), [])

    def test_library_is_cached_and_included_in_coach_context(self):
        server.upsert_workout_library([{
            "id": 42, "name": "Locker Rad", "type": "Ride",
            "description": "- 45m Z2", "moving_time": 2700,
        }])
        self.assertEqual(server.list_workout_library()[0]["name"], "Locker Rad")
        self.assertIn("LOCAL TRAINING LIBRARY", server.build_training_context())

    def test_library_workout_can_be_planned_from_local_cache(self):
        server.upsert_workout_library([{
            "id": 42, "name": "Locker Rad", "type": "Ride",
            "description": "- 45m Z2", "moving_time": 2700,
        }])
        fake_event = {"id": "event-42", "name": "Locker Rad"}
        with patch.object(server, "CONFIG", server.Config(intervals_api_key="test-key")), patch.object(
            server.IntervalsClient, "plan_library_workout", return_value=fake_event
        ) as plan:
            result = server.plan_library_workout("42", (date.today() + timedelta(days=1)).isoformat())
        self.assertEqual(result["status"], "planned")
        plan.assert_called_once()

    def test_coach_library_creation_is_cached(self):
        created = [{"id": 77, "name": "Coach Tempo", "type": "Ride", "description": "- 30m 85%"}]
        with patch.object(server, "CONFIG", server.Config(intervals_api_key="test-key")), patch.object(
            server.IntervalsClient, "create_library_workouts", return_value=created
        ) as create:
            result = server.create_library_workouts([{
                "name": "Coach Tempo", "sport": "Ride", "description": "- 30m 85%",
            }])
        self.assertEqual(result[0]["id"], "77")
        create.assert_called_once()
        self.assertEqual(server.list_workout_library()[0]["name"], "Coach Tempo")

    def test_planned_event_delete_updates_local_snapshot(self):
        test_config = server.Config(**{**server.CONFIG.__dict__, "intervals_api_key": "test-key"})
        with patch.object(server, "CONFIG", test_config), patch.object(
            server.IntervalsClient, "delete_event", return_value=None
        ) as delete_event:
            snapshot = server.compact_snapshot({}, [], [], [{
                "id": "event-1", "name": "Tempo", "category": "WORKOUT",
            }])
            server.save_snapshot(snapshot)
            result = server.delete_planned_event("event-1")
        self.assertEqual(result["status"], "deleted")
        delete_event.assert_called_once_with("event-1")
        self.assertEqual(server.latest_snapshot()["upcoming_calendar"], [])

    def test_output_text_falls_back_to_nested_content(self):
        response = {"output": [{"type": "message", "content": [{"type": "output_text", "text": "Hello"}]}]}
        self.assertEqual(server.output_text(response), "Hello")

    def test_chat_can_request_a_fresh_training_snapshot(self):
        self.assertTrue(server.prompt_requests_fresh_data("Lade bitte meine letzten Einheiten und analysiere sie."))
        self.assertTrue(server.prompt_requests_fresh_data("Please load my latest workouts and review them."))
        self.assertFalse(server.prompt_requests_fresh_data("Was soll ich morgen trainieren?"))

    def test_model_selection_is_persisted_and_validated(self):
        self.assertEqual(server.selected_model(), "gpt-5.6-sol")
        self.assertEqual(server.save_model("gpt-5.6-terra"), {"model": "gpt-5.6-terra"})
        self.assertEqual(server.selected_model(), "gpt-5.6-terra")
        with self.assertRaises(server.AppError):
            server.save_model("not-a-model")

    def test_sync_period_supports_all_available_data_marker(self):
        self.assertEqual(server.set_sync_period("intervals", -1), -1)
        self.assertEqual(server.sync_period("intervals"), -1)
        self.assertEqual(server.set_sync_period("garmin", -1), -1)
        self.assertEqual(server.sync_period("garmin"), -1)
        self.assertGreater(len(server.sync_date_windows(-1, date(2026, 8, 29))), 1)

    def test_all_time_snapshot_does_not_truncate_activity_history(self):
        snapshot = server.compact_snapshot(
            {}, [{"id": str(index), "name": f"Ride {index}"} for index in range(600)],
            [{"id": f"2026-01-{index:02d}", "ctl": index} for index in range(1, 4)], [], history_days=-1,
        )
        self.assertEqual(len(snapshot["recent_activities"]), 600)
        self.assertEqual(len(snapshot["recent_wellness"]), 3)

    def test_chat_reuses_one_persistent_openai_conversation(self):
        calls = []

        def fake_openai(path, payload):
            calls.append((path, payload))
            if path == "/conversations":
                return {"id": "conv_test"}
            return {"output_text": "Coach reply", "output": []}

        with patch.object(server, "openai_request", side_effect=fake_openai):
            server.chat_with_coach("How am I doing?")
            server.chat_with_coach("What about tomorrow?")

        conversation_calls = [call for call in calls if call[0] == "/conversations"]
        response_calls = [call for call in calls if call[0] == "/responses"]
        self.assertEqual(len(conversation_calls), 1)
        self.assertEqual([call[1]["conversation"] for call in response_calls], ["conv_test", "conv_test"])
        self.assertEqual([m["role"] for m in server.list_messages()], ["user", "assistant", "user", "assistant"])

    def test_saved_profile_is_included_in_coach_context(self):
        server.save_profile({"name": "Ada", "goals": "Münsterland Giro", "constraints": "No hard sessions after poor sleep"})
        context = server.build_training_context()
        self.assertIn('"name":"Ada"', context)
        self.assertIn("Münsterland Giro", context)
        self.assertIn("No hard sessions after poor sleep", context)

    def test_structured_athlete_context_persists_competitions(self):
        event_date = (date.today() + timedelta(days=60)).isoformat()
        result = server.save_athlete_context(
            {"name": "Ada", "training_background": "Five years of cycling", "typical_weekly_volume": "8 hours"},
            [{
                "name": "Münsterland Giro",
                "event_date": event_date,
                "sport": "Cycling",
                "priority": "A",
                "distance": "125 km",
                "target": "Finish with the front group",
                "course_profile": "Flat and fast",
                "notes": "",
            }],
        )
        self.assertEqual(result["profile"]["training_background"], "Five years of cycling")
        self.assertEqual(result["competitions"][0]["priority"], "A")
        context = server.structured_athlete_context()
        self.assertEqual(context["target_competitions"][0]["name"], "Münsterland Giro")
        self.assertIn("bestätigte", context["source_policy"]["durable_profile"])

    def test_current_performance_is_derived_from_intervals_snapshot(self):
        today = date.today().isoformat()
        snapshot = {
            "synced_at": "2026-08-28T08:00:00+00:00",
            "athlete": {"icu_ftp": 300, "lthr": 171},
            "recent_wellness": [{"id": today, "ctl": 70, "atl": 76, "tsb": -6, "sleepSecs": 27000, "readiness": 8}],
            "recent_activities": [{"start_date_local": today + "T07:00:00", "moving_time": 7200, "icu_training_load": 110}],
        }
        performance = server.current_performance_context(snapshot)
        self.assertEqual(performance["thresholds"]["icu_ftp"], 300)
        self.assertEqual(performance["current_load"]["tsb"], -6)
        self.assertEqual(performance["recovery"]["sleep_hours"], 7.5)
        self.assertEqual(performance["rolling_training"]["last_7_days"]["training_load"], 110.0)

    def test_form_is_derived_from_ctl_and_atl_when_intervals_omits_tsb(self):
        today = date.today().isoformat()
        snapshot = {
            "synced_at": "now", "athlete": {},
            "recent_wellness": [{"id": today, "ctl": 60, "atl": 72}],
            "recent_activities": [],
        }
        performance = server.current_performance_context(snapshot)
        self.assertEqual(performance["current_load"]["tsb"], -12)

    def test_current_performance_includes_health_and_training_comparisons(self):
        today = date.today()
        wellness = [{
            "id": (today - timedelta(days=offset)).isoformat(), "sleepSecs": 25200,
            "readiness": 70, "restingHR": 60, "hrv": 50, "ctl": 50, "atl": 60, "tsb": -10,
        } for offset in range(7)]
        wellness[0]["sleepSecs"] = 28800
        wellness[0]["readiness"] = 80
        wellness[0]["restingHR"] = 55
        wellness[0]["hrv"] = 60
        snapshot = {"synced_at": "now", "athlete": {}, "recent_wellness": wellness, "recent_activities": []}
        comparisons = server.current_performance_context(snapshot)["comparisons"]
        self.assertEqual(comparisons["sleep_hours"]["days"], 7)
        self.assertEqual(comparisons["sleep_hours"]["color"], "good")
        self.assertEqual(comparisons["restingHR"]["color"], "good")
        self.assertEqual(comparisons["fitness_ctl"]["color"], "neutral")

    def test_actual_atl_uses_completed_activities_and_is_exposed_separately(self):
        today = date.today()
        wellness = [
            {"id": (today - timedelta(days=offset)).isoformat(), "atl": 60.0, "ctl": 55.0}
            for offset in range(7)
        ]
        snapshot = {
            "synced_at": "now", "athlete": {}, "recent_wellness": wellness,
            "recent_activities": [{"start_date_local": today.isoformat() + "T08:00:00", "icu_training_load": 60}],
        }
        performance = server.current_performance_context(snapshot)
        self.assertIn("atl", performance["actual_load"])
        self.assertEqual(performance["actual_load"]["source"], "Abgeschlossene Aktivitäten (berechnet)")
        self.assertIn("fatigue_atl_actual", performance["comparisons"])

    def test_actual_atl_recurrence_does_not_double_decay_daily_rows(self):
        today = date.today()
        retention = __import__("math").exp(-1 / 7)
        expected = 10 * retention + 70 * (1 - retention)
        wellness = [
            {"id": (today - timedelta(days=1)).isoformat(), "atl": 10},
            {"id": today.isoformat(), "atl": expected},
        ]
        activities = [{"start_date_local": today.isoformat() + "T08:00:00", "icu_training_load": 70}]
        series = server.actual_atl_series(wellness, activities, today)
        self.assertAlmostEqual(series[today], expected, places=2)

    def test_performance_reads_sport_settings_and_wellness_aliases(self):
        today = date.today().isoformat()
        snapshot = server.compact_snapshot(
            {
                "weight": 72.3,
                "sportSettings": [
                    {"types": ["Ride", "VirtualRide"], "ftp": 285, "lthr": 168, "vo2max": 62},
                    {"types": ["Run"], "ftp": 315, "lthr": 174, "threshold_pace": 3.5, "vo2max": 58},
                ],
            },
            [],
            [{"id": today, "ctLoad": 68, "atlLoad": 74, "form": -6, "readiness": 82}],
            [],
        )
        performance = server.current_performance_context(snapshot)
        metrics = performance["metrics"]
        self.assertEqual(metrics["cycling_ftp_watts"]["value"], 285)
        self.assertEqual(metrics["run_threshold_watts"]["value"], 315)
        self.assertEqual(metrics["run_threshold_pace_seconds_per_km"]["value"], 286)
        self.assertEqual(metrics["run_threshold_hr_bpm"]["value"], 174)
        self.assertEqual(metrics["cycling_vo2max_ml_kg_min"]["value"], 62)
        self.assertEqual(performance["current_load"]["ctl"], 68)
        self.assertEqual(performance["current_load"]["tsb"], -6)

    def test_manual_body_profile_values_are_used_when_api_values_are_absent(self):
        server.save_profile({"weight_kg": "71,4", "body_fat_pct": "10.5", "height_cm": "181"})
        performance = server.current_performance_context({"synced_at": "now", "athlete": {}, "recent_wellness": [], "recent_activities": []})
        self.assertEqual(performance["metrics"]["weight_kg"]["value"], 71.4)
        self.assertEqual(performance["metrics"]["body_fat_pct"]["source"], "Manuell")
        self.assertEqual(performance["metrics"]["height_cm"]["value"], 181)
        metric = server.current_performance_context({"synced_at": "now", "athlete": {"height": 1.83}, "recent_wellness": [], "recent_activities": []})["metrics"]["height_cm"]
        self.assertEqual(metric["value"], 183)

    def test_performance_refresh_does_not_request_activities(self):
        calls = []

        class FakeIntervalsClient:
            def fetch_performance_snapshot(self, existing):
                calls.append(existing)
                return {"synced_at": "2026-08-28T08:00:00+00:00", "athlete": {}, "recent_wellness": [], "recent_activities": [], "upcoming_calendar": []}

        with patch.object(server, "IntervalsClient", FakeIntervalsClient), patch.object(server, "estimate_performance_from_activities", return_value={"estimates": []}):
            with patch.object(server, "CONFIG", server.Config(intervals_api_key="test-key")):
                result = server.refresh_current_performance()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(calls), 1)

    def test_ai_estimate_accepts_structured_json_and_is_used_for_missing_metrics(self):
        snapshot = {
            "synced_at": "2026-08-28T08:00:00+00:00",
            "athlete": {},
            "recent_wellness": [],
            "recent_activities": [
                {"type": "Run", "start_date_local": "2026-08-27T07:00:00", "moving_time": 1800, "distance": 5000}
            ],
        }
        response = {"output_text": '```json\n{"estimates":[{"key":"run_5k_seconds","value":1500,"unit":"s","confidence":"mittel","basis":"5-km-Lauf"}]}\n```'}
        with patch.object(server, "CONFIG", server.Config(openai_api_key="test-key")), patch.object(server, "openai_request", return_value=response):
            result = server.estimate_performance_from_activities(snapshot)
            performance = server.current_performance_context(snapshot)
        self.assertEqual(len(result["estimates"]), 1)
        self.assertEqual(performance["metrics"]["run_5k_seconds"]["value"], 1500)
        self.assertEqual(performance["metrics"]["run_5k_seconds"]["source"], "KI-Schätzung")

    def test_ai_estimate_fills_missing_run_race_times_from_recent_runs(self):
        snapshot = {
            "synced_at": "2026-08-28T08:00:00+00:00", "athlete": {}, "recent_wellness": [],
            "recent_activities": [{"type": "Run", "start_date_local": "2026-08-27T07:00:00", "moving_time": 1800, "distance": 5000}],
        }
        response = {"output_text": '{"estimates":[{"key":"run_threshold_pace_seconds_per_km","value":360,"unit":"s/km","confidence":"mittel","basis":"Laufdaten"}]}' }
        with patch.object(server, "CONFIG", server.Config(openai_api_key="test-key")), patch.object(server, "openai_request", return_value=response):
            result = server.estimate_performance_from_activities(snapshot)
        self.assertTrue(any(item["key"] == "run_10k_seconds" for item in result["estimates"]))
        self.assertEqual(next(item for item in result["estimates"] if item["key"] == "run_10k_seconds")["source"], "Berechnete Schätzung")

    def test_public_state_exposes_completed_and_planned_activity_tabs(self):
        snapshot = {"synced_at": "now", "athlete": {}, "recent_activities": [{"name": "Morgenlauf"}], "recent_wellness": [], "upcoming_calendar": [{"name": "Intervalle"}]}
        server.save_snapshot(snapshot)
        state = server.public_state()
        self.assertEqual(state["activities"][0]["name"], "Morgenlauf")
        self.assertEqual(state["planned"][0]["name"], "Intervalle")

    def test_garmin_near_duplicate_is_skipped_in_favour_of_intervals_activity(self):
        garmin = {
            "activityId": 1, "activityType": "running", "activityName": "Morning Run",
            "startTimeLocal": "2026-08-29T07:05:00", "duration": 3600, "distance": 9900,
        }
        intervals = [{"type": "Run", "start_date_local": "2026-08-29T07:00:00", "moving_time": 3560, "distance": 10000}]
        self.assertTrue(server.garmin_activity_duplicates_intervals(garmin, intervals))
        kept, skipped = server.filter_garmin_activities([garmin], intervals)
        self.assertEqual(kept, [])
        self.assertEqual(skipped, 1)

    def test_garmin_near_duplicate_allows_thirty_minute_start_difference(self):
        garmin = {
            "activityId": 3, "activityType": "cycling", "activityName": "Ride",
            "startTimeLocal": "2026-08-29T07:30:00", "duration": 3600, "distance": 30000,
        }
        intervals = [{"type": "Ride", "start_date_local": "2026-08-29T07:00:00", "moving_time": 3560, "distance": 30000}]
        self.assertTrue(server.garmin_activity_duplicates_intervals(garmin, intervals))

    def test_garmin_activity_more_than_thirty_minutes_apart_is_kept(self):
        garmin = {
            "activityId": 4, "activityType": "cycling", "activityName": "Ride",
            "startTimeLocal": "2026-08-29T07:31:00", "duration": 3600, "distance": 30000,
        }
        intervals = [{"type": "Ride", "start_date_local": "2026-08-29T07:00:00", "moving_time": 3560, "distance": 30000}]
        self.assertFalse(server.garmin_activity_duplicates_intervals(garmin, intervals))

    def test_garmin_different_activity_is_kept(self):
        garmin = {
            "activityId": 2, "activityType": "cycling", "startTimeLocal": "2026-08-29T07:05:00",
            "duration": 3600, "distance": 30000,
        }
        intervals = [{"type": "Run", "start_date_local": "2026-08-29T07:00:00", "moving_time": 3560, "distance": 10000}]
        kept, skipped = server.filter_garmin_activities([garmin], intervals)
        self.assertEqual(len(kept), 1)
        self.assertEqual(skipped, 0)

    def test_diagnostics_redact_credentials_from_logs(self):
        server.initialise_logging()
        server.LOGGER.error("failed request with sk-test-secret-value")
        for handler in server.LOGGER.handlers:
            handler.flush()
        report_text = json.dumps(server.diagnostic_report())
        self.assertNotIn("sk-test-secret-value", report_text)
        self.assertIn("logs", server.diagnostic_report())

    def test_upstream_network_failures_are_structured_in_diagnostics(self):
        server.initialise_logging()
        with patch.object(server, "urlopen", side_effect=server.URLError("offline")):
            with self.assertRaises(server.AppError):
                server.http_json("GET", "https://intervals.icu/api/v1/athlete/0")
        for handler in server.LOGGER.handlers:
            handler.flush()
        entries = server.recent_log_entries()
        self.assertTrue(any(entry.get("event") == "upstream_network_error" for entry in entries))

if __name__ == "__main__":
    unittest.main()
