"""Server integration tests for sync."""

import json
import sys
import tempfile
import threading
import unittest
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from unittest.mock import call, Mock, patch
from urllib.error import HTTPError

from backend.activities.duplicates import filter_garmin_activities, garmin_activity_duplicates_intervals, intervals_cycling_activities_match, latest_wahoo_garmin_duplicate
from backend.http_api import server as http_server_module
from backend.performance import current_metrics as performance_current_metrics, garmin_observations
from backend.planning import adaptive as planning_adaptive, competitions as planning_competitions, context as planning_context, library as planning_library
from backend.providers import intervals_client as intervals_client_module
from backend.sync.intervals import IntervalsSnapshotReader, IntervalsSyncService
from backend.sync.intervals_lock import INTERVALS_SYNC_LOCK
from backend.sync.library import WorkoutLibraryRefreshService, WorkoutLibrarySyncService
from backend.sync.performance import PerformanceRefreshFollowupService
from backend.sync.selected import SelectedWorkoutSyncService
from server_test_support import _current_performance_context, _garmin_metrics, server, ServerTestCase
from support import IntervalsRequestRecorder, parsed_workout_fixture, RecordedIntervalsClient


class ServerSyncTests(ServerTestCase):

    def _prepare_remote_contract_fixture(self, include_competition=False):
        recorder = IntervalsRequestRecorder()
        client = RecordedIntervalsClient(recorder)
        server.workout_library_service().create_local_entry({
            "sport": "Ride",
            "name": "Contract fixture",
            "description": "- 30m Z2",
            "duration_minutes": 30,
            "target": "POWER",
            "rationale": "Test",
        })
        if include_competition:
            server.athlete_context_service().save({}, [{
                "name": "Contract race",
                "event_date": (date.today() + timedelta(days=30)).isoformat(),
                "sport": "Cycling",
            }])
        return recorder, client

    def _prepare_competition_contract_fixture(self):
        recorder = IntervalsRequestRecorder()
        client = RecordedIntervalsClient(recorder)
        server.athlete_context_service().save({}, [{
            "name": "Competition contract",
            "event_date": (date.today() + timedelta(days=30)).isoformat(),
            "sport": "Cycling",
        }])
        return recorder, client

    def test_startup_explicitly_recovers_jobs_before_starting_workers(self):
        order = []
        http_server = Mock()
        http_server_factory = Mock(return_value=http_server)
        with patch.object(server.observability, "configure_logging"), patch.object(
            server.app_config, "security_configuration_error", return_value=None
        ), patch.object(server, "initialise_database", side_effect=lambda: order.append("schema")), patch.object(
            server.SyncJobQueueService,
            "resume_interrupted",
            side_effect=lambda: order.append("sync-recovery"),
        ), patch(
            "backend.coach.job_store.CoachJobStore.resume_interrupted", side_effect=lambda *_: order.append("coach-recovery")
        ), patch.object(http_server_module, "CoachHTTPServer", http_server_factory), patch.object(
            server.SyncJobWorker, "start", side_effect=lambda _worker: order.append("sync-worker"), autospec=True
        ), patch.object(
            server.COACH_JOB_WORKER, "start", side_effect=lambda *_: order.append("coach-worker")
        ), patch.object(server.COACH_JOB_WORKER, "stop") as coach_stop, patch.object(
            server.COACH_JOB_WORKER, "join"
        ) as coach_join, patch.object(server.SyncJobWorker, "stop") as sync_stop, patch.object(
            server.SyncJobWorker, "join"
        ) as sync_join, patch.object(server, "startup_sync_scheduler") as startup_scheduler, patch.object(
            server, "daily_sync_loop_service"
        ) as daily_loop_factory, patch.object(server.threading, "Thread") as thread_factory:
            startup_scheduler.return_value.schedule.side_effect = lambda: order.append("startup-sync")
            daily_loop = Mock()
            daily_loop_factory.return_value = daily_loop
            server.main()
        http_server_factory.assert_called_once()
        address, handler_class = http_server_factory.call_args.args
        self.assertEqual(address, ("0.0.0.0", server.CONFIG.port))
        self.assertTrue(issubclass(handler_class, server.BaseHTTPRequestHandler))
        self.assertIsInstance(handler_class.static_asset_service, server.StaticAssetService)
        self.assertEqual(handler_class.static_asset_service._targets["index.html"], server.PUBLIC_DIR / "index.html")
        thread_factory.assert_called_once_with(target=daily_loop.run, daemon=True)
        self.assertEqual(
            order,
            ["schema", "sync-recovery", "coach-recovery", "sync-worker", "coach-worker", "startup-sync"],
        )
        daily_loop.stop.assert_called_once_with()
        http_server.server_close.assert_called_once_with()
        thread_factory.return_value.join.assert_called_once_with(timeout=5)
        sync_stop.assert_called_once_with()
        sync_join.assert_called_once_with(timeout=5)
        coach_stop.assert_called_once_with()
        coach_join.assert_called_once_with(timeout=5)

    def test_persistent_sync_job_claim_resume_retry_and_completion(self):
        job = server.sync_job_queue_service().enqueue(
            "intervals", "refresh", {"days": 7}, requested_by="user"
        )
        self.assertEqual(job["status"], "queued")
        self.assertEqual(job["progress"], {"completed": 0, "total": 1})
        claimed = server.sync_job_store().claim()
        self.assertEqual(claimed["id"], job["id"])
        self.assertEqual(
            server.sync_job_queue_service().state(job["id"])["status"], "running"
        )
        self.assertEqual(server.sync_job_queue_service().resume_interrupted(), 1)
        self.assertEqual(
            server.sync_job_queue_service().state(job["id"])["status"], "queued"
        )
        claimed = server.sync_job_store().claim()
        with patch.object(server.SyncJobExecutor, "execute", return_value={"status": "ok"}):
            server.sync_job_executor().run(claimed)
        completed = server.sync_job_queue_service().state(job["id"])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(completed["progress"], {"completed": 1, "total": 1})
        self.assertEqual(completed["items"][0]["status"], "completed")

    def test_persistent_sync_job_retries_only_safe_transient_errors(self):
        job = server.sync_job_queue_service().enqueue(
            "weather", "refresh", {"force": True}
        )
        claimed = server.sync_job_store().claim()
        provider_detail = "https://athlete:secret-pass@example.invalid/private-token-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        with patch.object(server.SyncJobExecutor, "execute", side_effect=server.AppError(503, provider_detail, reason="network_error")):
            server.sync_job_executor().run(claimed)
        state = server.sync_job_queue_service().state(job["id"])
        self.assertEqual(state["status"], "queued")
        self.assertEqual(state["error_class"], "network_error")
        self.assertEqual(state["items"][0]["status"], "queued")
        self.assertIsNotNone(state["available_at"])
        self.assertNotIn("secret-pass", state["items"][0]["error_detail"])
        self.assertNotIn("private-token-aaaaaaaa", state["items"][0]["error_detail"])

    def test_plan_push_job_preserves_all_failed_object_outcomes(self):
        local_id = str(uuid.uuid4())
        job = server.sync_job_queue_service().enqueue(
            "intervals",
            "plan_push",
            {"entries": [{"library_workout_id": local_id, "expected_payload_hash": "a" * 64}]},
            requested_by="coach",
            item_operations=[{"item_key": local_id, "operation": "plan_push", "payload_hash": "a" * 64}],
        )
        claimed = server.sync_job_store().claim()
        result = {"status": "error", "results": [{"library_workout_id": local_id, "status": "conflict", "error": "changed"}]}
        with patch.object(server.SyncJobExecutor, "execute", return_value=result):
            server.sync_job_executor().run(claimed)
        state = server.sync_job_queue_service().state(job["id"])
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["items"][0]["status"], "failed")
        self.assertEqual(state["progress"], {"completed": 1, "total": 1})

    def test_replacement_follow_up_sync_accepts_complete_plan_size(self):
        planned = server.local_plan_creation_service().save([
            {"date": (date.today() + timedelta(days=index + 1)).isoformat(), "sport": "Run",
             "name": "Synthetic replacement run", "description": "- 30m 60% Synthetic easy session", "duration_minutes": 30}
            for index in range(planning_library.LIBRARY_BULK_MAX_ENTRIES + 1)
        ])
        local_ids = [item["id"] for item in planned]
        entries = [item for item in server.planning_authority_service().pending_plan_push_entries() if item["library_workout_id"] in local_ids]
        intent = {
            "intent": "remote_sync", "operation": "replace_training_plan", "target_system": "intervals",
            "artifact_id": None, "ambiguities": [],
            "authorization_scope": ["local_plan", *(f"library_workout:{local_id}" for local_id in local_ids)],
            "follow_up_operations": ["start_intervals_plan_sync"],
            "_replacement_sync_entry_ids": local_ids,
        }

        with patch.object(server.PlanningAuthorityService, "mark_planning_authoritative"), patch.object(
            server.PlanPushCommandService, "enqueue", return_value={"ok": True, "status": "queued"},
        ) as enqueue:
            result = server.coach_tool_dispatch_service().execute(
                "start_intervals_plan_sync", {"entries": entries}, intent=intent,
                conversation_id="conversation-large-replacement", client_turn_id="turn-large-replacement",
                session_csrf_hash="", sync_job_ids=[],
            )

        self.assertEqual(result["status"], "queued")
        self.assertEqual(len(enqueue.call_args.args[0]), len(local_ids))

    def test_same_turn_plan_sync_rejects_a_subset_of_created_entries(self):
        local_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        intent = {
            "intent": "remote_sync", "operation": "stage_training_plan", "target_system": "intervals",
            "artifact_id": None, "ambiguities": [],
            "authorization_scope": [*(f"library_workout:{local_id}" for local_id in local_ids)],
            "follow_up_operations": ["commit_training_plan", "start_intervals_plan_sync"],
            "_sync_created_entries_only": True,
            "_created_sync_entry_ids": local_ids,
        }
        entries = [{"library_workout_id": local_ids[0], "expected_payload_hash": "b" * 64}]

        with patch.object(server.PlanPushCommandService, "enqueue") as enqueue, self.assertRaises(server.AppError) as error:
            server.coach_tool_dispatch_service().execute(
                "start_intervals_plan_sync", {"entries": entries}, intent=intent,
                conversation_id="conversation-created-subset", client_turn_id="turn-created-subset",
                session_csrf_hash="", sync_job_ids=[],
            )

        self.assertEqual(error.exception.reason, "intent_scope_denied")
        enqueue.assert_not_called()

    def test_new_intervals_job_types_execute_only_their_targeted_operation(self):
        performance_job = {
            "id": "job-performance", "provider": "intervals", "type": "performance_refresh",
            "payload": json.dumps({"reason": "Coach request"}),
        }
        competition_job = {
            "id": "job-competition", "provider": "intervals", "type": "competition_push",
            "payload": json.dumps({"reason": "Coach request"}),
        }
        performance_service = Mock()
        performance_service.refresh.return_value = {"status": "ok"}
        competition_service = Mock()
        competition_service.sync.return_value = {"status": "ok", "pushed": 1}
        with patch.object(server, "performance_refresh_service", return_value=performance_service), patch.object(
            server, "competition_sync_service", return_value=competition_service
        ):
            self.assertEqual(server.sync_job_executor().execute(performance_job)["status"], "ok")
            self.assertEqual(server.sync_job_executor().execute(competition_job)["pushed"], 1)
        performance_service.refresh.assert_called_once_with()
        competition_service.sync.assert_called_once_with(
            reason="Coach request", push_local=True
        )

    def test_normalized_intervals_job_type_dispatches_targeted_operation(self):
        refresh_job = {
            "id": "job-normalized-performance", "provider": "intervals", "type": " PERFORMANCE_REFRESH ",
            "payload": json.dumps({"reason": "Coach request"}),
        }
        performance_service = Mock()
        performance_service.refresh.return_value = {"status": "ok"}
        with patch.object(server, "performance_refresh_service", return_value=performance_service), patch.object(
            IntervalsSyncService,
            "sync",
            side_effect=AssertionError("normalized job fell through to full sync"),
        ):
            self.assertEqual(server.sync_job_executor().execute(refresh_job)["status"], "ok")
        performance_service.refresh.assert_called_once_with()

    def test_intervals_job_delegates_performance_follow_up_to_common_sync_path(self):
        refresh_job = {
            "id": "job-refresh", "provider": "intervals", "type": "refresh",
            "payload": json.dumps({"days": 90, "reason": "tägliche automatische Aktualisierung"}),
        }
        competition_service = Mock()
        competition_service.sync.return_value = {"status": "ok"}
        with patch.object(IntervalsSyncService, "sync", return_value={"status": "ok"}) as sync, patch.object(
            server, "competition_sync_service", return_value=competition_service
        ), patch.object(
            server.SyncJobQueueService,
            "enqueue",
            return_value={"id": "job-performance-follow-up"},
        ) as enqueue:
            result = server.sync_job_executor().execute(refresh_job)
        self.assertEqual(result["status"], "ok")
        sync.assert_called_once()
        enqueue.assert_not_called()

    def test_sync_intervals_queues_performance_follow_up_for_current_refresh(self):
        snapshot = {"synced_at": "now", "athlete": {}, "recent_activities": [], "recent_wellness": [], "upcoming_calendar": []}
        config = replace(server.CONFIG, intervals_api_key="test-key")
        with patch.object(server, "CONFIG", config), patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=snapshot
        ), patch.object(WorkoutLibraryRefreshService, "refresh", return_value={"workouts": 0}), patch.object(
            PerformanceRefreshFollowupService,
            "enqueue_after_sync",
            return_value={"id": "job-performance-follow-up"},
        ) as enqueue, patch.object(PerformanceRefreshFollowupService, "wait") as wait:
            result = server.intervals_sync_service().sync(
                "startup", activity_days=90, wait_for_performance=True
            )
        self.assertEqual(result["performance_refresh_job_id"], "job-performance-follow-up")
        enqueue.assert_called_once_with("startup")
        wait.assert_called_once_with("job-performance-follow-up", cancel_event=None)

    def test_apply_result_deduplicates_changed_ids_for_sync(self):
        planned = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=9)).isoformat(),
            "sport": "Ride", "name": "Repeated", "description": "- 20m 60% easy",
        })
        intent = {
            "intent": "local_action", "operation": "apply_training_changes", "target_system": "local",
            "artifact_id": None, "ambiguities": [], "authorization_scope": ["local_plan"],
        }
        result = server.coach_tool_dispatch_service().execute(
            "apply_training_changes",
            {"changes": [
                {"local_id": planned["id"], "action": "update", "name": "First"},
                {"local_id": planned["id"], "action": "update", "name": "Second"},
            ]},
            intent=intent, conversation_id="conversation-dedup", client_turn_id="turn-dedup",
            session_csrf_hash="", sync_job_ids=[],
        )
        self.assertEqual(result["library_entry_ids"], [planned["id"]])

    def test_changed_batch_sync_is_limited_to_changed_entries(self):
        changed = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=6)).isoformat(),
            "sport": "Ride", "name": "Changed", "description": "- 20m 60% easy",
        })
        untouched = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=7)).isoformat(),
            "sport": "Run", "name": "Untouched", "description": "- 20m 60% easy",
        })
        intent = {
            "intent": "remote_sync", "operation": "start_intervals_plan_sync", "target_system": "intervals",
            "artifact_id": None, "ambiguities": [],
            "authorization_scope": [f"library_workout:{changed['id']}"],
            "_sync_changed_entries_only": True, "_changed_sync_entry_ids": [changed["id"]],
        }
        with patch.object(server.SyncJobQueueService, "enqueue", return_value={"id": "job-changed"}) as enqueue:
            result = server.coach_tool_dispatch_service().execute(
                "start_intervals_plan_sync", {}, intent=intent,
                conversation_id="conversation-changed-sync", client_turn_id="turn-changed-sync",
                session_csrf_hash="", sync_job_ids=[],
            )
        queued = enqueue.call_args.args[2]["entries"]
        self.assertEqual({item["library_workout_id"] for item in queued}, {changed["id"]})
        self.assertNotEqual(changed["id"], untouched["id"])
        self.assertEqual(result["status"], "queued")

    def test_changed_batch_sync_accepts_the_coach_change_limit(self):
        for index in range(101):
            server.planned_unit_service().create({
                "date": (date.today() + timedelta(days=index + 10)).isoformat(),
                "sport": "Ride", "name": f"Changed {index}", "description": "- 20m 60% easy",
            })
        pending = server.planning_authority_service().pending_plan_push_entries()
        selected = pending[:101]
        intent = {
            "intent": "remote_sync", "operation": "start_intervals_plan_sync", "target_system": "intervals",
            "artifact_id": None, "ambiguities": [],
            "authorization_scope": [f"library_workout:{item['library_workout_id']}" for item in selected],
            "_sync_changed_entries_only": True,
            "_changed_sync_entry_ids": [item["library_workout_id"] for item in selected],
        }
        with patch.object(server.SyncJobQueueService, "enqueue", return_value={"id": "job-large-changed"}) as enqueue:
            result = server.coach_tool_dispatch_service().execute(
                "start_intervals_plan_sync", {"entries": selected}, intent=intent,
                conversation_id="conversation-large-changed", client_turn_id="turn-large-changed",
                session_csrf_hash="", sync_job_ids=[],
            )
        queued = [entry for call in enqueue.call_args_list for entry in call.args[2]["entries"]]
        self.assertEqual(len(queued), 101)
        self.assertEqual(enqueue.call_count, 4)
        self.assertEqual(result["status"], "queued")

    def test_sync_status_is_bounded_and_contains_versions(self):
        server.key_value_service().set("sync_operation_id", "operation-test")
        server.key_value_service().set("sync_operation_status", "running")
        server.key_value_service().set("sync_operation_phase", "fetching")
        server.key_value_service().set("sync_operation_progress", "35")
        server.key_value_service().set("sync_operation_message", "Daten werden gelesen…")
        with patch.object(server, "state_version_service") as versions:
            versions.return_value.versions.return_value = {"activities": "v1"}
            status = server.sync_public_state_service().state()
        self.assertEqual(status["operation_id"], "operation-test")
        self.assertEqual(status["phase"], "fetching")
        self.assertEqual(status["progress"], 35)
        bootstrap = server.public_bootstrap_service().read()
        self.assertEqual(bootstrap["sync"]["progress"], 35)
        self.assertEqual(bootstrap["sync"]["message"], "Daten werden gelesen…")

    def test_sync_status_projection_is_dependency_light(self):
        from backend.sync.status import persist_sync_operation_state, project_sync_status

        values = {}
        persist_sync_operation_state(
            "operation-test",
            "running",
            "fetching",
            140,
            "Daten werden gelesen",
            "secret provider detail",
            set_value=values.__setitem__,
            redact=lambda value: f"redacted:{value}",
        )
        self.assertEqual(values["sync_operation_progress"], "100")
        self.assertEqual(values["last_sync_error"], "redacted:secret provider detail")
        status = project_sync_status(
            running=True,
            get_value=values.get,
            state_versions={"activities": "v1"},
            provider_freshness=[],
            maintenance={"active": False, "running_operations": 0},
        )
        self.assertEqual(status["phase"], "fetching")
        self.assertEqual(status["state_versions"], {"activities": "v1"})
        self.assertNotIn("activities", json.dumps(status["message"]))

    def test_daily_sync_markers_are_separate_per_provider(self):
        local_day = datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)
        markers = server.daily_sync_marker_service()
        markers.mark("intervals", local_day)
        self.assertFalse(markers.is_due("intervals", local_day))
        self.assertTrue(markers.is_due("intervals", local_day + timedelta(hours=1)))
        self.assertTrue(markers.is_due("garmin", local_day))
        self.assertTrue(markers.is_due("calendar", local_day))
        with patch.object(server.ATHLETE_CLOCK, "now", return_value=local_day):
            server.sync_job_queue_service().enqueue(
                "calendar", "refresh", {}, requested_by="scheduler"
            )
        self.assertFalse(markers.is_due("calendar", local_day))
        self.assertTrue(markers.is_due("calendar", local_day + timedelta(hours=1)))

    def test_daily_sync_marker_module_is_dependency_light(self):
        from backend.sync.daily import daily_sync_is_due, mark_daily_sync, mark_daily_sync_attempt

        values = {}
        current = datetime(2026, 3, 30, 0, 30, tzinfo=timezone.utc)

        self.assertTrue(daily_sync_is_due("intervals", current, get_value=values.get))
        mark_daily_sync("intervals", current, set_value=values.__setitem__)
        self.assertEqual(values["sync_intervals_last_success_at"], current.isoformat())
        self.assertFalse(daily_sync_is_due("intervals", current, get_value=values.get))
        self.assertTrue(daily_sync_is_due("intervals", current + timedelta(hours=1), get_value=values.get))
        mark_daily_sync_attempt("intervals", current + timedelta(hours=2), set_value=values.__setitem__)
        self.assertFalse(daily_sync_is_due("intervals", current + timedelta(hours=2), get_value=values.get))
        self.assertTrue(daily_sync_is_due("intervals", current + timedelta(hours=3), get_value=values.get))

    def test_daily_sync_scheduler_uses_local_provider_markers(self):
        import inspect

        from backend.sync.scheduler import DailySyncScheduler

        self.assertEqual(DailySyncScheduler.__module__, "backend.sync.scheduler")
        source = Path(sys.modules[DailySyncScheduler.__module__].__file__).resolve()
        module_source = source.read_text(encoding="utf-8")
        daily_scheduler = inspect.getsource(DailySyncScheduler)
        self.assertIn('self._markers.is_due("calendar")', daily_scheduler)
        self.assertIn('self._markers.is_due("garmin")', daily_scheduler)
        self.assertIn('self._markers.is_due("intervals")', daily_scheduler)
        self.assertNotIn("import server", module_source)
        self.assertNotIn("from server", module_source)
        self.assertNotIn('[:10]', daily_scheduler)

    def test_sync_status_exposes_non_sensitive_maintenance_state(self):
        status = server.sync_public_state_service().state()
        self.assertEqual(set(status["maintenance"]), {"active", "running_operations"})
        self.assertFalse(status["maintenance"]["active"])

    def test_illness_pause_can_sync_sick_events_after_confirmation(self):
        server.checkin_service().save({"illness": "Erkältung"})
        preview = server.adaptive_replan_preview_service().preview()
        calls = []

        class FakeIntervalsClient:
            def upsert_calendar_events(self, events):
                calls.extend(events)
                return [{"id": index} for index, _ in enumerate(events, 1)]

        with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(
            server, "intervals_client", return_value=FakeIntervalsClient()
        ):
            result = server.illness_pause_sync_service().apply(preview["id"], sync_illness_to_intervals=True)

        self.assertEqual(result["intervals_sync"]["status"], "ok")
        self.assertEqual(result["intervals_sync"]["category"], "SICK")
        self.assertEqual(len(calls), planning_adaptive.DEFAULT_ILLNESS_PAUSE_DAYS)
        self.assertTrue(all(event["category"] == "SICK" for event in calls))
        self.assertEqual(calls[0]["name"], "Krankheit")

    def test_compact_snapshot_drops_unknown_and_sensitive_fields(self):
        result = planning_context.compact_snapshot(
            {"id": "i1", "name": "Ada", "secret": "nope"},
            [{"id": "a1", "name": "Ride", "icu_vo2max": 52, "vO2MaxValue": 53, "private_note": "nope"}],
            [{"id": "2026-01-01", "ctl": 42, "unknown": 99}],
            [{"id": 1, "name": "Tempo", "category": "WORKOUT", "raw": "nope"}],
            all_sync_days=server.ALL_SYNC_DAYS,
            synced_at=server.utc_now(),
        )
        self.assertEqual(result["athlete"]["name"], "Ada")
        self.assertNotIn("secret", result["athlete"])
        self.assertNotIn("private_note", result["recent_activities"][0])
        self.assertEqual(result["recent_activities"][0]["icu_vo2max"], 52)
        self.assertEqual(result["recent_activities"][0]["vO2MaxValue"], 53)
        self.assertEqual(result["recent_wellness"][0]["ctl"], 42)

    def test_manual_competition_normalizes_intervals_event_fields(self):
        competition = planning_competitions.normalize_competition({
            "name": "Alpenbrevet", "event_date": "2026-09-20", "start_date_local": "2026-09-20T06:30",
            "sport": "Radfahren", "category": "RACE_A", "description": "Lange Bergetappe",
            "moving_time": "21600", "distance": "250 km", "target": "Finish", "external_id": "alpenbrevet-2026",
        })
        self.assertEqual(competition["event_date"], "2026-09-20")
        self.assertEqual(competition["start_date_local"], "2026-09-20T06:30:00")
        self.assertEqual(competition["category"], "RACE_A")
        self.assertEqual(competition["moving_time"], 21600)
        self.assertEqual(competition["distance"], "250000")
        self.assertEqual(planning_competitions.competition_event_payload(competition)["type"], "Ride")
        self.assertEqual(planning_competitions.competition_event_payload(competition)["distance"], 250000)

    def test_remote_competition_updates_all_intervals_event_fields(self):
        data = planning_competitions.remote_competition_data({
            "id": 42, "category": "RACE_C", "start_date_local": "2026-09-20T07:15:00",
            "type": "Run", "name": "Remote Race", "description": "Remote description",
            "moving_time": 7200, "distance": 21097, "target": "Sub 2:00",
        })
        self.assertEqual(data["intervals_event_id"], "42")
        self.assertEqual(data["category"], "RACE_C")
        self.assertEqual(data["priority"], "C")
        self.assertEqual(data["start_date_local"], "2026-09-20T07:15:00")
        self.assertEqual(data["moving_time"], 7200)
        self.assertEqual(data["distance"], "21097")
        self.assertEqual(data["target"], "Sub 2:00")

    def test_max_heart_rate_uses_intervals_fallback_for_both_sports(self):
        snapshot = {
            "athlete": {"sport_settings": [
                {"types": ["Ride"], "max_hr": 188},
                {"types": ["Run"], "max_hr": 193},
            ]},
            "recent_activities": [], "recent_wellness": [],
        }
        metrics = performance_current_metrics.current_performance_metrics(
            snapshot,
            server.profile_service().get(),
            _garmin_metrics(server.garmin_payload_service().snapshot()),
        )
        self.assertEqual(metrics["cycling_max_hr_bpm"]["value"], 188)
        self.assertEqual(metrics["cycling_max_hr_bpm"]["source"], "Intervals.icu")
        self.assertEqual(metrics["running_max_hr_bpm"]["value"], 193)
        self.assertEqual(metrics["running_max_hr_bpm"]["source"], "Intervals.icu")

    def test_garmin_daily_health_is_averaged_over_the_last_seven_days(self):
        today = server.ATHLETE_CLOCK.now().date()
        server.key_value_service().set("garmin_snapshot", json.dumps({
            "daily_stats": [
                {
                    "calendarDate": today.isoformat(),
                    "totalSteps": 1,
                    "floorsAscended": 0,
                    "totalKilocalories": 10,
                },
                *[{
                    "calendarDate": (today - timedelta(days=offset + 1)).isoformat(),
                    "totalSteps": 1000 + offset * 100,
                    "floorsAscended": 5 + offset,
                    "totalKilocalories": 2000 + offset * 10,
                } for offset in range(7)],
            ]
        }))
        performance = _current_performance_context({
            "synced_at": "now", "athlete": {}, "recent_activities": [], "recent_wellness": []
        })
        self.assertEqual(performance["metrics"]["steps_7d"], {
            "value": 1300, "unit": "Schritte/Tag", "source": "Garmin Connect",
            "note": "Durchschnitt der letzten 7 Tage",
            "freshness": "unknown", "fetched_at": None, "observed_at": None,
            "measurement_status": "unknown", "measurement_age_days": None,
        })
        self.assertIsInstance(performance["metrics"]["steps_7d"]["value"], int)
        self.assertEqual(performance["metrics"]["floors_7d"]["value"], 8)
        self.assertIsInstance(performance["metrics"]["floors_7d"]["value"], int)
        self.assertEqual(performance["metrics"]["calories_7d"]["value"], 2030)

    def test_performance_does_not_compare_garmin_metrics_to_intervals_history(self):
        today = server.ATHLETE_CLOCK.now().date()
        snapshot = {
            "synced_at": "now", "athlete": {}, "recent_activities": [],
            "recent_wellness": [{"id": today.isoformat(), "sport_info": [{"types": ["Ride"], "ftp": 280}]}],
        }
        server.key_value_service().set("garmin_snapshot", json.dumps({
            "cycling_ftp": {"functionalThresholdPower": 300},
            "performance_history": [],
        }))

        comparison = _current_performance_context(snapshot)["comparisons"]["cycling_ftp_watts_30d"]
        self.assertIsNone(comparison)

    def test_existing_snapshot_uses_configured_intervals_window(self):
        server.sync_state_repository().save_snapshot({"synced_at": "2026-08-28T08:00:00+00:00", "athlete": {}, "recent_activities": [{"id": "old"}], "recent_wellness": [], "upcoming_calendar": []})
        calls = []

        def fake_get(path, params=None):
            calls.append((path, params or {}))
            if path.endswith("/activities"):
                return [{"id": "new", "start_date_local": "2026-08-29T08:00:00"}]
            if path.endswith("/wellness"):
                return []
            if path.endswith("/events"):
                return []
            return {}

        with patch.object(
            server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")
        ):
            reader = server.intervals_snapshot_reader()
            with patch.object(reader._api_client, "get", side_effect=fake_get):
                snapshot = reader.fetch_snapshot(activity_days=90)
        activity_call = next(params for path, params in calls if path.endswith("/activities"))
        self.assertEqual((date.fromisoformat(activity_call["newest"]) - date.fromisoformat(activity_call["oldest"])).days, 89)
        event_call = next(params for path, params in calls if path.endswith("/events"))
        self.assertEqual(date.fromisoformat(event_call["oldest"]), server.ATHLETE_CLOCK.now().date() - timedelta(days=server.PLANNED_CALENDAR_HISTORY_DAYS))
        self.assertEqual(date.fromisoformat(event_call["newest"]), server.ATHLETE_CLOCK.now().date() + timedelta(days=server.PLANNED_CALENDAR_FUTURE_DAYS))
        self.assertEqual(snapshot["provider_sync"]["calendar_window"]["start"], event_call["oldest"])
        self.assertEqual(snapshot["provider_sync"]["calendar_window"]["end"], event_call["newest"])
        self.assertEqual({item["id"] for item in snapshot["recent_activities"]}, {"old", "new"})

    def test_synced_library_template_must_be_archived_instead_of_deleted(self):
        entry = server.workout_library_remote_reconciler().reconcile([{"id": "remote-1", "name": "Remote Vorlage", "type": "Ride", "description": "Easy ride"}])[0]
        with self.assertRaises(server.AppError) as error:
            server.workout_library_service().update(entry["id"], {"action": "delete"})
        self.assertEqual(error.exception.status, 409)
        archived = server.workout_library_service().update(entry["id"], {"action": "archive"})
        self.assertTrue(archived["library_entry"]["archived"])

    def test_existing_intervals_coach_folder_is_reused(self):
        client = server.intervals_client(replace(server.CONFIG, intervals_api_key="test-key", intervals_athlete_id="athlete-1"))
        with patch.object(client, "get", return_value=[{"id": 77, "name": "Intervals Coach", "type": "FOLDER"}]), patch.object(
            client, "post", return_value={"id": "remote-1"}
        ) as post:
            client.create_library_workouts([{"name": "Easy", "description": "- 30m Z2", "sport": "Ride"}])
        post.assert_called_once_with(
            "/athlete/athlete-1/workouts",
            {"name": "Easy", "description": "- 30m Z2", "type": "Ride", "folder_id": 77, "target": "AUTO"},
        )

    def test_library_sync_reconciles_remote_template_before_creating(self):
        entry = server.workout_library_service().create_local_entry({
            "sport": "Ride", "name": "Coach Tempo", "description": "- 30m 85%", "duration_minutes": 30,
        })
        remote = {"id": "remote-recovered", "name": "Coach Tempo", "type": "Ride", "description": "- 30m 85%", **parsed_workout_fixture()}
        with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(
            intervals_client_module.IntervalsClient, "get_workout_library", return_value=[remote]
        ), patch.object(intervals_client_module.IntervalsClient, "create_library_workouts") as create:
            synced = server.workout_library_sync_service().sync_entry(entry["id"])
        self.assertEqual(synced["external_id"], "remote-recovered")
        create.assert_not_called()
        self.assertEqual(server.workout_library_service().list()[0]["sync_status"], "synced")

    def test_intervals_read_transport_injects_request_and_builds_query(self):
        from backend.providers.intervals import IntervalsReadTransport

        request = Mock(return_value={"id": "athlete-1"})
        transport = IntervalsReadTransport(
            "https://intervals.icu/api/v1",
            {"Authorization": "Basic test"},
            request,
        )

        result = transport.get("/athlete/athlete-1", {"include": ["a", "b"]})

        self.assertEqual(result, {"id": "athlete-1"})
        request.assert_called_once_with(
            "GET",
            "https://intervals.icu/api/v1/athlete/athlete-1?include=a&include=b",
            headers={"Authorization": "Basic test"},
            service="intervals",
        )

    def test_intervals_write_transport_injects_request_for_each_method(self):
        from backend.providers.intervals import IntervalsWriteTransport

        request = Mock(side_effect=[{"id": "post"}, {"id": "put"}, {"deleted": True}])
        headers = {"Authorization": "Basic test"}
        transport = IntervalsWriteTransport("https://intervals.icu/api/v1", headers, request)

        self.assertEqual(transport.post("/events", [{"id": "one"}], {"upsert": "true"}), {"id": "post"})
        self.assertEqual(transport.put("/events/bulk-delete", [{"id": "one"}]), {"id": "put"})
        self.assertEqual(transport.delete("/events/one", {"force": "true"}), {"deleted": True})

        self.assertEqual(request.call_args_list[0].args[:3], ("POST", "https://intervals.icu/api/v1/events?upsert=true", [{"id": "one"}]))
        self.assertEqual(request.call_args_list[1].args[:3], ("PUT", "https://intervals.icu/api/v1/events/bulk-delete", [{"id": "one"}]))
        self.assertEqual(request.call_args_list[2].args[:2], ("DELETE", "https://intervals.icu/api/v1/events/one?force=true"))
        self.assertEqual(request.call_args_list[0].args[3], headers)
        self.assertEqual(request.call_args_list[1].args[3], headers)
        self.assertEqual(request.call_args_list[2].kwargs, {"headers": headers, "service": "intervals"})

    def test_garmin_provider_collector_keeps_ranges_bounded_and_errors_redacted(self):
        from backend.providers.garmin import collect_garmin_data

        class FakeGarmin:
            def get_sleep_daily(self, start, end):
                return [{"date": start, "end": end}]

            def get_hrv_data_range(self, start, end):
                raise RuntimeError("secret provider detail")

            def get_body_battery(self, start, end):
                raise AssertionError("Body Battery must not be part of the range collector")

            def get_activities_by_date(self, start, end):
                return [{"start": start, "end": end}]

            def get_user_summary(self, current):
                return {"totalSteps": 1234, "floorsAscended": 7, "totalKilocalories": 2100}

            def get_heart_rates(self, current):
                return {"restingHeartRate": 51}

            def get_heart_rate_zones(self):
                return [{"sport": "DEFAULT", "maxHeartRateUsed": 186}]

            def get_training_readiness(self, current):
                return {"date": current, "score": 75}

            def get_race_predictions(self):
                return [{"race": "local fixture"}]

            def get_max_metrics_range(self, start, end):
                return {"date": end}

            def get_cycling_ftp(self):
                return {"functionalThresholdPower": 301}

            def get_lactate_threshold(self, *, latest=True):
                return {"speed_and_heart_rate": {"speed": 3.6, "heartRate": 175, "heartRateCycling": 168}, "power": {"functionalThresholdPower": 320}}

            def connectapi(self, *_args, **_kwargs):
                raise AssertionError("the undocumented cycling threshold range endpoint must not be called")

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
        self.assertEqual(result["running_threshold"]["power"]["functionalThresholdPower"], 320)
        self.assertEqual(result["resting_hr"][0]["restingHeartRate"], 51)
        self.assertEqual(result["heart_rate_zones"][0]["maxHeartRateUsed"], 186)
        self.assertTrue(any(source == "heart_rate_zones" for _service, source, _details in calls))
        self.assertEqual(len(result["daily_stats"]), 2)
        self.assertEqual(result["daily_stats"][0]["calendarDate"], "2026-08-30")
        self.assertEqual(result["daily_stats"][1]["totalSteps"], 1234)
        self.assertEqual(result["provider_sync"]["pagination"]["daily_stats"]["records"], 2)

    def test_garmin_source_observed_at_uses_latest_nested_valid_date(self):
        observed_at = garmin_observations.garmin_source_observed_at({
            "calendarDate": "invalid-date",
            "nested": [
                {"summaryDate": "2026-09-03"},
                {"startTimeGMT": "2026-09-05T06:00:00+00:00"},
            ],
        })
        self.assertEqual(observed_at, "2026-09-05")

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
                server.time.sleep(0.01)
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

    def test_intervals_collection_rejects_repeated_full_page(self):
        client = server.intervals_client(replace(server.CONFIG, intervals_api_key="test-key"))
        page = [{"id": f"activity-{index}"} for index in range(500)]
        with patch.object(client._api, "get", side_effect=[page, page]):
            with self.assertRaises(server.AppError) as raised:
                client.get_paged_collection("/athlete/0/activities", {}, "activities")
        self.assertEqual(raised.exception.status, 502)

    def test_intervals_snapshot_exposes_complete_page_metadata(self):
        with patch.object(
            server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")
        ):
            reader = server.intervals_snapshot_reader()
            with patch.object(reader._api_client, "get", side_effect=[
                [{"id": "activity-1", "start_date_local": "2026-08-31T08:00:00"}],
                [{"id": "2026-08-31"}],
                [],
                {"id": "athlete-1"},
            ]):
                snapshot = reader.fetch_snapshot(activity_days=1)
        self.assertTrue(snapshot["provider_sync"]["pagination"]["activities"]["complete"])
        self.assertEqual(snapshot["provider_sync"]["pagination"]["activities"]["records"], 1)
        self.assertTrue(snapshot["provider_sync"]["pagination"]["events"]["complete"])
        self.assertEqual(snapshot["raw_provider_data"]["activities"][0]["id"], "activity-1")
        self.assertEqual(snapshot["raw_provider_data"]["wellness"][0]["id"], "2026-08-31")

    def test_plan_push_job_requires_bounded_selected_hashed_entries(self):
        local_id = str(uuid.uuid4())
        entry = {"library_workout_id": local_id, "expected_payload_hash": "a" * 64}
        job = server.sync_job_queue_service().enqueue(
            "intervals", "plan_push", {"entries": [entry]}, requested_by="coach"
        )
        self.assertEqual(job["type"], "plan_push")
        self.assertEqual(job["payload"], {"entries": [entry], "reason": "job"})
        with self.assertRaises(server.AppError) as too_many:
            server.sync_job_queue_service().enqueue(
                "intervals",
                "plan_push",
                {"entries": [entry] * 29},
                requested_by="coach",
            )
        self.assertEqual(too_many.exception.reason, "invalid_job_request")

    def test_build_training_context_uses_compact_intervals_projection(self):
        today = server.ATHLETE_CLOCK.now().date()
        snapshot = {
            "synced_at": "now",
            "athlete": {},
            "recent_activities": [
                {"id": f"ride-{index}", "type": "Ride", "name": f"Ride {index}", "start_date_local": (today - timedelta(days=index)).isoformat()}
                for index in range(6)
            ],
            "recent_wellness": [],
            "upcoming_calendar": [],
        }
        server.sync_state_repository().save_snapshot(snapshot)
        context = server.coach_training_context_service().build()
        self.assertIn("Ride 0", context)
        self.assertNotIn("Ride 5", context)
        self.assertNotIn("LATEST INTERVALS.ICU SNAPSHOT", context)
        self.assertEqual(context.count('"local_planned_workouts"'), 1)
        preview = server.coach_context_preview_service().preview(server.SETTINGS.selected_ai_provider())
        self.assertTrue(preview["snapshot_compacted"])
        self.assertFalse(preview["snapshot_truncated"])
        self.assertTrue(preview["projection"]["within_total_budget"])

    def test_sync_period_supports_all_available_data_marker(self):
        from backend.sync.windows import split_date_windows

        repository = server.sync_state_repository()
        self.assertEqual(
            repository.set_sync_period(
                "intervals", -1, server.ALL_SYNC_DAYS
            ),
            -1,
        )
        self.assertEqual(
            repository.sync_period(
                "intervals", server.SYNC_PERIOD_DEFAULTS, server.ALL_SYNC_DAYS
            ),
            -1,
        )
        self.assertEqual(
            repository.set_sync_period(
                "garmin", -1, server.ALL_SYNC_DAYS
            ),
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

        self.assertEqual(windows, [
            (date(2026, 8, 25), date(2026, 8, 26)),
            (date(2026, 8, 27), date(2026, 8, 28)),
            (date(2026, 8, 29), date(2026, 8, 29)),
        ])
        with self.assertRaises(ValueError):
            split_date_windows(1, end_date=date(2026, 8, 29), earliest_date=date(2020, 1, 1), chunk_days=0, all_days=-1)

    def test_sync_intervals_uses_saved_period_when_not_explicitly_given(self):
        snapshot = {"synced_at": "now", "athlete": {}, "recent_activities": [], "recent_wellness": [], "upcoming_calendar": []}
        config = replace(server.CONFIG, intervals_api_key="test-key")
        server.sync_state_repository().set_sync_period(
            "intervals", 65, server.ALL_SYNC_DAYS
        )
        with patch.object(server, "CONFIG", config), patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=snapshot
        ) as fetch_snapshot, patch.object(WorkoutLibraryRefreshService, "refresh", return_value={"workouts": 0}), patch.object(server, "openai_responses_client") as openai_client:
            result = server.intervals_sync_service().sync("test")
        fetch_snapshot.assert_called_once_with(activity_days=65)
        openai_client.assert_not_called()
        self.assertEqual(result["activity_days"], 65)
        self.assertEqual(result["window_end"], server.ATHLETE_CLOCK.now().date().isoformat())

    def test_sync_intervals_passes_cancellation_to_snapshot_fetch(self):
        snapshot = {"synced_at": "now", "athlete": {}, "recent_activities": [], "recent_wellness": [], "upcoming_calendar": []}
        cancel_event = threading.Event()
        config = replace(server.CONFIG, intervals_api_key="test-key")
        with patch.object(server, "CONFIG", config), patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=snapshot
        ) as fetch_snapshot, patch.object(
            WorkoutLibraryRefreshService, "refresh", return_value={"workouts": 0}
        ) as refresh_library:
            server.intervals_sync_service().sync(
                "cancellable", activity_days=42, cancel_event=cancel_event
            )
        fetch_snapshot.assert_called_once_with(activity_days=42, cancel_event=cancel_event)
        refresh_library.assert_called_once_with(
            reason="Initialer Intervals.icu-Sync (cancellable)", cancel_event=cancel_event
        )

    def test_sync_intervals_reraises_library_import_cancellation(self):
        snapshot = {"synced_at": "now", "athlete": {}, "recent_activities": [], "recent_wellness": [], "upcoming_calendar": []}
        cancel_event = threading.Event()
        config = replace(server.CONFIG, intervals_api_key="test-key")
        cancellation = server.AppError(499, "abgebrochen", reason="chat_cancelled")
        with patch.object(server, "CONFIG", config), patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=snapshot
        ), patch.object(WorkoutLibraryRefreshService, "refresh", side_effect=cancellation):
            with self.assertRaises(server.AppError) as raised:
                server.intervals_sync_service().sync(
                    "cancellable-library",
                    activity_days=42,
                    cancel_event=cancel_event,
                )
        self.assertEqual(raised.exception.reason, "chat_cancelled")
        self.assertFalse(server.key_value_service().get("last_library_sync_error"))

    def test_sync_intervals_persists_activity_coverage_with_snapshot(self):
        snapshot = {"synced_at": "new", "athlete": {}, "recent_activities": [], "recent_wellness": [], "upcoming_calendar": []}
        config = replace(server.CONFIG, intervals_api_key="test-key")
        server.key_value_service().set("last_sync_activity_days", "7")
        cancellation = server.AppError(499, "abgebrochen", reason="chat_cancelled")
        with patch.object(server, "CONFIG", config), patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=snapshot
        ), patch.object(WorkoutLibraryRefreshService, "refresh", side_effect=cancellation):
            with self.assertRaises(server.AppError):
                server.intervals_sync_service().sync(
                    "cancellable-library",
                    activity_days=42,
                    cancel_event=threading.Event(),
                )
        self.assertEqual(server.key_value_service().get("last_sync_at"), "new")
        self.assertEqual(server.key_value_service().get("last_sync_activity_days"), "42")

    def test_cancelled_intervals_sync_is_recorded_as_skipped(self):
        cancel_event = threading.Event()
        cancel_event.set()
        config = replace(server.CONFIG, intervals_api_key="test-key")
        with patch.object(server, "CONFIG", config):
            with self.assertRaises(server.AppError) as raised:
                server.intervals_sync_service().sync(
                    "cancelled", activity_days=42, cancel_event=cancel_event
                )
            freshness = {
                (item["provider"], item["area"]): item
                for item in server.provider_freshness_service().current(
                    profile=server.profile_service().get(),
                    garmin_has_core_error=bool(
                        server.garmin_sync_state_service().core_error_entries()
                    ),
                    garmin_tokenstore_exists=Path(server.CONFIG.garmin_tokenstore).exists(),
                )
            }
        self.assertEqual(raised.exception.reason, "chat_cancelled")
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            row = db.execute(
                "SELECT status, phase, error_code FROM provider_refresh_history "
                "WHERE provider='intervals' AND area='activities' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
        self.assertEqual(row["status"], "skipped")
        self.assertEqual(row["phase"], "cancelled")
        self.assertIsNone(row["error_code"])
        self.assertEqual(freshness[("intervals", "activities")]["state"], "never_loaded")

    def test_initial_intervals_sync_copies_remote_library_to_empty_local_library(self):
        snapshot = {"synced_at": "now", "athlete": {}, "recent_activities": [], "recent_wellness": [], "upcoming_calendar": []}
        remote = [{
            "id": "remote-template-1",
            "name": "Remote Vorlage",
            "type": "Run",
            "description": "- 30m 60% locker",
            "moving_time": 1800,
        }]
        config = replace(server.CONFIG, intervals_api_key="test-key")
        with patch.object(server, "CONFIG", config), patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=snapshot
        ), patch.object(intervals_client_module.IntervalsClient, "get_workout_library", return_value=remote) as get_library:
            result = server.intervals_sync_service().sync("initial", activity_days=42)

        get_library.assert_called_once_with()
        library = server.workout_library_service().list()
        self.assertEqual(len(library), 1)
        self.assertEqual(library[0]["external_id"], "remote-template-1")
        self.assertEqual(library[0]["name"], "Remote Vorlage")
        self.assertEqual(result["library"], 1)
        self.assertEqual(result["library_imported"], 1)
        self.assertIsNone(result["library_error"])

    def test_intervals_sync_imports_future_planning_only_once(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        first_snapshot = {
            "synced_at": "first",
            "athlete": {},
            "recent_activities": [],
            "recent_wellness": [],
            "upcoming_calendar": [{
                "id": "initial-plan",
                "category": "WORKOUT",
                "type": "Ride",
                "name": "Initiale Planung",
                "start_date_local": tomorrow + "T08:00:00",
                "moving_time": 1800,
            }],
        }
        second_snapshot = {
            **first_snapshot,
            "synced_at": "second",
            "upcoming_calendar": [{
                **first_snapshot["upcoming_calendar"][0],
                "id": "later-remote-plan",
                "name": "Spätere Remote-Planung",
            }],
        }
        config = replace(server.CONFIG, intervals_api_key="test-key")
        with patch.object(server, "CONFIG", config), patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", side_effect=[first_snapshot, second_snapshot]
        ), patch.object(WorkoutLibraryRefreshService, "refresh", return_value={"workouts": 0}):
            first = server.intervals_sync_service().sync("initial", activity_days=42)
            second = server.intervals_sync_service().sync("later", activity_days=42)

        self.assertEqual(first["planned_import"]["imported"], 1)
        self.assertEqual(second["planned_import"]["imported"], 0)
        planned = server.planned_unit_service().list()
        self.assertEqual([item["name"] for item in planned], ["Initiale Planung"])
        self.assertEqual(server.key_value_service().get("planned_units_initial_import_at"), "first")

    def test_intervals_sync_imports_remote_templates_alongside_local_library(self):
        local = server.workout_library_service().create_local_entry({
            "sport": "Ride",
            "name": "Lokale Vorlage",
            "description": "- 20m 60% locker", "duration_minutes": 20,
        })
        snapshot = {"synced_at": "now", "athlete": {}, "recent_activities": [], "recent_wellness": [], "upcoming_calendar": []}
        config = replace(server.CONFIG, intervals_api_key="test-key")
        with patch.object(server, "CONFIG", config), patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=snapshot
        ), patch.object(intervals_client_module.IntervalsClient, "get_workout_library", return_value=[{
            "id": "remote-template-2", "name": "Remote Vorlage", "type": "Ride",
            "description": "- 30m Z2", "moving_time": 1800,
        }]) as get_library:
            result = server.intervals_sync_service().sync("existing", activity_days=42)

        get_library.assert_called_once_with()
        self.assertEqual(result["library"], 2)
        self.assertEqual(result["library_imported"], 1)
        library = server.workout_library_service().list()
        self.assertEqual(len(library), 2)
        self.assertIn(local["id"], {item["id"] for item in library})
        self.assertEqual(next(item for item in library if item["name"] == "Remote Vorlage")["external_id"], "remote-template-2")

    def test_sync_intervals_does_not_run_library_push(self):
        snapshot = {"synced_at": "now", "athlete": {}, "recent_activities": [], "recent_wellness": [], "upcoming_calendar": []}
        config = replace(server.CONFIG, intervals_api_key="test-key")
        with patch.object(server, "CONFIG", config), patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=snapshot
        ), patch.object(
            SelectedWorkoutSyncService, "sync", return_value={"status": "partial", "workouts": 1, "local_errors": ["upload failed"]}
        ) as library_sync, patch.object(WorkoutLibraryRefreshService, "refresh", return_value={"workouts": 0}):
            result = server.intervals_sync_service().sync("test", activity_days=42)
        library_sync.assert_not_called()
        self.assertEqual(result["status"], "ok")
        self.assertIsNone(result["library_error"])

    def test_startup_sync_contract_rejects_remote_mutations(self):
        recorder, client = self._prepare_remote_contract_fixture()
        with patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=client.snapshot
        ), patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(
            server, "intervals_client", return_value=client
        ):
            server.sync_job_queue_service().enqueue(
                "intervals", "refresh", {"days": 7, "reason": "startup"}
            )
            server.sync_job_executor().run(server.sync_job_store().claim())
        self.assertEqual(recorder.mutations, [])

    def test_daily_sync_contract_rejects_remote_mutations(self):
        recorder, client = self._prepare_remote_contract_fixture()
        with patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=client.snapshot
        ), patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(
            server, "intervals_client", return_value=client
        ):
            server.sync_job_queue_service().enqueue(
                "intervals", "refresh", {"days": 7, "reason": "daily"}
            )
            server.sync_job_executor().run(server.sync_job_store().claim())
        self.assertEqual(recorder.mutations, [])

    def test_startup_sync_competition_contract_rejects_remote_mutations(self):
        recorder, client = self._prepare_competition_contract_fixture()
        with patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=client.snapshot
        ), patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(
            server, "intervals_client", return_value=client
        ):
            server.sync_job_queue_service().enqueue(
                "intervals", "refresh", {"days": 7, "reason": "startup"}
            )
            server.sync_job_executor().run(server.sync_job_store().claim())
        self.assertEqual(recorder.mutations, [])

    def test_daily_sync_competition_contract_rejects_remote_mutations(self):
        recorder, client = self._prepare_competition_contract_fixture()
        with patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=client.snapshot
        ), patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(
            server, "intervals_client", return_value=client
        ):
            server.sync_job_queue_service().enqueue(
                "intervals", "refresh", {"days": 7, "reason": "daily"}
            )
            server.sync_job_executor().run(server.sync_job_store().claim())
        self.assertEqual(recorder.mutations, [])

    def test_manual_activity_sync_contract_rejects_remote_mutations(self):
        recorder, client = self._prepare_remote_contract_fixture()
        with patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=client.snapshot
        ), patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(
            server, "intervals_client", return_value=client
        ):
            server.intervals_sync_service().sync("activity", activity_days=7)
        self.assertEqual(recorder.mutations, [])

    def test_full_resync_contract_rejects_remote_mutations(self):
        recorder, client = self._prepare_remote_contract_fixture()
        with patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=client.snapshot
        ), patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(
            server, "intervals_client", return_value=client
        ):
            server.full_provider_resync_service().resync("intervals")
        self.assertEqual(recorder.mutations, [])

    def test_explicit_competition_sync_records_create_change_and_delete_contract(self):
        event_date = (date.today() + timedelta(days=30)).isoformat()
        saved = server.athlete_context_service().save({}, [{
            "name": "Explicit race",
            "event_date": event_date,
            "sport": "Cycling",
        }])
        competition_id = saved["competitions"][0]["id"]
        recorder = IntervalsRequestRecorder()
        client = RecordedIntervalsClient(recorder)
        with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(
            server, "intervals_client", return_value=client
        ):
            created = server.competition_sync_service().sync("explicit approval", push_local=True)
            server.competition_service().save({
                "competition_id": competition_id,
                "name": "Explicit race changed",
                "event_date": event_date,
                "sport": "Cycling",
            })
            server.athlete_context_service().save({}, [])
            deleted = server.competition_sync_service().sync("explicit approval", push_local=True)
        self.assertEqual(created["pushed"], 1)
        self.assertEqual(deleted["deleted_remote"], 1)
        self.assertEqual([call["method"] for call in recorder.mutations], ["POST", "DELETE"])

    def test_local_sync_error_and_remote_missing_entries_are_not_retried_by_read_sync(self):
        recorder = IntervalsRequestRecorder()
        entries = [
            server.workout_library_service().create_local_entry({"sport": "Ride", "name": state, "description": "- 20m Z2", "duration_minutes": 20})
            for state in ("local", "sync_error", "remote_missing")
        ]
        for entry, state in zip(entries[1:], ("sync_error", "remote_missing")):
            server.workout_library_sync_state_service().update(
                entry["id"], state, "fake failure"
            )
        client = RecordedIntervalsClient(recorder)
        with patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=client.snapshot
        ), patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(
            server, "intervals_client", return_value=client
        ):
            server.intervals_sync_service().sync("read-only", activity_days=1)
        self.assertEqual(recorder.mutations, [])

    def test_full_intervals_resync_preserves_local_library_and_never_remote_data(self):
        server.athlete_context_service().save({}, [{"name": "Old local race", "event_date": (date.today() + timedelta(days=30)).isoformat()}])
        server.workout_library_remote_reconciler().reconcile([{
            "id": "old-workout", "name": "Local template", "type": "Ride",
            "description": "- 30m Z2", "moving_time": 1800,
        }])
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute("INSERT INTO snapshots(payload, created_at) VALUES (?, ?)", (json.dumps({"synced_at": "old"}), "old"))
            db.execute(
                "INSERT INTO competition_sync_tombstones(id, intervals_event_id, external_id, created_at) VALUES (?, ?, ?, ?)",
                ("tombstone", "remote-event", "remote-external", "old"),
            )
        remote_race = {
            "id": "remote-event",
            "category": "RACE_A",
            "start_date_local": (date.today() + timedelta(days=45)).isoformat() + "T08:00:00",
            "type": "Ride",
            "name": "Cloud race",
        }
        deleted = []
        new_snapshot = {
            "synced_at": "new",
            "athlete": {},
            "recent_activities": [],
            "recent_wellness": [],
            "upcoming_calendar": [],
        }

        class FakeIntervalsClient:
            def get_workout_library(self):
                return []

            def fetch_competition_events(self):
                return [remote_race]

            def upsert_competition_events(self, events):
                if events:
                    raise AssertionError("A full resync must not push local competition data.")
                return []

            def bulk_delete_events(self, identifiers):
                deleted.extend(identifiers)

        with patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=new_snapshot
        ), patch.object(server, "intervals_client", FakeIntervalsClient), patch.object(
            server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")
        ), patch.object(SelectedWorkoutSyncService, "sync", return_value={"workouts": 0}):
            result = server.full_provider_resync_service().resync("intervals")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(deleted, [])
        self.assertEqual(
            server.sync_state_repository().latest_snapshot()["synced_at"], "new"
        )
        self.assertEqual(
            {competition["name"] for competition in server.competition_service().list()},
            {"Old local race"},
        )
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM workout_library").fetchone()["count"], 1)
            self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM competition_sync_tombstones").fetchone()["count"], 1)
        self.assertEqual(server.workout_library_service().list()[0]["external_id"], "old-workout")

    def test_full_intervals_resync_keeps_last_snapshot_on_provider_failure(self):
        old_snapshot = {"synced_at": "old", "athlete": {}, "recent_activities": [], "recent_wellness": [], "upcoming_calendar": []}
        server.sync_state_repository().save_snapshot(old_snapshot)

        with patch.object(
            IntervalsSnapshotReader,
            "fetch_snapshot",
            side_effect=RuntimeError("provider unavailable"),
        ), patch.object(
            server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")
        ):
            with self.assertRaises(RuntimeError):
                server.full_provider_resync_service().resync("intervals")
        self.assertEqual(
            server.sync_state_repository().latest_snapshot()["synced_at"], "old"
        )

    def test_full_garmin_resync_keeps_last_snapshot_on_provider_failure(self):
        server.key_value_service().set("garmin_snapshot", json.dumps({"old": True}))
        config = replace(server.CONFIG, garmin_fixture_path="fixture.json")
        with patch.object(server, "CONFIG", config), patch.object(
            server.GarminSyncService,
            "sync",
            side_effect=RuntimeError("provider unavailable"),
        ):
            with self.assertRaises(RuntimeError):
                server.full_provider_resync_service().resync("garmin")
        self.assertEqual(json.loads(server.key_value_service().get("garmin_snapshot")), {"old": True})

    def test_full_resync_blocks_intervals_operations(self):
        self.assertTrue(server.INTERVALS_RESYNC_GATE.begin_reset())
        errors = []
        try:
            with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):
                def attempt_sync():
                    try:
                        server.sync_job_executor().execute(
                            server.sync_job_queue_service().enqueue(
                                "intervals",
                                "competition_push",
                                {"reason": "test"},
                            )
                        )
                    except server.AppError as error:
                        errors.append(error)
                thread = threading.Thread(target=attempt_sync)
                thread.start()
                thread.join()
            self.assertEqual(len(errors), 1)
            self.assertEqual(errors[0].status, 409)
        finally:
            server.INTERVALS_RESYNC_GATE.end_reset()

    def test_full_garmin_resync_replaces_local_snapshot_without_touching_tokens(self):
        server.key_value_service().set("garmin_snapshot", json.dumps({"old": True}))
        server.key_value_service().set("last_garmin_sync_at", "old")
        with tempfile.TemporaryDirectory() as temp_root:
            fixture = Path(temp_root) / "garmin.json"
            fixture.write_text(json.dumps({"activities": [], "errors": []}), encoding="utf-8")
            config = replace(server.CONFIG, garmin_fixture_path=str(fixture))
            with patch.object(server, "CONFIG", config):
                result = server.full_provider_resync_service().resync("garmin")
        self.assertEqual(result["status"], "ok")
        self.assertNotEqual(server.key_value_service().get("garmin_snapshot"), json.dumps({"old": True}))
        self.assertEqual(server.garmin_payload_service().snapshot().get("source"), "fixture")

    def test_all_time_snapshot_does_not_truncate_activity_history(self):
        snapshot = planning_context.compact_snapshot(
            {}, [{"id": str(index), "name": f"Ride {index}"} for index in range(600)],
            [{"id": f"2026-01-{index:02d}", "ctl": index} for index in range(1, 4)], [], history_days=-1,
            all_sync_days=server.ALL_SYNC_DAYS,
            synced_at=server.utc_now(),
        )
        self.assertEqual(len(snapshot["recent_activities"]), 600)
        self.assertEqual(len(snapshot["recent_wellness"]), 3)

    def test_competition_sync_pushes_local_events_idempotently(self):
        event_date = (date.today() + timedelta(days=60)).isoformat()
        saved = server.athlete_context_service().save({}, [{"name": "Test Race", "event_date": event_date, "priority": "A", "sport": "Cycling"}])
        local_id = saved["competitions"][0]["id"]
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

        with patch.object(server, "intervals_client", FakeIntervalsClient), patch.object(
            server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")
        ):
            result = server.competition_sync_service().sync("test", push_local=True)
            second = server.competition_sync_service().sync("test", push_local=True)

        self.assertEqual(result["pushed"], 1)
        self.assertEqual(second["pushed"], 0)
        self.assertEqual(calls["events"][0]["category"], "RACE_A")
        self.assertEqual(
            calls["events"][0]["external_id"],
            planning_competitions.competition_external_id(local_id),
        )
        synced = server.competition_service().list()[0]
        self.assertEqual(synced["intervals_event_id"], "12345")
        self.assertEqual(synced["sync_dirty"], 0)

    def test_competition_sync_marks_dirty_identity_match_as_conflict(self):
        event_date = (date.today() + timedelta(days=60)).isoformat()
        server.athlete_context_service().save({}, [{
            "name": "Existing Race", "event_date": event_date, "priority": "A", "sport": "Cycling",
        }])
        pushed = []

        class FakeIntervalsClient:
            def fetch_competition_events(self):
                return [{
                    "id": 54321,
                    "category": "RACE_A",
                    "start_date_local": event_date + "T08:00:00",
                    "type": "Ride",
                    "name": "Existing Race",
                }]

            def upsert_competition_events(self, events):
                pushed.extend(events)
                return []

            def bulk_delete_events(self, identifiers):
                return 0

        with patch.object(server, "intervals_client", FakeIntervalsClient), patch.object(
            server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")
        ):
            result = server.competition_sync_service().sync("test", push_local=True)

        self.assertEqual(result["pushed"], 0)
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(result["imported"], 0)
        self.assertEqual(pushed, [])
        competition = server.competition_service().list()[0]
        self.assertIsNone(competition["intervals_event_id"])
        self.assertEqual(competition["sync_dirty"], 1)
        self.assertEqual(competition["sync_state"], "conflict")
        self.assertEqual(json.loads(competition["sync_conflict"])["remote"]["name"], "Existing Race")

    def test_competition_sync_imports_remote_race_events(self):
        event_date = (date.today() + timedelta(days=45)).isoformat()

        class FakeIntervalsClient:
            def fetch_competition_events(self):
                return [
                    {
                        "id": 777,
                        "category": "RACE_B",
                        "start_date_local": event_date + "T08:00:00",
                        "type": "Run",
                        "name": "Remote Half Marathon",
                        "description": "Ziel unter zwei Stunden",
                    },
                    {
                        "id": 778,
                        "category": "RACE_C",
                        "start_date_local": event_date + "T09:00:00",
                        "type": "Swim",
                        "name": "Unsupported Swim Race",
                    },
                ]

            def upsert_competition_events(self, events):
                return []

            def bulk_delete_events(self, identifiers):
                return 0

        with patch.object(server, "intervals_client", FakeIntervalsClient), patch.object(
            server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")
        ):
            result = server.competition_sync_service().sync("test")

        self.assertEqual(result["imported"], 1)
        competition = server.competition_service().list()[0]
        self.assertEqual(competition["name"], "Remote Half Marathon")
        self.assertEqual(competition["event_date"], event_date)
        self.assertEqual(competition["intervals_event_id"], "777")
        self.assertEqual(competition["sync_dirty"], 0)

        # Saving the profile after an import must retain the provider link.
        server.athlete_context_service().save({}, [competition])
        saved_again = server.competition_service().list()[0]
        self.assertEqual(saved_again["intervals_event_id"], "777")

    def test_competition_sync_skips_unsupported_local_sports(self):
        event_date = (date.today() + timedelta(days=30)).isoformat()
        server.athlete_context_service().save({}, [{"name": "Swim Race", "event_date": event_date, "sport": "Swim"}])
        pushed = []

        class FakeIntervalsClient:
            def fetch_competition_events(self):
                return []

            def upsert_competition_events(self, events):
                pushed.extend(events)
                return []

            def bulk_delete_events(self, identifiers):
                return 0

        with patch.object(server, "intervals_client", FakeIntervalsClient), patch.object(
            server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")
        ):
            result = server.competition_sync_service().sync("test")

        self.assertEqual(result["pushed"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(pushed, [])
        self.assertEqual(server.competition_service().list()[0]["name"], "Swim Race")

    def test_current_performance_is_derived_from_intervals_snapshot(self):
        today = date.today().isoformat()
        snapshot = {
            "synced_at": "2026-08-28T08:00:00+00:00",
            "athlete": {"icu_ftp": 300, "lthr": 171},
            "recent_wellness": [{"id": today, "ctl": 70, "atl": 76, "tsb": -6, "sleepSecs": 27000, "readiness": 8}],
            "recent_activities": [{"start_date_local": today + "T07:00:00", "moving_time": 7200, "icu_training_load": 110}],
        }
        performance = _current_performance_context(snapshot)
        self.assertEqual(performance["thresholds"]["icu_ftp"], 300)
        self.assertEqual(performance["current_load"]["tsb"], -6)
        self.assertEqual(performance["recovery"]["sleep_hours"], 7.5)
        self.assertEqual(performance["rolling_training"]["last_7_days"]["training_load"], 110.0)
        self.assertNotIn("ai_estimates", performance)

    def test_form_is_derived_from_ctl_and_atl_when_intervals_omits_tsb(self):
        today = date.today().isoformat()
        snapshot = {
            "synced_at": "now", "athlete": {},
            "recent_wellness": [{"id": today, "ctl": 60, "atl": 72}],
            "recent_activities": [],
        }
        performance = _current_performance_context(snapshot)
        self.assertEqual(performance["current_load"]["tsb"], -12)

    def test_current_eftp_prefers_current_intervals_model_over_latest_activity_estimate(self):
        today = date.today().isoformat()
        snapshot = planning_context.compact_snapshot(
            {
                "sportSettings": [{"types": ["Ride"], "ftp": 300, "eFTP": 309}],
            },
            [{"start_date_local": f"{today}T08:00:00", "type": "Ride", "icu_ftp": 300, "icu_eftp": 300}],
            [{"id": today, "sportInfo": [{"types": ["Ride"], "eFTP": 274}]}],
            [],
            all_sync_days=server.ALL_SYNC_DAYS,
            synced_at=server.utc_now(),
        )

        performance = _current_performance_context(snapshot)
        metrics = performance["metrics"]
        self.assertEqual(metrics["cycling_ftp_watts"]["value"], 300)
        self.assertEqual(metrics["cycling_eftp_watts"]["value"], 309)
        self.assertEqual(metrics["cycling_eftp_watts"]["source"], "Intervals.icu")
        self.assertEqual(performance["comparisons"]["cycling_eftp_30d"]["average"], 287)
        eftp_reference = next(item for item in performance["activity_validation"]["provider_references"] if item["metric"] == "cycling_eftp_watts")
        self.assertEqual(eftp_reference["historical_comparison"]["average"], 287)
        self.assertEqual(performance["activity_validation"]["direct_activity_estimates"]["activity_configured_ftp_watts"], 300)

    def test_garmin_near_duplicate_is_skipped_in_favour_of_intervals_activity(self):
        garmin = {
            "activityId": 1, "activityType": "running", "activityName": "Morning Run",
            "startTimeLocal": "2026-08-29T07:05:00", "duration": 3600, "distance": 9900,
        }
        intervals = [{"type": "Run", "start_date_local": "2026-08-29T07:00:00", "moving_time": 3560, "distance": 10000}]
        self.assertTrue(garmin_activity_duplicates_intervals(garmin, intervals))
        kept, skipped = filter_garmin_activities([garmin], intervals)
        self.assertEqual(kept, [])
        self.assertEqual(skipped, 1)

    def test_latest_intervals_duplicate_keeps_wahoo_and_selects_garmin_for_deletion(self):
        activities = [
            {
                "id": "i-wahoo", "type": "Ride", "source": "Wahoo", "device_name": "ELEMNT BOLT",
                "start_date_local": "2026-08-29T07:00:00", "moving_time": 7200, "distance": 60200,
            },
            {
                "id": "i-garmin", "type": "Ride", "source": "Garmin Connect", "device_name": "Edge 1040",
                "start_date_local": "2026-08-29T07:04:00", "moving_time": 7160, "distance": 59800,
            },
        ]
        pair = latest_wahoo_garmin_duplicate({
            "synced_at": "2026-08-29T10:00:00+00:00",
            "raw_provider_data": {"activities": activities},
        })
        self.assertEqual(pair["canonical_id"], "i-wahoo")
        self.assertEqual(pair["duplicate_id"], "i-garmin")

    def test_latest_intervals_duplicate_is_ignored_when_a_newer_activity_is_unrelated(self):
        pair = [
            {"id": "i-wahoo", "type": "Ride", "source": "Wahoo", "start_date_local": "2026-08-29T07:00:00", "moving_time": 7200, "distance": 60200},
            {"id": "i-garmin", "type": "Ride", "source": "Garmin", "start_date_local": "2026-08-29T07:04:00", "moving_time": 7160, "distance": 59800},
            {"id": "i-run", "type": "Run", "source": "Garmin", "start_date_local": "2026-08-30T07:00:00", "moving_time": 3600, "distance": 10000},
        ]
        self.assertIsNone(latest_wahoo_garmin_duplicate({"raw_provider_data": {"activities": pair}}))

    def test_intervals_duplicate_requires_matching_start_duration_and_distance(self):
        wahoo = {
            "id": "wahoo", "type": "Ride", "source": "Wahoo", "start_date_local": "2026-08-29T07:00:00",
            "moving_time": 7200, "distance": 60000,
        }
        garmin = {
            "id": "garmin", "type": "Ride", "source": "Garmin", "start_date_local": "2026-08-29T07:05:00",
            "moving_time": 7200, "distance": 80000,
        }
        self.assertFalse(intervals_cycling_activities_match(wahoo, garmin))
        self.assertIsNone(latest_wahoo_garmin_duplicate({"raw_provider_data": {"activities": [wahoo, garmin]}}))

    def test_sync_intervals_waits_for_active_sync_and_uses_its_new_snapshot(self):
        server.key_value_service().set("last_sync_at", "old-sync")
        INTERVALS_SYNC_LOCK.acquire()
        previous_snapshot_read = threading.Event()
        service = server.intervals_sync_service()
        status = service._status
        original_get_value = status.get

        def get_value_after_read(key):
            value = original_get_value(key)
            if key == "last_sync_at":
                previous_snapshot_read.set()
            return value

        def finish_active_sync():
            if not previous_snapshot_read.wait(2):
                INTERVALS_SYNC_LOCK.release()
                return
            server.key_value_service().set("last_sync_at", "new-sync")
            INTERVALS_SYNC_LOCK.release()

        worker = threading.Thread(target=finish_active_sync)
        worker.start()
        try:
            with patch.object(status, "get", side_effect=get_value_after_read):
                result = service.sync(
                    "latest activity test",
                    activity_days=7,
                    wait_for_existing=True,
                )
        finally:
            worker.join(timeout=2)
            if INTERVALS_SYNC_LOCK.locked():
                INTERVALS_SYNC_LOCK.release()
        self.assertEqual(result["status"], "ok")
        self.assertTrue(result["waited_for_existing"])
        self.assertEqual(result["synced_at"], "new-sync")

    def test_intervals_validation_error_includes_safe_provider_detail(self):
        error_body = json.dumps({"error": {"message": "Invalid workout type"}}).encode("utf-8")
        upstream_error = HTTPError(
            "https://intervals.icu/api/v1/athlete/0/workouts",
            422,
            "Unprocessable Entity",
            {},
            BytesIO(error_body),
        )
        with patch.object(server.provider_http_client(), "opener", side_effect=upstream_error):
            with self.assertRaises(server.AppError) as raised:
                server.provider_http_client().request("POST", "https://intervals.icu/api/v1/athlete/0/workouts", payload={}, service="intervals")
        self.assertEqual(raised.exception.status, 502)
        self.assertIn("422", raised.exception.message)
        self.assertIn("Invalid workout type", raised.exception.message)

    def test_sync_logs_end_to_end_operation_id_without_athlete_content(self):
        snapshot = {"synced_at": "now", "athlete": {}, "recent_activities": [], "recent_wellness": [], "upcoming_calendar": []}
        operation_id = "operation-test-026"
        config = replace(server.CONFIG, intervals_api_key="test-key")
        server.observability.configure_logging(server.LOGGER, server.DATA_DIR, server.LOG_PATH, server.REDACTOR)
        with patch.object(server, "CONFIG", config), patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=snapshot
        ), patch.object(intervals_client_module.IntervalsClient, "get_workout_library", return_value=[]):
            server.intervals_sync_service().sync(
                "manual", activity_days=1, operation_id=operation_id
            )
        for handler in server.LOGGER.handlers:
            handler.flush()
        entries = server.recent_log_entries_service().list(200)
        correlated = [entry for entry in entries if entry.get("context", {}).get("operation_id") == operation_id]
        events = {entry.get("event") for entry in correlated}
        self.assertTrue({"operation_started", "operation_completed", "operation_count"}.issubset(events))
        for entry in correlated:
            context = entry.get("context", {})
            self.assertIn(context.get("trigger"), {"manual", "background"})
            self.assertNotIn("athlete", json.dumps(entry).casefold())

    def test_garmin_sync_persists_fatal_error_status(self):
        config = replace(server.CONFIG, garmin_fixture_path="missing-garmin-fixture.json")
        with patch.object(server, "CONFIG", config):
            with self.assertRaises(server.AppError):
                server.garmin_sync_service().sync()
        state = server.garmin_projection_service().public_state()
        self.assertTrue(state["last_error"])

    def test_selected_library_sync_is_exact_and_reports_per_object(self):
        first = server.workout_library_service().create_local_entry({"sport": "Ride", "name": "Remote eins", "description": "- 30m Z2", "duration_minutes": 30})
        second = server.workout_library_service().create_local_entry({"sport": "Run", "name": "Remote zwei", "description": "- 20m 60% Easy", "duration_minutes": 20})
        config = replace(server.CONFIG, intervals_api_key="fake-intervals-key")
        with patch.object(server, "CONFIG", config), patch.object(
            WorkoutLibrarySyncService, "sync_entry",
            side_effect=[{"id": first["id"], "external_id": "remote-1"}, server.AppError(502, "provider unavailable")],
        ) as sync_entry:
            pending = {item["library_workout_id"]: item for item in server.planning_authority_service().pending_plan_push_entries()}
            result = server.selected_workout_sync_service().sync({"entries": [pending[first["id"]], pending[second["id"]]]})
        self.assertEqual(result["status"], "partial")
        self.assertEqual(len(result["results"]), 2)
        self.assertEqual(result["results"][0]["status"], "synced")
        self.assertEqual(result["results"][1]["status"], "error")
        self.assertEqual(result["failed_object_ids"], [second["id"]])
        self.assertEqual([call.args[0] for call in sync_entry.call_args_list], [first["id"], second["id"]])


if __name__ == "__main__":
    unittest.main()
