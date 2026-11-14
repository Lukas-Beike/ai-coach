"""Server integration tests for runtime."""

import json
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

from server_test_support import ServerTestCase, server

from backend.coach import streams as coach_streams
from backend.coach.job_worker import CoachJobWorker
from backend.runtime import clock as runtime_clock
from backend.sync import queue as sync_queue
from backend.sync import worker as sync_worker_runtime


class ServerRuntimeTests(ServerTestCase):
    def test_worker_start_functions_do_not_repeat_recovery(self):
        with (
            patch.object(
                sync_queue.SyncJobQueueService, "resume_interrupted"
            ) as sync_recovery,
            patch(
                "backend.coach.job_store.CoachJobStore.resume_interrupted"
            ) as coach_recovery,
            patch.object(sync_worker_runtime.SyncJobWorker, "start") as sync_start,
            patch.object(server.threading, "Thread") as thread,
            patch.object(server, "COACH_JOB_WORKER", CoachJobWorker()),
        ):
            server.SYNC_WORKERS.create().start()
            server.COACH_JOB_WORKER.start(
                server.COACH_BACKGROUND_JOBS.job_store,
                server.COACH_BACKGROUND_JOBS.background_job_runner,
                server.runtime_maintenance.MAINTENANCE_GATE,
                Mock(),
            )
        sync_start.assert_called_once_with()
        self.assertEqual(thread.call_count, 1)
        sync_recovery.assert_not_called()
        coach_recovery.assert_not_called()

    def test_more_segments_group_settings_and_localize_sensitive_inputs(self):
        app = (
            Path(__file__).resolve().parents[1] / "public" / "settings.js"
        ).read_text(encoding="utf-8")
        views = (Path(__file__).resolve().parents[1] / "public" / "views.js").read_text(
            encoding="utf-8"
        )
        navigation = (
            Path(__file__).resolve().parents[1] / "public" / "navigation.js"
        ).read_text(encoding="utf-8")
        index = (
            Path(__file__).resolve().parents[1] / "public" / "index.html"
        ).read_text(encoding="utf-8")
        for segment in ("profile", "connections", "coach", "operations"):
            self.assertIn(f'"more/{segment}"', navigation)
            self.assertIn(f'href="#more/{segment}"', index)
        self.assertNotIn("more/privacy", navigation)
        self.assertNotIn("more/privacy", index)
        self.assertIn(
            "function moreSegmentFromRoute(route = AppState.state.route)", navigation
        )
        self.assertIn("function renderMoreSegments(segment)", views)
        self.assertIn("function profileFormValues(form)", app)
        self.assertIn('new FormData(form).getAll("sports")', app)
        plan_views = (
            Path(__file__).resolve().parents[1] / "public" / "plan-views.js"
        ).read_text(encoding="utf-8")
        self.assertIn("function competitionCard(", plan_views)
        self.assertNotIn("function competitionCard(", app)
        self.assertIn('type="checkbox" name="sports"', index)
        self.assertNotIn('name="sports" multiple', index)
        self.assertIn('name="timezone" autocomplete="off"', index)
        self.assertNotIn("profileContextNotice", index)
        self.assertIn('"Erwartete Dauer"', plan_views)
        self.assertIn(
            "competitionDistance(competition.distance)",
            plan_views,
        )
        self.assertNotIn('data-more-segment-panel="privacy"', index)
        self.assertIn('data-more-segment-panel="operations"', index)

    def test_unlimited_retention_does_not_delete_history(self):
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO messages(role, content, created_at) VALUES (?, ?, ?)",
                ("user", "old chat", "2000-01-01T00:00:00+00:00"),
            )
            db.execute(
                "INSERT INTO snapshots(payload, created_at) VALUES (?, ?)",
                (
                    json.dumps({"synced_at": "2000-01-01T00:00:00+00:00"}),
                    "2000-01-01T00:00:00+00:00",
                ),
            )
        with patch.object(
            server.CONFIG_HOLDER,
            "value",
            replace(server.CONFIG_HOLDER.value, data_retention_days=-1),
        ):
            server.initialise_database()
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) AS count FROM messages WHERE content = 'old chat'"
                ).fetchone()["count"],
                1,
            )
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) AS count FROM snapshots WHERE created_at LIKE '2000-%'"
                ).fetchone()["count"],
                1,
            )

    def test_background_worker_forwards_live_deltas_and_completion_to_attached_stream(
        self,
    ):
        auth = server.session_auth_service()
        csrf_hash = auth.session_token_hash("csrf-background-streamed")
        with (
            auth.session_lock,
            server.DB_LOCK,
            server.database_manager().unit_of_work() as db,
        ):
            db.execute(
                "INSERT INTO sessions(token_hash, csrf_hash, expires_at, created_at, last_seen) VALUES (?, ?, ?, ?, ?)",
                (
                    auth.session_token_hash("session-background-streamed"),
                    csrf_hash,
                    time.time() + 3600,
                    runtime_clock.utc_now(),
                    runtime_clock.utc_now(),
                ),
            )
        operation_id, _cancel_event = coach_streams.CHAT_STREAM_REGISTRY.register(
            csrf_hash
        )
        try:
            server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
                "Wie soll ich heute trainieren?",
                "turn-background-streamed",
                csrf_hash,
                operation_id=operation_id,
            )
            job = server.COACH_BACKGROUND_JOBS.job_store().claim()

            def complete_chat(*_args, **kwargs):
                kwargs["on_text_delta"]("Erster ")
                kwargs["on_text_delta"]("Teil")
                return {
                    "status": "completed",
                    "session_key": "must-not-leave-server",
                    "message": {
                        "id": 42,
                        "role": "assistant",
                        "content": "Erster Teil",
                    },
                }

            with patch(
                "backend.coach.chat_turn.CoachChatTurnService.run",
                side_effect=complete_chat,
            ):
                server.COACH_BACKGROUND_JOBS.background_job_runner().run(job)

            events = coach_streams.CHAT_STREAM_REGISTRY.events(csrf_hash, operation_id)
            self.assertEqual(events.get_nowait(), ("delta", {"text": "Erster "}))
            self.assertEqual(events.get_nowait(), ("delta", {"text": "Teil"}))
            event, receipt = events.get_nowait()
            self.assertEqual(event, "completed")
            self.assertEqual(receipt["message"]["content"], "Erster Teil")
            self.assertNotIn("session_key", receipt)
        finally:
            coach_streams.CHAT_STREAM_REGISTRY.unregister(csrf_hash, operation_id)


if __name__ == "__main__":
    unittest.main()
