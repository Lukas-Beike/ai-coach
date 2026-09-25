"""Server integration tests for database."""

import http.client
import json
import os
import sqlite3
import tempfile
import threading
import time
import unittest
import zipfile
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend import privacy as privacy_module
from backend.coach import limits as coach_limits
from backend.db.schema import configure_cipher, CURRENT_DATABASE_INDEXES, CURRENT_DATABASE_SCHEMA, database_index_names, database_schema_is_current, database_table_names
from backend.http_api import server as http_server_module
from backend.http_api.chat_page import ChatHistoryPageService
from backend.http_api.public_state import PublicStateService
from backend.http_api.readiness import ReadinessService
from backend.http_api.response_transport import STREAM_CHUNK_BYTES
from backend.providers import gemini as gemini_provider
from backend.runtime import maintenance as runtime_maintenance
from backend.weather import cache as weather_cache
from server_test_support import create_test_session, server, ServerTestCase


class ServerDatabaseTests(ServerTestCase):

    def test_database_uses_exact_current_schema(self):
        server.initialise_database()
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            self.assertEqual(db.execute("PRAGMA foreign_keys").fetchone()["foreign_keys"], 1)
            self.assertTrue(database_schema_is_current(db))
            self.assertEqual(database_table_names(db), set(CURRENT_DATABASE_SCHEMA))
            self.assertEqual(database_index_names(db), CURRENT_DATABASE_INDEXES)

    def test_provider_state_service_is_recreated_with_database_manager(self):
        first = server.provider_state_service()
        first_http_client = server.provider_http_client()
        first_refresh_tracker = server.provider_refresh_tracker()
        first_weather_service = server.weather_service()
        server.database_manager().close()
        server.DATABASE_MANAGER = None
        server.DATABASE_MANAGER_SIGNATURE = None

        second = server.provider_state_service()
        second_http_client = server.provider_http_client()
        second_refresh_tracker = server.provider_refresh_tracker()
        second_weather_service = server.weather_service()

        self.assertIsNot(second, first)
        self.assertIsNot(second_http_client, first_http_client)
        self.assertIsNot(second_refresh_tracker, first_refresh_tracker)
        self.assertIsNot(second_weather_service, first_weather_service)
        self.assertIs(second_http_client.provider_state, second)
        second.record_status(
            "openai", state="ok", reason="ok", message="OpenAI ist verfügbar.", http_status=200
        )
        self.assertEqual(second.summary("openai")["status"]["state"], "ok")

    def test_initialise_database_rejects_a_non_current_schema_without_modifying_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "partial.db"
            connection = sqlite3.connect(database_path)
            try:
                connection.execute("CREATE TABLE unexpected_records (id TEXT PRIMARY KEY)")
                connection.commit()
            finally:
                connection.close()

            config = replace(server.CONFIG, app_password="")
            try:
                with patch.object(server, "CONFIG", config), patch.object(server, "DATA_DIR", Path(temporary)), patch.object(
                    server, "DB_PATH", database_path
                ):
                    with self.assertRaises(RuntimeError):
                        server.initialise_database()
                    server.database_manager().close()
            finally:
                server.DATABASE_MANAGER = None
                server.DATABASE_MANAGER_SIGNATURE = None

            connection = sqlite3.connect(database_path)
            try:
                tables = {
                    row[0]
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                    if not str(row[0]).startswith("sqlite_")
                }
            finally:
                connection.close()
            self.assertEqual(tables, {"unexpected_records"})

    def test_database_initialization_does_not_recover_jobs(self):
        with patch.object(server.SyncJobQueueService, "resume_interrupted") as sync_recovery, patch(
            "backend.coach.job_store.CoachJobStore.resume_interrupted"
        ) as coach_recovery:
            server.initialise_database()
        sync_recovery.assert_not_called()
        coach_recovery.assert_not_called()

    def test_key_value_repository_preserves_get_and_upsert_contract(self):
        repository = server.KeyValueRepository(lambda: "2026-09-01T00:00:00+00:00")
        with server.database_manager().unit_of_work() as db:
            self.assertIsNone(repository.get(db, "repository-test"))
            repository.set(db, "repository-test", "first")
            self.assertEqual(repository.get(db, "repository-test"), "first")
            repository.set(db, "repository-test", "second")
            self.assertEqual(repository.get(db, "repository-test"), "second")

    def test_chat_repository_preserves_trimmed_insert_and_order_contract(self):
        repository = server.ChatRepository(lambda: "2026-09-01T00:00:00+00:00")
        with server.database_manager().unit_of_work() as db:
            first = repository.add(db, "user", "  first  ")
            second = repository.add(db, "assistant", "second")
            self.assertEqual(first["content"], "first")
            self.assertEqual([row["id"] for row in repository.list(db)], [first["id"], second["id"]])

    def test_checkin_repository_preserves_upsert_and_date_order_contract(self):
        repository = server.CheckinRepository(lambda: "2026-09-01T00:00:00+00:00")
        older = {
            "checkin_date": "2026-08-30", "soreness": 2, "stress": 3, "motivation": 4, "session_rpe": 5,
            "day_form": "good", "illness": "", "pain": "", "available_minutes": 60,
            "availability_notes": "", "notes": "older",
        }
        newer = dict(older, checkin_date="2026-08-31", notes="newer")
        with server.database_manager().unit_of_work() as db:
            repository.upsert(db, older)
            repository.upsert(db, newer)
            repository.upsert(db, dict(newer, notes="updated"))
            rows = repository.list(db)
        self.assertEqual([row["checkin_date"] for row in rows], ["2026-08-31", "2026-08-30"])
        self.assertEqual(rows[0]["notes"], "updated")
        self.assertEqual(rows[0]["created_at"], "2026-09-01T00:00:00+00:00")

    def test_profile_repository_preserves_serialized_profile_contract(self):
        repository = server.ProfileRepository(server.KeyValueRepository(lambda: "2026-09-01T00:00:00+00:00"))
        payload = json.dumps({"name": "Ada", "timezone": "Europe/Berlin"}, ensure_ascii=False)
        with server.database_manager().unit_of_work() as db:
            self.assertIsInstance(repository.get(db), str)
            repository.set(db, payload)
            self.assertEqual(repository.get(db), payload)

    def test_competition_repository_preserves_order_and_full_row_lookup_contract(self):
        saved = server.competition_service().save({
            "name": "Repository race",
            "event_date": "2026-09-20",
            "sport": "Run",
            "priority": "A",
            "distance": "10 km",
        })
        repository = server.CompetitionRepository()
        with server.database_manager().unit_of_work() as db:
            rows = repository.list(db)
            row = repository.get(db, saved["competition"]["id"])
        self.assertEqual(rows[0]["name"], "Repository race")
        self.assertEqual(row["event_date"], "2026-09-20")
        self.assertEqual(row["sync_state"], "local")

    def test_training_plan_repository_preserves_create_and_newest_first_contract(self):
        repository = server.TrainingPlanRepository()
        with server.database_manager().unit_of_work() as db:
            repository.create(db, "plan-old", "Old", "Base", "2026-09-01", "2026-09-07", "draft", "2026-09-01T00:00:00+00:00")
            repository.create(db, "plan-new", "New", "Build", "2026-09-08", "2026-09-14", "planned", "2026-09-02T00:00:00+00:00")
            repository.update(db, "plan-old", "Renamed", "Updated", "2026-09-02", "2026-09-09", "active", "2026-09-02T01:00:00+00:00")
            rows = repository.list(db)
            updated = repository.get(db, "plan-old")
        self.assertEqual([row["id"] for row in rows], ["plan-new", "plan-old"])
        self.assertEqual(rows[0]["status"], "planned")
        self.assertEqual(updated["name"], "Renamed")
        with server.database_manager().unit_of_work() as db:
            repository.delete(db, "plan-old")
            self.assertIsNone(repository.get(db, "plan-old"))

    def test_plan_adjustment_repository_preserves_preview_lookup_and_status_contract(self):
        repository = server.PlanAdjustmentRepository()
        payload = json.dumps({"changes": [], "message": "No changes"}, ensure_ascii=False)
        with server.database_manager().unit_of_work() as db:
            repository.create_preview(db, "adjustment-test", payload, "2026-09-01T00:00:00+00:00")
            self.assertEqual(repository.latest(db)["id"], "adjustment-test")
            self.assertEqual(repository.get(db, "adjustment-test")["status"], "preview")
            repository.mark_applied(db, "adjustment-test", payload, "applied", "2026-09-01T01:00:00+00:00")
            self.assertEqual(repository.get(db, "adjustment-test")["status"], "applied")

    def test_activity_feedback_repository_preserves_upsert_delete_and_order_contract(self):
        repository = server.ActivityFeedbackRepository(lambda: "2026-09-01T00:00:00+00:00")
        older = {"activity_id": "activity-old", "activity_name": "Run", "activity_date": "2026-08-30", "notes": "older"}
        newer = {"activity_id": "activity-new", "activity_name": "Ride", "activity_date": "2026-08-31", "notes": "newer"}
        with server.database_manager().unit_of_work() as db:
            repository.upsert(db, older)
            repository.upsert(db, newer)
            repository.upsert(db, dict(newer, notes="updated"))
            rows = repository.list(db)
            self.assertEqual(next(row for row in rows if row["activity_id"] == "activity-new")["notes"], "updated")
            repository.delete(db, "activity-new")
            self.assertEqual([row["activity_id"] for row in repository.list(db)], ["activity-old"])

    def test_snapshot_repository_preserves_latest_payload_and_retention_contract(self):
        repository = server.SnapshotRepository()
        with server.database_manager().unit_of_work() as db:
            for index in range(13):
                repository.save(db, {"synced_at": f"2026-09-{index + 1:02d}", "index": index}, f"2026-09-{index + 1:02d}")
            payload = repository.latest_payload(db)
            count = db.execute("SELECT COUNT(*) AS count FROM snapshots").fetchone()["count"]
        self.assertEqual(json.loads(payload)["index"], 12)
        self.assertEqual(count, 12)

    def test_local_public_state_reuses_request_database_connections(self):
        backend = server.sqlite_backend if server.CONFIG.app_password else server.sqlite3
        real_connect = backend.connect
        with patch.object(backend, "connect", wraps=real_connect) as connect:
            server.public_state_service().read(local_only=True)
        self.assertEqual(connect.call_count, 2)

    def test_public_state_resolves_database_manager_under_database_lock(self):
        database_lock = threading.RLock()
        manager_factory = server.database_manager
        calls = []

        def resolve_manager():
            self.assertTrue(database_lock._is_owned())
            calls.append(True)
            return manager_factory()

        with patch.object(server, "DB_LOCK", database_lock), patch.object(
            server, "database_manager", side_effect=resolve_manager
        ):
            server.public_state_service()
        self.assertTrue(calls)

    def test_public_state_resolves_active_manager_after_weather_restore(self):
        class Manager:
            def __init__(self):
                self.closed = False
                self.unit_of_work_calls = 0

            @contextmanager
            def unit_of_work(self):
                self.unit_of_work_calls += 1
                if self.closed:
                    raise RuntimeError("database manager is closed")
                yield object()

        old_manager = Manager()
        new_manager = Manager()
        active_manager = [old_manager]
        database_lock = threading.RLock()

        def manager_factory():
            self.assertTrue(database_lock._is_owned())
            return active_manager[0]

        def owner(**methods):
            result = Mock()
            for name, value in methods.items():
                getattr(result, name).return_value = value
            return result

        settings = Mock()
        settings.selected_ai_provider.return_value = ""
        settings.available_ai_providers.return_value = []
        settings.selected_model.return_value = ""
        settings.available_model_options.return_value = []
        settings.selected_thinking_level.return_value = ""
        settings.available_thinking_level_options.return_value = []
        settings.calendar_display_settings.return_value = {}
        weather_prelude = Mock()

        def restore_during_weather(*_args):
            old_manager.closed = True
            active_manager[0] = new_manager
            return {"configured": False}

        weather_prelude.project.side_effect = restore_during_weather
        dependencies = SimpleNamespace(
            local_prelude=owner(read=SimpleNamespace(
                snapshot={}, activities=[], local_planned=[], canonical_planned=[],
                calendar_window={}, weather={},
            )),
            weather_prelude=weather_prelude,
            calendar_projection=owner(read=SimpleNamespace(
                checkins=[], competitions=[], external_calendar={}, daily_context=[],
                calendar_projection={},
            )),
            database_manager=manager_factory,
            database_lock=database_lock,
            key_values=owner(get=""),
            app_name="Intervals Coach",
            app_version="test",
            config=SimpleNamespace(
                garmin_tokenstore=str(Path("missing-garmin-tokenstore")),
                intervals_api_key="", openai_api_key="", gemini_api_key="",
                calendar_ical_url="",
            ),
            settings=settings,
            coach_messages=owner(list=[]),
            training_plans=owner(list=[]),
            workout_library=owner(list=[]),
            profile=owner(get={}),
            public_feedback=owner(feedback_state={
                "checkins": [], "local_feedback": [], "activity_feedback": [],
            }),
            public_performance=owner(from_snapshot={"performance": {}, "garmin": {}}),
            sync_state=owner(sync_period=30),
            provider_freshness=owner(current={}),
            garmin_sync_state=owner(core_error_entries=[]),
            sync_public_state=owner(browser_state={}),
            intervals_sync_lock=owner(locked=False),
            workout_library_sync_running=lambda: False,
            workout_library_sync_state=owner(summary={}),
            garmin_sync=owner(running=False),
            provider_resync=owner(state={}),
            planning_preview=owner(latest_preview={}, status={}),
            morning_checkin=owner(state={}),
            coach_quick_actions=owner(state={}),
            provider_state=owner(summary={}),
            sync_period_defaults={"intervals": 90, "garmin": 30},
            all_sync_days=3650,
            calendar_history_days=30,
            calendar_future_days=90,
            local_now=lambda: datetime(2026, 9, 23),
        )
        service = PublicStateService(dependencies)

        result = service.read(local_only=True)

        self.assertIn("configured", result)
        self.assertEqual(old_manager.unit_of_work_calls, 0)
        self.assertGreater(new_manager.unit_of_work_calls, 0)

    def test_composed_handler_resolves_current_auth_service_after_database_manager_change(self):
        handler_class = server.request_handler_class()
        handler_class.protocol_version = "HTTP/1.1"
        httpd = http_server_module.CoachHTTPServer(("127.0.0.1", 0), handler_class)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)

        def library_status(token):
            connection.request(
                "GET", "/api/library?limit=1",
                headers={"Cookie": f"ic_session={token}"},
            )
            response = connection.getresponse()
            return response.status, json.loads(response.read())

        try:
            with patch.object(server.app_config, "security_configuration_error", return_value=None):
                original_manager = server.database_manager()
                original_token = create_test_session(server)
                status, _payload = library_status(original_token)
                self.assertEqual(status, 200)
                original_auth = server.session_auth_service()
                keep_alive_socket = connection.sock
                self.assertIsNotNone(keep_alive_socket)

                with tempfile.TemporaryDirectory(prefix="session-auth-manager-switch-") as directory:
                    switched_db = Path(directory) / "switched.db"
                    with patch.object(server, "DB_PATH", switched_db):
                        switched_manager = server.database_manager()
                        try:
                            self.assertIsNot(switched_manager, original_manager)
                            server.initialise_database()
                            barrier = threading.Barrier(8)
                            auth_services = []
                            errors = []

                            def resolve_auth_service():
                                try:
                                    barrier.wait(timeout=5)
                                    auth_services.append(server.session_auth_service())
                                except Exception as error:
                                    errors.append(error)

                            resolvers = [threading.Thread(target=resolve_auth_service) for _ in range(8)]
                            for resolver in resolvers:
                                resolver.start()
                            for resolver in resolvers:
                                resolver.join(5)
                            self.assertEqual(errors, [])
                            self.assertEqual(len(auth_services), 8)
                            switched_auth = auth_services[0]
                            self.assertTrue(all(auth is switched_auth for auth in auth_services))
                            self.assertIsNot(switched_auth, original_auth)
                            switched_token = create_test_session(server)

                            status, payload = library_status(switched_token)
                            self.assertEqual(status, 200)
                            self.assertIn("workouts", payload)
                            self.assertIs(connection.sock, keep_alive_socket)
                        finally:
                            switched_manager.close()
                            server.DATABASE_MANAGER = None
                            server.DATABASE_MANAGER_SIGNATURE = None
        finally:
            connection.close()
            httpd.shutdown()
            worker.join(5)
            httpd.server_close()

    def test_privacy_export_contains_archived_and_provider_state_without_sessions_or_credentials(self):
        archived = server.workout_library_remote_reconciler().reconcile([{
            "id": "remote-template-1", "name": "Archived template", "type": "Ride",
            "description": "- 60m 60% local", "duration_minutes": 60,
        }])[0]
        server.workout_library_service().update(archived["id"], {"action": "archive"})
        server.key_value_service().set("garmin_snapshot", json.dumps({"source": "Garmin", "days": []}))
        server.key_value_service().set(weather_cache.CACHE_KEY, json.dumps({"query": "Berlin", "forecast": {}}))
        server.key_value_service().set("calendar_display", json.dumps({"past_weeks": 2, "future_weeks": 6}))
        server.key_value_service().set("openai_conversation_id", "conv-test")
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO competition_sync_tombstones(intervals_event_id, external_id, created_at) VALUES (?, ?, ?)",
                ("event-1", "external-1", server.utc_now()),
            )
            db.execute(
                "INSERT INTO plan_adjustments(id, payload, status, created_at, applied_at) VALUES (?, ?, ?, ?, ?)",
                ("adjustment-1", json.dumps({"reason": "test"}), "preview", server.utc_now(), None),
            )
        exported = server.privacy_data_export_service().export()
        self.assertTrue(any(item.get("name") == "Archived template" for item in exported["workout_library"]))
        self.assertEqual(exported["garmin_snapshot"]["source"], "Garmin")
        self.assertEqual(exported["weather_cache"]["query"], "Berlin")
        self.assertEqual(exported["application_state"]["calendar_display"]["future_weeks"], 6)
        self.assertEqual(exported["competition_sync_tombstones"][0]["external_id"], "external-1")
        self.assertEqual(exported["plan_adjustments"][0]["id"], "adjustment-1")
        self.assertNotIn("sessions", exported)
        export_text = json.dumps(exported, ensure_ascii=False)
        self.assertNotIn("test-openai-key", export_text)
        self.assertNotIn("test-intervals-key", export_text)
        self.assertNotIn("test-password-123", export_text)

    def test_privacy_json_projection_filters_runtime_keys_and_preserves_malformed_json_fallbacks(self):
        server.key_value_service().set("profile", json.dumps({"name": "Private profile"}))
        server.key_value_service().set("garmin_snapshot", "{")
        server.key_value_service().set(weather_cache.CACHE_KEY, "{")
        server.key_value_service().set("ordinary_state", "{")
        server.key_value_service().set("job_running", "true")
        server.key_value_service().set("job_status", "done")

        exported = server.privacy_data_export_service().export()

        self.assertNotIn("profile", exported["application_state"])
        self.assertNotIn("garmin_snapshot", exported["application_state"])
        self.assertNotIn(weather_cache.CACHE_KEY, exported["application_state"])
        self.assertNotIn("job_running", exported["application_state"])
        self.assertNotIn("job_status", exported["application_state"])
        self.assertEqual(exported["application_state"]["ordinary_state"], "{")
        self.assertEqual(exported["garmin_snapshot"], {})
        self.assertEqual(exported["weather_cache"], {})

    def test_privacy_json_projection_uses_composed_local_clock(self):
        fixed_local_time = datetime(2026, 1, 2, 3, 4, tzinfo=timezone.utc)
        with patch.object(server.ATHLETE_CLOCK, "now", return_value=fixed_local_time) as local_clock:
            exported = server.privacy_data_export_service().export()

        self.assertEqual(exported["planning"]["season"]["as_of"], "2026-01-02")
        self.assertGreaterEqual(local_clock.call_count, 2)

    def test_privacy_export_zip_streams_collections_and_contains_complete_manifest(self):
        server.sync_state_repository().save_snapshot({"export-test": True, "synced_at": "2026-09-01", "athlete": {}, "recent_activities": [], "recent_wellness": [], "upcoming_calendar": []})
        temporary = server.privacy_archive_export_service().create_file()
        try:
            with zipfile.ZipFile(temporary) as archive:
                names = set(archive.namelist())
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["format"], "intervals-coach-privacy-export")
                self.assertEqual(manifest["format_version"], 1)
                self.assertEqual(manifest["status"], "complete")
                self.assertIn("snapshots.jsonl", names)
                self.assertIn("profile.json", names)
                self.assertNotIn("sessions.jsonl", names)
                self.assertEqual(
                    manifest["categories"],
                    sorted(name.rsplit(".", 1)[0] for name in names if name != "manifest.json"),
                )
                self.assertEqual(
                    manifest["jsonl_files"],
                    sorted(name for name in names if name.endswith(".jsonl")),
                )
                state = json.loads(archive.read("application_state.json"))
                self.assertTrue(
                    {"profile", "garmin_snapshot", weather_cache.CACHE_KEY}.isdisjoint(state)
                )
                snapshots = [json.loads(line) for line in archive.read("snapshots.jsonl").splitlines()]
                self.assertTrue(any(item.get("export-test") for item in snapshots))
        finally:
            temporary.unlink(missing_ok=True)

        class ExportHandler:
            def __init__(self):
                self.payload = b""
                self.path = None

            def send_file_stream(self, path, _content_type, _filename, **kwargs):
                self.path = path
                self.payload = path.read_bytes()
                if kwargs.get("cleanup"):
                    path.unlink()

        handler = ExportHandler()
        server.export_stream_transport().stream_privacy_export(handler)
        self.assertTrue(handler.payload.startswith(b"PK"))
        self.assertFalse(handler.path.exists())

    def test_privacy_download_routes_require_auth_before_streaming(self):
        from backend.http_api.privacy_get import PrivacyGetRoutes

        routes = {
            "/api/privacy/export": "stream_privacy_export",
            "/api/privacy/backup": "stream_database_backup",
        }
        for path, stream_method in routes.items():
            with self.subTest(path=path):
                handler = object.__new__(server.request_handler_class())
                handler.path = path
                auth = Mock()
                transport = Mock()
                transport_factory = Mock(return_value=transport)
                route = PrivacyGetRoutes(
                    Mock(return_value=auth), transport_factory, Mock()
                )
                self.assertTrue(route.handle(handler, path))
                auth.require_auth.assert_called_once_with(handler)
                getattr(transport, stream_method).assert_called_once_with(handler)
                transport_factory.assert_called_once_with()

                denied = server.AppError(401, "unauthorized")
                auth.require_auth.side_effect = denied
                transport.reset_mock()
                transport_factory.reset_mock()
                with self.assertRaises(server.AppError) as caught:
                    route.handle(handler, path)
                self.assertIs(caught.exception, denied)
                transport_factory.assert_not_called()
                getattr(transport, stream_method).assert_not_called()

    def test_privacy_archive_export_enforces_free_space_size_timeout_and_cleanup(self):
        service = server.privacy_archive_export_service()
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            no_space_config = replace(
                service._config,
                data_dir=data_dir,
                minimum_free_bytes=10**12,
                disk_usage=lambda _path: Mock(free=0),
            )
            with patch.object(service, "_config", no_space_config), self.assertRaises(server.AppError) as no_space:
                service.create_file()
            self.assertEqual(no_space.exception.status, 507)
            self.assertEqual(list(data_dir.iterdir()), [])

            too_large_config = replace(
                service._config,
                data_dir=data_dir,
                maximum_bytes=1,
                minimum_free_bytes=1,
                disk_usage=lambda _path: Mock(free=10**12),
            )
            with patch.object(service, "_config", too_large_config), self.assertRaises(server.AppError) as too_large:
                service.create_file()
            self.assertEqual(too_large.exception.status, 413)
            self.assertEqual(list(data_dir.iterdir()), [])

            clock = Mock(side_effect=[0, 1])
            timeout_config = replace(
                service._config,
                data_dir=data_dir,
                minimum_free_bytes=1,
                time_limit_seconds=0,
                monotonic=clock,
                disk_usage=lambda _path: Mock(free=10**12),
            )
            with patch.object(service, "_config", timeout_config), self.assertRaises(server.AppError) as timeout:
                service.create_file()
            self.assertEqual(timeout.exception.status, 408)
            self.assertEqual(list(data_dir.iterdir()), [])

    def test_file_stream_uses_bounded_chunks_and_cleans_up_after_disconnect(self):
        class RecordingWriter:
            def __init__(self):
                self.writes = []

            def write(self, data):
                self.writes.append(data)
                return len(data)

        class FailingWriter:
            def write(self, _data):
                raise BrokenPipeError()

        with tempfile.TemporaryDirectory() as temp_root:
            path = Path(temp_root) / "export.zip"
            path.write_bytes(b"x" * (STREAM_CHUNK_BYTES * 2 + 1))
            handler = object.__new__(server.request_handler_class())
            handler.send_response = Mock()
            handler.send_header = Mock()
            handler.end_headers = Mock()
            writer = RecordingWriter()
            handler.wfile = writer
            handler.client_disconnect_errors = (BrokenPipeError,)
            handler.log_client_disconnect = Mock()
            handler.send_file_stream(path, "application/octet-stream", "export.zip")
            self.assertEqual(sum(len(data) for data in writer.writes), STREAM_CHUNK_BYTES * 2 + 1)
            self.assertTrue(all(len(data) <= STREAM_CHUNK_BYTES for data in writer.writes))

            path.write_bytes(b"x")
            handler.wfile = FailingWriter()
            handler.send_file_stream(path, "application/octet-stream", "export.zip", cleanup=True)
            handler.log_client_disconnect.assert_called_once()
            self.assertFalse(path.exists())

    def test_privacy_delete_reports_remote_attempt_and_failure(self):
        server.key_value_service().set("openai_conversation_id", "conv-test")
        with patch.object(server.openai_provider.OpenAIResponsesClient, "delete_conversation", side_effect=server.AppError(503, "upstream")):
            result = server.privacy_delete_service().delete(privacy_module.PRIVACY_DELETE_CONFIRMATION_TEXT)
        self.assertTrue(result["remote_delete_attempted"])
        self.assertFalse(result["remote_conversation_deleted"])
        self.assertTrue(result["local_data_deleted"])
        self.assertIn("remote_untouched", result)

    def test_privacy_delete_preview_covers_every_durable_table_and_reports_counts(self):
        expected_tables = set(CURRENT_DATABASE_SCHEMA)
        scoped_tables = {table for _category, _label, tables in privacy_module.PRIVACY_DELETE_SCOPE for table in tables}
        self.assertEqual(scoped_tables, expected_tables)
        server.key_value_service().set("openai_conversation_id", "conv-test")
        preview = server.privacy_delete_service().preview()
        self.assertEqual({item["id"] for item in preview["categories"]}, {item[0] for item in privacy_module.PRIVACY_DELETE_SCOPE})
        self.assertEqual(preview["confirmation_text"], "LOKALE DATEN LÖSCHEN")
        self.assertTrue(preview["remote_untouched"])
        with patch.object(server.openai_provider.OpenAIResponsesClient, "delete_conversation", return_value=True):
            result = server.privacy_delete_service().delete(privacy_module.PRIVACY_DELETE_CONFIRMATION_TEXT)
        self.assertTrue(result["local_data_deleted"])
        self.assertEqual(set(result["deleted_categories"]), {item[0] for item in privacy_module.PRIVACY_DELETE_SCOPE})
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            for table in expected_tables - {"kv"}:
                self.assertEqual(db.execute(f"SELECT COUNT(*) AS count FROM {table}").fetchone()["count"], 0)

    def test_privacy_delete_rolls_back_earlier_table_deletes_on_sql_failure(self):
        server.coach_message_service().add("user", "Synthetic private message")
        server.sync_state_repository().save_snapshot({
            "synced_at": "synthetic", "recent_activities": [], "recent_wellness": [],
            "upcoming_calendar": [],
        })
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "CREATE TRIGGER synthetic_privacy_abort BEFORE DELETE ON snapshots "
                "BEGIN SELECT RAISE(ABORT, 'synthetic rollback'); END"
            )
        try:
            with self.assertRaises(sqlite3.DatabaseError):
                server.privacy_delete_service().delete(privacy_module.PRIVACY_DELETE_CONFIRMATION_TEXT)
        finally:
            with server.DB_LOCK, server.database_manager().unit_of_work() as db:
                db.execute("DROP TRIGGER synthetic_privacy_abort")
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            self.assertGreater(db.execute("SELECT COUNT(*) AS count FROM messages").fetchone()["count"], 0)
            self.assertGreater(db.execute("SELECT COUNT(*) AS count FROM snapshots").fetchone()["count"], 0)

    def test_chat_history_cursor_and_generation_share_database_unit_of_work(self):
        added = [
            server.coach_message_service().add("user", f"cursor message {index}")
            for index in range(5)
        ]
        server.key_value_service().set("chat_generation", "synthetic-generation")
        manager = server.database_manager()
        page_service = ChatHistoryPageService(
            server.coach_conversation_history_service(),
            Mock(current=Mock(return_value=[])),
            maximum=server.CHAT_PAGE_MAX,
        )
        statements = []
        connections = []
        original_unit_of_work = manager.unit_of_work

        @contextmanager
        def traced_unit_of_work():
            with original_unit_of_work() as db:
                connections.append(db)
                db.set_trace_callback(statements.append)
                try:
                    yield db
                finally:
                    db.set_trace_callback(None)

        with patch.object(
            manager, "unit_of_work", side_effect=traced_unit_of_work
        ), patch.object(
            server.KEY_VALUE_REPOSITORY, "get", wraps=server.KEY_VALUE_REPOSITORY.get
        ) as read_key_value:
            first = page_service.page(limit=2)
        read_key_value.assert_called_once_with(
            read_key_value.call_args.args[0], "chat_generation"
        )
        self.assertEqual(len(connections), 1)
        self.assertIs(read_key_value.call_args.args[0], connections[0])
        self.assertIn("FROM messages ORDER BY id DESC LIMIT 3", statements[0])
        self.assertEqual(
            statements[1], "SELECT value FROM kv WHERE key = 'chat_generation'"
        )
        self.assertEqual(first["generation"], "synthetic-generation")

        second = page_service.page(cursor=first["next_cursor"], limit=2)
        third = page_service.page(cursor=second["next_cursor"], limit=2)
        ids = [item["id"] for page in (first, second, third) for item in page["messages"]]
        self.assertEqual(set(ids), {item["id"] for item in added})
        self.assertEqual(len(ids), len(set(ids)))
        self.assertIsNone(third["next_cursor"])

    def test_bootstrap_reuses_one_database_connection_for_local_reads(self):
        with patch.object(server.sqlite3, "connect", wraps=sqlite3.connect) as connect:
            server.public_bootstrap_service().read()
        self.assertEqual(connect.call_count, 1)

    def test_bootstrap_resolves_database_manager_inside_shared_lock(self):
        real_manager = server.database_manager
        lock_states = []

        def manager_factory():
            lock_states.append(server.DB_LOCK._is_owned())
            return real_manager()

        with patch.object(server, "database_manager", side_effect=manager_factory):
            server.public_bootstrap_service().read()

        self.assertTrue(lock_states)
        self.assertTrue(all(lock_states))

    def test_backup_export_helpers_are_dependency_light_and_preserve_bounds(self):
        from backend.backup import export as backup_export
        from backend.backup.export import application_state, manifest, write_jsonl_rows

        source = Path(backup_export.__file__).read_text(encoding="utf-8")
        self.assertNotIn("import server", source)
        self.assertIn("class PrivacyArchiveExportService", source)
        self.assertIn("def create_file(self)", source)
        server_source = Path(server.__file__).read_text(encoding="utf-8")
        self.assertNotIn("def _privacy_export_file", server_source)
        self.assertIn("def privacy_archive_export_service", server_source)

        class Rows:
            def execute(self, query):
                if query.startswith("SELECT key, value FROM kv"):
                    return [{"key": "visible", "value": "{\"enabled\":true}"}, {"key": "raw", "value": "not-json"}, {"key": "job_status", "value": "running"}]
                raise AssertionError(query)

        db = Rows()
        self.assertEqual(application_state(db, excluded_keys={"profile"}), {"raw": "not-json", "visible": {"enabled": True}})

        archive_buffer = BytesIO()
        with zipfile.ZipFile(archive_buffer, "w") as archive:
            write_jsonl_rows(archive, "rows.jsonl", [{"id": "one"}], 10, now=lambda: 1, timeout_error=lambda: RuntimeError("timeout"))
            self.assertEqual(manifest(["rows.jsonl", "profile.json"], exported_at="now", format_version=1, jsonl_files={"rows.jsonl"})["categories"], ["profile", "rows"])
        with self.assertRaises(RuntimeError):
            with zipfile.ZipFile(BytesIO(), "w") as archive:
                write_jsonl_rows(archive, "rows.jsonl", [{"id": "one"}], 0, now=lambda: 1, timeout_error=lambda: RuntimeError("timeout"))

    def test_maintenance_gate_clears_after_restore_exception(self):
        gate = runtime_maintenance.MaintenanceGate()
        with self.assertRaises(RuntimeError):
            with gate.restore():
                raise RuntimeError("restore failed")
        self.assertEqual(gate.state(), {"active": False, "running_operations": 0})

    @unittest.skipUnless(server.SQLCIPHER_AVAILABLE, "SQLCipher ist in dieser Testumgebung nicht verfügbar.")
    def test_sqlcipher_database_returns_mapping_rows(self):
        with tempfile.TemporaryDirectory() as temp_root:
            data_dir = Path(temp_root) / "data"
            config = replace(server.CONFIG, app_password="test-password-123")
            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", data_dir / "intervals-coach.db"), patch.object(server, "CONFIG", config):
                server.initialise_database()
                with server.database_manager().unit_of_work() as db:
                    row = db.execute("SELECT value FROM kv WHERE key = 'profile'").fetchone()
                    self.assertIsInstance(row, dict)
                    self.assertIn("value", row)

    @unittest.skipUnless(server.SQLCIPHER_AVAILABLE, "SQLCipher ist in dieser Testumgebung nicht verfÃ¼gbar.")
    def test_session_is_persisted_and_restored_from_database(self):
        class Handler:
            client_address = ("127.0.0.1", 8090)

            def __init__(self, cookies="", csrf=""):
                self.headers = {"Cookie": cookies, "X-CSRF-Token": csrf}

        with tempfile.TemporaryDirectory() as temp_root:
            data_dir = Path(temp_root) / "data"
            config = replace(server.CONFIG, app_password="test-password-123")
            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", data_dir / "intervals-coach.db"), patch.object(server, "CONFIG", config):
                server.initialise_database()
                auth = server.session_auth_service()
                login = auth.login_user(Handler(), "test-password-123")
                token = login["session_token"]
                csrf = login["csrf"]
                restored = auth.authenticated_session(Handler(f"ic_session={token}", csrf))
                self.assertIsNotNone(restored)
                auth.require_csrf(Handler(f"ic_session={token}", csrf), restored)
                with server.database_manager().unit_of_work() as db:
                    row = db.execute("SELECT token_hash, csrf_hash FROM sessions").fetchone()
                    self.assertNotEqual(row["token_hash"], token)
                    self.assertNotEqual(row["csrf_hash"], csrf)

    def test_local_library_template_can_be_edited_archived_restored_and_deleted(self):
        entry = server.workout_library_service().create_local_entry({
            "sport": "Ride", "name": "Lokale Vorlage", "description": "- 45m 60% Easy ride", "duration_minutes": 45,
        })
        updated = server.workout_library_service().update(entry["id"], {"action": "update", "name": "Neue Vorlage", "description": "- 45m 55% Recovery ride"})
        self.assertEqual(updated["library_entry"]["name"], "Neue Vorlage")
        self.assertEqual(server.workout_library_service().list()[0]["name"], "Neue Vorlage")
        server.workout_library_service().update(entry["id"], {"action": "archive"})
        self.assertEqual(server.workout_library_service().list(), [])
        self.assertTrue(server.workout_library_service().list(include_archived=True)[0]["archived"])
        server.workout_library_service().update(entry["id"], {"action": "restore"})
        self.assertEqual(len(server.workout_library_service().list()), 1)
        server.workout_library_service().update(entry["id"], {"action": "delete"})
        self.assertEqual(server.workout_library_service().list(include_archived=True), [])

    def test_gemini_function_schemas_keep_openai_nullable_fields_as_json_schema(self):
        schema = {"type": "object", "properties": {"notes": {"type": ["string", "null"]}}}
        declaration = gemini_provider.function_tools(
            [{"type": "function", "name": "save_feedback", "parameters": schema}]
        )[0]["functionDeclarations"][0]
        self.assertEqual(declaration["parametersJsonSchema"], schema)
        self.assertNotIn("parameters", declaration)

    def test_training_change_tool_schema_exposes_complete_plan_limit(self):
        tool = next(tool for tool in server.COACH_STRUCTURED_TOOLS if tool["name"] == "apply_training_changes")
        changes = tool["parameters"]["properties"]["changes"]
        self.assertEqual(changes["minItems"], 1)
        self.assertEqual(changes["maxItems"], coach_limits.COACH_TRAINING_CHANGE_LIMIT)

    def test_background_submission_resolves_current_database_manager_per_call(self):
        service = server.coach_job_submission_service()
        first_manager = server.database_manager()
        first = service.enqueue(
            "Eine lange Planung bitte", "turn-background-manager-refresh", "csrf-background-manager-refresh",
            operation_id="operation-background-manager-refresh",
        )

        first_manager.close()
        server.DATABASE_MANAGER = None
        server.DATABASE_MANAGER_SIGNATURE = None
        second_manager = server.database_manager()

        self.assertIsNot(first_manager, second_manager)
        self.assertEqual(
            service.active("csrf-background-manager-refresh")["client_turn_id"],
            "turn-background-manager-refresh",
        )
        replay = service.enqueue(
            "Replay", "turn-background-manager-refresh", "csrf-background-manager-refresh",
            operation_id="operation-background-manager-replay",
        )
        self.assertEqual(replay, first)

    def test_background_worker_restores_session_binding_from_persisted_key(self):
        auth = server.session_auth_service()
        csrf_hash = auth.session_token_hash("csrf-background-bound")
        with auth.session_lock, server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO sessions(token_hash, csrf_hash, expires_at, created_at, last_seen) VALUES (?, ?, ?, ?, ?)",
                (auth.session_token_hash("session-background-bound"), csrf_hash, time.time() + 3600, server.utc_now(), server.utc_now()),
            )
        server.coach_job_submission_service().enqueue(
            "Erstelle einen Trainingsplan fuer die naechsten 2 Wochen.",
            "turn-background-bound",
            csrf_hash,
            operation_id="operation-background-bound",
        )
        job = server.coach_job_store().claim()
        seen = {}
        with patch("backend.coach.chat_turn.CoachChatTurnService.run", side_effect=lambda *args, **kwargs: seen.update(kwargs) or {}):
            server.coach_background_job_runner().run(job)
        self.assertEqual(seen["session_csrf_hash"], csrf_hash)

    @unittest.skipUnless(server.SQLCIPHER_AVAILABLE, "SQLCipher ist in dieser Testumgebung nicht verfügbar.")
    def test_restore_accepts_only_exact_schema_and_invalidates_sessions(self):
        with tempfile.TemporaryDirectory() as temp_root:
            data_dir = Path(temp_root) / "data"
            config = replace(server.CONFIG, app_password="test-password-123")
            db_path = data_dir / "intervals-coach.db"
            with patch.object(server, "DATA_DIR", data_dir), patch.object(server, "DB_PATH", db_path), patch.object(server, "CONFIG", config):
                server.initialise_database()
                server.key_value_service().set("restore-marker", "preserved")
                with server.DB_LOCK, server.database_manager().unit_of_work() as db:
                    db.execute(
                        "INSERT INTO sessions(token_hash, csrf_hash, expires_at, created_at, last_seen) VALUES (?, ?, ?, ?, ?)",
                        ("token", "csrf", 9999999999, "now", "now"),
                    )
                valid_backup = server.database_backup_service().read_bytes()
                restored = server.database_restore_service().restore(valid_backup)
                self.assertEqual(restored["status"], "ok")
                self.assertEqual(server.key_value_service().get("restore-marker"), "preserved")
                with server.DB_LOCK, server.database_manager().unit_of_work() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM sessions").fetchone()["count"], 0)

                incomplete_path = data_dir / "incomplete.db"
                incomplete_path.write_bytes(valid_backup)
                connection = server.sqlite_backend.connect(incomplete_path, timeout=20)
                try:
                    configure_cipher(connection, config.app_password)
                    connection.execute("DROP TABLE snapshots")
                    connection.commit()
                finally:
                    connection.close()
                with self.assertRaises(server.AppError) as error:
                    server.database_restore_service().restore(incomplete_path.read_bytes())
                self.assertEqual(error.exception.status, 400)
                self.assertEqual(server.key_value_service().get("restore-marker"), "preserved")
                self.assertEqual(list(data_dir.glob(".intervals-coach-restore-*.db")), [])

                unexpected_path = data_dir / "unexpected.db"
                unexpected_path.write_bytes(valid_backup)
                connection = server.sqlite_backend.connect(unexpected_path, timeout=20)
                try:
                    configure_cipher(connection, config.app_password)
                    connection.execute("CREATE TABLE unexpected_records (id TEXT PRIMARY KEY)")
                    connection.commit()
                finally:
                    connection.close()
                with self.assertRaises(server.AppError) as error:
                    server.database_restore_service().restore(unexpected_path.read_bytes())
                self.assertEqual(error.exception.status, 400)
                self.assertEqual(server.key_value_service().get("restore-marker"), "preserved")
                self.assertEqual(list(data_dir.glob(".intervals-coach-restore-*.db")), [])

    def test_readiness_fails_when_database_is_unavailable(self):
        manager = server.database_manager()
        with patch.object(manager, "unit_of_work", side_effect=OSError("database unavailable")):
            readiness = ReadinessService(
                lambda: manager, server.DB_LOCK, Path(os.environ["DATA_DIR"]),
                runtime_maintenance.MAINTENANCE_GATE,
            ).state()
        self.assertEqual(readiness["status"], "not_ready")
        self.assertFalse(readiness["ready"])
        self.assertFalse(readiness["checks"]["database"])
        self.assertFalse(readiness["checks"]["schema"])

    def test_readiness_fails_during_database_maintenance(self):
        maintenance_gate = runtime_maintenance.MaintenanceGate()
        with tempfile.TemporaryDirectory() as data_dir, maintenance_gate.restore():
            readiness = ReadinessService(
                server.database_manager, server.DB_LOCK, Path(data_dir),
                maintenance_gate,
            ).state()
        self.assertEqual(readiness["status"], "not_ready")
        self.assertFalse(readiness["ready"])
        self.assertFalse(readiness["checks"]["maintenance"])
        self.assertTrue(readiness["maintenance"]["active"])

    def test_privacy_delete_removes_change_history(self):
        server.profile_service().save({"name": "Ada"})
        self.assertTrue(server.change_history_service().list())
        with patch.object(server.openai_provider.OpenAIResponsesClient, "delete_conversation", return_value=True):
            server.privacy_delete_service().delete(privacy_module.PRIVACY_DELETE_CONFIRMATION_TEXT)
        self.assertEqual(server.change_history_service().list(), [])


if __name__ == "__main__":
    unittest.main()
