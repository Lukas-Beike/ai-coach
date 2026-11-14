"""Server integration tests for coach."""

import json
import threading
import unittest
import uuid
from datetime import timedelta
from unittest.mock import patch

import snapshot_seed
from garmin_support import read_garmin, save_garmin
from server_test_support import ServerTestCase, server
from support import store_canonical_snapshot, store_garmin_activities

from backend.coach import context as coach_context
from backend.coach import limits as coach_limits
from backend.coach import streams as coach_streams
from backend.errors import AppError
from backend.http_api import server as http_server_module
from backend.planning import competitions as planning_competitions
from backend.runtime import events as runtime_events


class ServerCoachTests(ServerTestCase):
    def test_coach_http_server_retains_threading_contract(self):
        from http.server import ThreadingHTTPServer

        self.assertTrue(
            issubclass(http_server_module.CoachHTTPServer, ThreadingHTTPServer)
        )
        self.assertTrue(http_server_module.CoachHTTPServer.daemon_threads)
        self.assertEqual(http_server_module.CoachHTTPServer.request_queue_size, 32)

    def test_structured_commit_rejects_model_artifact_outside_classified_scope(self):
        artifact = server.COACH_PLANNING_TOOLS.training_plan_artifact_service().stage(
            {
                "payload": {
                    "plan_name": "Scoped",
                    "workouts": [
                        {
                            "date": "2099-01-01",
                            "sport": "Ride",
                            "description": "- 30m 60% Easy session",
                            "duration_minutes": 30,
                        }
                    ],
                }
            },
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
        with self.assertRaises(AppError) as denied:
            server.COACH_TOOL_DISPATCH.service().execute(
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
        artifact = server.COACH_PLANNING_TOOLS.training_plan_artifact_service().stage(
            {
                "payload": {
                    "plan_name": "Foreign",
                    "workouts": [
                        {
                            "date": "2099-01-04",
                            "sport": "Ride",
                            "name": "Foreign ride",
                            "description": "- 30m 60% easy",
                            "duration_minutes": 30,
                        }
                    ],
                }
            },
            "conversation-foreign",
            "turn-foreign",
        )
        intent = {
            "intent": "local_action",
            "operation": "commit_training_plan",
            "target_system": "local",
            "artifact_id": artifact["artifact_id"],
            "ambiguities": [],
            "authorization_scope": [f"artifact:{artifact['artifact_id']}"],
            "follow_up_operations": [],
            "_allow_artifact_rebind": True,
        }

        with self.assertRaises(AppError) as denied:
            server.COACH_TOOL_DISPATCH.service().execute(
                "commit_training_plan",
                {"artifact_id": artifact["artifact_id"]},
                intent=intent,
                conversation_id="conversation-current",
                client_turn_id="turn-current",
                session_csrf_hash="",
                sync_job_ids=[],
            )

        self.assertEqual(denied.exception.reason, "artifact_conversation_conflict")

    def test_structured_state_exposes_current_local_targets_and_hashes(self):
        planned = server.PLANNING_DATA.planned_unit().create(
            {
                "date": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=1)
                ).isoformat(),
                "sport": "Run",
                "name": "Easy run",
                "description": "- 30m 60% easy",
            }
        )
        template = server.PLANNING_DATA.workout_library().create_template(
            {
                "sport": "Ride",
                "name": "Endurance",
                "description": "- 45m Z2",
                "duration_minutes": 45,
            }
        )

        state = server.PLANNING_WORKFLOWS.structured_training_state_service().read()

        planned_ref = next(
            item for item in state["planned_units"] if item["local_id"] == planned["id"]
        )
        template_ref = next(
            item
            for item in state["training_templates"]
            if item["local_id"] == template["id"]
        )
        self.assertRegex(planned_ref["expected_payload_hash"], r"^[0-9a-f]{64}$")
        self.assertRegex(template_ref["expected_payload_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(planned_ref["date"], planned["date"])

    def test_structured_coach_can_archive_multiple_templates_directly(self):
        templates = [
            server.PLANNING_DATA.workout_library().create_template(
                {
                    "sport": "Ride",
                    "name": f"Template {index}",
                    "description": "- 30m Z2",
                    "duration_minutes": 30,
                }
            )
            for index in range(2)
        ]
        intent = {
            "intent": "local_action",
            "operation": "manage_training_templates",
            "target_system": "local",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": ["local_template"],
        }

        result = server.COACH_TOOL_DISPATCH.service().execute(
            "manage_training_templates",
            {
                "templates": [
                    {"local_id": item["id"], "action": "archive"} for item in templates
                ]
            },
            intent=intent,
            conversation_id="conversation-template",
            client_turn_id="turn-template",
            session_csrf_hash="",
            sync_job_ids=[],
        )

        self.assertEqual(len(result["templates"]), 2)
        self.assertEqual(server.PLANNING_DATA.workout_library().list(), [])
        self.assertEqual(
            len(server.PLANNING_DATA.workout_library().list(include_archived=True)), 2
        )

    def test_structured_context_carries_garmin_values_in_recovery_and_performance(self):
        payload = {
            "synced_at": "2026-10-11T08:00:00+00:00",
            "max_metrics": [
                {"calendarDate": "2026-10-10", "generic": {"vo2MaxValue": 55}}
            ],
            "race_predictions": {"5k": 1320},
            "activities": [{"activityId": 1, "activityName": "Duplicate raw activity"}],
        }
        # Saving writes the canonical rows too; Garmin values are read only from
        # them (#1415), so the context reads the stored snapshot as production does.
        save_garmin(payload)
        # Completes the first canonical backfill, so the tables serve the context.
        store_canonical_snapshot(
            server,
            {
                "synced_at": "2026-10-11T07:00:00+00:00",
                "athlete": {},
                "recent_activities": [],
                "recent_wellness": [],
                "upcoming_calendar": [],
            },
        )
        context = server.COACH_CONTEXT.structured_context_service().build()

        # The recovery section always carries Garmin's performance values.
        self.assertIn("performance", context["recovery"])
        self.assertNotIn("activities", context["recovery"])
        self.assertEqual(
            context["current_performance"]["metrics"]["running_vo2max_ml_kg_min"][
                "value"
            ],
            55,
        )
        self.assertEqual(
            context["current_performance"]["metrics"]["running_vo2max_ml_kg_min"][
                "source"
            ],
            "Garmin Connect",
        )
        self.assertEqual(
            context["current_performance"]["metrics"]["run_5k_seconds"]["value"], 1320
        )

    def test_context_preview_exposes_context_and_last_chat_input(self):
        server.APP.coach_conversation.message_service().add(
            "user", "Wie soll ich morgen trainieren?"
        )
        preview = server.COACH_CONTEXT.preview_service().preview()
        self.assertIn(
            "<coaching_rules>\nYou receive a fresh structured training snapshot",
            preview["context_text"],
        )
        self.assertIn("<athlete_context>", preview["context_text"])
        self.assertEqual(preview["chat_prompt"]["field"], "input")
        self.assertEqual(
            preview["chat_prompt"]["content"], "Wie soll ich morgen trainieren?"
        )
        self.assertIn("instructions", preview["chat_prompt"]["note"])

    def test_context_budget_factories_use_backend_owned_values(self):
        training = server.COACH_CONTEXT.training_context_service()
        preview_limits = server.COACH_CONTEXT.preview_service()._limits
        self.assertEqual(
            server.COACH_CONTEXT.request_payload_service()._max_output_tokens,
            coach_limits.COACH_DEFAULT_MAX_OUTPUT_TOKENS,
        )
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
        self.assertEqual(
            preview_limits.local_planned_limit, coach_context.COACH_LOCAL_PLANNED_LIMIT
        )
        self.assertEqual(
            preview_limits.library_limit, coach_context.COACH_LIBRARY_LIMIT
        )
        self.assertEqual(
            preview_limits.library_description_limit,
            coach_context.COACH_LIBRARY_DESCRIPTION_LIMIT,
        )
        self.assertEqual(
            preview_limits.section_limits, coach_context.COACH_CONTEXT_SECTION_LIMITS
        )
        self.assertEqual(
            preview_limits.total_char_limit,
            coach_context.COACH_CONTEXT_TOTAL_CHAR_LIMIT,
        )
        self.assertEqual(
            preview_limits.activity_limit_per_sport,
            coach_context.COACH_RECENT_ACTIVITIES_PER_SPORT,
        )
        self.assertEqual(
            preview_limits.planned_event_limit, coach_context.COACH_PLANNED_EVENT_LIMIT
        )

    def test_coach_projection_does_not_change_provider_snapshots(self):
        today = server.ATHLETE_CLOCK.now().date()
        intervals_snapshot = {
            "synced_at": "now",
            "athlete": {"provider_detail": "kept in the full snapshot"},
            "recent_activities": [
                {
                    "id": f"ride-{index}",
                    "type": "Ride",
                    "name": f"Ride {index}",
                    "start_date_local": (today - timedelta(days=index)).isoformat(),
                    "provider_detail": "kept in the full snapshot",
                }
                for index in range(6)
            ],
            "recent_wellness": [],
            "upcoming_calendar": [],
        }
        garmin_snapshot = {
            "synced_at": "now",
            "activities": [
                {"activityId": 7, "vendor_payload": "kept in the full snapshot"}
            ],
            "sleep": [{"calendarDate": today.isoformat(), "sleepScore": 82}],
            "vendor_payload": "kept in the full snapshot",
        }
        intervals_before = json.dumps(
            intervals_snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        snapshot_seed.save_snapshot(
            server.SYNC_PERSISTENCE.state_repository(), intervals_snapshot
        )
        save_garmin(garmin_snapshot)
        garmin_stored = read_garmin()
        self.assertEqual(garmin_stored["vendor_payload"], "kept in the full snapshot")

        context = server.COACH_CONTEXT.training_context_service().build()

        self.assertEqual(
            snapshot_seed.latest_snapshot(server.database_manager()),
            intervals_snapshot,
        )
        self.assertEqual(read_garmin(), garmin_stored)
        self.assertEqual(
            json.dumps(
                snapshot_seed.latest_snapshot(server.database_manager()),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ),
            intervals_before,
        )
        self.assertNotIn("provider_detail", context)
        self.assertNotIn("vendor_payload", context)

    def test_background_job_replay_reuses_receipt_without_republishing(self):
        registry = coach_streams.CHAT_STREAM_REGISTRY

        def publish_after_commit(topic, event):
            self.assertEqual(topic, "coach")
            with server.database_manager().unit_of_work() as db:
                command = db.execute(
                    "SELECT status FROM coach_commands WHERE client_turn_id=?",
                    (event["client_turn_id"],),
                ).fetchone()
            self.assertEqual(command["status"], "queued")

        with (
            patch.object(
                runtime_events.STATE_EVENT_BUFFER,
                "publish",
                side_effect=publish_after_commit,
            ) as publish,
            patch.object(registry, "set_background_event") as register_event,
            patch.object(server.COACH_JOB_WORKER.wake_event, "set") as wake_worker,
        ):
            first = server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
                "Eine lange Planung bitte",
                "turn-background-idempotent",
                "csrf-background-idempotent",
                operation_id="operation-background-idempotent",
            )
            replay = server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
                "Andere Nachricht ignorieren",
                "turn-background-idempotent",
                "csrf-background-idempotent",
                operation_id="operation-background-replay",
            )
            with self.assertRaises(AppError) as foreign_replay:
                server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
                    "Fremde Sitzung",
                    "turn-background-idempotent",
                    "csrf-background-foreign",
                )

        self.assertEqual(replay, first)
        self.assertEqual(foreign_replay.exception.reason, "command_scope_denied")
        with server.database_manager().unit_of_work() as db:
            stored_intent = db.execute(
                "SELECT intent FROM coach_commands WHERE client_turn_id=?",
                ("turn-background-idempotent",),
            ).fetchone()["intent"]
        self.assertEqual(json.loads(stored_intent), {"allow_mutations": True})
        publish.assert_called_once()
        register_event.assert_called_once()
        wake_worker.assert_called_once()

    def test_cancel_set_before_enqueue_is_persisted_with_the_job(self):
        cancel_event = threading.Event()
        cancel_event.set()

        server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
            "Synthetic request",
            "early-cancel",
            "synthetic-session",
            operation_id="early-cancel-operation",
            cancel_event=cancel_event,
        )

        with server.database_manager().unit_of_work() as db:
            receipt = db.execute(
                "SELECT receipt FROM coach_commands WHERE client_turn_id='early-cancel'"
            ).fetchone()
        self.assertTrue(json.loads(receipt["receipt"])["cancel_requested"])
        self.assertTrue(
            server.COACH_BACKGROUND_JOBS.job_store().cancel_requested("early-cancel")
        )

    def test_restart_job_observes_cancel_during_session_restore(self):
        server.COACH_BACKGROUND_JOBS.job_submission_service().enqueue(
            "Synthetic request",
            "cancel-race",
            "synthetic-session",
            operation_id="cancel-operation",
        )
        job = server.COACH_BACKGROUND_JOBS.job_store().claim()
        coach_streams.CHAT_STREAM_REGISTRY.clear_state()  # Process restart loses in-memory events.

        def restore(_):
            self.assertEqual(
                server.COACH_BACKGROUND_JOBS.cancellation_service().cancel(
                    "synthetic-session", "cancel-operation"
                )["status"],
                "cancelling",
            )
            self.assertIsNone(
                coach_streams.CHAT_STREAM_REGISTRY.get_background_event(
                    "cancel-operation"
                )
            )
            with server.database_manager().unit_of_work() as db:
                receipt = db.execute(
                    "SELECT receipt FROM coach_commands WHERE client_turn_id='cancel-race'"
                ).fetchone()
            self.assertTrue(json.loads(receipt["receipt"])["cancel_requested"])
            return "synthetic-session"

        def coach(*args, **kwargs):
            self.assertTrue(kwargs["cancel_event"].is_set())
            return {"status": "cancelled"}

        with (
            patch.object(
                server.session_auth_service(),
                "restore_coach_session_csrf_hash",
                side_effect=restore,
            ),
            patch(
                "backend.coach.chat_turn.CoachChatTurnService.run", side_effect=coach
            ) as execute,
        ):
            server.COACH_BACKGROUND_JOBS.background_job_runner().run(job)
        execute.assert_called_once()

    def test_saved_profile_is_included_in_coach_context(self):
        server.ATHLETE_DATA.profile().save(
            {
                "name": "Ada",
                "goals": "Münsterland Giro",
                "constraints": "No hard sessions after poor sleep",
            }
        )
        context = server.COACH_CONTEXT.training_context_service().build()
        self.assertIn('"name":"Ada"', context)
        self.assertIn("Münsterland Giro", context)
        self.assertIn("No hard sessions after poor sleep", context)

    def test_coach_activity_feedback_is_persisted_and_attached_to_activity(self):
        store_garmin_activities(
            server,
            [
                {
                    "activityId": "activity-1",
                    "activityName": "Morgenlauf",
                    "activityType": {"typeKey": "running"},
                    "startTimeLocal": "2026-08-30 07:00:00",
                }
            ],
        )
        result = server.ATHLETE_DATA.activity_feedback().save_coach(
            "activity-1",
            {
                "activity_name": "Morgenlauf",
                "activity_date": "2026-08-30T07:00:00",
                "notes": "Linkes Knie ungewohnt empfindlich",
            },
        )
        self.assertEqual(
            result["activity_feedback"]["notes"], "Linkes Knie ungewohnt empfindlich"
        )
        activity = server.ACTIVITY_READS.activity_read().page(
            today=server.ATHLETE_CLOCK.now().date()
        )["activities"][0]
        self.assertEqual(activity["activity_feedback"]["activity_id"], activity["id"])
        self.assertTrue(activity["id"].startswith("act_"))
        self.assertEqual(
            activity["activity_feedback"]["notes"], "Linkes Knie ungewohnt empfindlich"
        )
        context = server.COACH_CONTEXT.structured_context_service().build()
        self.assertEqual(
            context["activity_feedback"]["recent"][0]["activity_name"], "Morgenlauf"
        )
        self.assertIn("Linkes Knie", context["activity_feedback"]["recent"][0]["notes"])

    def test_coach_can_create_update_and_delete_competition_without_replacing_profile(
        self,
    ):
        server.ATHLETE_DATA.profile().save({"name": "Ada", "goals": "Long course"})
        event_date = (
            server.ATHLETE_CLOCK.now().date() + timedelta(days=60)
        ).isoformat()
        arguments = {
            "competition_id": "",
            "name": "Münsterland Giro",
            "event_date": event_date,
            "starts_at_local": "",
            "sport": "Cycling",
            "priority": "A",
            "distance": "125 km",
            "target": "Finish strong",
            "course_profile": "Rolling",
            "notes": "",
            "description": "",
            "planned_duration_s": -1,
        }
        created = server.PLANNING_DATA.competition().save(arguments)
        competition_id = created["competition"]["id"]
        self.assertEqual(created["status"], "created")
        self.assertEqual(server.ATHLETE_DATA.profile().get()["name"], "Ada")

        updated = server.PLANNING_DATA.competition().save(
            {
                **arguments,
                "competition_id": competition_id,
                "name": "Münsterland Giro 2027",
                "priority": "B",
            }
        )
        self.assertEqual(updated["status"], "updated")
        self.assertEqual(updated["competition"]["name"], "Münsterland Giro 2027")
        self.assertEqual(updated["competition"]["priority"], "B")

        with server.database_manager().unit_of_work() as db:
            db.execute(
                "UPDATE competitions SET intervals_event_id=?, external_id=? WHERE id=?",
                (
                    "123",
                    planning_competitions.competition_external_id(competition_id),
                    competition_id,
                ),
            )
        deleted = server.PLANNING_DATA.competition().delete(competition_id)
        self.assertEqual(deleted["status"], "deleted")
        self.assertTrue(deleted["remote_sync_pending"])
        self.assertEqual(server.PLANNING_DATA.competition().list(), [])
        with server.database_manager().unit_of_work() as db:
            tombstone = db.execute(
                "SELECT intervals_event_id, external_id FROM competition_sync_tombstones"
            ).fetchone()
        self.assertEqual(tombstone["intervals_event_id"], "123")


if __name__ == "__main__":
    unittest.main()
