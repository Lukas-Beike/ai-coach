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
from datetime import date, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from unittest.mock import Mock, patch

from backend.coach import streams as coach_streams
import test_coach_dialogue as dialogue
from backend.http_api import server as http_server_module
from backend.providers import calendar as calendar_provider
from backend.providers import intervals_client as intervals_client_module
from backend.providers import weather as weather_provider
from backend.planning import competitions as planning_competitions
from backend.planning import context as planning_context
from backend.runtime import maintenance as runtime_maintenance
from backend.sync import garmin as garmin_sync
from backend.weather import cache as weather_cache

server = dialogue.server


class AuditRemediationTests(unittest.TestCase):
    setUp = dialogue.CoachDialogueTests.setUp
    request = dialogue.CoachDialogueTests.request
    call = dialogue.CoachDialogueTests.call
    turn = dialogue.CoachDialogueTests.turn

    def competition(self):
        item = server.competition_service().save({"name": "Synthetic race", "event_date": "2026-10-01", "sport": "Cycling"})["competition"]
        external = planning_competitions.competition_external_id(item["id"])
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute("UPDATE competitions SET intervals_event_id='123', external_id=?, sync_dirty=0, sync_state='synced' WHERE id=?", (external, item["id"]))
        remote = {"id": 123, "external_id": external, "name": "Synthetic race", "start_date_local": "2026-10-01T08:00:00", "category": "RACE_B", "type": "Ride"}
        return item, remote

    def test_competition_fetch_preserves_a_concurrent_local_edit(self):
        item, remote = self.competition()
        def fetch(*args):
            server.competition_service().save({"competition_id": item["id"], "name": "New local name"})
            return [remote]
        client = Mock()
        client.fetch_competition_events.side_effect = fetch
        with patch.object(intervals_client_module, "IntervalsClient", return_value=client):
            server.competition_sync_service().sync()
        current = server.competition_service().list()[0]
        self.assertEqual(current["name"], "New local name")
        self.assertEqual(current["sync_dirty"], 1)

    def test_tombstone_suppresses_import_before_and_after_remote_delete(self):
        item, remote = self.competition()
        server.competition_service().delete(item["id"])
        client = Mock()
        client.fetch_competition_events.return_value = [remote]
        with patch.object(intervals_client_module, "IntervalsClient", return_value=client):
            server.competition_sync_service().sync()
            self.assertEqual(server.competition_service().list(), [])
            server.competition_sync_service().sync(push_local=True)
        self.assertEqual(server.competition_service().list(), [])
        client.bulk_delete_events.assert_called_once()

    def test_delete_only_acknowledges_captured_tombstones(self):
        item, remote = self.competition()
        server.competition_service().delete(item["id"])
        client = Mock()
        client.fetch_competition_events.return_value = [remote]
        def delete(_):
            with server.DB_LOCK, server.database_manager().unit_of_work() as db:
                db.execute("INSERT INTO competition_sync_tombstones VALUES ('later', '456', 'later-external', ?)", (server.utc_now(),))
        client.bulk_delete_events.side_effect = delete
        with patch.object(intervals_client_module, "IntervalsClient", return_value=client):
            server.competition_sync_service().sync(push_local=True)
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            self.assertEqual([row["id"] for row in db.execute("SELECT id FROM competition_sync_tombstones")], ["later"])

    def test_weather_fetch_participates_in_maintenance_and_rechecks_location(self):
        server.profile_service().save({"weather_location": "Synthetic city"})
        def fetch(query):
            self.assertGreater(runtime_maintenance.MAINTENANCE_GATE.state()["running_operations"], 0)
            server.profile_service().save({"weather_location": ""})
            return {"query": query, "forecast": {}, "fetched_at": server.utc_now()}
        with patch.object(weather_provider.WeatherClient, "fetch", side_effect=fetch):
            self.assertEqual(server.weather_service().state()["state"], "not_configured")
        self.assertFalse(server.key_value_service().get(weather_cache.CACHE_KEY))
        self.assertFalse(server.key_value_service().get(weather_cache.HISTORY_KEY))

    def test_privacy_delete_drains_a_direct_weather_read(self):
        server.profile_service().save({"weather_location": "Synthetic city"})
        entered, release, deleted = threading.Event(), threading.Event(), threading.Event()
        failures = []
        def fetch(query):
            entered.set()
            if not release.wait(5):
                raise AssertionError("Synthetic weather barrier timed out")
            return {"query": query, "forecast": {}, "fetched_at": server.utc_now()}
        def read():
            try:
                server.public_weather_state_service().state()
            except Exception as error:
                failures.append(type(error).__name__)
        def erase():
            try:
                server.privacy_delete_service().delete("LOKALE DATEN LÖSCHEN")
                deleted.set()
            except Exception as error:
                failures.append(type(error).__name__)
        with patch.object(weather_provider.WeatherClient, "fetch", side_effect=fetch):
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
        self.assertFalse(server.key_value_service().get(weather_cache.CACHE_KEY))
        self.assertFalse(server.key_value_service().get(weather_cache.HISTORY_KEY))

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
        server.profile_service().save({"weather_location": "Synthetic city"})
        server.key_value_service().set(weather_cache.CACHE_KEY, json.dumps({"query": "Synthetic city", "forecast": {}, "fetched_at": "2020-01-01T00:00:00+00:00"}))
        self.assertEqual(server.weather_service().state(refresh=False)["state"], "stale")
        with patch.object(
            server.weather_service(),
            "state",
            return_value={"stale": True, "days": [{}], "error": "Synthetic failure"},
        ):
            server.weather_sync_service().sync()
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            self.assertEqual(db.execute("SELECT status FROM provider_refresh_history ORDER BY started_at DESC LIMIT 1").fetchone()["status"], "error")

    def test_garmin_daily_schedule_is_independent_of_intervals(self):
        with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="", calendar_ical_url="")), patch.object(garmin_sync.GarminFixtureLoader, "path", return_value=Path("synthetic")), patch.object(server, "daily_sync_marker_service") as marker_service:
            marker_service.return_value.is_due.return_value = True
            server.daily_sync_scheduler().schedule()
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            rows = db.execute("SELECT provider, payload FROM sync_jobs").fetchall()
        self.assertEqual([row["provider"] for row in rows], ["garmin"])
        self.assertEqual(json.loads(rows[0]["payload"])["days"], 2)

    def test_ongoing_calendar_event_and_nested_alarm(self):
        feed = b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:synthetic\r\nDTSTART;VALUE=DATE:20260906\r\nDTEND;VALUE=DATE:20260909\r\nSUMMARY:Trip\r\nDESCRIPTION:[SHORT_ONLY]\r\nBEGIN:VALARM\r\nACTION:DISPLAY\r\nDESCRIPTION:Reminder\r\nTRIGGER:-PT15M\r\nEND:VALARM\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        events = calendar_provider.parse_ical_calendar(
            feed,
            local_zone=timezone.utc,
            today=date(2026, 9, 7),
            window_start=date(2026, 9, 7),
            window_end=date(2026, 9, 10),
        )
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0]["short_only"])
        self.assertEqual(
            planning_context.external_calendar_event_dates(
                events[0], today=date(2026, 9, 7), window_days=30
            ),
            ["2026-09-06", "2026-09-07", "2026-09-08"],
        )
        self.assertEqual(
            calendar_provider.parse_ical_calendar(
                feed,
                local_zone=timezone.utc,
                today=date(2026, 9, 9),
                window_start=date(2026, 9, 9),
                window_end=date(2026, 9, 10),
            ),
            [],
        )

    def test_privacy_export_has_every_checkin_and_library_record(self):
        for offset in range(20):
            server.checkin_service().save(
                {
                    "checkin_date": (
                        date(2026, 9, 7) - timedelta(days=offset)
                    ).isoformat(),
                    "notes": "Synthetic",
                }
            )
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.executemany("INSERT INTO workout_library(id,local_id,payload,updated_at) VALUES (?,?,?,?)", [(str(i), str(i), json.dumps({"id": str(i), "name": "Synthetic"}), server.utc_now()) for i in range(1001)])
        temporary = server.privacy_archive_export_service().create_file()
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
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.executemany("INSERT INTO workout_library(id,local_id,payload,updated_at) VALUES (?,?,?,?)",
                           [(item["id"], item["id"], json.dumps(item), server.utc_now()) for item in records])
        from support import create_test_session
        token = create_test_session(server)
        # This temporary SQLite fixture exercises pagination and real session
        # authentication; secure startup has separate SQLCipher integration tests.
        startup = patch.object(server.app_config, "security_configuration_error", return_value=None)
        startup.start()
        self.addCleanup(startup.stop)
        httpd = http_server_module.CoachHTTPServer(("127.0.0.1", 0), server.request_handler_class())
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
            latest = server.adaptive_replan_preview_service().latest_preview()
            return self.call("apply_adaptive_replan", {"adjustment_id": latest["id"]}, scope=["adaptive_replan:" + latest["id"]])
        first, _ = self.turn("Show a preview, do not apply it.", [preview, apply, {"output_text": "Preview ready."}])
        self.assertEqual(first["command_receipts"][1]["result"]["reason"], "adaptive_approval_required")
        with patch.object(server.IllnessPauseSyncService, "apply", return_value={"status": "applied"}) as mutation:
            second, _ = self.turn("Apply that preview.", [apply, {"output_text": "Applied."}])
        mutation.assert_called_once()
        self.assertEqual(second["status"], "completed")

    def test_incomplete_provider_answer_is_partial_and_keeps_pending_request(self):
        result, _ = self.turn("Explain the week", [{"status": "incomplete", "incomplete_details": {"reason": "max_output_tokens"}, "output_text": "Monday starts"}])
        self.assertEqual(result["status"], "partial")
        self.assertIn("nicht abgeschlossen", result["message"]["content"])
        self.assertIsNotNone(json.loads(server.key_value_service().get("coach_pending_request")))

    def test_completed_async_job_refreshes_model_context(self):
        job = server.sync_job_queue_service().enqueue(
            "garmin", "refresh", {"days": 1}
        )
        server.sync_job_outcome_service().update(job["id"], "completed")
        steps = iter([lambda _: self.call("get_sync_job", {"job_id": job["id"]}), {"output_text": "Fresh data read."}])
        def response(payload, **kwargs):
            step = next(steps)
            return step(payload) if callable(step) else step
        with patch.object(server, "coach_conversation_provision_service", return_value=Mock(ensure=Mock(return_value="synthetic"))), patch("backend.coach.context.CoachTrainingContextService.build", side_effect=["Old Garmin data", "Fresh Garmin data"]) as context, patch.object(server, "coach_response_transport") as transport_factory:
            transport_factory.return_value.request.side_effect = response
            result = server.coach_chat_turn_service().run("Read refreshed data", client_turn_id="refresh-context", session_csrf_hash="synthetic")
        self.assertEqual(result["status"], "completed")
        self.assertEqual(context.call_count, 2)
        self.assertTrue(transport_factory.return_value.request.call_args.args[0]["instructions"].startswith("Fresh Garmin data"))

    def test_restart_job_observes_cancel_during_session_restore(self):
        server.coach_job_submission_service().enqueue("Synthetic request", "cancel-race", "synthetic-session", operation_id="cancel-operation")
        job = server.coach_job_store().claim()
        coach_streams.CHAT_STREAM_REGISTRY.clear_state()  # Process restart loses in-memory events.
        def restore(_):
            self.assertEqual(server.coach_cancellation_service().cancel("synthetic-session", "cancel-operation")["status"], "cancelling")
            self.assertIsNone(coach_streams.CHAT_STREAM_REGISTRY.get_background_event("cancel-operation"))
            with server.database_manager().unit_of_work() as db:
                receipt = db.execute(
                    "SELECT receipt FROM coach_commands WHERE client_turn_id='cancel-race'"
                ).fetchone()
            self.assertTrue(json.loads(receipt["receipt"])["cancel_requested"])
            return "synthetic-session"
        def coach(*args, **kwargs):
            self.assertTrue(kwargs["cancel_event"].is_set())
            return {"status": "cancelled"}
        with patch.object(server.session_auth_service(), "restore_coach_session_csrf_hash", side_effect=restore), patch("backend.coach.chat_turn.CoachChatTurnService.run", side_effect=coach) as execute:
            server.coach_background_job_runner().run(job)
        execute.assert_called_once()

    @unittest.skipUnless(server.SQLCIPHER_AVAILABLE, "SQLCipher runtime required")
    def test_restore_makes_interrupted_sync_job_claimable(self):
        with tempfile.TemporaryDirectory(prefix="audit-encrypted-") as directory:
            root = Path(directory)
            with patch.object(server, "CONFIG", replace(server.CONFIG, app_password="synthetic-encrypted-key")), patch.object(server, "DATA_DIR", root), patch.object(server, "DB_PATH", root / "test.db"), patch.object(server, "LOG_PATH", root / "test.log"):
                try:
                    server.initialise_database()
                    job = server.sync_job_queue_service().enqueue(
                        "intervals", "refresh", {"days": 1}
                    )
                    server.sync_job_store().claim()
                    backup = server.database_backup_service().read_bytes()
                    server.sync_job_outcome_service().update(job["id"], "completed")
                    self.assertTrue(server.database_restore_service().restore(backup)["restored"])
                    self.assertEqual(
                        server.sync_job_queue_service().state(job["id"])["status"],
                        "queued",
                    )
                    self.assertEqual(server.sync_job_store().claim()["id"], job["id"])
                finally:
                    server.database_manager().close()

    def test_chat_reset_changes_history_generation(self):
        before = server.chat_history_page_service().page()["generation"]
        server.coach_conversation_reset_service().reset()
        self.assertNotEqual(
            server.chat_history_page_service().page()["generation"], before
        )
