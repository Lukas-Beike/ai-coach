"""Server integration tests for sync."""

import json
import signal
import sys
import tempfile
import threading
import time
import unittest
import uuid
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from unittest.mock import Mock, patch

import intervals_compaction
from garmin_support import read_garmin, save_garmin
from performance_day_support import SYNCED_AT, snapshot_metrics
from server_test_support import (
    ServerTestCase,
    _current_performance_context,
    _garmin_metrics,
    server,
)
from support import (
    IntervalsRequestRecorder,
    RecordedIntervalsClient,
    parsed_workout_fixture,
    store_garmin_activities,
)

from backend.errors import AppError
from backend.http_api import server as http_server_module
from backend.http_api import wiring as http_wiring
from backend.http_api.static_assets import StaticAssetService
from backend.planning import adaptive as planning_adaptive
from backend.planning import competitions as planning_competitions
from backend.planning import library as planning_library
from backend.providers import intervals_client as intervals_client_module
from backend.runtime import clock as runtime_clock
from backend.sync import executor as sync_executor
from backend.sync import garmin as garmin_sync
from backend.sync import garmin_service
from backend.sync import queue as sync_queue
from backend.sync import wiring as sync_wiring
from backend.sync import worker as sync_worker_runtime
from backend.sync.authority import PlanningAuthorityService
from backend.sync.library import WorkoutLibrarySyncService
from backend.sync.plan_commands import PlanPushCommandService


class ServerSyncTests(ServerTestCase):
    def _prepare_remote_contract_fixture(self, include_competition=False):
        recorder = IntervalsRequestRecorder()
        client = RecordedIntervalsClient(recorder)
        server.PLANNING_DATA.workout_library().create_local_entry(
            {
                "sport": "Ride",
                "name": "Contract fixture",
                "description": "- 30m Z2",
                "duration_minutes": 30,
                "target": "POWER",
                "rationale": "Test",
            }
        )
        if include_competition:
            server.PLANNING_DATA.competition().save(
                {
                    "name": "Contract race",
                    "event_date": (
                        server.ATHLETE_CLOCK.now().date() + timedelta(days=30)
                    ).isoformat(),
                    "sport": "Cycling",
                }
            )
        return recorder, client

    def _prepare_competition_contract_fixture(self):
        recorder = IntervalsRequestRecorder()
        client = RecordedIntervalsClient(recorder)
        server.PLANNING_DATA.competition().save(
            {
                "name": "Competition contract",
                "event_date": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=30)
                ).isoformat(),
                "sport": "Cycling",
            }
        )
        return recorder, client

    def test_startup_explicitly_recovers_jobs_before_starting_workers(self):
        order = []
        http_server = Mock()
        http_server_factory = Mock(return_value=http_server)
        startup_scheduler = Mock()
        daily_loop_factory = Mock()
        with (
            patch.object(server.observability, "configure_logging"),
            patch.object(
                server.app_config, "security_configuration_error", return_value=None
            ),
            patch.object(
                server,
                "initialise_database",
                side_effect=lambda: order.append("schema"),
            ),
            patch.object(
                sync_queue.SyncJobQueueService,
                "resume_interrupted",
                side_effect=lambda: order.append("sync-recovery"),
            ),
            patch(
                "backend.coach.job_store.CoachJobStore.resume_interrupted",
                side_effect=lambda *_: order.append("coach-recovery"),
            ),
            patch.object(http_server_module, "CoachHTTPServer", http_server_factory),
            patch.object(
                sync_worker_runtime.SyncJobWorker,
                "start",
                side_effect=lambda _worker: order.append("sync-worker"),
                autospec=True,
            ),
            patch.object(
                server.COACH_JOB_WORKER,
                "start",
                side_effect=lambda *_: order.append("coach-worker"),
            ),
            patch.object(
                server.CANONICAL_BACKFILL.worker,
                "start",
                side_effect=lambda: order.append("canonical-backfill"),
            ),
            patch.object(server.COACH_JOB_WORKER, "stop") as coach_stop,
            patch.object(server.COACH_JOB_WORKER, "join") as coach_join,
            patch.object(sync_worker_runtime.SyncJobWorker, "stop") as sync_stop,
            patch.object(sync_worker_runtime.SyncJobWorker, "join") as sync_join,
            patch.object(
                server,
                "SYNC_SCHEDULERS",
                replace(
                    server.SYNC_SCHEDULERS,
                    startup_scheduler=startup_scheduler,
                    daily_loop=daily_loop_factory,
                ),
            ),
            patch.object(
                server,
                "PERFORMANCE",
                replace(
                    server.PERFORMANCE,
                    all_time_records=lambda: order.append("all-time-build"),
                ),
            ),
            patch.object(server.threading, "Thread") as thread_factory,
            patch.object(server.signal, "signal") as install_signal_handler,
            patch.object(server.DIAGNOSTIC_CAPTURE, "close") as capture_close,
            patch.object(server.DIAGNOSTIC_CAPTURE, "flush") as capture_flush,
        ):
            startup_scheduler.return_value.schedule.side_effect = lambda: order.append(
                "startup-sync"
            )
            daily_loop = Mock()
            daily_loop_factory.return_value = daily_loop
            shutdown = []
            for name, step in (
                ("server-close", http_server.server_close),
                ("capture-close", capture_close),
                ("daily-join", thread_factory.return_value.join),
                ("sync-join", sync_join),
                ("coach-join", coach_join),
                ("capture-flush", capture_flush),
            ):
                step.side_effect = lambda *_args, name=name, **_kwargs: shutdown.append(
                    name
                )
            server.main()
        install_signal_handler.assert_called_once_with(
            signal.SIGTERM, signal.default_int_handler
        )
        # Pending diagnostics are written before the workers are joined and once more
        # after them, inside Docker's stop grace period.
        self.assertEqual(
            shutdown,
            [
                "server-close",
                "capture-close",
                "daily-join",
                "sync-join",
                "coach-join",
                "capture-flush",
            ],
        )
        http_server_factory.assert_called_once()
        address, handler_class = http_server_factory.call_args.args
        self.assertEqual(address, ("0.0.0.0", server.CONFIG_HOLDER.value.port))
        self.assertTrue(issubclass(handler_class, BaseHTTPRequestHandler))
        self.assertIsInstance(handler_class.static_asset_service, StaticAssetService)
        self.assertEqual(
            handler_class.static_asset_service._targets["index.html"],
            server.PUBLIC_DIR / "index.html",
        )
        thread_factory.assert_called_once_with(target=daily_loop.run, daemon=True)
        # The startup jobs are written on this thread before any worker that can
        # start the canonical backfill, whose batches hold the writer (#2287).
        self.assertEqual(
            order,
            [
                "schema",
                "sync-recovery",
                "coach-recovery",
                "startup-sync",
                "sync-worker",
                "coach-worker",
                "canonical-backfill",
                # The paced all-time curve build starts once at start-up, so the
                # first views find their session curves warm (#2783).
                "all-time-build",
            ],
        )
        daily_loop.stop.assert_called_once_with()
        http_server.server_close.assert_called_once_with()
        thread_factory.return_value.join.assert_called_once_with(timeout=5)
        sync_stop.assert_called_once_with()
        sync_join.assert_called_once_with(timeout=5)
        coach_stop.assert_called_once_with()
        coach_join.assert_called_once_with(timeout=5)

    def test_persisted_intervals_ingest_jobs_are_retired_unrun(self):
        now = "2026-11-07T10:00:00+00:00"
        ids = []
        with server.database_manager().unit_of_work() as db:
            for index, job_type in enumerate(
                (
                    "refresh",
                    "performance_refresh",
                    "activity_details",
                    "historical_backfill",
                )
            ):
                job_id = f"legacy-{index}"
                ids.append(job_id)
                db.execute(
                    "INSERT INTO sync_jobs(id, provider, type, status, payload, requested_by, "
                    "attempts, progress_total, progress_completed, available_at, created_at, "
                    "updated_at) VALUES (?, 'intervals', ?, ?, '{}', 'scheduler', 0, 1, 0, ?, ?, ?)",
                    (
                        job_id,
                        job_type,
                        "running" if index == 3 else "queued",
                        now,
                        now,
                        now,
                    ),
                )
                db.execute(
                    "INSERT INTO sync_job_items(id, job_id, item_key, operation, payload_hash, "
                    "status, attempts, created_at, updated_at) "
                    "VALUES (?, ?, 'job', 'refresh', 'h', ?, 0, ?, ?)",
                    (
                        f"{job_id}-0",
                        job_id,
                        "running" if index == 3 else "queued",
                        now,
                        now,
                    ),
                )
        # The interrupted one is requeued by the restart recovery, like any other.
        self.assertEqual(server.SYNC_JOB_QUEUE.service().resume_interrupted(), 1)
        executor = server.SYNC_JOB_EXECUTION.executor()
        with patch.object(
            sync_executor.SyncJobExecutor, "execute", side_effect=AssertionError("ran")
        ):
            for _ in ids:
                claimed = server.SYNC_JOB_QUEUE.store().claim()
                self.assertIsNotNone(claimed)
                executor.run(claimed)
        for job_id in ids:
            state = server.SYNC_JOB_QUEUE.service().state(job_id)
            self.assertEqual(state["status"], "completed", job_id)
            self.assertIsNone(state["error_class"])

    def test_persistent_sync_job_claim_resume_retry_and_completion(self):
        job = server.SYNC_JOB_QUEUE.service().enqueue(
            "garmin", "refresh", {"days": 7}, requested_by="user"
        )
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["progress"], {"completed": 0, "total": 1})
        claimed = server.SYNC_JOB_QUEUE.store().claim()
        self.assertEqual(claimed["id"], job["id"])
        self.assertEqual(
            server.SYNC_JOB_QUEUE.service().state(job["id"])["status"], "running"
        )
        self.assertEqual(server.SYNC_JOB_QUEUE.service().resume_interrupted(), 1)
        self.assertEqual(
            server.SYNC_JOB_QUEUE.service().state(job["id"])["status"], "queued"
        )
        claimed = server.SYNC_JOB_QUEUE.store().claim()
        with patch.object(
            sync_executor.SyncJobExecutor, "execute", return_value={"status": "ok"}
        ):
            server.SYNC_JOB_EXECUTION.executor().run(claimed)
        completed = server.SYNC_JOB_QUEUE.service().state(job["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["progress"], {"completed": 1, "total": 1})
        self.assertEqual(completed["items"][0]["status"], "completed")

    def test_persistent_sync_job_retries_only_safe_transient_errors(self):
        job = server.SYNC_JOB_QUEUE.service().enqueue(
            "weather", "refresh", {"force": True}
        )
        claimed = server.SYNC_JOB_QUEUE.store().claim()
        provider_detail = "https://athlete:secret-pass@example.invalid/private-token-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        with patch.object(
            sync_executor.SyncJobExecutor,
            "execute",
            side_effect=AppError(503, provider_detail, reason="network_error"),
        ):
            server.SYNC_JOB_EXECUTION.executor().run(claimed)
        state = server.SYNC_JOB_QUEUE.service().state(job["id"])
        self.assertEqual(state["status"], "queued")
        self.assertEqual(state["error_class"], "network_error")
        self.assertEqual(state["items"][0]["status"], "queued")
        self.assertIsNotNone(state["available_at"])
        self.assertNotIn("secret-pass", state["items"][0]["error_detail"])
        self.assertNotIn("private-token-aaaaaaaa", state["items"][0]["error_detail"])

    def test_plan_push_job_preserves_all_failed_object_outcomes(self):
        local_id = str(uuid.uuid4())
        job = server.SYNC_JOB_QUEUE.service().enqueue(
            "intervals",
            "plan_push",
            {
                "entries": [
                    {"library_workout_id": local_id, "expected_payload_hash": "a" * 64}
                ]
            },
            requested_by="coach",
            item_operations=[
                {
                    "item_key": local_id,
                    "operation": "plan_push",
                    "payload_hash": "a" * 64,
                }
            ],
        )
        claimed = server.SYNC_JOB_QUEUE.store().claim()
        result = {
            "status": "error",
            "results": [
                {
                    "library_workout_id": local_id,
                    "status": "conflict",
                    "error": "changed",
                }
            ],
        }
        with patch.object(
            sync_executor.SyncJobExecutor, "execute", return_value=result
        ):
            server.SYNC_JOB_EXECUTION.executor().run(claimed)
        state = server.SYNC_JOB_QUEUE.service().state(job["id"])
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["items"][0]["status"], "failed")
        self.assertEqual(state["progress"], {"completed": 1, "total": 1})

    def test_replacement_follow_up_sync_accepts_complete_plan_size(self):
        today = server.ATHLETE_CLOCK.now().date()
        planned = server.PLANNING_WORKFLOWS.local_plan_creation_service().save(
            [
                {
                    "date": (today + timedelta(days=index + 1)).isoformat(),
                    "sport": "VirtualRide",
                    "name": "Synthetic replacement run",
                    "description": "- 30m 60% Synthetic easy session",
                    "duration_minutes": 30,
                }
                for index in range(planning_library.LIBRARY_BULK_MAX_ENTRIES + 1)
            ]
        )
        local_ids = [item["id"] for item in planned]
        entries = [
            item
            for item in server.SYNC_COMMANDS.authority().pending_plan_push_entries()
            if item["library_workout_id"] in local_ids
        ]
        intent = {
            "intent": "remote_sync",
            "operation": "replace_training_plan",
            "target_system": "intervals",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": [
                "local_plan",
                *(f"library_workout:{local_id}" for local_id in local_ids),
            ],
            "follow_up_operations": ["start_intervals_plan_sync"],
            "_replacement_sync_entry_ids": local_ids,
        }

        with (
            patch.object(PlanningAuthorityService, "mark_planning_authoritative"),
            patch.object(
                PlanPushCommandService,
                "enqueue",
                return_value={"ok": True, "status": "queued"},
            ) as enqueue,
        ):
            result = server.COACH_TOOL_DISPATCH.service().execute(
                "start_intervals_plan_sync",
                {"entries": entries},
                intent=intent,
                conversation_id="conversation-large-replacement",
                client_turn_id="turn-large-replacement",
                session_csrf_hash="",
                sync_job_ids=[],
            )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(len(enqueue.call_args.args[0]), len(local_ids))

    def test_same_turn_plan_sync_rejects_a_subset_of_created_entries(self):
        local_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        intent = {
            "intent": "remote_sync",
            "operation": "stage_training_plan",
            "target_system": "intervals",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": [
                *(f"library_workout:{local_id}" for local_id in local_ids)
            ],
            "follow_up_operations": [
                "commit_training_plan",
                "start_intervals_plan_sync",
            ],
            "_sync_created_entries_only": True,
            "_created_sync_entry_ids": local_ids,
        }
        entries = [
            {"library_workout_id": local_ids[0], "expected_payload_hash": "b" * 64}
        ]

        with (
            patch.object(PlanPushCommandService, "enqueue") as enqueue,
            self.assertRaises(AppError) as error,
        ):
            server.COACH_TOOL_DISPATCH.service().execute(
                "start_intervals_plan_sync",
                {"entries": entries},
                intent=intent,
                conversation_id="conversation-created-subset",
                client_turn_id="turn-created-subset",
                session_csrf_hash="",
                sync_job_ids=[],
            )

        self.assertEqual(error.exception.reason, "intent_scope_denied")
        enqueue.assert_not_called()

    def test_apply_result_deduplicates_changed_ids_for_sync(self):
        planned = server.PLANNING_DATA.planned_unit().create(
            {
                "date": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=9)
                ).isoformat(),
                "sport": "Ride",
                "name": "Repeated",
                "description": "- 20m 60% easy",
            }
        )
        intent = {
            "intent": "local_action",
            "operation": "apply_training_changes",
            "target_system": "local",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": ["local_plan"],
        }
        result = server.COACH_TOOL_DISPATCH.service().execute(
            "apply_training_changes",
            {
                "changes": [
                    {"local_id": planned["id"], "action": "update", "name": "First"},
                    {"local_id": planned["id"], "action": "update", "name": "Second"},
                ]
            },
            intent=intent,
            conversation_id="conversation-dedup",
            client_turn_id="turn-dedup",
            session_csrf_hash="",
            sync_job_ids=[],
        )
        self.assertEqual(result["library_entry_ids"], [planned["id"]])

    def test_changed_batch_sync_is_limited_to_changed_entries(self):
        changed = server.PLANNING_DATA.planned_unit().create(
            {
                "date": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=6)
                ).isoformat(),
                "sport": "VirtualRide",
                "name": "Changed",
                "description": "- 20m 60% easy",
            }
        )
        untouched = server.PLANNING_DATA.planned_unit().create(
            {
                "date": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=7)
                ).isoformat(),
                "sport": "Run",
                "name": "Untouched",
                "description": "- 20m 60% easy",
            }
        )
        intent = {
            "intent": "remote_sync",
            "operation": "start_intervals_plan_sync",
            "target_system": "intervals",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": [f"library_workout:{changed['id']}"],
            "_sync_changed_entries_only": True,
            "_changed_sync_entry_ids": [changed["id"]],
        }
        with patch.object(
            sync_queue.SyncJobQueueService,
            "enqueue",
            return_value={"id": "job-changed"},
        ) as enqueue:
            result = server.COACH_TOOL_DISPATCH.service().execute(
                "start_intervals_plan_sync",
                {},
                intent=intent,
                conversation_id="conversation-changed-sync",
                client_turn_id="turn-changed-sync",
                session_csrf_hash="",
                sync_job_ids=[],
            )
        queued = enqueue.call_args.args[2]["entries"]
        self.assertEqual(
            {item["library_workout_id"] for item in queued}, {changed["id"]}
        )
        self.assertNotEqual(changed["id"], untouched["id"])
        self.assertEqual(result["status"], "queued")

    def test_changed_batch_sync_accepts_the_coach_change_limit(self):
        today = server.ATHLETE_CLOCK.now().date()
        for index in range(101):
            server.PLANNING_DATA.planned_unit().create(
                {
                    "date": (today + timedelta(days=index + 10)).isoformat(),
                    "sport": "VirtualRide",
                    "name": f"Changed {index}",
                    "description": "- 20m 60% easy",
                }
            )
        pending = server.SYNC_COMMANDS.authority().pending_plan_push_entries()
        selected = pending[:101]
        intent = {
            "intent": "remote_sync",
            "operation": "start_intervals_plan_sync",
            "target_system": "intervals",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": [
                f"library_workout:{item['library_workout_id']}" for item in selected
            ],
            "_sync_changed_entries_only": True,
            "_changed_sync_entry_ids": [
                item["library_workout_id"] for item in selected
            ],
        }
        with patch.object(
            sync_queue.SyncJobQueueService,
            "enqueue",
            return_value={"id": "job-large-changed"},
        ) as enqueue:
            result = server.COACH_TOOL_DISPATCH.service().execute(
                "start_intervals_plan_sync",
                {"entries": selected},
                intent=intent,
                conversation_id="conversation-large-changed",
                client_turn_id="turn-large-changed",
                session_csrf_hash="",
                sync_job_ids=[],
            )
        queued = [
            entry
            for call in enqueue.call_args_list
            for entry in call.args[2]["entries"]
        ]
        self.assertEqual(len(queued), 101)
        self.assertEqual(enqueue.call_count, 4)
        self.assertEqual(result["status"], "queued")

    def test_sync_status_is_bounded_and_contains_versions(self):
        server.key_value_service().set("sync_operation_id", "operation-test")
        server.key_value_service().set("sync_operation_status", "running")
        server.key_value_service().set("sync_operation_phase", "fetching")
        server.key_value_service().set("sync_operation_progress", "35")
        server.key_value_service().set(
            "sync_operation_message", "Daten werden gelesen…"
        )
        with patch.object(http_wiring, "StateVersionService") as versions:
            versions.return_value.versions.return_value = {"activities": "v1"}
            status = server.PUBLIC_STATE.sync_public_state_service().state()
        self.assertEqual(status["operation_id"], "operation-test")
        self.assertEqual(status["phase"], "fetching")
        self.assertEqual(status["progress"], 35)
        bootstrap = server.PUBLIC_STATE.bootstrap_service().read()
        self.assertEqual(bootstrap["sync"]["progress"], 35)
        self.assertEqual(bootstrap["sync"]["message"], "Daten werden gelesen…")

    def test_daily_sync_scheduler_uses_local_provider_markers(self):
        import inspect

        from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY
        from backend.sync.scheduler import DailySyncScheduler

        self.assertEqual(DailySyncScheduler.__module__, "backend.sync.scheduler")
        source = Path(sys.modules[DailySyncScheduler.__module__].__file__).resolve()
        module_source = source.read_text(encoding="utf-8")
        daily_scheduler = inspect.getsource(DailySyncScheduler)
        # Marker ids come from the descriptor ranks; behaviour is covered by
        # tests/test_daily_sync_scheduler.py.
        self.assertEqual(
            DEFAULT_PROVIDER_REGISTRY.daily_marker_ids(),
            frozenset({"calendar", "garmin", "wahoo"}),
        )
        self.assertNotIn("import server", module_source)
        self.assertNotIn("from server", module_source)
        self.assertNotIn("[:10]", daily_scheduler)

    def test_garmin_daily_schedule_is_independent_of_intervals(self):
        with (
            patch.object(
                server.CONFIG_HOLDER,
                "value",
                replace(
                    server.CONFIG_HOLDER.value,
                    intervals_api_key="",
                    calendar_ical_url="",
                ),
            ),
            patch.object(
                garmin_sync.GarminFixtureLoader, "path", return_value=Path("synthetic")
            ),
            patch.object(sync_wiring, "DailySyncMarkerService") as marker_service,
        ):
            marker_service.return_value.is_due.return_value = True
            server.SYNC_SCHEDULERS.daily_scheduler().schedule()
        with server.database_manager().unit_of_work() as db:
            rows = db.execute(
                "SELECT provider, payload FROM sync_jobs WHERE type='refresh'"
            ).fetchall()
        self.assertEqual([row["provider"] for row in rows], ["garmin"])
        self.assertEqual(json.loads(rows[0]["payload"])["days"], 84)

    def test_illness_pause_can_sync_sick_events_after_confirmation(self):
        server.ATHLETE_DATA.checkin().save({"illness": "Erkältung"})
        preview = server.PLANNING_WORKFLOWS.adaptive_replan_preview_service().preview()
        calls = []

        class FakeIntervalsClient:
            def upsert_calendar_events(self, events):
                calls.extend(events)
                return [{"id": index} for index, _ in enumerate(events, 1)]

        with (
            patch.object(
                server.CONFIG_HOLDER,
                "value",
                replace(server.CONFIG_HOLDER.value, intervals_api_key="test-key"),
            ),
            patch.object(
                server.APP,
                "provider_transport",
                replace(
                    server.PROVIDER_TRANSPORT,
                    intervals_client=Mock(return_value=FakeIntervalsClient()),
                ),
            ),
        ):
            result = server.SYNC_COMMANDS.illness_pause().apply(
                preview["id"], sync_illness_to_intervals=True
            )

        self.assertEqual(result["intervals_sync"]["status"], "ok")
        self.assertEqual(result["intervals_sync"]["category"], "SICK")
        self.assertEqual(len(calls), planning_adaptive.DEFAULT_ILLNESS_PAUSE_DAYS)
        self.assertTrue(all(event["category"] == "SICK" for event in calls))
        self.assertEqual(calls[0]["name"], "Krankheit")

    def test_compact_snapshot_drops_unknown_and_sensitive_fields(self):
        result = intervals_compaction.compact_snapshot(
            {"id": "i1", "name": "Ada", "secret": "nope"},
            [
                {
                    "id": "a1",
                    "name": "Ride",
                    "icu_vo2max": 52,
                    "vO2MaxValue": 53,
                    "private_note": "nope",
                }
            ],
            [{"id": "2026-01-01", "ctl": 42, "unknown": 99}],
            [{"id": 1, "name": "Tempo", "category": "WORKOUT", "raw": "nope"}],
            all_sync_days=server.ALL_SYNC_DAYS,
            synced_at=runtime_clock.utc_now(),
        )
        self.assertEqual(result["athlete"]["name"], "Ada")
        self.assertNotIn("secret", result["athlete"])
        self.assertNotIn("private_note", result["recent_activities"][0])
        self.assertEqual(result["recent_activities"][0]["icu_vo2max"], 52)
        self.assertEqual(result["recent_activities"][0]["vO2MaxValue"], 53)
        self.assertEqual(result["recent_wellness"][0]["ctl"], 42)

    def test_max_heart_rate_has_no_intervals_fallback(self):
        snapshot = {
            "athlete": {
                "sport_settings": [
                    {"types": ["Ride"], "max_hr": 188},
                    {"types": ["Run"], "max_hr": 193},
                ]
            },
            "recent_activities": [],
            "recent_wellness": [],
        }
        metrics = snapshot_metrics(
            snapshot,
            server.ATHLETE_DATA.profile().get(),
            _garmin_metrics(read_garmin()),
        )
        self.assertIsNone(metrics["cycling_max_hr_bpm"]["value"])
        self.assertIsNone(metrics["running_max_hr_bpm"]["value"])

    def test_garmin_daily_health_is_averaged_over_the_last_seven_days(self):
        today = server.ATHLETE_CLOCK.now().date()
        save_garmin(
            {
                "daily_stats": [
                    {
                        "calendarDate": today.isoformat(),
                        "totalSteps": 1,
                        "floorsAscended": 0,
                        "totalKilocalories": 10,
                    },
                    *[
                        {
                            "calendarDate": (
                                today - timedelta(days=offset + 1)
                            ).isoformat(),
                            "totalSteps": 1000 + offset * 100,
                            "floorsAscended": 5 + offset,
                            "totalKilocalories": 2000 + offset * 10,
                        }
                        for offset in range(7)
                    ],
                ]
            }
        )
        performance = _current_performance_context(
            {
                "synced_at": "now",
                "athlete": {},
                "recent_activities": [],
                "recent_wellness": [],
            }
        )
        self.assertEqual(
            performance["metrics"]["steps_7d"],
            {
                "value": 1300,
                "unit": "Schritte/Tag",
                "source": "Garmin Connect",
                "note": "Durchschnitt der letzten 7 Tage",
                "freshness": "unknown",
                "fetched_at": None,
                "observed_at": None,
                "measurement_status": "unknown",
                "measurement_age_days": None,
            },
        )
        self.assertIsInstance(performance["metrics"]["steps_7d"]["value"], int)
        self.assertEqual(performance["metrics"]["floors_7d"]["value"], 8)
        self.assertIsInstance(performance["metrics"]["floors_7d"]["value"], int)
        self.assertEqual(performance["metrics"]["calories_7d"]["value"], 2030)

    def test_performance_does_not_compare_garmin_metrics_to_intervals_history(self):
        # The fixture maps the undated Garmin FTP to its fixed sync day, so
        # "today" is that day, not the wall clock: 30 days later the FTP leaves
        # the comparison window and there is nothing left to compare.
        today = SYNCED_AT.date()
        snapshot = {
            "synced_at": "now",
            "athlete": {},
            "recent_activities": [],
            "recent_wellness": [
                {
                    "id": today.isoformat(),
                    "sport_info": [{"types": ["Ride"], "ftp": 280}],
                }
            ],
        }
        save_garmin(
            {
                "cycling_ftp": {"functionalThresholdPower": 300},
                "performance_history": [],
            }
        )

        comparison = _current_performance_context(snapshot, today)["comparisons"][
            "cycling_ftp_watts_30d"
        ]
        # The Garmin FTP is compared with its own canonical history only, never
        # with the Intervals.icu 280 W.
        self.assertEqual(comparison["average"], 300)

    def test_library_sync_reconciles_remote_template_before_creating(self):
        entry = server.PLANNING_DATA.workout_library().create_local_entry(
            {
                "sport": "Ride",
                "name": "Coach Tempo",
                "description": "- 30m 85%",
                "duration_minutes": 30,
            }
        )
        remote = {
            "id": "remote-recovered",
            "name": "Coach Tempo",
            "type": "Ride",
            "description": "- 30m 85%",
            **parsed_workout_fixture(),
        }
        with (
            patch.object(
                server.CONFIG_HOLDER,
                "value",
                replace(server.CONFIG_HOLDER.value, intervals_api_key="test-key"),
            ),
            patch.object(
                intervals_client_module.IntervalsClient,
                "get_workout_library",
                return_value=[remote],
            ),
            patch.object(
                intervals_client_module.IntervalsClient, "create_library_workouts"
            ) as create,
        ):
            synced = server.WORKOUT_LIBRARY_SYNC.sync_service().sync_entry(entry["id"])
        self.assertEqual(synced["external_id"], "remote-recovered")
        create.assert_not_called()
        self.assertEqual(
            server.PLANNING_DATA.workout_library().list()[0]["sync_status"], "synced"
        )

    def test_garmin_provider_collector_keeps_ranges_bounded_and_errors_redacted(self):
        from backend.providers.garmin import collect_garmin_data

        class FakeGarmin:
            def get_sleep_daily(self, start, end):
                return [{"date": start, "end": end}]

            def get_hrv_data_range(self, start, end):
                raise RuntimeError("secret provider detail")

            def get_body_battery(self, start, end):
                raise AssertionError(
                    "Body Battery must not be part of the range collector"
                )

            def get_activities_by_date(self, start, end):
                return [{"start": start, "end": end}]

            def get_user_summary(self, current):
                return {
                    "totalSteps": 1234,
                    "floorsAscended": 7,
                    "totalKilocalories": 2100,
                }

            def get_heart_rates(self, current):
                return {"restingHeartRate": 51}

            def get_heart_rate_zones(self):
                return [{"sport": "DEFAULT", "maxHeartRateUsed": 186}]

            def get_training_readiness(self, current):
                return {"date": current, "score": 75}

            def get_training_status(self, current):
                return {"acuteTrainingLoadDTO": {"acuteTrainingLoad": 480}}

            def get_race_predictions(self):
                return [{"race": "local fixture"}]

            def get_max_metrics_range(self, start, end):
                return {"date": end}

            def get_cycling_ftp(self):
                return {"functionalThresholdPower": 301}

            def get_lactate_threshold(self, *, latest=True):
                return {
                    "speed_and_heart_rate": {
                        "speed": 3.6,
                        "heartRate": 175,
                        "heartRateCycling": 168,
                    },
                    "power": {"functionalThresholdPower": 320},
                }

            def connectapi(self, *_args, **_kwargs):
                raise AssertionError(
                    "the undocumented cycling threshold range endpoint must not be called"
                )

            def get_weigh_ins(self, start, end):
                return [{"date": end, "weight": 70}]

        calls = []
        statuses = []

        def external_call(service, source, operation, details):
            calls.append((service, source, details))
            return operation()

        result = collect_garmin_data(
            FakeGarmin(),
            [(date(2026, 8, 30), date(2026, 8, 31))],
            start=date(2026, 8, 30),
            today=date(2026, 8, 31),
            synced_at="2026-09-01T00:00:00+00:00",
            external_call=external_call,
            redact=lambda _value: "[redacted]",
            status=statuses.append,
        )

        self.assertEqual(result["start"], "2026-08-30")
        self.assertEqual(result["end"], "2026-08-31")
        self.assertEqual(len(result["activities"]), 1)
        self.assertEqual(result["errors"], [{"source": "hrv", "message": "[redacted]"}])
        self.assertFalse(result["provider_sync"]["pagination"]["hrv"]["complete"])
        self.assertEqual(statuses, ["Garmin: Zeitraum 1/1 wird synchronisiert…"])
        self.assertTrue(any(source == "weight" for _service, source, _details in calls))
        self.assertEqual(result["cycling_ftp"]["functionalThresholdPower"], 301)
        self.assertEqual(
            result["running_threshold"]["power"]["functionalThresholdPower"], 320
        )
        self.assertEqual(result["resting_hr"][0]["restingHeartRate"], 51)
        self.assertEqual(result["heart_rate_zones"][0]["maxHeartRateUsed"], 186)
        self.assertTrue(
            any(source == "heart_rate_zones" for _service, source, _details in calls)
        )
        self.assertEqual(len(result["daily_stats"]), 2)
        self.assertEqual(result["daily_stats"][0]["calendarDate"], "2026-08-30")
        self.assertEqual(result["daily_stats"][1]["totalSteps"], 1234)
        self.assertEqual(
            result["provider_sync"]["pagination"]["daily_stats"]["records"], 2
        )
        self.assertEqual(
            [row["calendarDate"] for row in result["training_status"]],
            ["2026-08-31"],
        )
        self.assertEqual(
            result["provider_sync"]["pagination"]["training_status"]["records"], 1
        )

    def test_garmin_recovery_reads_skip_days_the_daily_summaries_cover(self):
        from backend.providers.garmin import collect_garmin_data

        class FakeGarmin:
            def __init__(self):
                self.calls = {"get_heart_rates": 0, "get_training_status": 0}

            def __getattr__(self, name):
                # Every other collector source reads nothing in this test.
                if name.startswith("get_"):
                    return lambda *_args, **_kwargs: []
                raise AttributeError(name)

            def get_daily_summaries(self, start, end):
                first = date.fromisoformat(start)
                days = (date.fromisoformat(end) - first).days + 1
                return [
                    {
                        "calendarDate": (first + timedelta(days=offset)).isoformat(),
                        "restingHeartRate": 50,
                    }
                    for offset in range(days)
                    if offset % 2 == 0
                ]

            def get_user_summary(self, current):
                return {"calendarDate": current}

            def get_heart_rates(self, current):
                self.calls["get_heart_rates"] += 1
                return {"restingHeartRate": 51}

            def get_training_status(self, current):
                self.calls["get_training_status"] += 1
                return {"acuteTrainingLoadDTO": {"acuteTrainingLoad": 480}}

        for days in (7, 90):
            with self.subTest(days=days):
                client = FakeGarmin()
                end = date(2026, 8, 31)
                start = end - timedelta(days=days - 1)
                result = collect_garmin_data(
                    client,
                    [(start, end)],
                    start=start,
                    today=end,
                    synced_at="2026-09-01T00:00:00+00:00",
                    external_call=lambda _s, _o, operation, _d: operation(),
                    redact=lambda _value: "[redacted]",
                )
                self.assertEqual(client.calls["get_heart_rates"], days // 2)
                self.assertEqual(client.calls["get_training_status"], 1)
                self.assertEqual(len(result["resting_hr"]), days)
                self.assertEqual(
                    sorted(row["calendarDate"] for row in result["resting_hr"]),
                    [
                        (start + timedelta(days=offset)).isoformat()
                        for offset in range(days)
                    ],
                )

    def test_garmin_range_collector_never_exceeds_two_parallel_calls(self):
        from backend.providers.garmin import collect_garmin_data

        class FakeGarmin:
            def __init__(self):
                self.active = 0
                self.maximum = 0
                self.lock = threading.Lock()

            def range_call(self, start, end):
                with self.lock:
                    self.active += 1
                    self.maximum = max(self.maximum, self.active)
                time.sleep(0.01)
                with self.lock:
                    self.active -= 1
                return [{"date": start, "end": end}]

            get_sleep_daily = range_call
            get_hrv_data_range = range_call
            get_body_battery = range_call
            get_activities_by_date = range_call

            def get_training_readiness(self, current):
                return {"date": current}

            def get_race_predictions(self):
                return []

            def get_max_metrics_range(self, start, end):
                return {"date": end}

        fake = FakeGarmin()
        collect_garmin_data(
            fake,
            [(date(2026, 8, 30), date(2026, 8, 31))],
            start=date(2026, 8, 30),
            today=date(2026, 8, 31),
            synced_at="2026-09-01T00:00:00+00:00",
            external_call=lambda _service, _source, operation, _details: operation(),
            redact=lambda value: value,
        )
        self.assertEqual(fake.maximum, 2)

    def test_plan_push_job_requires_bounded_selected_hashed_entries(self):
        local_id = str(uuid.uuid4())
        entry = {"library_workout_id": local_id, "expected_payload_hash": "a" * 64}
        job = server.SYNC_JOB_QUEUE.service().enqueue(
            "intervals", "plan_push", {"entries": [entry]}, requested_by="coach"
        )
        self.assertEqual(job["type"], "plan_push")
        self.assertEqual(job["payload"], {"entries": [entry], "reason": "job"})
        with self.assertRaises(AppError) as too_many:
            server.SYNC_JOB_QUEUE.service().enqueue(
                "intervals",
                "plan_push",
                {"entries": [entry] * 29},
                requested_by="coach",
            )
        self.assertEqual(too_many.exception.reason, "invalid_job_request")

    def test_build_training_context_uses_compact_activity_projection(self):
        today = server.ATHLETE_CLOCK.now().date()
        store_garmin_activities(
            server,
            [
                {
                    "activityId": f"ride-{index}",
                    "activityName": f"Ride {index}",
                    "activityType": {"typeKey": "cycling"},
                    "startTimeLocal": f"{today - timedelta(days=index)} 07:00:00",
                }
                for index in range(6)
            ],
        )
        context = server.COACH_CONTEXT.training_context_service().build()
        self.assertIn("Ride 0", context)
        self.assertNotIn("Ride 5", context)
        self.assertNotIn("LATEST INTERVALS.ICU SNAPSHOT", context)
        self.assertEqual(context.count('"local_planned_workouts"'), 1)
        preview = server.COACH_CONTEXT.preview_service().preview()
        # Activities of a read not vouched complete carry no sync time (#1728).
        self.assertFalse(preview["snapshot_compacted"])
        self.assertFalse(preview["snapshot_truncated"])
        self.assertTrue(preview["projection"]["within_total_budget"])

    def test_sync_period_supports_all_available_data_marker(self):
        from backend.sync.windows import split_date_windows

        repository = server.SYNC_PERSISTENCE.state_repository()
        self.assertEqual(
            repository.set_sync_period("garmin", -1, server.ALL_SYNC_DAYS),
            -1,
        )
        self.assertEqual(
            repository.sync_period(
                "garmin", server.SYNC_PERIOD_DEFAULTS, server.ALL_SYNC_DAYS
            ),
            -1,
        )
        self.assertEqual(
            repository.set_sync_period("garmin", -1, server.ALL_SYNC_DAYS),
            -1,
        )
        self.assertEqual(
            repository.sync_period(
                "garmin", server.SYNC_PERIOD_DEFAULTS, server.ALL_SYNC_DAYS
            ),
            -1,
        )
        self.assertGreater(
            len(
                split_date_windows(
                    -1,
                    end_date=date(2026, 8, 29),
                    earliest_date=server.SYNC_EARLIEST_DATE,
                    chunk_days=server.SYNC_CHUNK_DAYS,
                    all_days=server.ALL_SYNC_DAYS,
                )
            ),
            1,
        )

    def test_sync_window_helper_is_bounded_and_contiguous_without_app_globals(self):
        from backend.sync.windows import split_date_windows

        windows = split_date_windows(
            5,
            end_date=date(2026, 8, 29),
            earliest_date=date(2020, 1, 1),
            chunk_days=2,
            all_days=-1,
        )

        self.assertEqual(
            windows,
            [
                (date(2026, 8, 25), date(2026, 8, 26)),
                (date(2026, 8, 27), date(2026, 8, 28)),
                (date(2026, 8, 29), date(2026, 8, 29)),
            ],
        )
        with self.assertRaises(ValueError):
            split_date_windows(
                1,
                end_date=date(2026, 8, 29),
                earliest_date=date(2020, 1, 1),
                chunk_days=0,
                all_days=-1,
            )

    def test_explicit_competition_sync_records_create_change_and_delete_contract(self):
        event_date = (
            server.ATHLETE_CLOCK.now().date() + timedelta(days=30)
        ).isoformat()
        saved = server.PLANNING_DATA.competition().save(
            {
                "name": "Explicit race",
                "event_date": event_date,
                "sport": "Cycling",
            }
        )
        competition_id = saved["competition"]["id"]
        recorder = IntervalsRequestRecorder()
        client = RecordedIntervalsClient(recorder)
        with (
            patch.object(
                server.CONFIG_HOLDER,
                "value",
                replace(server.CONFIG_HOLDER.value, intervals_api_key="test-key"),
            ),
            patch.object(
                server.APP,
                "provider_transport",
                replace(
                    server.PROVIDER_TRANSPORT,
                    intervals_client=Mock(return_value=client),
                ),
            ),
        ):
            created = server.PROVIDER_RESYNC.competition_sync_service().sync(
                "explicit approval",
            )
            server.PLANNING_DATA.competition().save(
                {
                    "competition_id": competition_id,
                    "name": "Explicit race changed",
                    "event_date": event_date,
                    "sport": "Cycling",
                }
            )
            server.PLANNING_DATA.competition().delete(competition_id)
            deleted = server.PROVIDER_RESYNC.competition_sync_service().sync(
                "explicit approval",
            )
        self.assertEqual(created["pushed"], 1)
        self.assertEqual(deleted["deleted_remote"], 1)
        self.assertEqual(
            [call["method"] for call in recorder.mutations], ["POST", "DELETE"]
        )

    def test_full_garmin_resync_keeps_last_snapshot_on_provider_failure(self):
        save_garmin({"old": True})
        config = replace(server.CONFIG_HOLDER.value, garmin_fixture_path="fixture.json")
        with (
            patch.object(server.CONFIG_HOLDER, "value", config),
            patch.object(
                garmin_service.GarminSyncService,
                "sync",
                side_effect=RuntimeError("provider unavailable"),
            ),
            self.assertRaises(RuntimeError),
        ):
            server.PROVIDER_RESYNC.full_resync_service().resync("garmin")
        self.assertIs(read_garmin().get("old"), True)

    def test_full_resync_blocks_intervals_operations(self):
        self.assertTrue(server.INTERVALS_RESYNC_GATE.begin_reset())
        errors = []
        try:
            with patch.object(
                server.CONFIG_HOLDER,
                "value",
                replace(server.CONFIG_HOLDER.value, intervals_api_key="test-key"),
            ):

                def attempt_sync():
                    try:
                        server.SYNC_JOB_EXECUTION.executor().execute(
                            server.SYNC_JOB_QUEUE.service().enqueue(
                                "intervals",
                                "competition_push",
                                {"reason": "test", "approval_manifest": []},
                            )
                        )
                    except AppError as error:
                        errors.append(error)

                thread = threading.Thread(target=attempt_sync)
                thread.start()
                thread.join()
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].status, 409)
        finally:
            server.INTERVALS_RESYNC_GATE.end_reset()

    def test_full_garmin_resync_replaces_local_snapshot_without_touching_tokens(self):
        save_garmin({"old": True})
        server.key_value_service().set("last_garmin_sync_at", "old")
        with tempfile.TemporaryDirectory() as temp_root:
            fixture = Path(temp_root) / "garmin.json"
            fixture.write_text(
                json.dumps({"activities": [], "errors": []}), encoding="utf-8"
            )
            config = replace(
                server.CONFIG_HOLDER.value, garmin_fixture_path=str(fixture)
            )
            with patch.object(server.CONFIG_HOLDER, "value", config):
                result = server.PROVIDER_RESYNC.full_resync_service().resync("garmin")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(read_garmin().get("source"), "fixture")

    def test_all_time_snapshot_does_not_truncate_activity_history(self):
        snapshot = intervals_compaction.compact_snapshot(
            {},
            [{"id": str(index), "name": f"Ride {index}"} for index in range(600)],
            [{"id": f"2026-01-{index:02d}", "ctl": index} for index in range(1, 4)],
            [],
            history_days=-1,
            all_sync_days=server.ALL_SYNC_DAYS,
            synced_at=runtime_clock.utc_now(),
        )
        self.assertEqual(len(snapshot["recent_activities"]), 600)
        self.assertEqual(len(snapshot["recent_wellness"]), 3)

    def test_competition_sync_pushes_local_events_idempotently(self):
        event_date = (
            server.ATHLETE_CLOCK.now().date() + timedelta(days=60)
        ).isoformat()
        saved = server.PLANNING_DATA.competition().save(
            {
                "name": "Test Race",
                "event_date": event_date,
                "priority": "A",
                "sport": "Cycling",
            }
        )
        local_id = saved["competition"]["id"]
        calls = {}
        remote = []

        class FakeIntervalsClient:
            def fetch_competition_events(self):
                return list(remote)

            def upsert_competition_events(self, events):
                if not events:
                    return []
                calls["events"] = events
                created = {**events[0], "id": 12345}
                remote[:] = [created]
                return [created]

            def bulk_delete_events(self, identifiers):
                return 0

        with (
            patch.object(
                server.APP,
                "provider_transport",
                replace(
                    server.PROVIDER_TRANSPORT, intervals_client=FakeIntervalsClient
                ),
            ),
            patch.object(
                server.CONFIG_HOLDER,
                "value",
                replace(server.CONFIG_HOLDER.value, intervals_api_key="test-key"),
            ),
        ):
            result = server.PROVIDER_RESYNC.competition_sync_service().sync(
                "test",
            )
            second = server.PROVIDER_RESYNC.competition_sync_service().sync(
                "test",
            )

        self.assertEqual(result["pushed"], 1)
        self.assertEqual(second["pushed"], 0)
        self.assertEqual(calls["events"][0]["category"], "RACE_A")
        self.assertEqual(
            calls["events"][0]["external_id"],
            planning_competitions.competition_external_id(local_id),
        )
        synced = server.PLANNING_DATA.competition().list()[0]
        self.assertEqual(synced["intervals_event_id"], "12345")
        self.assertEqual(synced["sync_dirty"], 0)

    def test_competition_sync_skips_unsupported_local_sports(self):
        event_date = (
            server.ATHLETE_CLOCK.now().date() + timedelta(days=30)
        ).isoformat()
        server.PLANNING_DATA.competition().save(
            {"name": "Swim Race", "event_date": event_date, "sport": "Swim"}
        )
        pushed = []

        class FakeIntervalsClient:
            def fetch_competition_events(self):
                return []

            def upsert_competition_events(self, events):
                pushed.extend(events)
                return []

            def bulk_delete_events(self, identifiers):
                return 0

        with (
            patch.object(
                server.APP,
                "provider_transport",
                replace(
                    server.PROVIDER_TRANSPORT, intervals_client=FakeIntervalsClient
                ),
            ),
            patch.object(
                server.CONFIG_HOLDER,
                "value",
                replace(server.CONFIG_HOLDER.value, intervals_api_key="test-key"),
            ),
        ):
            result = server.PROVIDER_RESYNC.competition_sync_service().sync("test")

        self.assertEqual(result["pushed"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(pushed, [])
        self.assertEqual(
            server.PLANNING_DATA.competition().list()[0]["name"], "Swim Race"
        )

    def _synced_competition_with_remote_event(self):
        self.enterContext(
            patch.object(
                server.CONFIG_HOLDER,
                "value",
                replace(server.CONFIG_HOLDER.value, intervals_api_key="test-key"),
            )
        )
        self.enterContext(
            patch.object(
                server.ATHLETE_CLOCK,
                "now",
                return_value=datetime(2026, 9, 7, 12, tzinfo=UTC),
            )
        )
        item = server.PLANNING_DATA.competition().save(
            {"name": "Synthetic race", "event_date": "2026-10-01", "sport": "Cycling"}
        )["competition"]
        external = planning_competitions.competition_external_id(item["id"])
        with server.database_manager().unit_of_work() as db:
            db.execute(
                "UPDATE competitions SET intervals_event_id='123', external_id=?, sync_dirty=0, sync_state='synced' WHERE id=?",
                (external, item["id"]),
            )
        remote = {
            "id": 123,
            "external_id": external,
            "name": "Synthetic race",
            "start_date_local": "2026-10-01T08:00:00",
            "category": "RACE_B",
            "type": "Ride",
        }
        return item, remote

    def test_competition_fetch_preserves_a_concurrent_local_edit(self):
        item, remote = self._synced_competition_with_remote_event()

        def fetch(*args):
            server.PLANNING_DATA.competition().save(
                {"competition_id": item["id"], "name": "New local name"}
            )
            return [remote]

        client = Mock()
        client.fetch_competition_events.side_effect = fetch
        with patch.object(
            intervals_client_module, "IntervalsClient", return_value=client
        ):
            server.PROVIDER_RESYNC.competition_sync_service().sync()
        current = server.PLANNING_DATA.competition().list()[0]
        self.assertEqual(current["name"], "New local name")
        self.assertEqual(current["sync_dirty"], 1)

    def test_competition_tombstone_suppresses_import_before_and_after_remote_delete(
        self,
    ):
        item, remote = self._synced_competition_with_remote_event()
        server.PLANNING_DATA.competition().delete(item["id"])
        client = Mock()
        client.fetch_competition_events.return_value = [remote]
        with patch.object(
            intervals_client_module, "IntervalsClient", return_value=client
        ):
            server.PROVIDER_RESYNC.competition_sync_service().sync()
            self.assertEqual(server.PLANNING_DATA.competition().list(), [])
            server.PROVIDER_RESYNC.competition_sync_service().sync()
        self.assertEqual(server.PLANNING_DATA.competition().list(), [])
        client.bulk_delete_events.assert_called_once()

    def test_competition_remote_delete_only_acknowledges_captured_tombstones(self):
        item, remote = self._synced_competition_with_remote_event()
        server.PLANNING_DATA.competition().delete(item["id"])
        client = Mock()
        client.fetch_competition_events.return_value = [remote]

        def delete(_):
            with server.database_manager().unit_of_work() as db:
                db.execute(
                    "INSERT INTO competition_sync_tombstones VALUES ('later', '456', 'later-external', ?, NULL)",
                    (runtime_clock.utc_now(),),
                )

        client.bulk_delete_events.side_effect = delete
        with patch.object(
            intervals_client_module, "IntervalsClient", return_value=client
        ):
            server.PROVIDER_RESYNC.competition_sync_service().sync()
        with server.database_manager().unit_of_work() as db:
            self.assertEqual(
                [
                    row["id"]
                    for row in db.execute("SELECT id FROM competition_sync_tombstones")
                ],
                ["later"],
            )

    def test_intervals_snapshot_gives_no_threshold_recovery_or_load(self):
        today = server.ATHLETE_CLOCK.now().date().isoformat()
        snapshot = {
            "synced_at": f"{today}T00:00:00+00:00",
            "athlete": {"icu_ftp": 300, "lthr": 171},
            "recent_wellness": [
                {
                    "id": today,
                    "ctl": 70,
                    "atl": 76,
                    "tsb": -6,
                    "sleepSecs": 27000,
                    "readiness": 8,
                }
            ],
            "recent_activities": [
                {
                    "id": "ride-1",
                    "type": "Ride",
                    "start_date_local": today + "T07:00:00",
                    "moving_time": 7200,
                    "icu_training_load": 110,
                    "icu_weighted_avg_watts": 270,
                }
            ],
        }
        performance = _current_performance_context(snapshot)
        # Intervals.icu is output-only: its FTP, load history and wellness rows
        # give no current value (athlete decision 2026-11-07).
        self.assertIsNone(performance["thresholds"]["ftp_w"])
        self.assertNotIn("intervals_load_history", performance)
        self.assertIsNone(performance["recovery"]["sleep_hours"])
        # The local load (card M6) has no FTP for the session, and Intervals.icu's
        # 110 is no load: the session is counted as left out.
        last_7 = performance["rolling_training"]["last_7_days"]
        self.assertEqual(last_7["training_load"], 0.0)
        self.assertEqual(last_7["load_missing_sessions"], last_7["sessions"])
        self.assertNotIn("ai_estimates", performance)

    def test_stored_intervals_ctl_and_atl_give_no_load_or_form(self):
        today = server.ATHLETE_CLOCK.now().date().isoformat()
        snapshot = {
            "synced_at": "now",
            "athlete": {},
            "recent_wellness": [{"id": today, "ctl": 60, "atl": 72}],
            "recent_activities": [],
        }
        performance = _current_performance_context(snapshot)
        self.assertNotIn("intervals_load_history", performance)
        # Rows holding only CTL and ATL are no provider value at all.
        self.assertFalse(performance["available"])

    def test_intervals_eftp_is_not_read_from_settings_wellness_or_activities(
        self,
    ):
        today = server.ATHLETE_CLOCK.now().date().isoformat()
        snapshot = intervals_compaction.compact_snapshot(
            {
                "sportSettings": [{"types": ["Ride"], "ftp": 300, "eFTP": 309}],
            },
            [
                {
                    "id": "ride-1",
                    "start_date_local": f"{today}T08:00:00",
                    "type": "Ride",
                    "icu_ftp": 300,
                    "icu_eftp": 300,
                }
            ],
            [{"id": today, "sportInfo": [{"types": ["Ride"], "eFTP": 274}]}],
            [],
            all_sync_days=server.ALL_SYNC_DAYS,
            synced_at=runtime_clock.utc_now(),
        )

        performance = _current_performance_context(snapshot)
        metrics = performance["metrics"]
        self.assertIsNone(metrics["cycling_ftp_watts"]["value"])
        # Intervals.icu eFTP is no longer read by any view (#1727).
        self.assertNotIn("cycling_eftp_watts", metrics)
        self.assertNotIn("cycling_eftp_30d", performance.get("comparisons") or {})
        validation = performance["activity_validation"]
        self.assertNotIn(
            "cycling_eftp_watts",
            [item["metric"] for item in validation["provider_references"]],
        )
        estimates = validation["direct_activity_estimates"]
        self.assertNotIn("activity_eftp_watts", estimates)
        self.assertEqual(estimates["activity_configured_ftp_watts"], 300)

    def test_selected_library_sync_is_exact_and_reports_per_object(self):
        first = server.PLANNING_DATA.workout_library().create_local_entry(
            {
                "sport": "Ride",
                "name": "Remote eins",
                "description": "- 30m Z2",
                "duration_minutes": 30,
            }
        )
        second = server.PLANNING_DATA.workout_library().create_local_entry(
            {
                "sport": "Run",
                "name": "Remote zwei",
                "description": "- 20m 60% Easy",
                "duration_minutes": 20,
            }
        )
        config = replace(
            server.CONFIG_HOLDER.value, intervals_api_key="fake-intervals-key"
        )
        with (
            patch.object(server.CONFIG_HOLDER, "value", config),
            patch.object(
                WorkoutLibrarySyncService,
                "sync_entry",
                side_effect=[
                    {"id": first["id"], "external_id": "remote-1"},
                    AppError(502, "provider unavailable"),
                ],
            ) as sync_entry,
        ):
            pending = {
                item["library_workout_id"]: item
                for item in server.SYNC_COMMANDS.authority().pending_plan_push_entries()
            }
            result = server.SELECTED_WORKOUT_SYNC.service().sync(
                {"entries": [pending[first["id"]], pending[second["id"]]]}
            )
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][0]["status"], "synced")
        self.assertEqual(result["results"][1]["status"], "error")
        self.assertEqual(result["failed_object_ids"], [second["id"]])
        self.assertEqual(
            [call.args[0] for call in sync_entry.call_args_list],
            [first["id"], second["id"]],
        )

    def test_garmin_sync_persists_fatal_error_status(self):
        config = replace(
            server.CONFIG_HOLDER.value,
            garmin_fixture_path="missing-garmin-fixture.json",
        )
        with (
            patch.object(server.CONFIG_HOLDER, "value", config),
            self.assertRaises(AppError),
        ):
            server.GARMIN_ASSEMBLY.sync_service().sync()
        state = server.GARMIN_ASSEMBLY.projection_service().public_state()
        self.assertTrue(state["last_error"])

    def test_one_garmin_change_check_follows_the_personal_key(self):
        # One check per process keeps its cadence and one Personal API client
        # per key, so the 24-hour token is reused across loop passes (#2303).
        check = server.GARMIN_ASSEMBLY.change_check()
        self.assertIs(check, server.GARMIN_ASSEMBLY.change_check())
        policy = server.SYNC_SCHEDULERS.daily_scheduler()._policies["garmin"]
        self.assertIs(check, policy._change_check)
        report = server.DIAGNOSTICS.report_service().report()
        self.assertEqual(
            check.status()["checks"], report["garmin_change_check"]["checks"]
        )
        for key, active in (("", False), ("synthetic-personal-key", True)):
            config = replace(
                server.CONFIG_HOLDER.value,
                garmin_personal_api_key=key,
                garmin_fixture_path="",
            )
            with (
                self.subTest(key=bool(key)),
                patch.object(server.CONFIG_HOLDER, "value", config),
            ):
                self.assertEqual(active, check.active())
                self.assertIs(
                    server.GARMIN_ASSEMBLY.change_personal_client(),
                    server.GARMIN_ASSEMBLY.change_personal_client(),
                )

    def test_daily_sync_markers_are_separate_per_provider(self):
        local_day = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
        markers = server.SYNC_PERSISTENCE.daily_markers()
        markers.mark("wahoo", local_day)
        self.assertFalse(markers.is_due("wahoo", local_day))
        self.assertTrue(markers.is_due("wahoo", local_day + timedelta(hours=1)))
        self.assertTrue(markers.is_due("garmin", local_day))
        self.assertTrue(markers.is_due("calendar", local_day))
        with patch.object(server.ATHLETE_CLOCK, "now", return_value=local_day):
            server.SYNC_JOB_QUEUE.service().enqueue(
                "calendar", "refresh", {}, requested_by="scheduler"
            )
        self.assertFalse(markers.is_due("calendar", local_day))
        self.assertTrue(markers.is_due("calendar", local_day + timedelta(hours=1)))


if __name__ == "__main__":
    unittest.main()
