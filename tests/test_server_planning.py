"""Server integration tests for planning."""

import json
import threading
import unittest
import uuid
from dataclasses import replace
from datetime import date, datetime, timedelta
from unittest.mock import call, patch

from backend import change_history
from backend.activities import calendar_projection as activity_calendar_projection
from backend.coach import context as coach_context, limits as coach_limits
from backend.coach.response_transport import raise_if_chat_cancelled
from backend.planning import adaptive as planning_adaptive, competitions as planning_competitions, season as planning_season, workouts as planning_workouts
from backend.providers import intervals_client as intervals_client_module
from backend.runtime import events as runtime_events
from backend.sync.intervals import IntervalsSnapshotReader
from backend.sync.library import WorkoutLibraryRefreshService
from backend.sync.planned_units import RemotePlannedUnitReconciler
from server_test_support import _current_performance_context, server, ServerTestCase
from support import IntervalsRequestRecorder, parsed_workout_fixture, RecordedIntervalsClient


class ServerPlanningTests(ServerTestCase):

    def test_structured_plan_push_declares_and_uses_bounded_entries(self):
        planned = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=1)).isoformat(), "sport": "Run", "name": "Synthetic selected run",
            "description": "- 30m 60% Synthetic easy session", "duration_minutes": 30,
        })
        local_id = planned["id"]
        entry = next(item for item in server.planning_authority_service().pending_plan_push_entries() if item["library_workout_id"] == local_id)
        intent = {
            "intent": "remote_sync",
            "operation": "start_intervals_plan_sync",
            "target_system": "intervals",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": [f"library_workout:{local_id}"],
        }
        with patch.object(server.SyncJobQueueService, "enqueue", return_value={"id": "job-plan-push"}) as enqueue:
            result = server.coach_tool_dispatch_service().execute(
                "start_intervals_plan_sync",
                {"entries": [entry]},
                intent=intent,
                conversation_id="conversation-push",
                client_turn_id="turn-push",
                session_csrf_hash="",
                sync_job_ids=[],
            )
        schema = next(tool for tool in server.COACH_STRUCTURED_TOOLS if tool["name"] == "start_intervals_plan_sync")["parameters"]
        self.assertIn("entries", schema["properties"])
        self.assertEqual(result["status"], "queued")
        self.assertEqual(enqueue.call_args.kwargs["item_operations"][0]["item_key"], local_id)

    def test_structured_performance_refresh_and_competition_push_are_queued_jobs(self):
        refresh_intent = {
            "intent": "remote_sync", "operation": "refresh_current_performance", "target_system": "intervals",
            "artifact_id": None, "ambiguities": [], "authorization_scope": ["intervals_refresh"],
        }
        competition_intent = {
            "intent": "remote_sync", "operation": "sync_competitions", "target_system": "intervals",
            "artifact_id": None, "ambiguities": [], "authorization_scope": ["local_competitions"],
        }
        with patch.object(
            server.SyncJobQueueService,
            "enqueue",
            side_effect=[{"id": "job-performance"}, {"id": "job-competition"}],
        ) as enqueue:
            performance = server.coach_tool_dispatch_service().execute(
                "refresh_current_performance", {}, intent=refresh_intent, conversation_id="conversation-jobs",
                client_turn_id="turn-performance", session_csrf_hash="", sync_job_ids=[],
            )
            competition = server.coach_tool_dispatch_service().execute(
                "sync_competitions", {}, intent=competition_intent, conversation_id="conversation-jobs",
                client_turn_id="turn-competition", session_csrf_hash="", sync_job_ids=[],
            )
        self.assertEqual(performance["sync_job_id"], "job-performance")
        self.assertEqual(competition["sync_job_id"], "job-competition")
        self.assertEqual(enqueue.call_args_list[0].args[:2], ("intervals", "performance_refresh"))
        self.assertEqual(enqueue.call_args_list[1].args[:2], ("intervals", "competition_push"))

    def test_explicit_competition_push_preserves_provider_id_for_ordinary_edits(self):
        competition = server.competition_service().save({
            "name": "Linked Race", "event_date": "2099-01-02", "sport": "Cycling",
        })["competition"]
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "UPDATE competitions SET intervals_event_id='123', sync_dirty=1, sync_state='local', sync_conflict='' WHERE id=?",
                (competition["id"],),
            )

        self.assertEqual(server.planning_authority_service().mark_competitions_authoritative(), 1)
        local_override = server.competition_service().list()[0]
        self.assertEqual(local_override["intervals_event_id"], "123")
        self.assertEqual(local_override["sync_state"], "local_override")

        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "UPDATE competitions SET sync_state='conflict', sync_conflict=? WHERE id=?",
                (json.dumps({"type": "remote_missing"}), competition["id"]),
            )
        server.planning_authority_service().mark_competitions_authoritative()
        recreated = server.competition_service().list()[0]
        self.assertIsNone(recreated["intervals_event_id"])

    def test_apply_training_changes_rejects_unknown_create_target(self):
        intent = {
            "intent": "local_action", "operation": "apply_training_changes", "target_system": "local",
            "artifact_id": None, "ambiguities": [], "authorization_scope": ["local_plan_create"],
        }
        with self.assertRaises(server.AppError) as error:
            server.coach_tool_dispatch_service().execute(
                "apply_training_changes",
                {"changes": [{
                    "action": "create", "date": (date.today() + timedelta(days=4)).isoformat(),
                    "sport": "Run", "name": "Bad target", "description": "- 20m 60% easy",
                    "duration_minutes": 20, "target": "CADENCE", "rationale": "Test",
                }]},
                intent=intent, conversation_id="conversation-target", client_turn_id="turn-target",
                session_csrf_hash="", sync_job_ids=[],
            )
        self.assertEqual(error.exception.reason, "invalid_change")

    def test_mixed_create_recomputes_attached_plan_bounds(self):
        original_date = (date.today() + timedelta(days=5)).isoformat()
        created = server.local_plan_creation_service().save([{
            "date": original_date, "sport": "Ride", "name": "Plan start",
            "description": "- 30m 60% easy", "duration_minutes": 30, "target": "AUTO",
            "rationale": "Base",
        }], plan_name="Bounds plan", goal="Consistency")
        plan_id = created[0]["plan_id"]
        existing_id = created[0]["id"]
        state = server.structured_training_state_service().read()
        target = next(item for item in state["planned_units"] if item["local_id"] == existing_id)
        later_date = (date.today() + timedelta(days=12)).isoformat()
        intent = {
            "intent": "local_action", "operation": "apply_training_changes", "target_system": "local",
            "artifact_id": None, "ambiguities": [],
            "authorization_scope": ["local_plan_create", f"planned_unit:{existing_id}"],
        }
        result = server.coach_tool_dispatch_service().execute(
            "apply_training_changes",
            {"changes": [{"local_id": existing_id, "action": "update", "date": original_date,
                           "expected_payload_hash": target["expected_payload_hash"]}, {
                "action": "create", "date": later_date, "sport": "Run", "name": "Recovery",
                "description": "- 20m 60% easy", "duration_minutes": 20, "target": "AUTO",
                "rationale": "Recovery",
            }]},
            intent=intent, conversation_id="conversation-bounds", client_turn_id="turn-bounds",
            session_csrf_hash="", sync_job_ids=[],
        )
        self.assertEqual(result["status"], "applied")
        plan = next(item for item in server.training_plan_service().list() if item["id"] == plan_id)
        self.assertEqual(plan["start_date"], original_date)
        self.assertEqual(plan["end_date"], later_date)

    def test_non_date_plan_edit_does_not_overwrite_metadata_bounds(self):
        original_date = (date.today() + timedelta(days=8)).isoformat()
        created = server.local_plan_creation_service().save([{
            "date": original_date, "sport": "Ride", "name": "Plan workout",
            "description": "- 30m 60% easy", "duration_minutes": 30, "target": "AUTO",
            "rationale": "Base",
        }], plan_name="Metadata plan", goal="Consistency")
        plan_id = created[0]["plan_id"]
        server.training_plan_service().update(plan_id, {
            "start_date": "2099-01-01", "end_date": "2099-12-31",
        })
        state = server.structured_training_state_service().read()
        target = next(item for item in state["planned_units"] if item["local_id"] == created[0]["id"])
        intent = {
            "intent": "local_action", "operation": "apply_training_changes", "target_system": "local",
            "artifact_id": None, "ambiguities": [], "authorization_scope": [f"planned_unit:{created[0]['id']}"],
        }
        server.coach_tool_dispatch_service().execute(
            "apply_training_changes",
            {"changes": [{"local_id": created[0]["id"], "action": "update", "name": "Renamed",
                           "expected_payload_hash": target["expected_payload_hash"]}]},
            intent=intent, conversation_id="conversation-metadata", client_turn_id="turn-metadata",
            session_csrf_hash="", sync_job_ids=[],
        )
        plan = next(item for item in server.training_plan_service().list() if item["id"] == plan_id)
        self.assertEqual(plan["start_date"], "2099-01-01")
        self.assertEqual(plan["end_date"], "2099-12-31")

    def test_adaptive_replan_shortens_long_ride_on_near_term_all_day_rain(self):
        tomorrow = (server.ATHLETE_CLOCK.now().date() + timedelta(days=1)).isoformat()
        draft = server.local_plan_creation_service().save([{
            "date": tomorrow, "sport": "Ride", "name": "Lange Ausfahrt",
            "description": "- 240m 60% Easy endurance ride", "duration_minutes": 240, "target": "POWER",
        }])[0]
        with patch.object(server.weather_service(), "state", return_value={"days": [{
            "date": tomorrow, "weather_code": 63, "precipitation_probability_max": 100,
            "rain_sum": 12, "showers_sum": 0, "snowfall_sum": 0,
        }]}) as weather:
            preview = server.adaptive_replan_preview_service().preview()
        weather.assert_called_once_with(refresh=False)
        self.assertEqual(preview["changes"][0]["library_workout_id"], draft["id"])
        self.assertEqual(preview["changes"][0]["after"]["duration_minutes"], 90)
        self.assertIn("Wetterprognose", preview["changes"][0]["after"]["rationale"])

    def test_adaptive_replan_ignores_near_term_rain_for_indoor_or_later_rides(self):
        tomorrow = server.ATHLETE_CLOCK.now().date() + timedelta(days=1)
        day_three = server.ATHLETE_CLOCK.now().date() + timedelta(days=3)
        drafts = server.local_plan_creation_service().save([
            {"date": tomorrow.isoformat(), "sport": "VirtualRide", "name": "Indoor lang", "description": "- 240m 60% Indoor endurance ride", "duration_minutes": 240},
            {"date": day_three.isoformat(), "sport": "Ride", "name": "Spätere Ausfahrt", "description": "- 240m 60% Outdoor endurance ride", "duration_minutes": 240},
        ])
        with patch.object(server.weather_service(), "state", return_value={"days": [{
            "date": tomorrow.isoformat(), "weather_code": 63, "precipitation_probability_max": 100,
            "rain_sum": 12, "showers_sum": 0, "snowfall_sum": 0,
        }]}):
            preview = server.adaptive_replan_preview_service().preview()
        self.assertEqual(preview["changes"], [])
        self.assertEqual({draft["name"] for draft in drafts}, {"Indoor lang", "Spätere Ausfahrt"})

    def test_planning_state_exposes_required_adaptive_update(self):
        server.profile_service().save({"weather_location": ""})
        with patch.object(server.AdaptiveReplanPreviewService, "latest_preview", return_value={"status": "preview", "changes": [{"date": "2026-09-01"}]}):
            planning = planning_season.planning_state(
                server.competition_service().list(),
                server.ATHLETE_CLOCK.now().date(),
                server.adaptive_replan_preview_service().latest_preview(),
                server.adaptive_replan_preview_service().status(),
            )
        self.assertTrue(planning["needs_replan"])
        self.assertEqual(planning["replan_changes"], 1)

    def test_local_feedback_is_persisted_without_provider_values(self):
        local_today = server.ATHLETE_CLOCK.now().date().isoformat()
        result = server.checkin_service().save({
            "checkin_date": local_today, "soreness": "7", "stress": "4", "motivation": "8",
            "available_minutes": "45", "day_form": "Schwere Beine und müde", "illness": "",
            "pain": "left knee", "notes": "Short easy session preferred",
        })
        self.assertEqual(result["checkin"]["soreness"], 7)
        self.assertEqual(result["checkin"]["day_form"], "Schwere Beine und müde")
        self.assertEqual(server.checkin_service().context()["today"]["pain"], "left knee")
        with self.assertRaises(server.AppError):
            server.checkin_service().save({"soreness": 11})

    def test_empty_activity_feedback_removes_entry_and_input_is_bounded(self):
        result = server.activity_feedback_service().save(
            "activity-2", {"notes": "x" * 5000}
        )
        self.assertEqual(len(result["activity_feedback"]["notes"]), 4000)
        server.activity_feedback_service().save("activity-2", {"notes": "   "})
        self.assertEqual(server.activity_feedback_service().list(), [])

    def test_adaptive_replan_only_changes_future_local_drafts_after_preview(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        draft = server.local_plan_creation_service().save([{
            "date": tomorrow, "sport": "Ride", "name": "VO2 intervals",
            "description": "- 5m 115%\n- 40m 55%", "duration_minutes": 45, "target": "POWER",
        }])[0]
        server.checkin_service().save({"illness": "Fever", "soreness": 8})
        preview = server.adaptive_replan_preview_service().preview()
        self.assertEqual(preview["illness_pause"]["recommended_pause_days"], planning_adaptive.DEFAULT_ILLNESS_PAUSE_DAYS)
        self.assertEqual(preview["illness_pause"]["start_date"], server.ATHLETE_CLOCK.now().date().isoformat())
        self.assertEqual(len(preview["changes"]), 1)
        self.assertEqual(server.planned_unit_service().list()[0]["description"], "- 5m 115%\n- 40m 55%")
        result = server.illness_pause_sync_service().apply(preview["id"])
        self.assertEqual(result["updated"], 1)
        self.assertEqual(server.planned_unit_service().list(), [])
        self.assertTrue(server.planned_unit_service().list(include_archived=True)[0]["archived"])
        self.assertEqual(server.planned_unit_service().list(include_archived=True)[0]["description"], "- 5m 115%\n- 40m 55%")
        checkins = {
            row["checkin_date"]: row for row in server.checkin_service().list(30)
        }
        for offset in range(planning_adaptive.DEFAULT_ILLNESS_PAUSE_DAYS):
            pause_date = (server.ATHLETE_CLOCK.now().date() + timedelta(days=offset)).isoformat()
            self.assertEqual(checkins[pause_date]["illness"], "Fever")
        repeated_preview = server.adaptive_replan_preview_service().preview()
        self.assertTrue(repeated_preview["illness_pause"]["approved"])
        self.assertFalse(server.adaptive_replan_preview_service().status()["illness_pause_pending"])
        self.assertEqual(server.planned_unit_service().list(include_archived=True)[0]["id"], draft["id"])

    def test_adaptive_preview_rejects_changed_target_and_is_idempotent(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        draft = server.local_plan_creation_service().save([{
            "date": tomorrow, "sport": "Ride", "name": "VO2 intervals",
            "description": "- 5m 115%\n- 40m 55%", "duration_minutes": 45, "target": "POWER",
        }])[0]
        server.checkin_service().save({"illness": "Fever", "soreness": 8})
        preview = server.adaptive_replan_preview_service().preview()
        self.assertTrue(preview["changes"][0].get("source_fingerprint"))
        server.planned_unit_service().update(draft["id"], {"action": "update", "name": "Athletenänderung"})

        result = server.illness_pause_sync_service().apply(preview["id"])
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["stale"][0]["reason"], "changed")
        self.assertEqual(server.planned_unit_service().list()[0]["name"], "Athletenänderung")
        repeated = server.illness_pause_sync_service().apply(preview["id"])
        self.assertEqual(repeated["status"], "already_stale")

    def test_adaptive_preview_reports_missing_target_and_repeat_apply_is_safe(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        draft = server.local_plan_creation_service().save([{
            "date": tomorrow, "sport": "Ride", "name": "VO2 intervals",
            "description": "- 5m 115%\n- 40m 55%", "duration_minutes": 45, "target": "POWER",
        }])[0]
        server.checkin_service().save({"illness": "Fever", "soreness": 8})
        preview = server.adaptive_replan_preview_service().preview()
        server.planned_unit_service().update(draft["id"], {"action": "delete"})
        result = server.illness_pause_sync_service().apply(preview["id"])
        self.assertEqual(result["status"], "stale")
        self.assertEqual(result["stale"][0]["reason"], "missing")

        fresh = server.local_plan_creation_service().save([{
            "date": tomorrow, "sport": "Ride", "name": "Tempo",
            "description": "- 5m 110%\n- 40m 55%", "duration_minutes": 45, "target": "POWER",
        }])[0]
        fresh_preview = server.adaptive_replan_preview_service().preview()
        applied = server.illness_pause_sync_service().apply(fresh_preview["id"])
        self.assertEqual(applied["status"], "ok")
        self.assertGreaterEqual(applied["updated"], 1)
        self.assertEqual(server.illness_pause_sync_service().apply(fresh_preview["id"])["status"], "already_applied")
        self.assertEqual(server.planned_unit_service().list(), [])
        self.assertIn(fresh["id"], [item["id"] for item in server.planned_unit_service().list(include_archived=True)])

    def test_planned_workouts_match_activities_and_roll_up_weekly_compliance(self):
        today = date(2026, 8, 26)
        events = [
            {
                "id": "event-done", "category": "WORKOUT", "type": "Ride",
                "name": "Tempo", "start_date_local": f"{today.isoformat()}T00:00:00",
                "moving_time": 3600, "icu_training_load": 50,
            },
            {
                "id": "event-missed", "category": "WORKOUT", "type": "Ride",
                "name": "Grundlage", "start_date_local": f"{(today - timedelta(days=1)).isoformat()}T00:00:00",
                "moving_time": 3600, "icu_training_load": 50,
            },
            {
                "id": "race", "category": "RACE", "type": "Ride",
                "name": "Wettkampf", "start_date_local": f"{(today - timedelta(days=1)).isoformat()}T00:00:00",
                "moving_time": 7200, "icu_training_load": 100,
            },
        ]
        activities = [{
            "id": "activity-1", "paired_event_id": "event-done", "type": "Ride",
            "name": "Tempo gefahren", "start_date_local": f"{today.isoformat()}T07:00:00",
            "moving_time": 3300, "distance": 25000, "icu_training_load": 40, "icu_rpe": 6,
            "private_note": "must stay out of calendar",
        }]

        with patch.object(server.ATHLETE_CLOCK, "now", return_value=datetime(2026, 8, 26, 12, 0)):
            enriched, weekly = activity_calendar_projection.planning_compliance_state(
                events, activities, today
            )

        self.assertEqual(enriched[0]["compliance"]["status"], "completed")
        self.assertEqual(enriched[0]["compliance"]["percentage"], 80)
        self.assertEqual(enriched[0]["compliance"]["actual_activity"]["icu_rpe"], 6)
        self.assertEqual(enriched[0]["compliance"]["actual_activity"]["icu_training_load"], 40)
        self.assertNotIn("private_note", enriched[0]["compliance"]["actual_activity"])
        self.assertEqual(enriched[1]["compliance"]["status"], "missed")
        self.assertEqual(enriched[1]["compliance"]["percentage"], 0)
        self.assertNotIn("compliance", enriched[2])

        current_week = next(item for item in weekly if item["week_start"] == (today - timedelta(days=today.weekday())).isoformat())
        if today.weekday() == 0:
            # On Monday, yesterday belongs to the previous calendar week.
            self.assertEqual(current_week["planned_units"], 1)
            self.assertEqual(current_week["completed_units"], 1)
            self.assertEqual(current_week["unit_percentage"], 100)
            self.assertEqual(current_week["percentage"], 80)
            previous_week = next(item for item in weekly if item["week_start"] == (today - timedelta(days=7)).isoformat())
            self.assertEqual(previous_week["planned_units"], 1)
            self.assertEqual(previous_week["completed_units"], 0)
            self.assertEqual(previous_week["unit_percentage"], 0)
            self.assertEqual(previous_week["percentage"], 0)
            self.assertEqual(previous_week["basis"], "training_load")
        else:
            self.assertEqual(current_week["planned_units"], 2)
            self.assertEqual(current_week["completed_units"], 1)
            self.assertEqual(current_week["unit_percentage"], 50)
            self.assertEqual(current_week["percentage"], 40)
            self.assertEqual(current_week["basis"], "training_load")

    def test_workout_compliance_uses_duration_and_unavailable_fallbacks(self):
        today = date(2026, 9, 12)
        duration_event = {"start_date_local": today.isoformat(), "moving_time": 3600}
        duration_activity = {"id": "done", "start_date_local": today.isoformat(), "moving_time": 2700}
        duration = activity_calendar_projection.workout_compliance(
            duration_event, duration_activity, today
        )
        self.assertEqual((duration["basis"], duration["percentage"]), ("duration", 75))
        unavailable = activity_calendar_projection.workout_compliance(
            {"start_date_local": today.isoformat()}, duration_activity, today
        )
        self.assertEqual((unavailable["basis"], unavailable["percentage"]), ("unavailable", 100))

    def test_planned_workout_fallback_matches_unpaired_same_day_sport(self):
        today = server.ATHLETE_CLOCK.now().date().isoformat()
        enriched, _ = activity_calendar_projection.planning_compliance_state(
            [{"id": "event-1", "category": "WORKOUT", "type": "Run", "start_date_local": f"{today}T00:00:00", "moving_time": 1800}],
            [{"id": "activity-1", "type": "Run", "start_date_local": f"{today}T08:00:00", "moving_time": 1500}],
            date.fromisoformat(today),
        )
        self.assertEqual(enriched[0]["compliance"]["status"], "completed")
        self.assertEqual(enriched[0]["compliance"]["percentage"], 83)

    def test_remote_planned_units_import_idempotently_and_record_conflicts(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        event = {
            "id": "remote-event-1", "external_id": "intervals-event-1", "category": "WORKOUT",
            "start_date_local": tomorrow + "T07:00:00", "type": "Ride", "name": "Remote Einheit",
            "description": "- 30m Z2", "moving_time": 1800,
        }
        first = server.remote_planned_unit_reconciler().reconcile([event])
        revision_after_import = server.structured_training_state_service().read()["planning_revision"]
        second = server.remote_planned_unit_reconciler().reconcile([event])
        self.assertEqual(server.structured_training_state_service().read()["planning_revision"], revision_after_import)
        planned = server.planned_unit_service().list()
        self.assertEqual(first["imported"], 1)
        self.assertEqual(len(planned), 1)
        self.assertEqual(second["imported"], 0)
        self.assertEqual(planned[0]["remote_event_id"], "remote-event-1")
        server.planned_unit_service().update(planned[0]["id"], {"action": "update", "name": "Lokal geändert"})
        conflict = server.remote_planned_unit_reconciler().reconcile(
            [{**event, "name": "Remote geändert"}]
        )
        self.assertEqual(conflict["conflicts"], 1)
        self.assertEqual(server.planned_unit_service().list()[0]["sync_status"], "conflict")

    def test_remote_pull_preserves_local_only_planned_changes(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        event = {
            "id": "remote-local-only", "external_id": "intervals-event-local-only", "category": "WORKOUT",
            "start_date_local": tomorrow + "T07:00:00", "type": "Ride", "name": "Remote Original",
            "description": "- 30m Z2", "moving_time": 1800,
        }
        server.remote_planned_unit_reconciler().reconcile([event])
        local = server.planned_unit_service().list()[0]
        server.planned_unit_service().update(local["id"], {"action": "update", "name": "Lokal geändert"})
        result = server.remote_planned_unit_reconciler().reconcile([event])
        current = server.planned_unit_service().list()[0]
        self.assertEqual(result["conflicts"], 0)
        self.assertEqual(current["name"], "Lokal geändert")
        self.assertEqual(current["sync_status"], "local")

    def test_remote_planned_import_and_payload_preserve_sport(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        server.remote_planned_unit_reconciler().reconcile([{
            "id": "remote-run", "category": "WORKOUT", "start_date_local": tomorrow + "T08:00:00",
            "type": "Run", "name": "Remote Lauf", "moving_time": 1800,
        }])
        imported = server.planned_unit_service().list()[0]
        self.assertEqual(imported["type"], "Run")
        self.assertEqual(imported["sport"], "Run")
        payload = planning_workouts.workout_event_payload("local-run", {
            "date": tomorrow, "type": "Run", "name": "Lauf", "description": "- 30m 60% Easy", "duration_minutes": 30,
        }, today=server.ATHLETE_CLOCK.now().date())
        self.assertEqual(payload["type"], "Run")

    def test_planned_conflict_can_keep_local_or_adopt_remote(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        event = {
            "id": "remote-conflict", "external_id": "intervals-event-conflict", "category": "WORKOUT",
            "start_date_local": tomorrow + "T07:00:00", "type": "Ride", "name": "Original",
            "description": "- 30m Z2", "moving_time": 1800,
        }
        server.remote_planned_unit_reconciler().reconcile([event])
        local = server.planned_unit_service().list()[0]
        server.planned_unit_service().update(local["id"], {"action": "update", "name": "Lokal"})
        server.remote_planned_unit_reconciler().reconcile(
            [{**event, "name": "Remote"}]
        )
        kept = server.planned_unit_service().resolve_conflict(local["id"], "keep_local")
        self.assertEqual(kept["planned_unit"]["name"], "Lokal")
        server.remote_planned_unit_reconciler().reconcile(
            [{**event, "name": "Remote"}]
        )
        adopted = server.planned_unit_service().resolve_conflict(
            local["id"], "adopt_remote"
        )
        self.assertEqual(adopted["planned_unit"]["name"], "Remote")

    def test_local_planned_workout_can_be_edited_moved_and_removed(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        day_after = (date.today() + timedelta(days=2)).isoformat()
        local = server.planned_unit_service().create({
            "date": tomorrow, "sport": "Ride", "name": "Locker",
            "description": "- 30m Z2", "duration_minutes": 30,
            "source": "library", "rationale": "Test",
        })
        updated = server.planned_unit_service().update(local["id"], {
            "action": "update", "date": day_after, "name": "Verschoben",
            "description": "- 40m Z2", "duration_minutes": 40,
        })
        self.assertEqual(updated["library_entry"]["name"], "Verschoben")
        self.assertEqual(updated["library_entry"]["date"], day_after)
        self.assertEqual(updated["library_entry"]["sync_status"], "local")
        archived = server.planned_unit_service().update(local["id"], {"action": "archive"})
        self.assertTrue(archived["library_entry"]["archived"])
        restored = server.planned_unit_service().update(local["id"], {"action": "restore"})
        self.assertFalse(restored["library_entry"]["archived"])
        removed = server.planned_unit_service().update(local["id"], {"action": "delete"})
        self.assertEqual(removed["status"], "deleted")
        self.assertEqual(server.planned_unit_service().list(), [])

    def test_deleting_archived_planned_workout_records_recoverable_history(self):
        local = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Ride", "name": "Archived", "description": "- 30m Z2",
            "duration_minutes": 30, "source": "library", "rationale": "Test",
        })
        server.planned_unit_service().update(local["id"], {"action": "archive"})

        server.planned_unit_service().update(local["id"], {"action": "delete"})

        deletion = next(
            item for item in server.change_history_service().list()
            if item["entity_type"] == "planned_unit"
            and item["entity_id"] == local["id"]
            and item["action"] == "delete"
        )
        self.assertNotEqual(deletion["before_hash"], deletion["after_hash"])
        self.assertEqual(deletion["diff"]["fields"]["local_deleted"], {"changed": True})
        server.history_undo_service().apply({
            "change_id": deletion["id"],
            "expected_current_hash": deletion["after_hash"],
        })
        restored = next(
            item for item in server.planned_unit_service().list(include_archived=True)
            if item["id"] == local["id"]
        )
        self.assertFalse(restored["archived"])
        self.assertFalse(restored["local_deleted"])

    def test_competition_sport_mapping_supports_indoor_and_outdoor_cycling(self):
        self.assertEqual(planning_competitions.intervals_competition_sport("Radfahren"), "Ride")
        self.assertEqual(planning_competitions.intervals_competition_sport("Rad indoor"), "VirtualRide")
        self.assertEqual(planning_competitions.intervals_competition_sport("Lauf"), "Run")
        self.assertEqual(planning_competitions.intervals_competition_sport("Kraft"), "WeightTraining")
        self.assertEqual(planning_competitions.intervals_competition_sport("Krafttraining"), "WeightTraining")

    def test_competition_normalization_helpers_validate_category_and_fallback_id(self):
        category, priority = planning_competitions.competition_category_and_priority({"priority": "a"}, "Race")
        self.assertEqual((category, priority), ("RACE_A", "A"))
        normalized_id = planning_competitions.competition_normalized_id("not-a-uuid")
        self.assertEqual(str(uuid.UUID(normalized_id)), normalized_id)
        with self.assertRaises(server.AppError) as error:
            planning_competitions.competition_category_and_priority({"priority": "Z"}, "Race")
        self.assertEqual(error.exception.status, 400)

    def test_competition_event_optional_payload_excludes_invalid_distance(self):
        payload = planning_competitions.competition_event_optional_payload({
            "moving_time": "3600",
            "distance": "not-a-distance",
            "target": "Finish",
            "intervals_event_id": "external-race-id",
        })
        self.assertEqual(payload["moving_time"], 3600)
        self.assertNotIn("distance", payload)
        self.assertEqual(payload["target"], "Finish")
        self.assertEqual(payload["id"], "external-race-id")

    def test_remote_competition_helpers_normalize_invalid_duration_and_fractional_distance(self):
        self.assertIsNone(planning_competitions.remote_competition_moving_time("not-a-duration"))
        self.assertEqual(planning_competitions.remote_competition_distance(42195.5), "42195.5")
        self.assertEqual(planning_competitions.remote_competition_distance("42.195 km"), "42195")

    def test_past_workout_is_rejected(self):
        old = (date.today() - timedelta(days=4)).isoformat()
        with self.assertRaises(server.AppError):
            planning_workouts.workout_event_payload(
                "abc",
                {"date": old, "duration_minutes": 60},
                today=server.ATHLETE_CLOCK.now().date(),
            )

    def test_library_is_cached_and_included_in_coach_context(self):
        imported = server.workout_library_remote_reconciler().reconcile([{
            "id": 42, "name": "Locker Rad", "type": "Ride",
            "description": "- 45m Z2", "moving_time": 2700,
        }])[0]
        self.assertEqual(uuid.UUID(imported["id"]).version, 4)
        self.assertEqual(imported["external_id"], "42")
        updated = server.workout_library_remote_reconciler().reconcile([{
            "id": 42, "name": "Locker Rad aktualisiert", "type": "Ride",
            "description": "- 45m Z2", "moving_time": 2700,
        }])[0]
        self.assertEqual(updated["id"], imported["id"])
        self.assertEqual(server.workout_library_service().list()[0]["name"], "Locker Rad aktualisiert")
        self.assertIn("LOCAL TRAINING LIBRARY", server.coach_training_context_service().build())

    def test_library_update_always_sends_required_folder(self):
        client = server.intervals_client(replace(server.CONFIG, intervals_api_key="test-key", intervals_athlete_id="athlete-1"))
        with patch.object(client, "get_or_create_workout_folder", return_value=12345) as folder, patch.object(
            client, "put", return_value={"id": "remote-1"}
        ) as put:
            client.update_library_workout("remote-1", {
                "name": "Easy",
                "description": "- 30m Z2",
                "type": "Ride",
            })
        folder.assert_called_once_with()
        self.assertEqual(put.call_args.args[1], {
            "name": "Easy",
            "description": "- 30m Z2",
            "type": "Ride",
            "folder_id": 12345,
            "target": "AUTO",
        })

    def test_unknown_workout_sport_falls_back_to_provider_other_type(self):
        client = server.intervals_client(replace(server.CONFIG, intervals_api_key="test-key", intervals_athlete_id="athlete-1"))
        with patch.object(client, "get", return_value=[]), patch.object(
            client, "post", side_effect=[{"id": 12345}, {"id": "remote-1"}]
        ) as post:
            client.create_library_workouts([{
                "name": "Regeneration",
                "description": "- 30m Z1 HR Locker bewegen",
                "sport": "Recovery Session",
            }])
        self.assertEqual(post.call_args_list[1].args[1]["type"], "Other")

    def test_workout_sport_aliases_are_normalized_before_storage(self):
        normalized = planning_workouts.normalize_workout({
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Running",
            "name": "Easy run",
            "description": "- 30m Z2",
            "duration_minutes": 30,
        }, today=server.ATHLETE_CLOCK.now().date())
        self.assertEqual(normalized["sport"], "Run")

    def test_recovery_extension_bullet_is_rejected_before_plan_storage(self):
        workout = {
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Run", "name": "Optionaler Recovery Run - 6 bis 8 km",
            "description": (
                "Warm-up\n- 8m Gehen und sehr lockeres Einlaufen\n\nMain Set\n"
                "- 6km sehr locker in Zone 1-2, RPE 1-2/10\n"
                "- Nur bei wirklich lockerem Schritt und ohne Beschwerden auf maximal 8km verlaengern\n"
                "- Keine Steigerungen und kein Tempodruck\n\nCooldown\n- 5m Gehen"
            ),
            "duration_minutes": 50,
        }
        with self.assertRaises(server.AppError) as raised:
            server.local_plan_creation_service().save([workout])
        self.assertIn("Zeile 6", str(raised.exception))
        self.assertEqual(server.planned_unit_service().list(), [])

    def test_ambiguous_quantity_bullets_require_explicit_steps_or_plain_notes(self):
        for description in (
            "- If feeling fresh extend to 8 km",
            "- Bei Bedarf insgesamt 8,5km laufen",
            "- Optional another 10min",
            "- Walk for 5' if needed",
            "- 6-8km Z1 HR",
            "- 6km Z1 HR; if fresh extend to 8km",
            "- 6km-8km Z1 HR",
            "- Recovery 30s 50%",  # Rewrite valid provider cue-first syntax too.
        ):
            with self.subTest(description=description), self.assertRaises(server.AppError):
                planning_workouts.validate_workout_description({"type": "Run", "description": description})

    def test_quantity_first_steps_and_plain_optional_totals_are_preserved(self):
        descriptions = (
            "Optional bis insgesamt 8km verlaengern.\n\n- 6km Z1 HR\n\nBei Beschwerden auslassen.",
            "Warmup\n- 1km Z1 HR\n\nMain Set\n- 4km Z1-Z2 HR\n\nCooldown\n- 1km Z1 HR",
            "Warmup\n- 10m Z2\n\nMain Set 6x\n- 4m 100%\n- 30s 50%\n\n- 5m Z1",
            "- 1h30m Z2\n- 5' Z1\n- 30\" Z1",
            "- 500mtr Z2 Pace\n- 1mi Z2 Pace",
        )
        for description, minutes in zip(descriptions, (40, 40, 42, 96, 40)):
            with self.subTest(description=description):
                workout = planning_workouts.normalize_workout({
                    "date": (date.today() + timedelta(days=1)).isoformat(),
                    "sport": "Run", "description": description, "duration_minutes": minutes,
                }, today=server.ATHLETE_CLOCK.now().date())
                self.assertEqual(workout["description"], description)
        planning_workouts.validate_workout_description({
            "sport": "WeightTraining", "description": "- Squats 3x8, pause 60s",
        })

    def test_ambiguous_description_blocks_all_workout_export_paths_before_writes(self):
        client = server.intervals_client()
        workout = {
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "type": "Run", "description": "- 6km Z1 HR\n- Optional bis insgesamt 8km",
            "duration_minutes": 40,
        }
        with patch.object(client, "get_or_create_workout_folder") as folder, \
                patch.object(client, "post") as post, patch.object(client, "put") as put:
            for operation in (
                lambda: client.create_library_workouts([
                    {"type": "Run", "description": "- 6km Z1 HR"}, workout,
                ]),
                lambda: client.update_library_workout("synthetic", workout),
                lambda: client.plan_library_workout("synthetic", workout, workout["date"]),
                lambda: planning_workouts.workout_event_payload(
                    "synthetic", workout, today=server.ATHLETE_CLOCK.now().date()
                ),
            ):
                with self.assertRaises(server.AppError):
                    operation()
            folder.assert_not_called()
            post.assert_not_called()
            put.assert_not_called()

    def test_local_template_and_planned_edit_reject_ambiguous_extension(self):
        with self.assertRaises(server.AppError):
            server.workout_library_service().create_template({
                "sport": "Run", "description": "- If fresh extend to 8km", "duration_minutes": 40,
            })
        entry = server.local_plan_creation_service().save([{
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Run", "name": "Recovery", "description": "- 6km Z1 HR", "duration_minutes": 40,
        }])[0]
        with self.assertRaises(server.AppError):
            server.planned_unit_service().update(entry["id"], {"description": "- If fresh extend to 8km"})
        self.assertEqual(server.planned_unit_service().list()[0]["description"], "- 6km Z1 HR")

    def test_unparsed_library_export_keeps_identity_and_retries_as_update(self):
        entry = server.workout_library_service().create_local_entry({
            "sport": "Ride", "name": "Synthetic", "description": "- 30m 85%", "duration_minutes": 30,
        })
        with patch.object(intervals_client_module.IntervalsClient, "get_workout_library", return_value=[]), \
                patch.object(intervals_client_module.IntervalsClient, "create_library_workouts", return_value=[{"id": "synthetic-remote", "type": "Ride"}]) as create, \
                patch.object(intervals_client_module.IntervalsClient, "update_library_workout", return_value={"id": "synthetic-remote", **parsed_workout_fixture()}) as update:
            with self.assertRaises(server.AppError) as raised:
                server.workout_library_sync_service().sync_entry(entry["id"])
            self.assertEqual(raised.exception.reason, "intervals_workout_verification_failed")
            failed = server.workout_library_service().list()[0]
            self.assertEqual(failed["sync_status"], "sync_error")
            self.assertEqual(failed["external_id"], "synthetic-remote")
            self.assertEqual(failed["description"], "- 30m 85%")
            synced = server.workout_library_sync_service().sync_entry(entry["id"])
            self.assertEqual(synced["sync_status"], "synced")
            create.assert_called_once()
            self.assertEqual(update.call_args.args[0], "synthetic-remote")

    def test_invalid_workout_totals_cannot_be_saved_or_partially_applied(self):
        day = (date.today() + timedelta(days=1)).isoformat()
        valid = {"date": day, "sport": "Ride", "name": "Synthetic", "description": "- 30m 85%", "duration_minutes": 30}
        with self.assertRaises(server.AppError):
            server.local_plan_creation_service().save([valid, {**valid, "date": (date.today() + timedelta(days=2)).isoformat(), "duration_minutes": 65}])
        self.assertEqual(server.planned_unit_service().list(), [])
        entry = server.local_plan_creation_service().save([valid])[0]
        with self.assertRaises(server.AppError):
            server.planned_unit_service().update(entry["id"], {"duration_minutes": 65})
        self.assertEqual(server.planned_unit_service().list()[0]["duration_minutes"], 30)

    def test_missing_library_workout_stays_local_until_approval(self):
        with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")):
            entry = server.local_plan_creation_service().save([{
                "date": (date.today() + timedelta(days=1)).isoformat(), "sport": "Ride",
                "name": "Coach Tempo", "description": "- 30m 85%", "duration_minutes": 30,
                "target": "POWER", "rationale": "Schwelle",
            }])[0]
        self.assertEqual(uuid.UUID(entry["id"]).version, 4)
        planned = server.planned_unit_service().list()[0]
        self.assertEqual(planned["id"], entry["id"])
        self.assertIsNone(planned["external_id"])
        self.assertEqual(planned["sync_status"], "local")

    def test_saved_library_plan_can_be_applied_locally_as_a_batch(self):
        server.workout_library_remote_reconciler().reconcile([{
            "id": 42, "name": "Locker Rad", "type": "Ride",
            "description": "- 45m Z2", "moving_time": 2700,
        }])
        library = server.workout_library_service().list()[0]
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        result = server.workout_library_plan_service().apply([{
            "library_workout_id": library["id"], "date": tomorrow,
        }])
        self.assertEqual(result["status"], "local")
        self.assertEqual(result["local_planned"], 1)
        self.assertEqual(result["planned"][0]["library_entry"]["date"], tomorrow)
        self.assertEqual(len(server.workout_library_service().list()), 1)
        self.assertEqual(len(server.planned_unit_service().list()), 1)

    def test_library_plan_rejects_duplicate_source_on_same_date(self):
        server.workout_library_remote_reconciler().reconcile([{
            "id": 46, "name": "Locker Rad", "type": "Ride",
            "description": "- 30m Z2", "moving_time": 1800,
        }])
        library = server.workout_library_service().list()[0]
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        with self.assertRaises(server.AppError) as raised:
            server.workout_library_plan_service().apply([
                {"library_workout_id": library["id"], "date": tomorrow},
                {"library_workout_id": library["id"], "date": tomorrow},
            ])
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(len(server.workout_library_service().list()), 1)

    def test_library_plan_is_local_only(self):
        server.workout_library_remote_reconciler().reconcile([{
            "id": 44, "name": "Intervall", "type": "Ride",
            "description": "4x\n- 5m 105%\n- 5m 55%", "moving_time": 2400,
        }])
        library = server.workout_library_service().list()[0]
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        result = server.workout_library_plan_service().apply([{
            "library_workout_id": library["id"], "date": tomorrow,
        }])
        self.assertEqual(result["status"], "local")

    def test_outstanding_plan_drafts_remain_visible_across_provider_conversations(self):
        draft = server.training_plan_artifact_service().stage(
            {"payload": {"plan_name": "Basis", "goal": "Ausdauer", "workouts": [{
                "date": "2099-01-01", "sport": "Ride", "name": "Basis",
                "description": "- 30m 60% easy", "duration_minutes": 30,
            }]}},
            "gemini-conversation",
            "gemini-draft",
        )

        with server.database_manager().unit_of_work() as db:
            server.CHAT_REPOSITORY.add(db, "user", "Synthetic draft request", client_turn_id="gemini-draft")
        refs = server.coach_dialogue_read_service().artifact_refs()

        self.assertIn(draft["artifact_id"], [item["id"] for item in refs])

    def test_structured_training_changes_accept_complete_bounded_plan_without_remote_write(self):
        for count in (29, coach_limits.COACH_TRAINING_CHANGE_LIMIT):
            with self.subTest(count=count):
                self.setUp()
                planned = [server.planned_unit_service().create({
                    "date": (date(2098, 1, 1) + timedelta(days=index)).isoformat(),
                    "sport": "Ride", "name": f"Original {index}",
                    "description": "- 30m 60%", "duration_minutes": 30, "target": "AUTO",
                }) for index in range(count)]
                result = server.structured_training_change_service().apply({
                    "changes": [
                        {"local_id": item["id"], "action": "update", "name": f"Changed {index}"}
                        for index, item in enumerate(planned)
                    ],
                })
                self.assertEqual(len(result["changes"]), count)
                self.assertEqual(
                    [item["name"] for item in server.planned_unit_service().list(1000, include_archived=True)],
                    [f"Changed {index}" for index in range(count)],
                )
                with server.DB_LOCK, server.database_manager().unit_of_work() as db:
                    self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM sync_jobs").fetchone()["count"], 0)

    def test_structured_training_changes_move_and_create_in_one_atomic_batch(self):
        wednesday = (date.today() + timedelta(days=20)).isoformat()
        tuesday = (date.today() + timedelta(days=19)).isoformat()
        upper_body = server.planned_unit_service().create({
            "date": wednesday, "sport": "WeightTraining", "name": "Oberkörper Einheit",
            "description": "Krafttraining", "duration_minutes": 45, "target": "AUTO",
        })
        with patch.object(runtime_events.STATE_EVENT_BUFFER, "publish") as publish:
            result = server.structured_training_change_service().apply({
                "changes": [
                    {"local_id": upper_body["id"], "action": "update", "date": tuesday},
                    {"action": "create", "date": wednesday, "sport": "Run", "name": "Lockerer Lauf",
                     "description": "- 30m 60% locker", "duration_minutes": 30, "target": "AUTO", "rationale": "Test"},
                ],
            })
        self.assertTrue(any(
            call.args == ("planning", {"status": "changed"})
            for call in publish.call_args_list
        ))
        self.assertEqual(result["status"], "applied")
        planned = {item["name"]: item for item in server.planned_unit_service().list()}
        self.assertEqual(planned["Oberkörper Einheit"]["date"], tuesday)
        self.assertEqual(planned["Lockerer Lauf"]["date"], wednesday)
        self.assertEqual(len(result["changes"]), 2)

    def test_structured_training_create_strips_protected_identity_fields(self):
        workout_date = (date.today() + timedelta(days=21)).isoformat()
        result = server.structured_training_change_service().apply({
            "changes": [{
                "action": "create", "date": workout_date, "sport": "Run", "name": "Clean Run",
                "description": "- 30m 60% easy", "duration_minutes": 30, "target": "AUTO",
                "rationale": "Test", "id": "foreign-id", "local_id": None,
                "external_id": "foreign-external-id", "remote_event_id": "foreign-remote-id",
                "remote_event_external_id": "foreign-remote-external-id", "archived": True,
                "local_deleted": True, "sync_state": "synced",
            }],
        })
        created = next(item for item in server.planned_unit_service().list() if item["name"] == "Clean Run")
        self.assertEqual(result["status"], "applied")
        self.assertNotEqual(created["id"], "foreign-id")
        self.assertIsNone(created.get("external_id"))
        self.assertNotIn("remote_event_id", created)
        self.assertNotIn("remote_event_external_id", created)
        self.assertFalse(created.get("archived", False))
        self.assertFalse(created.get("local_deleted", False))
        self.assertEqual(created["sync_status"], "local")

    def test_structured_training_create_requires_all_workout_fields(self):
        with self.assertRaises(server.AppError) as raised:
            server.structured_training_change_service().apply({
                "changes": [{
                    "action": "create", "date": (date.today() + timedelta(days=22)).isoformat(),
                    "sport": "Run", "name": "Missing rationale", "description": "- 30m 60% easy",
                    "duration_minutes": 30, "target": "AUTO",
                }],
            })
        self.assertEqual(raised.exception.reason, "invalid_change")

    def test_structured_training_allows_repeated_updates_for_same_unit(self):
        workout = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=23)).isoformat(), "sport": "Run",
            "name": "Repeated update", "description": "- 30m 60% easy", "duration_minutes": 30,
            "target": "AUTO",
        })
        result = server.structured_training_change_service().apply({
            "changes": [
                {"local_id": workout["id"], "action": "update", "name": "First update"},
                {"local_id": workout["id"], "action": "update", "name": "Second update"},
            ],
        })
        self.assertEqual(result["status"], "applied")
        self.assertEqual(server.planned_unit_service().list()[0]["name"], "Second update")

    def test_structured_training_folds_repeated_updates_before_create_date_check(self):
        original_date = date.today() + timedelta(days=24)
        moved_date = original_date + timedelta(days=1)
        workout = server.planned_unit_service().create({
            "date": original_date.isoformat(), "sport": "Run", "name": "Move then create",
            "description": "- 30m 60% easy", "duration_minutes": 30, "target": "AUTO",
        })
        result = server.structured_training_change_service().apply({
            "changes": [
                {"local_id": workout["id"], "action": "update", "name": "Renamed"},
                {"local_id": workout["id"], "action": "update", "date": moved_date.isoformat()},
                {"action": "create", "date": original_date.isoformat(), "sport": "Run", "name": "New Wednesday",
                 "description": "- 20m 60% easy", "duration_minutes": 20, "target": "AUTO", "rationale": "Test"},
            ],
        })
        self.assertEqual(result["status"], "applied")
        current = {item["id"]: item for item in server.planned_unit_service().list()}
        self.assertEqual(current[workout["id"]]["date"], moved_date.isoformat())

    def test_structured_training_folds_inactive_repeated_changes_before_create_date_check(self):
        original_date = date.today() + timedelta(days=26)
        workout = server.planned_unit_service().create({
            "date": original_date.isoformat(), "sport": "Run", "name": "Archive then update",
            "description": "- 30m 60% easy", "duration_minutes": 30, "target": "AUTO",
        })
        result = server.structured_training_change_service().apply({
            "changes": [
                {"local_id": workout["id"], "action": "archive"},
                {"local_id": workout["id"], "action": "update", "name": "Still archived"},
                {"action": "create", "date": original_date.isoformat(), "sport": "Run", "name": "Replacement",
                 "description": "- 20m 60% easy", "duration_minutes": 20, "target": "AUTO", "rationale": "Test"},
            ],
        })
        self.assertEqual(result["status"], "applied")
        current = {item["id"]: item for item in server.planned_unit_service().list(include_archived=True)}
        self.assertTrue(current[workout["id"]]["archived"])
        self.assertEqual(sum(item["date"] == original_date.isoformat() and not item.get("archived") for item in current.values()), 1)

    def test_structured_training_restore_rechecks_original_calendar_date(self):
        workout = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=25)).isoformat(), "sport": "Run",
            "name": "Restore conflict", "description": "- 30m 60% easy", "duration_minutes": 30,
            "target": "AUTO",
        })
        server.planned_unit_service().update(workout["id"], {"action": "archive"})
        with patch.object(
            server.CalendarConflictService,
            "conflicts",
            return_value=[{"name": "Occupied"}],
        ) as conflicts:
            with self.assertRaises(server.AppError) as raised:
                server.structured_training_change_service().apply({
                    "changes": [{"local_id": workout["id"], "action": "restore"}],
                })
        self.assertEqual(raised.exception.reason, "plan_date_conflict")
        conflicts.assert_called_once()

    def test_structured_training_create_inherits_unambiguous_plan_membership(self):
        plan_id = "mixed-create-plan"
        plan_name = "Mixed Create Plan"
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            server.TRAINING_PLAN_REPOSITORY.create(
                db, plan_id, plan_name, "Build", "2099-01-01", "2099-01-31", "planned", server.utc_now(),
            )
        existing = server.planned_unit_service().create({
            "date": "2099-01-01", "sport": "Run", "name": "Existing plan unit",
            "description": "- 30m 60% easy", "duration_minutes": 30, "target": "AUTO",
            "plan_id": plan_id, "plan_name": plan_name,
        })
        result = server.structured_training_change_service().apply({
            "changes": [
                {"local_id": existing["id"], "action": "update", "name": "Updated"},
                {"action": "create", "date": "2099-01-02", "sport": "Run", "name": "Added plan unit",
                 "description": "- 20m 60% easy", "duration_minutes": 20, "target": "AUTO", "rationale": "Test"},
            ],
        })
        created_id = next(item["local_id"] for item in result["changes"] if item["local_id"] != existing["id"])
        created = next(item for item in server.planned_unit_service().list() if item["id"] == created_id)
        self.assertEqual(created["plan_id"], plan_id)
        self.assertEqual(created["plan_name"], plan_name)

    def test_structured_training_create_can_explicitly_stay_standalone(self):
        plan_id = "explicit-standalone-plan"
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            server.TRAINING_PLAN_REPOSITORY.create(
                db, plan_id, "Explicit standalone", "Build", "2099-03-01", "2099-03-31", "planned", server.utc_now(),
            )
        existing = server.planned_unit_service().create({
            "date": "2099-03-01", "sport": "Run", "name": "Plan reference",
            "description": "- 30m 60% easy", "duration_minutes": 30, "target": "AUTO",
            "plan_id": plan_id, "plan_name": "Explicit standalone",
        })
        result = server.structured_training_change_service().apply({
            "changes": [
                {"local_id": existing["id"], "action": "update", "name": "Updated"},
                {"action": "create", "date": "2099-03-02", "sport": "Run", "name": "Standalone walk",
                 "description": "- 20m 60% easy", "duration_minutes": 20, "target": "AUTO", "rationale": "Test",
                 "plan_id": ""},
            ],
        })
        created_id = next(item["local_id"] for item in result["changes"] if item["local_id"] != existing["id"])
        created = next(item for item in server.planned_unit_service().list() if item["id"] == created_id)
        self.assertNotIn("plan_id", created)

    def test_named_plan_scope_assigns_create_without_unit_reference(self):
        plan_id = "named-create-plan"
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            server.TRAINING_PLAN_REPOSITORY.create(
                db, plan_id, "Named create", "Build", "2099-04-01", "2099-04-30", "planned", server.utc_now(),
            )
        intent = {
            "intent": "local_action", "operation": "apply_training_changes", "target_system": "local",
            "artifact_id": None, "ambiguities": [],
            "authorization_scope": ["local_plan_create", f"training_plan:{plan_id}"],
        }
        result = server.coach_tool_dispatch_service().execute(
            "apply_training_changes",
            {"changes": [{"action": "create", "date": "2099-04-02", "sport": "Run",
                          "name": "Plan addition", "description": "- 20m 60% easy", "duration_minutes": 20,
                          "target": "AUTO", "rationale": "Test"}]},
            intent=intent, conversation_id="conversation-plan-create", client_turn_id="turn-plan-create",
            session_csrf_hash="", sync_job_ids=[],
        )
        created = next(item for item in server.planned_unit_service().list() if item["id"] == result["library_entry_ids"][0])
        self.assertEqual(created["plan_id"], plan_id)

    def test_standalone_create_does_not_recompute_referenced_plan_bounds(self):
        plan_id = "standalone-bounds-plan"
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            server.TRAINING_PLAN_REPOSITORY.create(
                db, plan_id, "Standalone bounds", "Build", "2099-05-01", "2099-05-31", "planned", server.utc_now(),
            )
        existing = server.planned_unit_service().create({
            "date": "2099-05-10", "sport": "Run", "name": "Plan unit", "description": "- 30m 60% easy",
            "duration_minutes": 30, "target": "AUTO", "plan_id": plan_id, "plan_name": "Standalone bounds",
        })
        server.structured_training_change_service().apply({"changes": [
            {"local_id": existing["id"], "action": "update", "name": "Renamed plan unit"},
            {"action": "create", "date": "2099-06-10", "sport": "Run", "name": "Standalone",
             "description": "- 20m 60% easy", "duration_minutes": 20, "target": "AUTO", "rationale": "Test",
             "plan_id": ""},
        ]})
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            plan = server.TRAINING_PLAN_REPOSITORY.get(db, plan_id)
        self.assertEqual((plan["start_date"], plan["end_date"]), ("2099-05-01", "2099-05-31"))

    def test_mixed_batch_recomputes_each_affected_plan_bounds(self):
        plan_ids = ["mixed-bounds-a", "mixed-bounds-b"]
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            for index, plan_id in enumerate(plan_ids):
                server.TRAINING_PLAN_REPOSITORY.create(
                    db, plan_id, f"Mixed {index}", "Build", "2099-06-01", "2099-06-30", "planned", server.utc_now(),
                )
        units = [
            server.planned_unit_service().create({
                "date": f"2099-06-{10 + index:02d}", "sport": "Run", "name": f"Plan {index}",
                "description": "- 30m 60% easy", "duration_minutes": 30, "target": "AUTO",
                "plan_id": plan_id, "plan_name": f"Mixed {index}",
            })
            for index, plan_id in enumerate(plan_ids)
        ]
        server.structured_training_change_service().apply({"changes": [
            {"local_id": units[0]["id"], "action": "update", "date": "2099-06-15"},
            {"local_id": units[1]["id"], "action": "update", "date": "2099-06-16"},
        ]})
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            plans = [server.TRAINING_PLAN_REPOSITORY.get(db, plan_id) for plan_id in plan_ids]
        self.assertEqual([(plan["start_date"], plan["end_date"]) for plan in plans], [
            ("2099-06-15", "2099-06-15"), ("2099-06-16", "2099-06-16"),
        ])

    def test_structured_training_plan_membership_includes_archived_and_standalone_references(self):
        plan_id = "membership-boundary-plan"
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            server.TRAINING_PLAN_REPOSITORY.create(
                db, plan_id, "Membership Boundary", "Build", "2099-02-01", "2099-02-28", "planned", server.utc_now(),
            )
        planned = server.planned_unit_service().create({
            "date": "2099-02-01", "sport": "Run", "name": "Planned reference",
            "description": "- 30m 60% easy", "duration_minutes": 30, "target": "AUTO",
            "plan_id": plan_id, "plan_name": "Membership Boundary",
        })
        replacement = server.structured_training_change_service().apply({
            "changes": [
                {"local_id": planned["id"], "action": "archive"},
                {"action": "create", "date": "2099-02-02", "sport": "Run", "name": "Plan replacement",
                 "description": "- 20m 60% easy", "duration_minutes": 20, "target": "AUTO", "rationale": "Test"},
            ],
        })
        replacement_id = next(item["local_id"] for item in replacement["changes"] if item["local_id"] != planned["id"])
        replacement_unit = next(item for item in server.planned_unit_service().list(include_archived=True) if item["id"] == replacement_id)
        self.assertEqual(replacement_unit["plan_id"], plan_id)

        standalone = server.planned_unit_service().create({
            "date": "2099-02-03", "sport": "Run", "name": "Standalone reference",
            "description": "- 30m 60% easy", "duration_minutes": 30, "target": "AUTO",
        })
        mixed = server.structured_training_change_service().apply({
            "changes": [
                {"local_id": replacement_id, "action": "update", "name": "Plan update"},
                {"local_id": standalone["id"], "action": "update", "name": "Standalone update"},
                {"action": "create", "date": "2099-02-04", "sport": "Run", "name": "Ambiguous membership",
                 "description": "- 20m 60% easy", "duration_minutes": 20, "target": "AUTO", "rationale": "Test"},
            ],
        })
        mixed_id = next(item["local_id"] for item in mixed["changes"] if item["local_id"] not in {replacement_id, standalone["id"]})
        mixed_unit = next(item for item in server.planned_unit_service().list() if item["id"] == mixed_id)
        self.assertNotIn("plan_id", mixed_unit)

    def test_structured_training_change_batch_rolls_back_after_old_boundary(self):
        planned = [server.planned_unit_service().create({
            "date": (date(2099, 1, 1) + timedelta(days=index)).isoformat(),
            "sport": "Ride", "name": f"Original {index}",
            "description": "- 30m 60%", "duration_minutes": 30, "target": "AUTO",
        }) for index in range(28)]
        with self.assertRaises(server.AppError) as raised:
            server.structured_training_change_service().apply({
                "changes": [
                    *[
                        {"local_id": item["id"], "action": "update", "name": f"Changed {index}"}
                        for index, item in enumerate(planned)
                    ],
                    {"local_id": str(uuid.uuid4()), "action": "update", "date": "2099-01-02", "name": "Missing"},
                ],
            })
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(
            [item["name"] for item in server.planned_unit_service().list(100, include_archived=True)],
            [f"Original {index}" for index in range(28)],
        )

    def test_structured_training_changes_reject_more_than_complete_plan_limit(self):
        with self.assertRaises(server.AppError) as raised:
            server.structured_training_change_service().apply({
                "changes": [{"local_id": str(uuid.uuid4()), "action": "delete"}]
                * (coach_limits.COACH_TRAINING_CHANGE_LIMIT + 1),
            })
        self.assertEqual(raised.exception.reason, "change_limit")

    def test_build_training_context_serializes_local_plans_once_and_reports_projection_budget(self):
        today = server.ATHLETE_CLOCK.now().date()
        server.planned_unit_service().create({
            "date": (today + timedelta(days=1)).isoformat(),
            "sport": "Ride",
            "name": "Local plan fixture",
            "description": "- 60m 60%\n\nlong description " + "x" * 20_000,
            "duration_minutes": 60,
            "target": "easy",
            "source": "coach",
        })
        context = server.coach_training_context_service().build()
        self.assertEqual(context.count("LOCAL PLANNED WORKOUTS"), 1)
        self.assertEqual(context.count('"local_planned_workouts"'), 1)
        self.assertLessEqual(len(context), coach_context.COACH_CONTEXT_TOTAL_CHAR_LIMIT)
        structured = server.coach_structured_context_service().build()
        self.assertIn("local_planned_workouts", structured)
        self.assertIn('"projection"', context)
        self.assertNotIn("long description", context)

    def test_build_training_context_applies_total_budget_deterministically(self):
        with patch.object(server.CoachStructuredContextService, "build", return_value={"source_policy": {"untrusted": "x" * 200_000}}):
            first = server.coach_training_context_service().build()
            second = server.coach_training_context_service().build()
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), coach_context.COACH_CONTEXT_TOTAL_CHAR_LIMIT)

    def test_complete_plan_replace_ignores_archived_units_in_date_conflicts(self):
        archived = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=2)).isoformat(),
            "sport": "Ride", "name": "Archived", "description": "- 30m 60% easy",
        })
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            row = db.execute("SELECT payload FROM planned_units WHERE local_id=?", (archived["id"],)).fetchone()
            payload = json.loads(row["payload"])
            payload.update({"archived": True, "local_deleted": True})
            db.execute("UPDATE planned_units SET payload=? WHERE local_id=?", (json.dumps(payload), archived["id"]))
        state = server.structured_training_state_service().read()
        intent = {
            "intent": "local_action", "operation": "replace_training_plan", "target_system": "local",
            "artifact_id": None, "ambiguities": [], "authorization_scope": ["local_plan"],
            "follow_up_operations": [],
        }
        result = server.coach_tool_dispatch_service().execute(
            "replace_training_plan",
            {"expected_revision": state["planning_revision"], "payload": {"plan_name": "Replacement", "goal": "", "workouts": [
                {"date": archived["date"], "sport": "Ride", "name": "New", "description": "- 40m 60% easy", "duration_minutes": 40, "target": "AUTO", "rationale": "Test"},
            ]}},
            intent=intent, conversation_id="conversation-archived", client_turn_id="turn-archived",
            session_csrf_hash="", sync_job_ids=[],
        )
        self.assertEqual(result["status"], "replaced")

    def test_training_plan_metadata_changes_advance_planning_revision(self):
        plan_entry = server.local_plan_creation_service().save([{
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Ride", "name": "Metadata", "description": "- 30m 60% easy", "duration_minutes": 30, "target": "AUTO", "rationale": "Test",
        }], plan_name="Metadata Plan")[0]
        plan = next(item for item in server.training_plan_service().list() if item["id"] == plan_entry["plan_id"])
        before = server.structured_training_state_service().read()["planning_revision"]
        server.training_plan_service().update(plan["id"], {"action": "update", "name": "Renamed Plan"})
        self.assertEqual(server.structured_training_state_service().read()["planning_revision"], before + 1)

    def test_training_plan_metadata_undo_advances_planning_revision(self):
        plan_entry = server.local_plan_creation_service().save([{
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Ride", "name": "Metadata", "description": "- 30m 60% easy",
            "duration_minutes": 30, "target": "AUTO", "rationale": "Test",
        }], plan_name="Metadata Plan")[0]
        plan = next(item for item in server.training_plan_service().list() if item["id"] == plan_entry["plan_id"])
        server.training_plan_service().update(plan["id"], {"action": "update", "name": "Renamed Plan"})
        metadata_change = next(
            item for item in server.change_history_service().list()
            if item["entity_type"] == "training_plan"
            and item["entity_id"] == plan["id"]
            and item["action"] == "update"
        )
        before_undo = server.structured_training_state_service().read()["planning_revision"]

        server.history_undo_service().apply({
            "change_id": metadata_change["id"],
            "expected_current_hash": metadata_change["after_hash"],
        })

        self.assertEqual(server.structured_training_state_service().read()["planning_revision"], before_undo + 1)
        restored = next(item for item in server.training_plan_service().list() if item["id"] == plan["id"])
        self.assertEqual(restored["name"], "Metadata Plan")

    def test_history_capacity_covers_one_complete_plan_replacement(self):
        self.assertGreaterEqual(change_history.MAX_ROWS, coach_limits.COACH_TRAINING_CHANGE_LIMIT * 2)

    def test_complete_plan_replacement_rejects_oversized_history_atomically(self):
        old = server.local_plan_creation_service().save([{
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Ride", "name": "Old", "description": "- 30m 60% easy",
            "duration_minutes": 30, "target": "AUTO", "rationale": "Test",
        }], plan_name="Old Plan")[0]
        old_plan = next(plan for plan in server.training_plan_service().list() if plan["id"] == old["plan_id"])
        state = server.structured_training_state_service().read()

        with patch.object(change_history, "MAX_ROWS", 3), self.assertRaises(server.AppError) as error:
            server.structured_training_plan_replacement_service().replace({
                "expected_revision": state["planning_revision"],
                "payload": {"plan_name": "Replacement", "goal": "", "workouts": [{
                    "date": (date.today() + timedelta(days=2)).isoformat(),
                    "sport": "Ride", "name": "New", "description": "- 40m 60% easy",
                    "duration_minutes": 40, "target": "AUTO", "rationale": "Test",
                }]},
            })

        self.assertEqual(error.exception.reason, "change_history_limit")
        active = server.planned_unit_service().list()
        self.assertEqual([item["id"] for item in active], [old["id"]])
        unchanged_plan = next(plan for plan in server.training_plan_service().list() if plan["id"] == old_plan["id"])
        self.assertEqual(unchanged_plan["status"], "planned")

    def test_complete_plan_replace_archives_selected_plan_without_future_units(self):
        past_plan_id = str(uuid.uuid4())
        past = (date.today() - timedelta(days=10)).isoformat()
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            server.TRAINING_PLAN_REPOSITORY.create(db, past_plan_id, "Past Plan", "", past, past, "planned", server.utc_now())
        state = server.structured_training_state_service().read()
        intent = {
            "intent": "local_action", "operation": "replace_training_plan", "target_system": "local",
            "artifact_id": None, "ambiguities": [], "authorization_scope": [f"training_plan:{past_plan_id}"],
            "follow_up_operations": [],
        }
        result = server.coach_tool_dispatch_service().execute(
            "replace_training_plan",
            {"expected_revision": state["planning_revision"], "payload": {"plan_name": "Past Plan", "goal": "", "workouts": [
                {"date": (date.today() + timedelta(days=1)).isoformat(), "sport": "Ride", "name": "New", "description": "- 40m 60% easy", "duration_minutes": 40, "target": "AUTO", "rationale": "Test"},
            ]}},
            intent=intent, conversation_id="conversation-past-plan", client_turn_id="turn-past-plan",
            session_csrf_hash="", sync_job_ids=[],
        )
        self.assertEqual(result["status"], "replaced")
        self.assertEqual(next(plan for plan in server.training_plan_service().list() if plan["id"] == past_plan_id)["status"], "archived")

    def test_broad_plan_replace_archives_future_plan_metadata_without_active_units(self):
        empty_plan_id = str(uuid.uuid4())
        starts = (date.today() + timedelta(days=1)).isoformat()
        ends = (date.today() + timedelta(days=7)).isoformat()
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            server.TRAINING_PLAN_REPOSITORY.create(
                db, empty_plan_id, "Empty Future Plan", "", starts, ends, "planned", server.utc_now(),
            )
        state = server.structured_training_state_service().read()

        result = server.structured_training_plan_replacement_service().replace({
            "expected_revision": state["planning_revision"],
            "payload": {"plan_name": "Replacement", "goal": "", "workouts": [{
                "date": (date.today() + timedelta(days=2)).isoformat(),
                "sport": "Ride", "name": "New", "description": "- 40m 60% easy",
                "duration_minutes": 40, "target": "AUTO", "rationale": "Test",
            }]},
        })

        self.assertEqual(result["status"], "replaced")
        old_plan = next(plan for plan in server.training_plan_service().list() if plan["id"] == empty_plan_id)
        self.assertEqual(old_plan["status"], "archived")
        metadata_history = next(
            item for item in server.change_history_service().list()
            if item["entity_type"] == "training_plan"
            and item["entity_id"] == empty_plan_id
            and item["action"] == "update"
        )
        self.assertNotEqual(metadata_history["before_hash"], metadata_history["after_hash"])

    def test_broad_plan_replace_preserves_imported_provider_units(self):
        remote_date = (date.today() + timedelta(days=2)).isoformat()
        server.remote_planned_unit_reconciler().reconcile([{
            "id": "remote-future-workout", "category": "WORKOUT", "type": "Ride",
            "name": "Provider workout", "start_date_local": remote_date + "T07:00:00",
            "moving_time": 1800,
        }])
        state = server.structured_training_state_service().read()
        result = server.structured_training_plan_replacement_service().replace({
            "expected_revision": state["planning_revision"],
            "payload": {"plan_name": "Coach replacement", "goal": "", "workouts": [{
                "date": (date.today() + timedelta(days=1)).isoformat(),
                "sport": "Ride", "name": "New", "description": "- 40m 60% easy",
                "duration_minutes": 40, "target": "AUTO", "rationale": "Test",
            }]},
        })
        self.assertEqual(result["status"], "replaced")
        imported = next(item for item in server.planned_unit_service().list(include_archived=True) if item.get("remote_event_id") == "remote-future-workout")
        self.assertFalse(imported.get("local_deleted", False))
        self.assertFalse(imported.get("archived", False))

    def test_planned_unit_undo_rejects_a_new_date_conflict(self):
        old = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "start_date_local": (date.today() + timedelta(days=1)).isoformat() + "T07:30:00",
            "sport": "Ride", "name": "Old", "description": "- 30m 60% easy",
        })
        state = server.structured_training_state_service().read()
        intent = {
            "intent": "local_action", "operation": "replace_training_plan", "target_system": "local",
            "artifact_id": None, "ambiguities": [], "authorization_scope": ["local_plan"],
            "follow_up_operations": [],
        }
        server.coach_tool_dispatch_service().execute(
            "replace_training_plan",
            {"expected_revision": state["planning_revision"], "payload": {"plan_name": "Conflict Replacement", "goal": "", "workouts": [
                {"date": old["date"], "sport": "Ride", "name": "New", "description": "- 40m 60% easy", "duration_minutes": 40, "target": "AUTO", "rationale": "Test"},
            ]}},
            intent=intent, conversation_id="conversation-undo-conflict", client_turn_id="turn-undo-conflict",
            session_csrf_hash="", sync_job_ids=[],
        )
        deleted_history = next(
            item for item in server.change_history_service().list()
            if item["entity_type"] == "planned_unit" and item["entity_id"] == old["id"] and item["action"] == "delete"
        )
        with self.assertRaises(server.AppError) as error:
            server.history_undo_service().apply({"change_id": deleted_history["id"], "expected_current_hash": deleted_history["after_hash"]})
        self.assertEqual(error.exception.reason, "plan_date_conflict")

    def test_structured_training_reads_expose_complete_bounded_plan(self):
        for index in range(coach_limits.COACH_TRAINING_CHANGE_LIMIT):
            server.planned_unit_service().create({
                "date": (date(2098, 1, 1) + timedelta(days=index)).isoformat(),
                "sport": "Ride", "name": f"Session {index}", "description": "- 30m 60% easy",
            })
        intent = {"intent": "local_action", "operation": "read_training_state", "target_system": "local", "authorization_scope": []}
        state = server.coach_tool_dispatch_service().execute(
            "read_training_state", {}, intent=intent, conversation_id="read-plan", client_turn_id="read-plan",
            session_csrf_hash="", sync_job_ids=[],
        )
        self.assertEqual(len(state["planned_units"]), coach_limits.COACH_TRAINING_CHANGE_LIMIT)
        listed = server.coach_tool_dispatch_service().execute(
            "list_planned_workouts", {"limit": coach_limits.COACH_TRAINING_CHANGE_LIMIT}, intent=intent,
            conversation_id="read-plan", client_turn_id="read-plan", session_csrf_hash="", sync_job_ids=[],
        )
        self.assertEqual(len(listed["local"]), coach_limits.COACH_TRAINING_CHANGE_LIMIT)

    def test_structured_training_state_filters_inactive_rows_before_limit(self):
        with patch(
            "backend.planning.state_service.STRUCTURED_TRAINING_STATE_PAGE_LIMIT",
            2,
        ):
            archived = server.planned_unit_service().create({
                "date": (date.today() + timedelta(days=1)).isoformat(),
                "sport": "Ride", "name": "Archived", "description": "- 30m 60% easy",
            })
            server.planned_unit_service().update(archived["id"], {"action": "archive"})
            active = [server.planned_unit_service().create({
                "date": (date.today() + timedelta(days=index)).isoformat(),
                "sport": "Ride", "name": f"Active {index}", "description": "- 30m 60% easy",
            }) for index in (2, 3)]
            state = server.structured_training_state_service().read()
        self.assertEqual([item["local_id"] for item in state["planned_units"]], [item["id"] for item in active])

    def test_structured_training_state_rejects_cursor_from_changed_revision(self):
        with patch(
            "backend.planning.state_service.STRUCTURED_TRAINING_STATE_PAGE_LIMIT",
            1,
        ):
            server.planned_unit_service().create({
                "date": (date.today() + timedelta(days=1)).isoformat(),
                "sport": "Ride", "name": "First", "description": "- 30m 60% easy",
            })
            server.planned_unit_service().create({
                "date": (date.today() + timedelta(days=2)).isoformat(),
                "sport": "Ride", "name": "Second", "description": "- 30m 60% easy",
            })
            first_page = server.structured_training_state_service().read()
            server.planned_unit_service().create({
                "date": (date.today() + timedelta(days=3)).isoformat(),
                "sport": "Ride", "name": "Changed", "description": "- 30m 60% easy",
            })
            with self.assertRaises(server.AppError) as raised:
                server.structured_training_state_service().read(cursor=first_page["planned_units_page"]["next_cursor"])
        self.assertEqual(raised.exception.reason, "planning_revision_conflict")

    def test_bulk_training_changes_require_revision_and_hashes(self):
        planned = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Ride", "name": "Bulk target", "description": "- 30m 60% easy",
        })
        intent = {
            "intent": "local_action", "operation": "apply_training_changes", "target_system": "local",
            "authorization_scope": ["local_plan"], "bulk_change": True,
        }
        with self.assertRaises(server.AppError) as raised:
            server.coach_tool_dispatch_service().execute(
                "apply_training_changes", {"changes": [{"local_id": planned["id"], "action": "update"}]},
                intent=intent, conversation_id="bulk-required", client_turn_id="bulk-required",
                session_csrf_hash="", sync_job_ids=[],
            )
        self.assertEqual(raised.exception.reason, "planning_revision_required")

    def test_bulk_training_changes_validate_final_schedule_before_writes(self):
        first_date = date.today() + timedelta(days=1)
        second_date = date.today() + timedelta(days=2)
        first = server.planned_unit_service().create({
            "date": first_date.isoformat(), "sport": "Ride", "name": "First", "description": "- 30m 60% easy",
        })
        second = server.planned_unit_service().create({
            "date": second_date.isoformat(), "sport": "Ride", "name": "Second", "description": "- 30m 60% easy",
        })
        state = server.structured_training_state_service().read()
        refs = {item["local_id"]: item for item in state["planned_units"]}
        intent = {
            "intent": "local_action", "operation": "apply_training_changes", "target_system": "local",
            "authorization_scope": ["local_plan"], "bulk_change": True,
        }
        result = server.coach_tool_dispatch_service().execute(
            "apply_training_changes", {
                "expected_revision": state["planning_revision"],
                "changes": [
                    {"local_id": first["id"], "action": "update", "date": second_date.isoformat(), "expected_payload_hash": refs[first["id"]]["expected_payload_hash"]},
                    {"local_id": second["id"], "action": "update", "date": first_date.isoformat(), "expected_payload_hash": refs[second["id"]]["expected_payload_hash"]},
                ],
            },
            intent=intent, conversation_id="bulk-rotation", client_turn_id="bulk-rotation",
            session_csrf_hash="", sync_job_ids=[],
        )
        self.assertEqual(result["status"], "applied")
        current = {item["id"]: item["date"] for item in server.planned_unit_service().list()}
        self.assertEqual(current[first["id"]], second_date.isoformat())
        self.assertEqual(current[second["id"]], first_date.isoformat())

    def test_training_patch_rolls_back_existing_updates_when_creation_fails(self):
        existing = server.planned_unit_service().create({
            "date": (date.today() + timedelta(days=4)).isoformat(),
            "sport": "Ride", "name": "Before", "description": "- 30m 60% easy",
        })
        revision = server.structured_training_state_service().read()["planning_revision"]
        expected_hash = next(
            item["expected_payload_hash"]
            for item in server.structured_training_state_service().read()["planned_units"]
            if item["local_id"] == existing["id"]
        )
        arguments = {
            "expected_revision": revision,
            "changes": [{"local_id": existing["id"], "action": "update", "name": "Changed", "expected_payload_hash": expected_hash}],
            "workouts": [{
                "date": (date.today() + timedelta(days=5)).isoformat(),
                "sport": "Run", "name": "New", "description": "- 30m 60% easy",
                "duration_minutes": 30, "target": "AUTO",
            }],
        }
        with patch.object(
            server.LocalTrainingPlanCreationService,
            "save",
            side_effect=RuntimeError("creation failed"),
        ):
            with self.assertRaises(RuntimeError):
                server.coach_training_patch_service().apply(arguments, {
                    "authorization_scope": ["local_plan"],
                    "request": {"constraints": []},
                })
        current = {item["id"]: item for item in server.planned_unit_service().list()}
        self.assertEqual(current[existing["id"]]["name"], "Before")
        self.assertEqual(len(current), 1)
        self.assertEqual(server.structured_training_state_service().read()["planning_revision"], revision)

    def test_workout_library_refresh_forwards_cancellation(self):
        cancel_event = threading.Event()
        config = replace(server.CONFIG, intervals_api_key="test-key")
        seen = {}

        def get_library(*, cancel_event=None):
            seen["cancel_event"] = cancel_event
            cancel_event.set()
            raise_if_chat_cancelled(cancel_event)

        with patch.object(server, "CONFIG", config), patch.object(
            intervals_client_module.IntervalsClient, "get_workout_library", side_effect=get_library
        ) as get_workout_library:
            with self.assertRaises(server.AppError) as raised:
                server.workout_library_refresh_service().refresh(
                    "cancellable", cancel_event=cancel_event
                )
        self.assertEqual(raised.exception.reason, "chat_cancelled")
        self.assertIs(seen["cancel_event"], cancel_event)
        get_workout_library.assert_called_once_with(cancel_event=cancel_event)

    def test_initial_planning_import_retries_after_import_failure(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        snapshot = {
            "synced_at": "retryable", "athlete": {}, "recent_activities": [], "recent_wellness": [],
            "upcoming_calendar": [{
                "id": "retry-plan", "category": "WORKOUT", "type": "Ride", "name": "Retry Plan",
                "start_date_local": tomorrow + "T08:00:00", "moving_time": 1800,
            }],
        }
        config = replace(server.CONFIG, intervals_api_key="test-key")
        with patch.object(server, "CONFIG", config), patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", side_effect=[snapshot, snapshot]
        ), patch.object(
            RemotePlannedUnitReconciler,
            "reconcile",
            side_effect=[RuntimeError("import failed"), {"imported": 1, "updated": 0, "conflicts": 0}],
        ) as import_units, patch.object(WorkoutLibraryRefreshService, "refresh", return_value={"workouts": 0}):
            with self.assertRaises(RuntimeError):
                server.intervals_sync_service().sync(
                    "initial attempt", activity_days=42
                )
            self.assertIsNone(server.key_value_service().get("planned_units_initial_import_at"))
            server.intervals_sync_service().sync("retry", activity_days=42)

        self.assertEqual(import_units.call_count, 2)
        self.assertEqual(server.key_value_service().get("planned_units_initial_import_at"), "retryable")

    def test_library_refresh_is_read_only_even_with_pending_local_entries(self):
        server.workout_library_service().create_local_entry({
            "sport": "Ride",
            "name": "Read-only refresh",
            "description": "- 20m Z2",
            "duration_minutes": 20,
        })
        recorder = IntervalsRequestRecorder()
        client = RecordedIntervalsClient(recorder)
        with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(
            server, "intervals_client", return_value=client
        ):
            result = server.workout_library_refresh_service().refresh("read-only")
        self.assertEqual(result["local_synced"], 0)
        self.assertEqual(recorder.mutations, [])

    def test_read_competition_pull_keeps_dirty_local_changes_as_conflict(self):
        event_date = (date.today() + timedelta(days=33)).isoformat()
        saved = server.athlete_context_service().save({}, [{
            "name": "Remote original",
            "event_date": event_date,
            "sport": "Cycling",
        }])
        competition_id = saved["competitions"][0]["id"]
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "UPDATE competitions SET intervals_event_id=?, external_id=?, sync_dirty=0, sync_state='synced' WHERE id=?",
                ("123", planning_competitions.competition_external_id(competition_id), competition_id),
            )
        server.competition_service().save({
            "competition_id": competition_id,
            "name": "Local pending change",
            "event_date": event_date,
            "sport": "Cycling",
        })
        recorder = IntervalsRequestRecorder()
        client = RecordedIntervalsClient(recorder, competitions=[{
            "id": 123,
            "category": "RACE_B",
            "start_date_local": event_date + "T08:00:00",
            "type": "Ride",
            "name": "Remote original",
        }])
        with patch.object(server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")), patch.object(
            server, "intervals_client", return_value=client
        ):
            result = server.competition_sync_service().sync("read-only")
        competition = server.competition_service().list()[0]
        self.assertEqual(result["pushed"], 0)
        self.assertEqual(competition["name"], "Local pending change")
        self.assertEqual(competition["sync_dirty"], 1)
        self.assertEqual(competition["sync_state"], "conflict")
        self.assertEqual(recorder.mutations, [])

    def test_structured_athlete_context_persists_competitions(self):
        event_date = (date.today() + timedelta(days=60)).isoformat()
        result = server.athlete_context_service().save(
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
        context = server.coach_structured_context_service().build()
        self.assertEqual(context["target_competitions"][0]["name"], "Münsterland Giro")
        self.assertIn("bestätigte", context["source_policy"]["durable_profile"])

    def test_competition_conflict_can_adopt_remote_or_keep_local(self):
        event_date = (date.today() + timedelta(days=61)).isoformat()
        saved = server.athlete_context_service().save({}, [{"name": "Remote Race", "event_date": event_date, "sport": "Cycling"}])
        competition_id = saved["competitions"][0]["id"]

        class FakeIntervalsClient:
            def __init__(self):
                self.pushed = []
            def fetch_competition_events(self):
                return [{"id": 54322, "category": "RACE_A", "start_date_local": event_date + "T08:00:00", "type": "Ride", "name": "Remote Race"}]
            def upsert_competition_events(self, events):
                self.pushed.extend(events)
                return [{**events[0], "id": 54323}] if events else []
            def bulk_delete_events(self, identifiers):
                return 0

        client = FakeIntervalsClient()
        with patch.object(server, "intervals_client", return_value=client), patch.object(
            server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")
        ):
            server.competition_sync_service().sync("test")
            adopted = server.competition_service().resolve_conflict(competition_id, "adopt_remote")
        self.assertEqual(adopted["competition"]["name"], "Remote Race")
        self.assertEqual(adopted["competition"]["sync_state"], "synced")
        self.assertEqual(adopted["competition"]["sync_dirty"], 0)

        saved = server.competition_service().save({
            "competition_id": competition_id, "name": "Remote Race", "event_date": event_date,
            "sport": "Cycling", "priority": "B",
        })
        self.assertEqual(saved["competition"]["sync_state"], "local")
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute("UPDATE competitions SET intervals_event_id=NULL, sync_dirty=1, sync_state='local', sync_conflict='' WHERE id=?", (competition_id,))
        with patch.object(server, "intervals_client", return_value=client), patch.object(
            server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")
        ):
            server.competition_sync_service().sync("test")
            # Explicitly choosing the local version enables a provider update.
            server.competition_service().resolve_conflict(competition_id, "keep_local")
            result = server.competition_sync_service().sync("test", push_local=True)
        self.assertEqual(result["pushed"], 1)
        self.assertEqual(server.competition_service().list()[0]["sync_state"], "synced")

    def test_competition_removal_creates_remote_delete_tombstone(self):
        event_date = (date.today() + timedelta(days=60)).isoformat()
        saved = server.athlete_context_service().save({}, [{"name": "Delete Race", "event_date": event_date}])
        local_id = saved["competitions"][0]["id"]
        deleted = []

        class FakeIntervalsClient:
            def fetch_competition_events(self):
                return []

            def upsert_competition_events(self, events):
                return [{**events[0], "id": 888}] if events else []

            def bulk_delete_events(self, identifiers):
                deleted.extend(identifiers)
                return len(identifiers)

        with patch.object(server, "intervals_client", FakeIntervalsClient), patch.object(
            server, "CONFIG", replace(server.CONFIG, intervals_api_key="test-key")
        ):
            server.competition_sync_service().sync("test", push_local=True)
            server.athlete_context_service().save({}, [])
            result = server.competition_sync_service().sync("test", push_local=True)

        self.assertEqual(result["deleted_remote"], 1)
        self.assertEqual(deleted, [{"id": "888"}])
        self.assertEqual(server.competition_service().list(), [])
        self.assertNotEqual(local_id, "")

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
        comparisons = _current_performance_context(snapshot)["comparisons"]
        self.assertEqual(comparisons["sleep_hours"]["days"], 7)
        self.assertEqual(comparisons["sleep_hours"]["color"], "good")
        self.assertEqual(comparisons["restingHR"]["color"], "good")
        self.assertEqual(comparisons["fitness_ctl"]["color"], "neutral")

    def test_adaptive_planning_is_only_actionable_through_the_coach(self):
        markup = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        app_source = (server.PUBLIC_DIR / "app.js").read_text(encoding="utf-8")
        self.assertNotIn('id="plannedPlanningSection"', markup)
        self.assertIn('id="coachAdaptivePlanningNotice"', markup)
        self.assertIn('id="coachAdaptivePlanningButton"', markup)
        self.assertNotIn('id="adaptivePlanningNotice"', markup)
        self.assertNotIn('id="adaptivePlanningDialog"', markup)
        self.assertNotIn("function applyReplan(", app_source)
        self.assertNotIn('id="externalCalendarEvents"', markup)
        self.assertNotIn('id="planningSummary"', markup)

    def test_change_history_records_safe_diff_and_explicit_undo(self):
        server.profile_service().save({"name": "Ada", "weight_kg": "71"})
        server.profile_service().save({"name": "Bea", "weight_kg": "72"})
        history = server.change_history_service().list()
        latest = next(item for item in history if item["entity_type"] == "profile")
        self.assertEqual(latest["action"], "update")
        self.assertEqual(latest["diff"]["fields"]["name"], {"changed": True})
        self.assertEqual(latest["diff"]["fields"]["weight_kg"], {"changed": True})
        self.assertNotIn("Ada", json.dumps(latest))
        self.assertNotIn('"before"', json.dumps(latest))
        self.assertNotIn('"after"', json.dumps(latest))
        self.assertNotIn("prompt", json.dumps(latest).casefold())
        preview = self.history_preview(latest["id"])
        confirmed = server.coach_proposal_confirmation_service().confirm(preview["proposed_action"]["id"], "session-csrf-hash")
        result = server.coach_proposal_execution_service().execute(confirmed["action_token"], "session-csrf-hash", confirmed["proposed_action"]["payload_hash"])
        self.assertTrue(result["remote_untouched"])
        self.assertEqual(server.profile_service().get()["name"], "Ada")
        with self.assertRaises(server.AppError) as replay:
            server.history_undo_service().preview(latest["id"])
        self.assertEqual(replay.exception.status, 409)

    def test_deleted_local_library_entry_can_be_undone_without_provider_write(self):
        entry = server.workout_library_service().create_local_entry({"name": "Easy", "sport": "Ride", "duration_minutes": 30, "description": "- 30m 60%"})
        created = next(item for item in server.change_history_service().list() if item["entity_id"] == entry["id"] and item["action"] == "create")
        preview = self.history_preview(created["id"])
        confirmed = server.coach_proposal_confirmation_service().confirm(preview["proposed_action"]["id"], "session-csrf-hash")
        result = server.coach_proposal_execution_service().execute(confirmed["action_token"], "session-csrf-hash", confirmed["proposed_action"]["payload_hash"])
        self.assertEqual(result["status"], "undone")
        self.assertFalse(server.workout_library_service().list(include_archived=True))


if __name__ == "__main__":
    unittest.main()
