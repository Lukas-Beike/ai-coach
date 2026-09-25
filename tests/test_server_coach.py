"""Server integration tests for coach."""

import json
import threading
import unittest
import uuid
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

from backend.coach import context as coach_context, streams as coach_streams
from backend.coach.attachments import gemini_history_parts
from backend.coach.context import CoachIntervalsContextService, future_coach_planned_workouts
from backend.coach.proposals import validated_coach_action_preview_input
from backend.http_api import server as http_server_module
from backend.planning import competitions as planning_competitions
from server_test_support import server, ServerTestCase
from support import build_gemini_request_payload


class ServerCoachTests(ServerTestCase):

    def test_coach_http_server_retains_threading_contract(self):
        from http.server import ThreadingHTTPServer

        self.assertTrue(issubclass(http_server_module.CoachHTTPServer, ThreadingHTTPServer))
        self.assertTrue(http_server_module.CoachHTTPServer.daemon_threads)
        self.assertEqual(http_server_module.CoachHTTPServer.request_queue_size, 32)

    def test_structured_commit_rejects_model_artifact_outside_classified_scope(self):
        artifact = server.training_plan_artifact_service().stage(
            {"payload": {"plan_name": "Scoped", "workouts": [{"date": "2099-01-01", "sport": "Ride", "description": "- 30m 60% Easy session", "duration_minutes": 30}]}},
            "conversation-scope",
            "turn-scope",
        )
        intent = {
            "intent": "local_action",
            "operation": "commit_training_plan",
            "target_system": "local",
            "artifact_id": artifact["artifact_id"],
            "ambiguities": [],
            "authorization_scope": [f"artifact:{artifact['artifact_id']}"],
        }
        with self.assertRaises(server.AppError) as denied:
            server.coach_tool_dispatch_service().execute(
                "commit_training_plan",
                {"artifact_id": str(uuid.uuid4())},
                intent=intent,
                conversation_id="conversation-scope",
                client_turn_id="turn-scope",
                session_csrf_hash="",
                sync_job_ids=[],
            )
        self.assertEqual(denied.exception.reason, "intent_scope_denied")

    def test_structured_commit_does_not_rebind_foreign_draft_via_recovery_flag(self):
        artifact = server.training_plan_artifact_service().stage(
            {"payload": {
                "plan_name": "Foreign",
                "workouts": [{
                    "date": "2099-01-04", "sport": "Ride", "name": "Foreign ride",
                    "description": "- 30m 60% easy", "duration_minutes": 30,
                }],
            }},
            "conversation-foreign",
            "turn-foreign",
        )
        intent = {
            "intent": "local_action", "operation": "commit_training_plan", "target_system": "local",
            "artifact_id": artifact["artifact_id"], "ambiguities": [],
            "authorization_scope": [f"artifact:{artifact['artifact_id']}"],
            "follow_up_operations": [], "_allow_artifact_rebind": True,
        }

        with self.assertRaises(server.AppError) as denied:
            server.coach_tool_dispatch_service().execute(
                "commit_training_plan", {"artifact_id": artifact["artifact_id"]},
                intent=intent, conversation_id="conversation-current", client_turn_id="turn-current",
                session_csrf_hash="", sync_job_ids=[],
            )

        self.assertEqual(denied.exception.reason, "artifact_conversation_conflict")

    def test_structured_coach_exposes_competitions_plans_and_adaptive_operations(self):
        names = {tool["name"] for tool in server.COACH_STRUCTURED_TOOLS}
        self.assertLessEqual({
            "list_competitions", "save_competition", "delete_competition", "sync_competitions",
            "list_training_plans", "update_training_plan", "preview_adaptive_replan", "apply_adaptive_replan",
            "list_recent_activities", "get_activity_details", "list_workout_library", "list_planned_workouts", "list_change_history",
            "apply_workout_library_plan", "delete_activity_feedback", "refresh_current_performance",
        }, names)

        competition = server.competition_service().save({
            "name": "Local Race", "event_date": "2099-01-01", "sport": "Cycling", "priority": "A",
        })["competition"]
        intent = {
            "intent": "local_action", "operation": "save_competition", "target_system": "local",
            "artifact_id": None, "ambiguities": [], "authorization_scope": ["local_competitions"],
        }
        listed = server.coach_tool_dispatch_service().execute(
            "list_competitions", {}, intent=intent, conversation_id="conversation-competition",
            client_turn_id="turn-competition", session_csrf_hash="", sync_job_ids=[],
        )
        self.assertEqual(listed["competitions"][0]["id"], competition["id"])

        with patch.object(server.SyncJobQueueService, "enqueue", return_value={"id": "job-competition"}) as enqueue:
            synced = server.coach_tool_dispatch_service().execute(
                "sync_competitions", {},
                intent={**intent, "operation": "sync_competitions", "intent": "remote_sync", "target_system": "intervals"},
                conversation_id="conversation-competition", client_turn_id="turn-competition-sync",
                session_csrf_hash="", sync_job_ids=[],
            )
        self.assertEqual(synced["sync_job_id"], "job-competition")
        enqueue.assert_called_once_with(
            "intervals", "competition_push", {"reason": "Bestätigter Coach-Auftrag"}, requested_by="coach",
        )

    def test_explicit_activity_detail_reads_only_the_requested_complete_raw_record(self):
        server.sync_state_repository().save_snapshot({
            "synced_at": "2026-09-11T08:00:00+00:00",
            "athlete": {},
            "recent_activities": [
                {"id": "activity-1", "name": "Tempo", "type": "Run", "start_date_local": "2026-09-10T07:00:00"},
                {"id": "activity-2", "name": "Recovery", "type": "Ride", "start_date_local": "2026-09-11T07:00:00"},
            ],
            "recent_wellness": [],
            "upcoming_calendar": [],
            "raw_provider_data": {
                "athlete": {},
                "activities": [
                    {
                        "id": "activity-1", "name": "Tempo", "type": "Run", "start_date_local": "2026-09-10T07:00:00",
                        "average_speed": 3.2, "average_heartrate": 166, "average_watts": 245,
                        "streams": {"watts": [200, 250, 280], "latlng": [[1, 2], [3, 4]]}, "provider_extra": "must not pass",
                    },
                    {"id": "activity-2", "name": "Recovery", "type": "Ride", "start_date_local": "2026-09-11T07:00:00", "average_watts": 120},
                ],
                "wellness": [],
                "upcoming_calendar": [],
            },
        })
        intent = {
            "intent": "local_action", "operation": "get_activity_details", "target_system": "local",
            "artifact_id": None, "ambiguities": [], "authorization_scope": [],
        }

        result = server.coach_tool_dispatch_service().execute(
            "get_activity_details", {"activity_id": "activity-1"}, intent=intent,
            conversation_id="conversation-activity-detail", client_turn_id="turn-activity-detail",
            session_csrf_hash="", sync_job_ids=[],
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["activity"]["streams"], {"watts": [200, 250, 280]})
        self.assertNotIn("id", result["activity"])
        self.assertNotIn("latlng", result["activity"]["streams"])
        self.assertNotIn("provider_extra", result["activity"])
        self.assertEqual(result["data_scope"], "bounded sanitized detail projection of exactly one Intervals.icu activity")
        self.assertNotIn("activity-2", json.dumps(result))
        self.assertEqual(result["activity_validation"]["activity"]["activity_id"], "activity-1")
        self.assertEqual(result["activity_validation"]["activity"]["sport"], "Laufen")

        with self.assertRaises(server.AppError) as missing:
            server.activity_read_service().detail(
                "activity-3",
                garmin_snapshot=server.garmin_payload_service().snapshot(),
                profile=server.profile_service().get(),
                today=server.ATHLETE_CLOCK.now().date(),
            )
        self.assertEqual(missing.exception.reason, "activity_details_not_found")

    def test_structured_coach_reads_local_detail_and_schedules_library_templates(self):
        template = server.workout_library_service().create_template({
            "sport": "Ride", "name": "Local tempo", "description": "- 60m 85%", "duration_minutes": 60,
        })
        tomorrow = (server.ATHLETE_CLOCK.now().date() + timedelta(days=1)).isoformat()
        intent = {
            "intent": "local_action", "operation": "apply_workout_library_plan", "target_system": "local",
            "artifact_id": None, "ambiguities": [], "authorization_scope": [f"library_workout:{template['id']}"],
        }
        scheduled = server.coach_tool_dispatch_service().execute(
            "apply_workout_library_plan", {"entries": [{"library_workout_id": template["id"], "date": tomorrow}]},
            intent=intent, conversation_id="conversation-library", client_turn_id="turn-library",
            session_csrf_hash="", sync_job_ids=[],
        )
        self.assertEqual(scheduled["local_planned"], 1)
        library = server.coach_tool_dispatch_service().execute(
            "list_workout_library", {"limit": 10}, intent=intent, conversation_id="conversation-library",
            client_turn_id="turn-library-read", session_csrf_hash="", sync_job_ids=[],
        )
        planned = server.coach_tool_dispatch_service().execute(
            "list_planned_workouts", {"limit": 10}, intent=intent, conversation_id="conversation-library",
            client_turn_id="turn-library-read", session_csrf_hash="", sync_job_ids=[],
        )
        self.assertEqual(library["templates"][0]["id"], template["id"])
        self.assertEqual(planned["local"][0]["date"], tomorrow)

    def test_structured_coach_can_keep_a_planning_conflict_local_before_push(self):
        planned = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=1)).isoformat(), "sport": "Ride", "name": "Local",
            "description": "- 30m 60% easy",
        })
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "UPDATE planned_units SET sync_state='conflict', sync_dirty=1, sync_conflict=? WHERE local_id=?",
                (json.dumps({"type": "remote_changed", "remote": {"name": "Remote"}}), planned["id"]),
            )
        result = server.coach_tool_dispatch_service().execute(
            "resolve_training_sync_conflict",
            {"local_id": planned["id"], "strategy": "keep_local"},
            intent={
                "intent": "local_action", "operation": "resolve_training_sync_conflict", "target_system": "local",
                "artifact_id": None, "ambiguities": [], "authorization_scope": [f"planned_unit:{planned['id']}"],
            },
            conversation_id="conversation-conflict", client_turn_id="turn-conflict",
            session_csrf_hash="", sync_job_ids=[],
        )
        self.assertEqual(result["planned_unit"]["sync_status"], "local")
        self.assertEqual(result["planned_unit"]["name"], "Local")

    def test_structured_state_exposes_current_local_targets_and_hashes(self):
        planned = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Run", "name": "Easy run", "description": "- 30m 60% easy",
        })
        template = server.workout_library_service().create_template({
            "sport": "Ride", "name": "Endurance", "description": "- 45m Z2", "duration_minutes": 45,
        })

        state = server.structured_training_state_service().read()

        planned_ref = next(item for item in state["planned_units"] if item["local_id"] == planned["id"])
        template_ref = next(item for item in state["training_templates"] if item["local_id"] == template["id"])
        self.assertRegex(planned_ref["expected_payload_hash"], r"^[0-9a-f]{64}$")
        self.assertRegex(template_ref["expected_payload_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(planned_ref["date"], planned["date"])

    def test_structured_coach_can_archive_multiple_templates_directly(self):
        templates = [server.workout_library_service().create_template({
            "sport": "Ride", "name": f"Template {index}", "description": "- 30m Z2", "duration_minutes": 30,
        }) for index in range(2)]
        intent = {
            "intent": "local_action", "operation": "manage_training_templates", "target_system": "local",
            "artifact_id": None, "ambiguities": [], "authorization_scope": ["local_template"],
        }

        result = server.coach_tool_dispatch_service().execute(
            "manage_training_templates",
            {"templates": [{"local_id": item["id"], "action": "archive"} for item in templates]},
            intent=intent, conversation_id="conversation-template", client_turn_id="turn-template",
            session_csrf_hash="", sync_job_ids=[],
        )

        self.assertEqual(len(result["templates"]), 2)
        self.assertEqual(server.workout_library_service().list(), [])
        self.assertEqual(len(server.workout_library_service().list(include_archived=True)), 2)

    def test_structured_coach_syncs_all_pending_plan_objects_without_selection(self):
        template = server.workout_library_service().create_template({
            "sport": "Ride", "name": "Template", "description": "- 45m Z2", "duration_minutes": 45,
        })
        planned = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Run", "name": "Planned", "description": "- 30m 60% easy",
        })
        intent = {
            "intent": "remote_sync", "operation": "start_intervals_plan_sync", "target_system": "intervals",
            "artifact_id": None, "ambiguities": [], "authorization_scope": ["local_plan"],
            "_sync_all_pending": True,
        }
        job_ids = []
        with patch.object(server.SyncJobQueueService, "enqueue", return_value={"id": "job-all"}) as enqueue:
            result = server.coach_tool_dispatch_service().execute(
                "start_intervals_plan_sync", {}, intent=intent,
                conversation_id="conversation-sync", client_turn_id="turn-sync",
                session_csrf_hash="", sync_job_ids=job_ids,
            )

        queued_ids = {item["library_workout_id"] for item in enqueue.call_args.args[2]["entries"]}
        self.assertEqual(queued_ids, {template["id"], planned["id"]})
        self.assertEqual(result["entries"], 2)
        self.assertEqual(job_ids, ["job-all"])

    def test_structured_coach_all_pending_sync_rejects_a_subset(self):
        first = server.workout_library_service().create_local_entry({
            "sport": "Ride", "name": "First pending", "description": "- 30m 60% easy", "duration_minutes": 30,
        })
        second = server.workout_library_service().create_local_entry({
            "sport": "Run", "name": "Second pending", "description": "- 20m 60% easy", "duration_minutes": 20,
        })
        intent = {
            "intent": "remote_sync", "operation": "start_intervals_plan_sync", "target_system": "intervals",
            "artifact_id": None, "ambiguities": [], "authorization_scope": ["local_plan"],
            "_sync_all_pending": True,
        }
        pending = {item["library_workout_id"]: item for item in server.planning_authority_service().pending_plan_push_entries()}
        with self.assertRaises(server.AppError) as error:
            server.coach_tool_dispatch_service().execute(
                "start_intervals_plan_sync",
                {"entries": [pending[first["id"]]]},
                intent=intent, conversation_id="conversation-sync-all", client_turn_id="turn-sync-all",
                session_csrf_hash="", sync_job_ids=[],
            )
        self.assertEqual(error.exception.reason, "intent_scope_denied")
        self.assertIn(second["id"], {item["library_workout_id"] for item in server.planning_authority_service().pending_plan_push_entries()})

    def test_coach_projection_helpers_are_dependency_light_and_bounded(self):
        from backend.coach.context import (
            bounded_coach_context_value,
            compact_coach_activity,
            compact_coach_local_planned_workouts,
        )
        from backend.activities.detail_projection import detailed_activity

        select = lambda value, fields: {key: value[key] for key in fields if key in value}
        activity = compact_coach_activity({"id": "a" * 300, "name": "n" * 300, "secret": "must not pass"}, select=select)
        self.assertEqual(len(activity["id"]), 200)
        self.assertNotIn("secret", activity)
        workouts = compact_coach_local_planned_workouts(
            [{"id": "2", "date": "2026-09-02", "name": "later"}, {"id": "1", "date": "2026-09-01", "name": "earlier"}],
            limit=1,
            select=select,
        )
        self.assertEqual([item["id"] for item in workouts], ["1"])
        self.assertLessEqual(len(json.dumps(bounded_coach_context_value({"text": "x" * 1000}, 100), ensure_ascii=False, separators=(",", ":"))), 100)
        detail = detailed_activity({
            "id": "provider-id", "average_watts": 245, "icu_weighted_avg_watts": 300, "provider_extra": "must not pass",
            "streams": {"watts": list(range(2505)), "latlng": [[1, 2]]},
        })
        self.assertEqual(detail["average_watts"], 245)
        self.assertEqual(detail["icu_weighted_avg_watts"], 300)
        self.assertEqual(len(detail["streams"]["watts"]), 2000)
        self.assertEqual(detail["streams"]["watts"][0], 0)
        self.assertEqual(detail["streams"]["watts"][-1], 2504)
        self.assertNotIn("id", detail)
        self.assertNotIn("provider_extra", detail)
        self.assertNotIn("latlng", detail["streams"])

    def test_coach_activity_feedback_is_persisted_and_attached_to_activity(self):
        server.sync_state_repository().save_snapshot({
            "synced_at": "2026-08-30T08:00:00+00:00",
            "athlete": {},
            "recent_activities": [{"id": "activity-1", "name": "Morgenlauf", "start_date_local": "2026-08-30T07:00:00"}],
            "recent_wellness": [],
            "upcoming_calendar": [],
        })
        result = server.activity_feedback_service().save_coach("activity-1", {
            "activity_name": "Morgenlauf", "activity_date": "2026-08-30T07:00:00", "notes": "Linkes Knie ungewohnt empfindlich",
        })
        self.assertEqual(result["activity_feedback"]["notes"], "Linkes Knie ungewohnt empfindlich")
        activity = server.public_state_service().read(local_only=True)["activities"][0]
        self.assertEqual(activity["activity_feedback"]["activity_id"], "activity-1")
        self.assertEqual(activity["activity_feedback"]["notes"], "Linkes Knie ungewohnt empfindlich")
        context = server.coach_structured_context_service().build()
        self.assertEqual(context["activity_feedback"]["recent"][0]["activity_name"], "Morgenlauf")
        self.assertIn("Linkes Knie", context["activity_feedback"]["recent"][0]["notes"])

    def test_coach_activity_feedback_requires_a_known_snapshot_activity(self):
        with self.assertRaises(server.AppError) as raised:
            server.activity_feedback_service().save_coach("unknown", {
                "activity_name": "Unbekannt", "activity_date": "2026-08-30", "notes": "War gut",
            })
        self.assertEqual(raised.exception.status, 404)

        server.sync_state_repository().save_snapshot({
            "synced_at": "now", "athlete": {},
            "recent_activities": [{"id": "activity-2", "name": "Abendlauf", "start_date_local": "2026-08-30T18:00:00"}],
            "recent_wellness": [], "upcoming_calendar": [],
        })
        result = server.activity_feedback_service().save_coach("activity-2", {
            "activity_name": "Abendlauf", "activity_date": "2026-08-30", "notes": "Locker, aber am Ende müde",
        })
        self.assertEqual(result["activity_feedback"]["activity_id"], "activity-2")

    def test_activity_history_feedback_is_read_only_and_coach_managed(self):
        markup = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        app = (server.PUBLIC_DIR / "app.js").read_text(encoding="utf-8")
        backend = Path(server.__file__).read_text(encoding="utf-8")
        self.assertNotIn('id="feedbackForm"', markup)
        self.assertNotIn("Lokales Athleten-Feedback", markup)
        self.assertIn('id="analysisHistorySegment"', markup)
        self.assertIn('data-analysis-segment="history"', markup)
        self.assertNotIn('id="activityDirtyIndicator"', markup)
        self.assertNotIn("function saveActivityFeedback", app)
        self.assertNotIn("Besonderheiten speichern", app)
        self.assertNotIn("activity-type-button", app)
        self.assertIn("if (feedbackNotes) {", app)
        self.assertIn("feedbackText.textContent = feedbackNotes;", app)
        self.assertIn('activity_feedback: ["feedback", "activities"]', app)
        self.assertNotIn('"^/api/activities/([^/]+)/feedback$"', backend)

    def test_structured_context_keeps_garmin_value_in_performance_only(self):
        server.key_value_service().set("garmin_snapshot", json.dumps({
            "max_metrics": {"running": {"vo2MaxValue": 55}},
            "race_predictions": {"5k": 1320},
            "activities": [{"activityId": 1, "activityName": "Duplicate raw activity"}],
        }))
        context = server.coach_structured_context_service().build({
            "synced_at": "now", "athlete": {}, "recent_activities": [],
            "recent_wellness": [], "upcoming_calendar": [],
        })

        self.assertNotIn("performance", context["garmin"])
        self.assertNotIn("activities", context["garmin"])
        self.assertEqual(context["current_performance"]["metrics"]["running_vo2max_ml_kg_min"]["value"], 55)
        self.assertEqual(context["current_performance"]["metrics"]["running_vo2max_ml_kg_min"]["source"], "Garmin Connect")
        self.assertEqual(context["current_performance"]["metrics"]["run_5k_seconds"]["value"], 1320)

    def test_manual_morning_quick_action_stops_before_coach_when_sleep_is_not_ready(self):
        receipt = {"request_kind": "morning_checkin"}
        error = server.AppError(503, "Garmin sleep is not ready", reason="garmin_sleep_not_ready")
        with patch("backend.coach.job_store.CoachJobStore.message", return_value="Morgen-Check-in"), patch(
            "backend.coach.job_store.CoachJobStore.merge_receipt"
        ), patch.object(server.ManualMorningCheckinService, "prepare", side_effect=error), patch(
            "backend.coach.chat_turn.CoachChatTurnService.run"
        ) as chat:
            with self.assertRaises(server.AppError):
                server.coach_background_job_runner()._execute(
                    {}, receipt, "operation", "client-turn", "session", threading.Event(), False
                )
        chat.assert_not_called()

    def test_completed_morning_background_job_returns_persisted_completion_receipt(self):
        completion = {"status": "completed", "coach_quick_actions": {"morning_checkin": False}}
        with patch("backend.coach.job_store.CoachJobStore.message", return_value="Morgen-Check-in"), patch(
            "backend.coach.job_store.CoachJobStore.merge_receipt"
        ), patch.object(server.ManualMorningCheckinService, "prepare"), patch(
            "backend.coach.chat_turn.CoachChatTurnService.run",
            return_value={"status": "completed", "message": {"content": "Guten Morgen"}},
        ), patch(
            "backend.coach.morning_completion.MorningCoachJobCompletionService.complete",
            return_value=completion,
        ) as persist_completion:
            result = server.coach_background_job_runner()._execute(
                {}, {"request_kind": "morning_checkin"}, "operation", "turn-morning", "session",
                threading.Event(), False,
            )

        self.assertEqual(result, completion)
        persist_completion.assert_called_once_with("turn-morning")

    def test_structured_command_failure_response_keeps_confirmed_sync_effects(self):
        commands = [{"tool": "start_intervals_plan_sync", "result": {"ok": True, "status": "queued"}}]
        status, text, question, cancelled = server.coach_turn_failure_service()._response(
            server.AppError(429, "Provider limit", reason="rate_limit_exceeded"), commands, commands, [], ["start_intervals_plan_sync"],
        )
        self.assertEqual(status, "partial")
        self.assertIsNone(question)
        self.assertFalse(cancelled)
        self.assertIn("Anfragelimit", text)
        self.assertIn("bleibt bestehen", text)
        self.assertIn("Noch offen", text)

    def test_structured_command_failure_response_keeps_completed_clarification(self):
        commands = [
            {"tool": "save_checkin", "result": {"ok": True, "status": "saved"}},
            {"tool": "clarify_coach_request", "result": {"ok": True, "question": "Wie fühlst du dich?"}},
        ]
        status, text, question, cancelled = server.coach_turn_failure_service()._response(
            server.AppError(502, "Provider error", reason="provider_unavailable"), commands, commands[:1], [], [],
        )
        self.assertEqual(status, "completed")
        self.assertTrue(text.startswith("Wie fühlst du dich?"))
        self.assertIn("Bereits erfolgreich ausgefuehrt", text)
        self.assertEqual(question, "Wie fühlst du dich?")
        self.assertFalse(cancelled)

    def test_structured_command_failure_response_keeps_partial_cancelled_effect(self):
        commands = [
            {"tool": "save_checkin", "result": {"ok": True, "status": "saved"}},
            {"tool": "clarify_coach_request", "result": {"ok": True, "question": "Wie fühlst du dich?"}},
        ]
        status, _text, question, cancelled = server.coach_turn_failure_service()._response(
            server.AppError(499, "Cancelled", reason="chat_cancelled"), commands, commands[:1], [], [],
        )
        self.assertEqual(status, "partial")
        self.assertEqual(question, "Wie fühlst du dich?")
        self.assertTrue(cancelled)

    def test_gemini_history_trimming_keeps_complete_tool_exchanges(self):
        history = [
            {"role": "user", "parts": [{"text": "Starte die Planung."}]},
            {"role": "model", "parts": [{"functionCall": {"name": "save_checkin", "args": {}}}]},
            {"role": "user", "parts": [{"functionResponse": {"name": "save_checkin", "response": {"ok": True}}}]},
            {"role": "model", "parts": [{"text": "Gespeichert."}]},
        ]
        for index in range(29):
            history.extend([
                {"role": "user", "parts": [{"text": f"Frage {index}"}]},
                {"role": "model", "parts": [{"text": f"Antwort {index}"}]},
            ])

        # Reproduce a legacy raw slice that starts with a tool response.
        server.key_value_service().set("gemini_conversation_history", json.dumps(history[-60:]))
        trimmed = server.gemini_conversation_history_service().load()

        self.assertEqual(len(trimmed), 58)
        self.assertEqual(trimmed[0]["parts"][0]["text"], "Frage 0")
        self.assertFalse(any("functionResponse" in part for content in trimmed for part in content["parts"]))

    def test_gemini_history_parts_preserve_safe_attachment_boundary(self):
        attachments = [
            {"type": "image", "name": "photo.jpg", "data": "raw-image", "mime": "image/jpeg"},
            {"type": "gpx", "name": "route.gpx", "data": "raw-file", "summary": {"distance": 12}},
        ]
        omitted = gemini_history_parts({"content": "Review this"}, attachments, 0, set())
        self.assertEqual(omitted[0], {"text": "Review this"})
        self.assertIn("raw_image_omitted", omitted[1]["text"])
        self.assertIn("untrusted_gpx", omitted[2]["text"])
        self.assertIn("raw_file_omitted", omitted[3]["text"])
        selected = gemini_history_parts({"content": "Review this"}, attachments, 0, {(0, 0)})
        self.assertEqual(selected[1]["inlineData"], {"mimeType": "image/jpeg", "data": "raw-image"})

    def test_gemini_rebuilds_history_from_the_shared_local_dialogue(self):
        server.coach_message_service().add("user", "Was war mein letzter Schwerpunkt?")
        server.coach_message_service().add("assistant", "Der Schwerpunkt war die Schwelle.")
        server.coach_message_service().add("user", "Und wie geht es weiter?")
        server.key_value_service().set("gemini_conversation_history", json.dumps([
            {"role": "user", "parts": [{"text": "Veraltete Gemini-Frage"}]},
            {"role": "model", "parts": [{"text": "Veraltete Gemini-Antwort"}]},
        ]))

        request, history, _ = build_gemini_request_payload(server, {"conversation": "gemini-shared-dialogue", "input": "Und wie geht es weiter?"}, "gemini-3.8-flash")

        self.assertEqual(history, request["contents"])
        self.assertEqual([content["parts"][0]["text"] for content in history], [
            "Was war mein letzter Schwerpunkt?", "Der Schwerpunkt war die Schwelle.", "Und wie geht es weiter?",
        ])

    def test_gemini_keeps_repeated_text_after_a_model_turn(self):
        server.key_value_service().set("gemini_conversation_history", json.dumps([
            {"role": "user", "parts": [{"text": "Ja"}]},
            {"role": "model", "parts": [{"text": "Ja"}]},
        ]))

        request, _, _ = build_gemini_request_payload(server, {"conversation": "gemini-repeated-text", "input": "Ja"}, "gemini-3.8-flash")

        self.assertEqual(request["contents"][-1], {"role": "user", "parts": [{"text": "Ja"}]})

    def test_structured_coach_exposes_checkin_and_activity_feedback_tools(self):
        names = {tool["name"] for tool in server.COACH_STRUCTURED_TOOLS}
        self.assertIn("save_checkin", names)
        self.assertIn("save_activity_feedback", names)
        stage = next(tool for tool in server.COACH_STRUCTURED_TOOLS if tool["name"] == "stage_training_plan")
        self.assertTrue(stage["strict"])
        payload = stage["parameters"]["properties"]["payload"]
        workout = payload["properties"]["workouts"]["items"]
        self.assertEqual(set(workout["required"]), set(workout["properties"]))
        self.assertEqual(workout["properties"]["duration_minutes"]["minimum"], 5)

    def test_context_preview_exposes_context_and_last_chat_input(self):
        server.coach_message_service().add("user", "Wie soll ich morgen trainieren?")
        preview = server.coach_context_preview_service().preview(server.SETTINGS.selected_ai_provider())
        self.assertIn("You are the athlete's long-term endurance coach.", preview["context_text"])
        self.assertIn("BEGIN UNTRUSTED EXTERNAL DATA", preview["context_text"])
        self.assertEqual(preview["chat_prompt"]["field"], "input")
        self.assertEqual(preview["chat_prompt"]["content"], "Wie soll ich morgen trainieren?")
        self.assertIn("instructions", preview["chat_prompt"]["note"])

    def test_coach_intervals_context_keeps_planned_event_limit(self):
        today = server.ATHLETE_CLOCK.now().date()
        events = [
            {"id": f"event-{index}", "name": f"Workout {index}",
             "start_date_local": (today + timedelta(days=1)).isoformat()}
            for index in range(coach_context.COACH_PLANNED_EVENT_LIMIT + 5)
        ]
        result = CoachIntervalsContextService().project(
            {}, events, today
        )
        self.assertEqual(
            len(result["planned_workouts"]), coach_context.COACH_PLANNED_EVENT_LIMIT
        )

    def test_context_budget_factories_use_backend_owned_values(self):
        training = server.coach_training_context_service()
        preview_limits = server.coach_context_preview_service()._limits
        expected = {
            "_local_planned_limit": coach_context.COACH_LOCAL_PLANNED_LIMIT,
            "_library_limit": coach_context.COACH_LIBRARY_LIMIT,
            "_library_description_limit": coach_context.COACH_LIBRARY_DESCRIPTION_LIMIT,
            "_section_limits": coach_context.COACH_CONTEXT_SECTION_LIMITS,
            "_total_char_limit": coach_context.COACH_CONTEXT_TOTAL_CHAR_LIMIT,
            "_activity_limit_per_sport": coach_context.COACH_RECENT_ACTIVITIES_PER_SPORT,
            "_planned_event_limit": coach_context.COACH_PLANNED_EVENT_LIMIT,
        }
        for attribute, value in expected.items():
            with self.subTest(attribute=attribute):
                self.assertEqual(getattr(training, attribute), value)
        self.assertEqual(preview_limits.local_planned_limit, coach_context.COACH_LOCAL_PLANNED_LIMIT)
        self.assertEqual(preview_limits.library_limit, coach_context.COACH_LIBRARY_LIMIT)
        self.assertEqual(preview_limits.library_description_limit, coach_context.COACH_LIBRARY_DESCRIPTION_LIMIT)
        self.assertEqual(preview_limits.section_limits, coach_context.COACH_CONTEXT_SECTION_LIMITS)
        self.assertEqual(preview_limits.total_char_limit, coach_context.COACH_CONTEXT_TOTAL_CHAR_LIMIT)
        self.assertEqual(preview_limits.activity_limit_per_sport, coach_context.COACH_RECENT_ACTIVITIES_PER_SPORT)
        self.assertEqual(preview_limits.planned_event_limit, coach_context.COACH_PLANNED_EVENT_LIMIT)

    def test_future_coach_planned_workouts_excludes_invalid_and_past_dates(self):
        today = date(2026, 9, 13)
        planned = future_coach_planned_workouts([
            {"name": "Later", "date": "2026-09-15"},
            {"name": "Invalid", "date": "not-a-date"},
            {"name": "Past", "start_date_local": "2026-09-12"},
            {"name": "Today", "date": "2026-09-13"},
        ], today)
        self.assertEqual([item["name"] for item in planned], ["Today", "Later"])

    def test_coach_intervals_context_is_deterministic_for_same_timestamps_and_missing_sports(self):
        today = server.ATHLETE_CLOCK.now().date()
        snapshot = {
            "synced_at": "now",
            "recent_activities": [
                {"id": "b", "type": "Ride", "name": "B", "start_date_local": today.isoformat()},
                {"id": "a", "type": "Ride", "name": "A", "start_date_local": today.isoformat()},
                {"id": "other", "name": "Unclassified", "start_date_local": today.isoformat()},
            ],
            "upcoming_calendar": [],
        }
        planned = server.planned_unit_service().list(250, future_only=True)
        first = CoachIntervalsContextService().project(snapshot, planned, today)
        second = CoachIntervalsContextService().project(
            {**snapshot, "recent_activities": list(reversed(snapshot["recent_activities"]))}, planned, today
        )
        self.assertEqual(first, second)
        self.assertEqual([item["id"] for item in first["recent_activities_by_sport"]["Radfahren"]], ["b", "a"])
        self.assertIn("Unclassified", first["recent_activities_by_sport"]["Unclassified"][0]["name"])

    def test_coach_planned_projection_omits_long_description_and_keeps_relevant_fields(self):
        today = server.ATHLETE_CLOCK.now().date()
        event = {
            "id": "planned-1",
            "start_date_local": (today + timedelta(days=1)).isoformat(),
            "name": "Threshold ride",
            "type": "Ride",
            "moving_time": 3600,
            "target": "2 x 20 min at threshold",
            "icu_intensity": 0.92,
            "status": "planned",
            "sync_status": "local",
            "description": "- 60m 92%\n\nprivate provider detail " + "x" * 20_000,
            "athlete_detail": "must not be projected",
        }
        server.planned_unit_service().create({**event, "sport": event["type"]})
        projected = CoachIntervalsContextService().project(
            {"upcoming_calendar": []}, server.planned_unit_service().list(250, future_only=True), today
        )["planned_workouts"][0]
        self.assertEqual(projected["name"], "Threshold ride")
        self.assertEqual(projected["status"], "planned")
        self.assertNotIn("description", projected)
        self.assertNotIn("athlete_detail", projected)

    def test_coach_context_requires_performance_assessment_for_completed_activity_analysis(self):
        context = server.coach_training_context_service().build()

        self.assertIn('"Leistungsfähigkeit und Entwicklung"', context)
        self.assertIn("VO2max", context)
        self.assertIn("Zone 2 pace", context)
        self.assertIn("keep FTP and Intervals.icu eFTP clearly separate", context)
        self.assertIn("do not claim a reliable trend", context)

    def test_coach_projection_does_not_change_provider_snapshots(self):
        today = server.ATHLETE_CLOCK.now().date()
        intervals_snapshot = {
            "synced_at": "now",
            "athlete": {"provider_detail": "kept in the full snapshot"},
            "recent_activities": [{
                "id": f"ride-{index}", "type": "Ride", "name": f"Ride {index}",
                "start_date_local": (today - timedelta(days=index)).isoformat(),
                "provider_detail": "kept in the full snapshot",
            } for index in range(6)],
            "recent_wellness": [],
            "upcoming_calendar": [],
        }
        garmin_snapshot = {
            "synced_at": "now",
            "activities": [{"activityId": 7, "vendor_payload": "kept in the full snapshot"}],
            "sleep": [{"calendarDate": today.isoformat(), "sleepScore": 82}],
            "vendor_payload": "kept in the full snapshot",
        }
        intervals_before = json.dumps(intervals_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        garmin_before = json.dumps(garmin_snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        server.sync_state_repository().save_snapshot(intervals_snapshot)
        server.key_value_service().set("garmin_snapshot", json.dumps(garmin_snapshot, ensure_ascii=False))

        context = server.coach_training_context_service().build()

        self.assertEqual(
            server.sync_state_repository().latest_snapshot(), intervals_snapshot
        )
        self.assertEqual(server.garmin_payload_service().snapshot(), garmin_snapshot)
        self.assertEqual(json.dumps(server.sync_state_repository().latest_snapshot(), ensure_ascii=False, sort_keys=True, separators=(",", ":")), intervals_before)
        self.assertEqual(json.dumps(server.garmin_payload_service().snapshot(), ensure_ascii=False, sort_keys=True, separators=(",", ":")), garmin_before)
        self.assertNotIn("provider_detail", context)
        self.assertNotIn("vendor_payload", context)

    def test_model_selection_is_persisted_and_validated(self):
        self.assertEqual(server.SETTINGS.selected_model(), "gpt-6-luna")
        self.assertEqual(server.SETTINGS.save_model("gpt-6-luna"), {"model": "gpt-6-luna"})
        self.assertEqual(server.SETTINGS.selected_model(), "gpt-6-luna")
        with self.assertRaises(server.AppError):
            server.SETTINGS.save_model("not-a-model")
        with self.assertRaises(server.AppError):
            server.SETTINGS.save_model("gpt-5.6-sol")

    def test_thinking_level_is_persisted_and_validated(self):
        self.assertEqual(server.SETTINGS.selected_thinking_level(), "medium")
        self.assertEqual(server.SETTINGS.save_thinking_level("high"), {"thinking_level": "high"})
        self.assertEqual(server.SETTINGS.selected_thinking_level(), "high")
        with self.assertRaises(server.AppError):
            server.SETTINGS.save_thinking_level("extreme")

    def test_reset_coach_chat_discards_outstanding_plan_drafts(self):
        artifact = server.training_plan_artifact_service().stage(
            {"payload": {"plan_name": "Reset test", "goal": "", "workouts": [{
                "date": "2099-01-02", "sport": "Run", "name": "Reset test",
                "description": "- 30m 60% easy", "duration_minutes": 30,
            }]}},
            "conversation-before-reset",
            "turn-before-reset",
        )
        with patch.object(server.openai_provider.OpenAIResponsesClient, "delete_conversation", return_value=True):
            result = server.coach_conversation_reset_service().reset()
        self.assertEqual(result["status"], "ok")
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            row = db.execute("SELECT status FROM coach_plan_artifacts WHERE id=?", (artifact["artifact_id"],)).fetchone()
        self.assertEqual(row["status"], "superseded")
        self.assertEqual(server.coach_dialogue_read_service().artifact_refs(), [])

    def test_coach_reset_keeps_local_history_when_reset_transaction_fails(self):
        message = server.coach_message_service().add("user", "Keep this message")
        generation = server.key_value_service().get("chat_generation")
        original_set = server.KEY_VALUE_REPOSITORY.set

        def fail_pending_request(db, key, value):
            if key == "coach_pending_request":
                raise RuntimeError("synthetic reset failure")
            return original_set(db, key, value)

        with patch.object(server.KEY_VALUE_REPOSITORY, "set", side_effect=fail_pending_request):
            with self.assertRaisesRegex(RuntimeError, "synthetic reset failure"):
                server.coach_conversation_reset_service().reset()
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            saved = db.execute("SELECT id FROM messages WHERE id=?", (message["id"],)).fetchone()
        self.assertIsNotNone(saved)
        self.assertEqual(server.key_value_service().get("chat_generation"), generation)

    def test_coach_reset_clears_local_state_when_remote_delete_fails(self):
        server.key_value_service().set("openai_conversation_id", "conv-reset-failure")
        server.coach_message_service().add("user", "Clear this message")
        with patch.object(
            server.openai_provider.OpenAIResponsesClient,
            "delete_conversation",
            side_effect=RuntimeError("synthetic remote failure"),
        ):
            result = server.coach_conversation_reset_service().reset()
        self.assertFalse(result["remote_conversation_deleted"])
        self.assertEqual(server.key_value_service().get("openai_conversation_id"), "")
        self.assertEqual(server.coach_message_service().list(), [])

    def test_background_job_replay_reuses_receipt_without_republishing(self):
        registry = server.coach_streams.CHAT_STREAM_REGISTRY

        def publish_after_commit(topic, event):
            self.assertEqual(topic, "coach")
            with server.database_manager().unit_of_work() as db:
                command = db.execute(
                    "SELECT status FROM coach_commands WHERE client_turn_id=?",
                    (event["client_turn_id"],),
                ).fetchone()
            self.assertEqual(command["status"], "queued")

        with (
            patch.object(server.runtime_events.STATE_EVENT_BUFFER, "publish", side_effect=publish_after_commit) as publish,
            patch.object(registry, "set_background_event") as register_event,
            patch.object(server.COACH_JOB_WORKER.wake_event, "set") as wake_worker,
        ):
            first = server.coach_job_submission_service().enqueue(
                "Eine lange Planung bitte", "turn-background-idempotent", "csrf-background-idempotent",
                operation_id="operation-background-idempotent",
            )
            replay = server.coach_job_submission_service().enqueue(
                "Andere Nachricht ignorieren", "turn-background-idempotent", "csrf-background-idempotent",
                operation_id="operation-background-replay",
            )
            with self.assertRaises(server.AppError) as foreign_replay:
                server.coach_job_submission_service().enqueue(
                    "Fremde Sitzung", "turn-background-idempotent", "csrf-background-foreign",
                )

        self.assertEqual(replay, first)
        self.assertEqual(foreign_replay.exception.reason, "command_scope_denied")
        publish.assert_called_once()
        register_event.assert_called_once()
        wake_worker.assert_called_once()

    def test_coach_planning_reuses_matching_local_template(self):
        template = server.workout_library_remote_reconciler().reconcile([{
            "id": "remote-template-1",
            "name": "Locker Lauf",
            "type": "Run",
            "description": "- 30m 60% Pace locker",
            "moving_time": 1800,
        }])[0]
        planned = server.local_plan_creation_service().save([{
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Run",
            "name": "Locker Lauf",
            "description": "- 30m 60% Pace locker",
            "duration_minutes": 30,
            "target": "PACE",
            "rationale": "Grundlage",
        }])[0]

        library = server.workout_library_service().list(include_archived=True)
        self.assertEqual(len(library), 1)
        self.assertEqual(template["id"], next(item["id"] for item in library if not item.get("date")))
        self.assertEqual(planned["source"], "library")
        self.assertEqual(planned["date"], (date.today() + timedelta(days=1)).isoformat())
        self.assertIsNone(planned["external_id"])

    def test_saved_profile_is_included_in_coach_context(self):
        server.profile_service().save({"name": "Ada", "goals": "Münsterland Giro", "constraints": "No hard sessions after poor sleep"})
        context = server.coach_training_context_service().build()
        self.assertIn('"name":"Ada"', context)
        self.assertIn("Münsterland Giro", context)
        self.assertIn("No hard sessions after poor sleep", context)

    def test_coach_can_create_update_and_delete_competition_without_replacing_profile(self):
        server.profile_service().save({"name": "Ada", "goals": "Long course"})
        event_date = (date.today() + timedelta(days=60)).isoformat()
        arguments = {
            "competition_id": "",
            "name": "Münsterland Giro",
            "event_date": event_date,
            "start_date_local": "",
            "sport": "Cycling",
            "priority": "A",
            "distance": "125 km",
            "target": "Finish strong",
            "course_profile": "Rolling",
            "notes": "",
            "description": "",
            "moving_time_seconds": -1,
        }
        created = server.competition_service().save(arguments)
        competition_id = created["competition"]["id"]
        self.assertEqual(created["status"], "created")
        self.assertEqual(server.profile_service().get()["name"], "Ada")

        updated = server.competition_service().save({
            **arguments,
            "competition_id": competition_id,
            "name": "Münsterland Giro 2027",
            "priority": "B",
        })
        self.assertEqual(updated["status"], "updated")
        self.assertEqual(updated["competition"]["name"], "Münsterland Giro 2027")
        self.assertEqual(updated["competition"]["priority"], "B")

        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "UPDATE competitions SET intervals_event_id=?, external_id=? WHERE id=?",
                ("123", planning_competitions.competition_external_id(competition_id), competition_id),
            )
        deleted = server.competition_service().delete(competition_id)
        self.assertEqual(deleted["status"], "deleted")
        self.assertTrue(deleted["remote_sync_pending"])
        self.assertEqual(server.competition_service().list(), [])
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            tombstone = db.execute("SELECT intervals_event_id, external_id FROM competition_sync_tombstones").fetchone()
        self.assertEqual(tombstone["intervals_event_id"], "123")

    def test_coach_competition_update_is_pushed_to_existing_remote_event(self):
        event_date = (date.today() + timedelta(days=60)).isoformat()
        saved = server.athlete_context_service().save({}, [{"name": "Old Race", "event_date": event_date, "sport": "Cycling"}])
        competition_id = saved["competitions"][0]["id"]
        external_id = planning_competitions.competition_external_id(competition_id)
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "UPDATE competitions SET intervals_event_id=?, external_id=?, sync_dirty=0 WHERE id=?",
                ("123", external_id, competition_id),
            )
        server.competition_service().save({
            "competition_id": competition_id,
            "name": "Updated Race",
            "event_date": event_date,
            "start_date_local": "",
            "sport": "Cycling",
            "priority": "A",
            "distance": "100 km",
            "target": "Finish",
            "course_profile": "Road",
            "notes": "Updated locally",
            "description": "Updated locally",
            "moving_time_seconds": -1,
        })
        pushed = []

        class FakeIntervalsClient:
            def fetch_competition_events(self):
                return [{
                    "id": 123, "category": "RACE_B", "start_date_local": event_date + "T08:00:00",
                    "type": "Ride", "name": "Old Race",
                }]

            def upsert_competition_events(self, events):
                pushed.extend(events)
                return [{**events[0], "id": 123}] if events else []

            def bulk_delete_events(self, identifiers):
                return 0

        with patch.object(server, "intervals_client", FakeIntervalsClient), patch.object(
            server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")
        ):
            result = server.competition_sync_service().sync("test", push_local=True)

        self.assertEqual(result["pushed"], 1)
        self.assertEqual(pushed[0]["id"], 123)
        self.assertEqual(pushed[0]["name"], "Updated Race")
        self.assertEqual(server.competition_service().list()[0]["sync_dirty"], 0)

    def test_coach_quick_actions_hide_completed_morning_and_limit_plan_blockers_to_three_days(self):
        today = server.ATHLETE_CLOCK.now().date()
        server.key_value_service().set("morning_checkin_status", "ready")
        server.key_value_service().set("morning_checkin_date", today.isoformat())
        preview = {
            "changes": [
                {"date": (today + timedelta(days=2)).isoformat(), "name": "Lange Ausfahrt", "blocking_triggers": ["weather"]},
                {"date": (today + timedelta(days=3)).isoformat(), "name": "Spätere Ausfahrt", "blocking_triggers": ["calendar"]},
                {"date": today.isoformat(), "name": "Intervalle", "blocking_triggers": []},
            ]
        }
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            server.PLAN_ADJUSTMENT_REPOSITORY.create_preview(db, str(uuid.uuid4()), json.dumps(preview), server.utc_now())
        actions = server.coach_quick_actions_service().state()
        self.assertFalse(actions["morning_checkin"])
        self.assertTrue(actions["adjust_plan"])
        self.assertEqual([item["name"] for item in actions["plan_blockers"]], ["Lange Ausfahrt"])
        self.assertEqual(actions["horizon_days"], 3)

    def test_background_cancel_event_can_be_recreated_after_process_restart(self):
        registry = coach_streams.ChatStreamRegistry()
        event = threading.Event()
        response = Mock()
        event._provider_response = response
        registry.set_background_event("background-operation", event)
        returned_event, active_response = registry.cancel_background_event("background-operation")
        self.assertIs(returned_event, event)
        self.assertIs(active_response, response)
        self.assertTrue(event.is_set())
        registry.remove_background_event("background-operation")
        self.assertIsNone(registry.get_background_event("background-operation"))

    def test_coach_action_preview_input_validates_safe_action_contract(self):
        values = {
            "action_type": "undo_change",
            "target_system": "local",
            "object_ids": {"history_id": "change-1"},
            "diff": {"fields": {"name": {"changed": True}}},
            "payload": {"history_id": "change-1"},
        }
        self.assertEqual(
            validated_coach_action_preview_input(values),
            ("undo_change", "local", values["object_ids"], values["diff"], values["payload"]),
        )
        for invalid in (
            None,
            {**values, "action_type": "unknown"},
            {**values, "target_system": "intervals"},
            {**values, "diff": {}},
            {**values, "payload": []},
        ):
            with self.subTest(invalid=invalid), self.assertRaises(server.AppError) as error:
                validated_coach_action_preview_input(invalid)
            self.assertEqual(error.exception.status, 400)

    def test_coach_dialogue_command_result_bounds_receipt_details(self):
        row = {"client_turn_id": "turn-1", "receipt": json.dumps({
            "status": "completed", "sync_job_ids": list(range(50)),
            "command_receipts": [{"tool": "save_checkin", "result": {"ok": True, "status": "saved"}, "request": {"scope": list(range(50))}}],
        })}
        result = server.coach_dialogue_read_service()._command_result(row)
        self.assertEqual(result["client_turn_id"], "turn-1")
        self.assertEqual(len(result["sync_job_ids"]), 40)
        self.assertTrue(result["steps"][0]["scope_truncated"])
        self.assertEqual(len(result["steps"][0]["scope"]), 40)


if __name__ == "__main__":
    unittest.main()
