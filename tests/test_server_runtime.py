"""Server integration tests for runtime."""

import json
import os
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from backend.activities import grouping as activity_grouping
from backend.coach import streams as coach_streams
from backend.coach.job_worker import CoachJobWorker
from backend.performance import morning_battery as performance_morning_battery
from backend.runtime import maintenance as runtime_maintenance
from backend.sync import observation as sync_observation
from server_test_support import server, ServerTestCase


class ServerRuntimeTests(ServerTestCase):

    def test_worker_start_functions_do_not_repeat_recovery(self):
        with patch.object(server.SyncJobQueueService, "resume_interrupted") as sync_recovery, patch(
            "backend.coach.job_store.CoachJobStore.resume_interrupted"
        ) as coach_recovery, patch.object(server.SyncJobWorker, "start") as sync_start, patch.object(server.threading, "Thread") as thread, patch.object(
            server, "SYNC_JOB_WORKER", None
        ), patch.object(server, "COACH_JOB_WORKER", CoachJobWorker()):
            server.sync_job_worker().start()
            server.COACH_JOB_WORKER.start(
                server.coach_job_store, server.coach_background_job_runner,
                server.runtime_maintenance.MAINTENANCE_GATE,
            )
        sync_start.assert_called_once_with()
        self.assertEqual(thread.call_count, 1)
        sync_recovery.assert_not_called()
        coach_recovery.assert_not_called()

    def test_maintenance_gate_blocks_new_operations_and_waits_for_running_one(self):
        gate = runtime_maintenance.MaintenanceGate()
        started = threading.Event()
        release = threading.Event()
        restore_entered = threading.Event()

        def blocked_provider_fetch():
            with gate.operation():
                started.set()
                release.wait(timeout=5)

        def restore_operation():
            with gate.restore():
                restore_entered.set()

        worker = threading.Thread(target=blocked_provider_fetch)
        worker.start()
        self.assertTrue(started.wait(timeout=5))
        restoring = threading.Thread(target=restore_operation)
        restoring.start()
        self.assertFalse(restore_entered.wait(timeout=0.05))
        with self.assertRaises(server.AppError) as blocked:
            with gate.operation():
                pass
        self.assertEqual(blocked.exception.status, 503)
        release.set()
        worker.join(timeout=5)
        restoring.join(timeout=5)
        self.assertTrue(restore_entered.is_set())
        self.assertEqual(gate.state(), {"active": False, "running_operations": 0})

    def test_more_segments_group_settings_and_localize_sensitive_inputs(self):
        app = (Path(__file__).resolve().parents[1] / "public" / "app.js").read_text(encoding="utf-8")
        forms = (Path(__file__).resolve().parents[1] / "public" / "forms.js").read_text(encoding="utf-8")
        navigation = (Path(__file__).resolve().parents[1] / "public" / "navigation.js").read_text(encoding="utf-8")
        index = (Path(__file__).resolve().parents[1] / "public" / "index.html").read_text(encoding="utf-8")
        for segment in ("profile", "connections", "coach", "privacy", "operations"):
            self.assertIn(f'"more/{segment}"', navigation)
            self.assertIn(f'href="#more/{segment}"', index)
        self.assertIn('function moreSegmentFromRoute(route = state.route)', navigation)
        self.assertIn('function renderMoreSegments(segment = moreSegmentFromRoute())', app)
        self.assertIn('formData.getAll("sports")', app)
        self.assertNotIn('function collectCompetitions()', forms)
        self.assertIn('function competitionCard(', app)
        self.assertIn('name="sports" multiple', index)
        self.assertIn('name="timezone" autocomplete="off"', index)
        self.assertIn('id="profileContextNotice"', index)
        self.assertIn('Erwartete Dauer (hh:mm)', app)
        self.assertIn('competitionFact("Distanz", distanceLabel(competition.distance))', app)
        self.assertIn('data-more-segment-panel="privacy"', index)
        self.assertIn('data-more-segment-panel="operations"', index)

    def test_unlimited_retention_does_not_delete_history(self):
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute("INSERT INTO messages(role, content, created_at) VALUES (?, ?, ?)", ("user", "old chat", "2000-01-01T00:00:00+00:00"))
            db.execute("INSERT INTO snapshots(payload, created_at) VALUES (?, ?)", (json.dumps({"synced_at": "2000-01-01T00:00:00+00:00"}), "2000-01-01T00:00:00+00:00"))
        with patch.object(server, "CONFIG", replace(server.CONFIG, data_retention_days=-1)):
            server.initialise_database()
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM messages WHERE content = 'old chat'").fetchone()["count"], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM snapshots WHERE created_at LIKE '2000-%'").fetchone()["count"], 1)

    def test_parallel_cycling_events_are_grouped_for_explicit_selection(self):
        groups = activity_grouping.parallel_cycling_event_groups([
            {"id": "ride-1", "type": "Ride", "name": "Intervalle", "start_date_local": "2026-08-30T08:00:00", "moving_time": 3600},
            {"id": "ride-2", "type": "Ride", "name": "Grundlage", "start_date_local": "2026-08-30T08:30:00", "moving_time": 3600},
            {"id": "run-1", "type": "Run", "name": "Lauf", "start_date_local": "2026-08-30T08:15:00", "moving_time": 1800},
        ])
        self.assertEqual([[event["id"] for event in group] for group in groups], [["ride-1", "ride-2"]])

    def test_separate_cycling_events_are_not_marked_as_parallel(self):
        groups = activity_grouping.parallel_cycling_event_groups([
            {"id": "ride-1", "type": "Ride", "start_date_local": "2026-08-30T08:00:00", "moving_time": 1800},
            {"id": "ride-2", "type": "Ride", "start_date_local": "2026-08-30T12:00:00", "moving_time": 1800},
        ])
        self.assertEqual(groups, [])

    def test_garmin_sleep_bounds_prefers_valid_nested_daily_sleep(self):
        start, end = performance_morning_battery.sleep_bounds({
            "dailySleepDTO": {
                "sleepStartTimestampGMT": "2026-09-03T21:30:00+00:00",
                "sleepEndTimestampGMT": "2026-09-04T05:45:00+00:00",
            },
            "invalid": {"startTimestampGMT": "2026-09-05T06:00:00+00:00", "endTimestampGMT": "2026-09-05T05:00:00+00:00"},
        })
        self.assertEqual(start, datetime(2026, 9, 3, 21, 30, tzinfo=timezone.utc))
        self.assertEqual(end, datetime(2026, 9, 4, 5, 45, tzinfo=timezone.utc))

    def test_background_worker_forwards_live_deltas_and_completion_to_attached_stream(self):
        auth = server.session_auth_service()
        csrf_hash = auth.session_token_hash("csrf-background-streamed")
        with auth.session_lock, server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO sessions(token_hash, csrf_hash, expires_at, created_at, last_seen) VALUES (?, ?, ?, ?, ?)",
                (auth.session_token_hash("session-background-streamed"), csrf_hash, time.time() + 3600, server.utc_now(), server.utc_now()),
            )
        operation_id, _cancel_event = coach_streams.CHAT_STREAM_REGISTRY.register(csrf_hash)
        try:
            server.coach_job_submission_service().enqueue(
                "Wie soll ich heute trainieren?", "turn-background-streamed", csrf_hash,
                operation_id=operation_id,
            )
            job = server.coach_job_store().claim()

            def complete_chat(*_args, **kwargs):
                kwargs["on_text_delta"]("Erster ")
                kwargs["on_text_delta"]("Teil")
                return {"status": "completed", "session_key": "must-not-leave-server", "message": {"id": 42, "role": "assistant", "content": "Erster Teil"}}

            with patch("backend.coach.chat_turn.CoachChatTurnService.run", side_effect=complete_chat):
                server.coach_background_job_runner().run(job)

            events = coach_streams.CHAT_STREAM_REGISTRY.events(csrf_hash, operation_id)
            self.assertEqual(events.get_nowait(), ("delta", {"text": "Erster "}))
            self.assertEqual(events.get_nowait(), ("delta", {"text": "Teil"}))
            event, receipt = events.get_nowait()
            self.assertEqual(event, "completed")
            self.assertEqual(receipt["message"]["content"], "Erster Teil")
            self.assertNotIn("session_key", receipt)
        finally:
            coach_streams.CHAT_STREAM_REGISTRY.unregister(csrf_hash, operation_id)

    def test_background_worker_requeues_transient_coach_contention(self):
        server.coach_job_submission_service().enqueue(
            "Erstelle einen Trainingsplan fuer die naechsten 2 Wochen.",
            "turn-background-requeue",
            "csrf-background-requeue",
            operation_id="operation-background-requeue",
        )
        job = server.coach_job_store().claim()
        auth = server.session_auth_service()
        with patch(
            "backend.coach.chat_turn.CoachChatTurnService.run",
            side_effect=server.AppError(429, "busy", reason="chat_queue_full"),
        ), patch.object(auth, "restore_coach_session_csrf_hash", return_value="csrf-background-requeue"):
            server.coach_background_job_runner().run(job)
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            command = db.execute(
                "SELECT status, receipt FROM coach_commands WHERE client_turn_id='turn-background-requeue'"
            ).fetchone()
        receipt = json.loads(command["receipt"])
        self.assertEqual(command["status"], "queued")
        self.assertEqual(receipt["phase"], "waiting_for_coach_slot")
        self.assertGreater(float(receipt["retry_after"]), time.time())

    def test_background_worker_preserves_checkpointed_recovery_phase(self):
        server.coach_job_submission_service().enqueue(
            "Erstelle einen Trainingsplan fuer die naechsten 2 Wochen.",
            "turn-background-recovery-phase",
            "csrf-background-recovery-phase",
            operation_id="operation-background-recovery-phase",
        )
        job = server.coach_job_store().claim()
        server.coach_job_store().merge_receipt(
            "turn-background-recovery-phase",
            {"openai_response_id": "resp-recovery-phase", "phase": "waiting_final_response", "tool_rounds": 1},
        )
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            row = db.execute(
                "SELECT receipt FROM coach_commands WHERE client_turn_id=?",
                ("turn-background-recovery-phase",),
            ).fetchone()
        job["receipt"] = server.command_receipt(row["receipt"])
        seen = {}

        def capture_phase(*_args, **_kwargs):
            with server.DB_LOCK, server.database_manager().unit_of_work() as db:
                row = db.execute(
                    "SELECT receipt FROM coach_commands WHERE client_turn_id=?",
                    ("turn-background-recovery-phase",),
                ).fetchone()
            seen["phase"] = json.loads(row["receipt"])["phase"]
            return {}

        with patch("backend.coach.chat_turn.CoachChatTurnService.run", side_effect=capture_phase), patch.object(
            server.session_auth_service(), "restore_coach_session_csrf_hash", return_value="csrf-background-recovery-phase"
        ):
            server.coach_background_job_runner().run(job)
        self.assertEqual(seen["phase"], "waiting_final_response")

    def test_settings_persist_in_data_for_container_restart(self):
        with tempfile.TemporaryDirectory() as temp_root:
            data_dir = Path(temp_root) / "data"
            with patch.object(server, "ROOT", Path(temp_root)), patch.object(server, "DATA_DIR", data_dir), patch.dict(
                os.environ,
                {"GARMIN_EMAIL": "", "GARMIN_PASSWORD": "", "GARMINTOKENS": ""},
                clear=False,
            ):
                server.app_config.save_persistent_settings(data_dir, {
                    "GARMIN_EMAIL": "athlete@example.com",
                    "GARMIN_PASSWORD": "test-password",
                    "GARMINTOKENS": "/data/garmin_tokens",
                }, os.environ)
                for key in ("GARMIN_EMAIL", "GARMIN_PASSWORD", "GARMINTOKENS"):
                    os.environ.pop(key, None)
                server.app_config.load_local_env(Path(temp_root), data_dir, os.environ)
                self.assertEqual(os.environ["GARMIN_EMAIL"], "athlete@example.com")
                self.assertEqual(os.environ["GARMIN_PASSWORD"], "test-password")
                self.assertEqual(os.environ["GARMINTOKENS"], "/data/garmin_tokens")

    def test_container_environment_values_override_persistent_settings(self):
        with tempfile.TemporaryDirectory() as temp_root:
            data_dir = Path(temp_root) / "data"
            with patch.object(server, "ROOT", Path(temp_root)), patch.object(server, "DATA_DIR", data_dir):
                server.app_config.save_persistent_settings(data_dir, {
                    "OPENAI_API_KEY": "file-openai",
                    "INTERVALS_API_KEY": "file-intervals",
                    "GARMIN_EMAIL": "file@example.com",
                    "GARMIN_PASSWORD": "file-password",
                    "GARMINTOKENS": "/data/file-tokens",
                }, os.environ)
                for key in ("OPENAI_API_KEY", "INTERVALS_API_KEY", "GARMIN_EMAIL", "GARMIN_PASSWORD", "GARMINTOKENS"):
                    os.environ.pop(key, None)
                with patch.dict(os.environ, {
                    "OPENAI_API_KEY": "env-openai",
                    "INTERVALS_API_KEY": "env-intervals",
                    "GARMIN_EMAIL": "env@example.com",
                    "GARMIN_PASSWORD": "env-password",
                    "GARMINTOKENS": "/data/env-tokens",
                }, clear=False):
                    server.app_config.load_local_env(Path(temp_root), data_dir, os.environ)
                    self.assertEqual(os.environ["OPENAI_API_KEY"], "env-openai")
                    self.assertEqual(os.environ["INTERVALS_API_KEY"], "env-intervals")
                    self.assertEqual(os.environ["GARMIN_EMAIL"], "env@example.com")
                    self.assertEqual(os.environ["GARMIN_PASSWORD"], "env-password")
                    self.assertEqual(os.environ["GARMINTOKENS"], "/data/env-tokens")

    def test_parallel_operations_keep_distinct_safe_correlation_ids(self):
        barrier = threading.Barrier(2)
        operation_ids = []

        def worker():
            with server.sync_operation_observer().observe(
                "test", "default", "manual"
            ) as scope:
                operation_ids.append(scope.operation_id)
                barrier.wait(timeout=5)
                self.assertEqual(
                    sync_observation.operation_context()["operation_id"],
                    scope.operation_id,
                )

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=5)
        self.assertEqual(len(operation_ids), 2)
        self.assertEqual(len(set(operation_ids)), 2)


if __name__ == "__main__":
    unittest.main()
