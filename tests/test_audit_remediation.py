"""Regression cases from the full audit; providers and athlete data are synthetic."""
import json
import http.client
import threading
import tempfile
import subprocess
import sys
import unittest
import zipfile
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import Mock, patch

import test_coach_dialogue as dialogue

server = dialogue.server


class AuditRemediationTests(unittest.TestCase):
    setUp = dialogue.CoachDialogueTests.setUp
    request = dialogue.CoachDialogueTests.request
    call = dialogue.CoachDialogueTests.call
    turn = dialogue.CoachDialogueTests.turn

    def competition(self):
        item = server.save_coach_competition({"name": "Synthetic race", "event_date": "2026-10-01", "sport": "Cycling"})["competition"]
        external = server.competition_external_id(item["id"])
        with server.DB_LOCK, server.database() as db:
            db.execute("UPDATE competitions SET intervals_event_id='123', external_id=?, sync_dirty=0, sync_state='synced' WHERE id=?", (external, item["id"]))
        remote = {"id": 123, "external_id": external, "name": "Synthetic race", "start_date_local": "2026-10-01T08:00:00", "category": "RACE_B", "type": "Ride"}
        return item, remote

    def test_competition_fetch_preserves_a_concurrent_local_edit(self):
        item, remote = self.competition()
        def fetch(*args):
            server.save_coach_competition({"competition_id": item["id"], "name": "New local name"})
            return [remote]
        client = Mock()
        client.fetch_competition_events.side_effect = fetch
        with patch.object(server, "IntervalsClient", return_value=client):
            server.sync_competitions()
        current = server.list_competitions()[0]
        self.assertEqual(current["name"], "New local name")
        self.assertEqual(current["sync_dirty"], 1)

    def test_tombstone_suppresses_import_before_and_after_remote_delete(self):
        item, remote = self.competition()
        server.delete_coach_competition(item["id"])
        client = Mock()
        client.fetch_competition_events.return_value = [remote]
        with patch.object(server, "IntervalsClient", return_value=client):
            server.sync_competitions()
            self.assertEqual(server.list_competitions(), [])
            server.sync_competitions(push_local=True)
        self.assertEqual(server.list_competitions(), [])
        client.bulk_delete_events.assert_called_once()

    def test_delete_only_acknowledges_captured_tombstones(self):
        item, remote = self.competition()
        server.delete_coach_competition(item["id"])
        client = Mock()
        client.fetch_competition_events.return_value = [remote]
        def delete(_):
            with server.DB_LOCK, server.database() as db:
                db.execute("INSERT INTO competition_sync_tombstones VALUES ('later', '456', 'later-external', ?)", (server.utc_now(),))
        client.bulk_delete_events.side_effect = delete
        with patch.object(server, "IntervalsClient", return_value=client):
            server.sync_competitions(push_local=True)
        with server.DB_LOCK, server.database() as db:
            self.assertEqual([row["id"] for row in db.execute("SELECT id FROM competition_sync_tombstones")], ["later"])

    def test_weather_fetch_participates_in_maintenance_and_rechecks_location(self):
        server.save_profile({"weather_location": "Synthetic city"})
        def fetch(query):
            self.assertGreater(server.MAINTENANCE_GATE.state()["running_operations"], 0)
            server.save_profile({"weather_location": ""})
            return {"query": query, "forecast": {}, "fetched_at": server.utc_now()}
        with patch.object(server, "_fetch_weather_forecast", side_effect=fetch):
            self.assertEqual(server.weather_state()["state"], "not_configured")
        self.assertFalse(server.get_kv(server.WEATHER_CACHE_KEY))
        self.assertFalse(server.get_kv(server.WEATHER_HISTORY_KEY))

    def test_privacy_delete_drains_a_direct_weather_read(self):
        server.save_profile({"weather_location": "Synthetic city"})
        entered, release, deleted = threading.Event(), threading.Event(), threading.Event()
        failures = []
        def fetch(query):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Synthetic weather barrier timed out")
            return {"query": query, "forecast": {}, "fetched_at": server.utc_now()}
        def read():
            try:
                server.public_weather_state()
            except Exception as error:
                failures.append(type(error).__name__)
        def erase():
            try:
                server.delete_local_data()
                deleted.set()
            except Exception as error:
                failures.append(type(error).__name__)
        with patch.object(server, "_fetch_weather_forecast", side_effect=fetch):
            reader = threading.Thread(target=read)
            reader.start()
            try:
                self.assertTrue(entered.wait(5))
                deletion = threading.Thread(target=erase)
                deletion.start()
                self.assertFalse(deleted.wait(.05))
            finally:
                release.set()
                reader.join(5)
            deletion.join(5)
        self.assertEqual(failures, [])
        self.assertTrue(deleted.is_set())
        self.assertFalse(server.get_kv(server.WEATHER_CACHE_KEY))
        self.assertFalse(server.get_kv(server.WEATHER_HISTORY_KEY))

    def test_test_bootstrap_never_reads_dotenv_or_inherits_provider_credentials(self):
        script = """
import os, sys
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, sys.argv[1])
os.environ.update(GEMINI_API_KEY='synthetic-inherited', AI_PROVIDER='gemini')
read = Path.read_text
def deny(path, *args, **kwargs):
    if path.name == '.env':
        raise AssertionError('Environment file access forbidden')
    return read(path, *args, **kwargs)
with patch.object(Path, 'read_text', deny):
    import test_server
assert test_server.server.CONFIG.gemini_api_key == ''
assert test_server.server.CONFIG.ai_provider == 'openai'
"""
        result = subprocess.run([sys.executable, "-c", script, str(Path(__file__).parent)], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_cached_weather_remains_stale_without_refresh(self):
        server.save_profile({"weather_location": "Synthetic city"})
        server.set_kv(server.WEATHER_CACHE_KEY, json.dumps({"query": "Synthetic city", "forecast": {}, "fetched_at": "2020-01-01T00:00:00+00:00"}))
        self.assertEqual(server.weather_state(refresh=False)["state"], "stale")
        with patch.object(server, "weather_state", return_value={"stale": True, "days": [{}], "error": "Synthetic failure"}):
            server.sync_weather()
        with server.DB_LOCK, server.database() as db:
            self.assertEqual(db.execute("SELECT status FROM provider_refresh_history ORDER BY started_at DESC LIMIT 1").fetchone()["status"], "error")

    def test_garmin_daily_schedule_is_independent_of_intervals(self):
        with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="", calendar_ical_url="")), patch.object(server, "garmin_fixture_path", return_value="synthetic"), patch.object(server, "daily_sync_due", return_value=True):
            server.schedule_daily_sync_jobs()
        with server.DB_LOCK, server.database() as db:
            self.assertEqual([row["provider"] for row in db.execute("SELECT provider FROM sync_jobs")], ["garmin"])

    def test_ongoing_calendar_event_and_nested_alarm(self):
        feed = b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:synthetic\r\nDTSTART;VALUE=DATE:20260906\r\nDTEND;VALUE=DATE:20260909\r\nSUMMARY:Trip\r\nDESCRIPTION:[SHORT_ONLY]\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:Reminder\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        events = server.parse_ical_calendar(feed, window_start=date(2026, 9, 7), window_end=date(2026, 9, 10))
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["short_only"])
        self.assertEqual(server.external_calendar_event_dates(events[0]), ["2026-09-06", "2026-09-07", "2026-09-08"])
        self.assertEqual(server.parse_ical_calendar(feed, window_start=date(2026, 9, 9), window_end=date(2026, 9, 10)), [])

    def test_privacy_export_has_every_checkin_and_library_record(self):
        for offset in range(20):
            server.save_checkin({"checkin_date": (date(2026, 9, 7) - timedelta(days=offset)).isoformat(), "notes": "Synthetic"})
        with server.DB_LOCK, server.database() as db:
            db.executemany("INSERT INTO workout_library(id,local_id,payload,updated_at) VALUES (?,?,?,?)", [(str(i), str(i), json.dumps({"id": str(i), "name": "Synthetic"}), server.utc_now()) for i in range(1001)])
        temporary = server._privacy_export_file()
        try:
            with zipfile.ZipFile(temporary) as archive:
                self.assertEqual(len(archive.read("athlete_checkins.jsonl").splitlines()), 20)
                self.assertEqual(len(archive.read("workout_library.jsonl").splitlines()), 1001)
                self.assertEqual(json.loads(archive.read("manifest.json"))["status"], "complete")
        finally:
            temporary.unlink()

    def test_library_http_pagination_reaches_every_active_template_beyond_1000(self):
        records = [{"id": f"template-{i:04}", "name": f"Synthetic {i:04}", "type": "Ride"} for i in range(1001)]
        records += [{"id": "archived", "name": "Archived", "archived": True}, {"id": "dated", "name": "Dated", "date": "2026-09-09"}]
        with server.DB_LOCK, server.database() as db:
            db.executemany("INSERT INTO workout_library(id,local_id,payload,updated_at) VALUES (?,?,?,?)",
                           [(item["id"], item["id"], json.dumps(item), server.utc_now()) for item in records])
        token = dialogue.fixtures.CoachTests.create_test_session(self)
        # This temporary SQLite fixture exercises pagination and real session
        # authentication; secure startup has separate SQLCipher integration tests.
        startup = patch.object(server, "security_configuration_error", return_value=None)
        startup.start()
        self.addCleanup(startup.stop)
        httpd = server.CoachHTTPServer(("127.0.0.1", 0), server.RequestHandler)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
        ids, cursor = [], None
        try:
            for _ in range(12):
                query = {"limit": 100}
                if cursor:
                    query["cursor"] = cursor
                connection.request("GET", "/api/library?" + urlencode(query), headers={"Cookie": f"ic_session={token}"})
                response = connection.getresponse()
                self.assertEqual(response.status, 200)
                page = json.loads(response.read())
                self.assertLessEqual(len(page["workouts"]), 100)
                ids.extend(item["id"] for item in page["workouts"])
                cursor = page["next_cursor"]
                if not cursor:
                    break
        finally:
            connection.close()
            httpd.shutdown()
            worker.join(5)
            httpd.server_close()
        self.assertIsNone(cursor)
        self.assertEqual(ids, [f"template-{i:04}" for i in range(1001)])

    def test_adaptive_apply_requires_a_published_preview_and_later_user_turn(self):
        def preview(_):
            return self.call("preview_adaptive_replan", scope=["adaptive_replan"])
        def apply(_):
            latest = server.latest_replan_preview()
            return self.call("apply_adaptive_replan", {"adjustment_id": latest["id"]}, scope=["adaptive_replan:" + latest["id"]])
        first, _ = self.turn("Show a preview, do not apply it.", [preview, apply, {"output_text": "Preview ready."}])
        self.assertEqual(first["command_receipts"][1]["result"]["reason"], "adaptive_approval_required")
        with patch.object(server, "apply_adaptive_replan", return_value={"status": "applied"}) as mutation:
            second, _ = self.turn("Apply that preview.", [apply, {"output_text": "Applied."}])
        mutation.assert_called_once()
        self.assertEqual(second["status"], "completed")

    def test_incomplete_provider_answer_is_partial_and_keeps_pending_request(self):
        result, _ = self.turn("Explain the week", [{"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output_text": "Monday starts"}])
        self.assertEqual(result["status"], "partial")
        self.assertIn("nicht abgeschlossen", result["message"]["content"])
        self.assertIsNotNone(json.loads(server.get_kv("coach_pending_request")))

    def test_completed_async_job_refreshes_model_context(self):
        job = server.enqueue_sync_job("garmin", "refresh", {"days": 1})
        server._sync_job_update(job["id"], "completed")
        steps = iter([lambda _: self.call("get_sync_job", {"job_id": job["id"]}), {"output_text": "Fresh data read."}])
        def response(payload, **kwargs):
            step = next(steps)
            return step(payload) if callable(step) else step
        with patch.object(server, "ensure_conversation", return_value="synthetic"), patch.object(server, "build_training_context", side_effect=["Old Garmin data", "Fresh Garmin data"]) as context, patch.object(server, "responses_request", side_effect=response) as model:
            result = server.chat_with_coach("Read refreshed data", client_turn_id="refresh-context", session_csrf_hash="synthetic")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(context.call_count, 2)
        self.assertTrue(model.call_args.args[0]["instructions"].startswith("Fresh Garmin data"))

    def test_restart_job_observes_cancel_during_session_restore(self):
        server.enqueue_background_coach_job("Synthetic request", "cancel-race", "synthetic-session", operation_id="cancel-operation")
        job = server._claim_background_coach_job()
        server.COACH_JOB_CANCEL_EVENTS.clear()  # Process restart loses in-memory events.
        def restore(_):
            self.assertEqual(server.cancel_chat_stream("synthetic-session", "cancel-operation")["status"], "cancelling")
            return "synthetic-session"
        def coach(*args, **kwargs):
            self.assertTrue(kwargs["cancel_event"].is_set())
            return {"status": "cancelled"}
        with patch.object(server, "_restore_coach_session_csrf_hash", side_effect=restore), patch.object(server, "chat_with_coach", side_effect=coach) as execute:
            server._run_background_coach_job(job)
        execute.assert_called_once()

    @unittest.skipUnless(server.SQLCIPHER_AVAILABLE, "SQLCipher runtime required")
    def test_restore_makes_interrupted_sync_job_claimable(self):
        with tempfile.TemporaryDirectory(prefix="audit-encrypted-") as directory:
            root = Path(directory)
            with patch.object(server, "CONFIG", replace(server.CONFIG, app_password="synthetic-encrypted-key")), patch.object(server, "DATA_DIR", root), patch.object(server, "DB_PATH", root / "test.db"), patch.object(server, "LOG_PATH", root / "test.log"):
                try:
                    server.initialise_database()
                    job = server.enqueue_sync_job("intervals", "refresh", {"days": 1})
                    server._claim_sync_job()
                    backup = server.database_backup_bytes()
                    server._sync_job_update(job["id"], "completed")
                    self.assertTrue(server.restore_database_backup(backup)["restored"])
                    self.assertEqual(server.sync_job_state(job["id"])["status"], "queued")
                    self.assertEqual(server._claim_sync_job()["id"], job["id"])
                finally:
                    server.database_manager().close()

    def test_failed_morning_answer_is_not_marked_ready(self):
        server.MORNING_CHECKIN_LOCK.acquire()
        with patch.object(server, "sync_intervals", return_value={"status": "ok"}), patch.object(server, "chat_with_coach", return_value={"status": "failed"}), patch.object(server, "garmin_fixture_path", return_value=None):
            server.run_morning_checkin("2026-09-07")
        self.assertEqual(server.get_kv("morning_checkin_status"), "error")
        self.assertNotEqual(server.get_kv("morning_checkin_date"), "2026-09-07")

    def test_chat_reset_changes_history_generation(self):
        before = server.paged_chat_history()["generation"]
        server.reset_coach_chat()
        self.assertNotEqual(server.paged_chat_history()["generation"], before)
