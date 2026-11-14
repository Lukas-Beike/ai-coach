"""Server integration tests for planning."""

import json
import unittest
import uuid
from dataclasses import replace
from datetime import date, timedelta
from unittest.mock import patch

import remote_reconcilers
from server_test_support import ServerTestCase, server
from support import (
    parsed_workout_fixture,
)

from backend.coach import context as coach_context
from backend.coach import limits as coach_limits
from backend.errors import AppError
from backend.planning import adaptive as planning_adaptive
from backend.planning import (
    calendar_service,
    local_plan_creation_service,
)
from backend.planning import workouts as planning_workouts
from backend.providers import intervals_client as intervals_client_module
from backend.runtime import clock as runtime_clock
from backend.runtime import events as runtime_events
from backend.sync import queue as sync_queue
from backend.sync.authority import competition_push_manifest


def ill_with_vo2_draft_tomorrow():
    """Save a VO2 draft for the athlete's tomorrow and a fever check-in; preview the replan."""
    tomorrow = (server.ATHLETE_CLOCK.now().date() + timedelta(days=1)).isoformat()
    draft = server.PLANNING_WORKFLOWS.local_plan_creation_service().save(
        [
            {
                "date": tomorrow,
                "sport": "Ride",
                "name": "VO2 intervals",
                "description": "- 5m 115%\n- 40m 55%",
                "duration_minutes": 45,
                "target": "POWER",
            }
        ]
    )[0]
    server.ATHLETE_DATA.checkin().save({"illness": "Fever", "soreness": 8})
    preview = server.PLANNING_WORKFLOWS.adaptive_replan_preview_service().preview()
    return tomorrow, draft, preview


class ServerPlanningTests(ServerTestCase):
    def test_structured_plan_push_declares_and_uses_bounded_entries(self):
        planned = server.PLANNING_DATA.planned_unit().create(
            {
                "date": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=1)
                ).isoformat(),
                "sport": "VirtualRide",
                "name": "Synthetic selected run",
                "description": "- 30m 60% Synthetic easy session",
                "duration_minutes": 30,
            }
        )
        local_id = planned["id"]
        entry = next(
            item
            for item in server.SYNC_COMMANDS.authority().pending_plan_push_entries()
            if item["library_workout_id"] == local_id
        )
        intent = {
            "intent": "remote_sync",
            "operation": "start_intervals_plan_sync",
            "target_system": "intervals",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": [f"library_workout:{local_id}"],
        }
        with patch.object(
            sync_queue.SyncJobQueueService,
            "enqueue",
            return_value={"id": "job-plan-push"},
        ) as enqueue:
            result = server.COACH_TOOL_DISPATCH.service().execute(
                "start_intervals_plan_sync",
                {"entries": [entry]},
                intent=intent,
                conversation_id="conversation-push",
                client_turn_id="turn-push",
                session_csrf_hash="",
                sync_job_ids=[],
            )
        schema = next(
            tool
            for tool in server.COACH_STRUCTURED_TOOLS
            if tool["name"] == "start_intervals_plan_sync"
        )["parameters"]
        self.assertIn("entries", schema["properties"])
        self.assertEqual(result["status"], "queued")
        self.assertEqual(
            enqueue.call_args.kwargs["item_operations"][0]["item_key"], local_id
        )

    def test_mixed_create_recomputes_attached_plan_bounds(self):
        original_date = (
            server.ATHLETE_CLOCK.now().date() + timedelta(days=5)
        ).isoformat()
        created = server.PLANNING_WORKFLOWS.local_plan_creation_service().save(
            [
                {
                    "date": original_date,
                    "sport": "Ride",
                    "name": "Plan start",
                    "description": "- 30m 60% easy",
                    "duration_minutes": 30,
                    "target": "AUTO",
                    "rationale": "Base",
                }
            ],
            plan_name="Bounds plan",
            goal="Consistency",
        )
        plan_id = created[0]["plan_id"]
        existing_id = created[0]["id"]
        state = server.PLANNING_WORKFLOWS.structured_training_state_service().read()
        target = next(
            item for item in state["planned_units"] if item["local_id"] == existing_id
        )
        later_date = (
            server.ATHLETE_CLOCK.now().date() + timedelta(days=12)
        ).isoformat()
        intent = {
            "intent": "local_action",
            "operation": "apply_training_changes",
            "target_system": "local",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": ["local_plan_create", f"planned_unit:{existing_id}"],
        }
        result = server.COACH_TOOL_DISPATCH.service().execute(
            "apply_training_changes",
            {
                "changes": [
                    {
                        "local_id": existing_id,
                        "action": "update",
                        "date": original_date,
                        "expected_payload_hash": target["expected_payload_hash"],
                    },
                    {
                        "action": "create",
                        "date": later_date,
                        "sport": "Run",
                        "name": "Recovery",
                        "description": "- 20m 60% easy",
                        "duration_minutes": 20,
                        "target": "AUTO",
                        "rationale": "Recovery",
                    },
                ]
            },
            intent=intent,
            conversation_id="conversation-bounds",
            client_turn_id="turn-bounds",
            session_csrf_hash="",
            sync_job_ids=[],
        )
        self.assertEqual(result["status"], "applied")
        plan = next(
            item
            for item in server.PLANNING_DATA.training_plan().list()
            if item["id"] == plan_id
        )
        self.assertEqual(plan["start_date"], original_date)
        self.assertEqual(plan["end_date"], later_date)

    def test_adaptive_replan_only_changes_future_local_drafts_after_preview(self):
        _, draft, preview = ill_with_vo2_draft_tomorrow()
        self.assertEqual(
            preview["illness_pause"]["recommended_pause_days"],
            planning_adaptive.DEFAULT_ILLNESS_PAUSE_DAYS,
        )
        self.assertEqual(
            preview["illness_pause"]["start_date"],
            server.ATHLETE_CLOCK.now().date().isoformat(),
        )
        self.assertEqual(len(preview["changes"]), 1)
        self.assertEqual(
            server.PLANNING_DATA.planned_unit().list()[0]["description"],
            "- 5m 115%\n- 40m 55%",
        )
        result = server.SYNC_COMMANDS.illness_pause().apply(preview["id"])
        self.assertEqual(result["updated"], 1)
        self.assertEqual(server.PLANNING_DATA.planned_unit().list(), [])
        self.assertTrue(
            server.PLANNING_DATA.planned_unit().list(include_archived=True)[0][
                "archived"
            ]
        )
        self.assertEqual(
            server.PLANNING_DATA.planned_unit().list(include_archived=True)[0][
                "description"
            ],
            "- 5m 115%\n- 40m 55%",
        )
        checkins = {
            row["checkin_date"]: row for row in server.ATHLETE_DATA.checkin().list(30)
        }
        today = server.ATHLETE_CLOCK.now().date()
        self.assertEqual(checkins[today.isoformat()]["illness"], "Fever")
        for offset in range(1, planning_adaptive.DEFAULT_ILLNESS_PAUSE_DAYS):
            self.assertNotIn((today + timedelta(days=offset)).isoformat(), checkins)
        repeated_preview = (
            server.PLANNING_WORKFLOWS.adaptive_replan_preview_service().preview()
        )
        self.assertTrue(repeated_preview["illness_pause"]["approved"])
        self.assertFalse(
            server.PLANNING_WORKFLOWS.adaptive_replan_preview_service().status()[
                "illness_pause_pending"
            ]
        )
        self.assertEqual(
            server.PLANNING_DATA.planned_unit().list(include_archived=True)[0]["id"],
            draft["id"],
        )

    def test_remote_planned_units_import_idempotently_and_record_conflicts(self):
        tomorrow = (server.ATHLETE_CLOCK.now().date() + timedelta(days=1)).isoformat()
        event = {
            "id": "remote-event-1",
            "external_id": "intervals-event-1",
            "category": "WORKOUT",
            "start_date_local": tomorrow + "T07:00:00",
            "type": "Ride",
            "name": "Remote Einheit",
            "description": "- 30m Z2",
            "moving_time": 1800,
        }
        first = remote_reconcilers.planned_reconciler(server).reconcile([event])
        revision_after_import = (
            server.PLANNING_WORKFLOWS.structured_training_state_service().read()[
                "planning_revision"
            ]
        )
        second = remote_reconcilers.planned_reconciler(server).reconcile([event])
        self.assertEqual(
            server.PLANNING_WORKFLOWS.structured_training_state_service().read()[
                "planning_revision"
            ],
            revision_after_import,
        )
        planned = server.PLANNING_DATA.planned_unit().list()
        self.assertEqual(first["imported"], 1)
        self.assertEqual(len(planned), 1)
        self.assertEqual(second["imported"], 0)
        self.assertEqual(planned[0]["remote_event_id"], "remote-event-1")
        server.PLANNING_DATA.planned_unit().update(
            planned[0]["id"], {"action": "update", "name": "Lokal geändert"}
        )
        conflict = remote_reconcilers.planned_reconciler(server).reconcile(
            [{**event, "name": "Remote geändert"}]
        )
        self.assertEqual(conflict["conflicts"], 1)
        self.assertEqual(
            server.PLANNING_DATA.planned_unit().list()[0]["sync_status"], "conflict"
        )

    def test_remote_pull_preserves_local_only_planned_changes(self):
        tomorrow = (server.ATHLETE_CLOCK.now().date() + timedelta(days=1)).isoformat()
        event = {
            "id": "remote-local-only",
            "external_id": "intervals-event-local-only",
            "category": "WORKOUT",
            "start_date_local": tomorrow + "T07:00:00",
            "type": "Ride",
            "name": "Remote Original",
            "description": "- 30m Z2",
            "moving_time": 1800,
        }
        remote_reconcilers.planned_reconciler(server).reconcile([event])
        local = server.PLANNING_DATA.planned_unit().list()[0]
        server.PLANNING_DATA.planned_unit().update(
            local["id"], {"action": "update", "name": "Lokal geändert"}
        )
        result = remote_reconcilers.planned_reconciler(server).reconcile([event])
        current = server.PLANNING_DATA.planned_unit().list()[0]
        self.assertEqual(result["conflicts"], 0)
        self.assertEqual(current["name"], "Lokal geändert")
        self.assertEqual(current["sync_status"], "local")

    def test_remote_planned_import_and_payload_preserve_sport(self):
        tomorrow = (server.ATHLETE_CLOCK.now().date() + timedelta(days=1)).isoformat()
        remote_reconcilers.planned_reconciler(server).reconcile(
            [
                {
                    "id": "remote-run",
                    "category": "WORKOUT",
                    "start_date_local": tomorrow + "T08:00:00",
                    "type": "Run",
                    "name": "Remote Lauf",
                    "moving_time": 1800,
                }
            ]
        )
        imported = server.PLANNING_DATA.planned_unit().list()[0]
        self.assertEqual(imported["type"], "Run")
        self.assertEqual(imported["sport"], "run")
        payload = planning_workouts.workout_event_payload(
            "local-run",
            {
                "date": tomorrow,
                "type": "Run",
                "name": "Lauf",
                "description": "- 30m 60% Easy",
                "duration_minutes": 30,
            },
            today=server.ATHLETE_CLOCK.now().date(),
        )
        self.assertEqual(payload["type"], "Run")

    def test_local_planned_workout_can_be_edited_moved_and_removed(self):
        tomorrow = (server.ATHLETE_CLOCK.now().date() + timedelta(days=1)).isoformat()
        day_after = (server.ATHLETE_CLOCK.now().date() + timedelta(days=2)).isoformat()
        local = server.PLANNING_DATA.planned_unit().create(
            {
                "date": tomorrow,
                "sport": "Ride",
                "name": "Locker",
                "description": "- 30m Z2",
                "duration_minutes": 30,
                "source": "library",
                "rationale": "Test",
            }
        )
        updated = server.PLANNING_DATA.planned_unit().update(
            local["id"],
            {
                "action": "update",
                "date": day_after,
                "name": "Verschoben",
                "description": "- 40m Z2",
                "duration_minutes": 40,
            },
        )
        self.assertEqual(updated["library_entry"]["name"], "Verschoben")
        self.assertEqual(updated["library_entry"]["date"], day_after)
        self.assertEqual(updated["library_entry"]["sync_status"], "local")
        archived = server.PLANNING_DATA.planned_unit().update(
            local["id"], {"action": "archive"}
        )
        self.assertTrue(archived["library_entry"]["archived"])
        restored = server.PLANNING_DATA.planned_unit().update(
            local["id"], {"action": "restore"}
        )
        self.assertFalse(restored["library_entry"]["archived"])
        removed = server.PLANNING_DATA.planned_unit().update(
            local["id"], {"action": "delete"}
        )
        self.assertEqual(removed["status"], "deleted")
        self.assertEqual(server.PLANNING_DATA.planned_unit().list(), [])

    def test_deleting_archived_planned_workout_records_recoverable_history(self):
        local = server.PLANNING_DATA.planned_unit().create(
            {
                "date": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=1)
                ).isoformat(),
                "sport": "Ride",
                "name": "Archived",
                "description": "- 30m Z2",
                "duration_minutes": 30,
                "source": "library",
                "rationale": "Test",
            }
        )
        server.PLANNING_DATA.planned_unit().update(local["id"], {"action": "archive"})

        server.PLANNING_DATA.planned_unit().update(local["id"], {"action": "delete"})

        deletion = next(
            item
            for item in server.HISTORY.change_history_service().list()
            if item["entity_type"] == "planned_unit"
            and item["entity_id"] == local["id"]
            and item["action"] == "delete"
        )
        self.assertNotEqual(deletion["before_hash"], deletion["after_hash"])
        self.assertEqual(deletion["diff"]["fields"]["local_deleted"], {"changed": True})
        server.HISTORY.undo_service().apply(
            {
                "change_id": deletion["id"],
                "expected_current_hash": deletion["after_hash"],
            }
        )
        restored = next(
            item
            for item in server.PLANNING_DATA.planned_unit().list(include_archived=True)
            if item["id"] == local["id"]
        )
        self.assertFalse(restored["archived"])
        self.assertFalse(restored["local_deleted"])

    def test_library_is_cached_and_included_in_coach_context(self):
        imported = remote_reconcilers.library_reconciler(server).reconcile(
            [
                {
                    "id": 42,
                    "name": "Locker Rad",
                    "type": "Ride",
                    "description": "- 45m Z2",
                    "planned_duration_s": 2700,
                }
            ]
        )[0]
        self.assertEqual(uuid.UUID(imported["id"]).version, 4)
        self.assertEqual(imported["external_id"], "42")
        updated = remote_reconcilers.library_reconciler(server).reconcile(
            [
                {
                    "id": 42,
                    "name": "Locker Rad aktualisiert",
                    "type": "Ride",
                    "description": "- 45m Z2",
                    "planned_duration_s": 2700,
                }
            ]
        )[0]
        self.assertEqual(updated["id"], imported["id"])
        self.assertEqual(
            server.PLANNING_DATA.workout_library().list()[0]["name"],
            "Locker Rad aktualisiert",
        )
        self.assertIn(
            "LOCAL TRAINING LIBRARY",
            server.COACH_CONTEXT.training_context_service().build(),
        )

    def test_local_template_and_planned_edit_reject_ambiguous_extension(self):
        with self.assertRaises(AppError):
            server.PLANNING_DATA.workout_library().create_template(
                {
                    "sport": "Run",
                    "description": "- If fresh extend to 8km",
                    "duration_minutes": 40,
                }
            )
        entry = server.PLANNING_WORKFLOWS.local_plan_creation_service().save(
            [
                {
                    "date": (
                        server.ATHLETE_CLOCK.now().date() + timedelta(days=1)
                    ).isoformat(),
                    "sport": "Run",
                    "name": "Recovery",
                    "description": "- 6km Z1 HR",
                    "duration_minutes": 40,
                }
            ]
        )[0]
        with self.assertRaises(AppError):
            server.PLANNING_DATA.planned_unit().update(
                entry["id"], {"description": "- If fresh extend to 8km"}
            )
        self.assertEqual(
            server.PLANNING_DATA.planned_unit().list()[0]["description"], "- 6km Z1 HR"
        )

    def test_unparsed_library_export_keeps_identity_and_retries_as_update(self):
        entry = server.PLANNING_DATA.workout_library().create_local_entry(
            {
                "sport": "Ride",
                "name": "Synthetic",
                "description": "- 30m 85%",
                "duration_minutes": 30,
            }
        )
        with (
            patch.object(
                intervals_client_module.IntervalsClient,
                "get_workout_library",
                return_value=[],
            ),
            patch.object(
                intervals_client_module.IntervalsClient,
                "create_library_workouts",
                return_value=[{"id": "synthetic-remote", "type": "Ride"}],
            ) as create,
            patch.object(
                intervals_client_module.IntervalsClient,
                "update_library_workout",
                return_value={"id": "synthetic-remote", **parsed_workout_fixture()},
            ) as update,
        ):
            with self.assertRaises(AppError) as raised:
                server.WORKOUT_LIBRARY_SYNC.sync_service().sync_entry(entry["id"])
            self.assertEqual(
                raised.exception.reason, "intervals_workout_verification_failed"
            )
            failed = server.PLANNING_DATA.workout_library().list()[0]
            self.assertEqual(failed["sync_status"], "sync_error")
            self.assertEqual(failed["external_id"], "synthetic-remote")
            self.assertEqual(failed["description"], "- 30m 85%")
            synced = server.WORKOUT_LIBRARY_SYNC.sync_service().sync_entry(entry["id"])
            self.assertEqual(synced["sync_status"], "synced")
            create.assert_called_once()
            self.assertEqual(update.call_args.args[0], "synthetic-remote")

    def test_invalid_workout_totals_cannot_be_saved_or_partially_applied(self):
        day = (server.ATHLETE_CLOCK.now().date() + timedelta(days=1)).isoformat()
        valid = {
            "date": day,
            "sport": "Ride",
            "name": "Synthetic",
            "description": "- 30m 85%",
            "duration_minutes": 30,
        }
        later = {
            **valid,
            "date": (server.ATHLETE_CLOCK.now().date() + timedelta(days=2)).isoformat(),
        }
        ambiguous_extension = (
            "Warm-up\n- 8m Gehen und sehr lockeres Einlaufen\n\nMain Set\n"
            "- 6km sehr locker in Zone 1-2, RPE 1-2/10\n"
            "- Nur bei wirklich lockerem Schritt und ohne Beschwerden auf maximal 8km verlaengern\n"
            "- Keine Steigerungen und kein Tempodruck\n\nCooldown\n- 5m Gehen"
        )
        for invalid, message in (
            ({**later, "duration_minutes": 65}, ""),
            (
                {
                    **later,
                    "sport": "Run",
                    "description": ambiguous_extension,
                    "duration_minutes": 50,
                },
                "Zeile 6",
            ),
        ):
            with self.subTest(message=message), self.assertRaises(AppError) as raised:
                server.PLANNING_WORKFLOWS.local_plan_creation_service().save(
                    [valid, invalid]
                )
            self.assertIn(message, str(raised.exception))
            self.assertEqual(server.PLANNING_DATA.planned_unit().list(), [])
        entry = server.PLANNING_WORKFLOWS.local_plan_creation_service().save([valid])[0]
        with self.assertRaises(AppError):
            server.PLANNING_DATA.planned_unit().update(
                entry["id"], {"duration_minutes": 65}
            )
        self.assertEqual(
            server.PLANNING_DATA.planned_unit().list()[0]["duration_minutes"], 30
        )

    def test_missing_library_workout_stays_local_until_approval(self):
        with patch.object(
            server.CONFIG_HOLDER,
            "value",
            replace(server.CONFIG_HOLDER.value, intervals_api_key="test-key"),
        ):
            entry = server.PLANNING_WORKFLOWS.local_plan_creation_service().save(
                [
                    {
                        "date": (
                            server.ATHLETE_CLOCK.now().date() + timedelta(days=1)
                        ).isoformat(),
                        "sport": "Ride",
                        "name": "Coach Tempo",
                        "description": "- 30m 85%",
                        "duration_minutes": 30,
                        "target": "POWER",
                        "rationale": "Schwelle",
                    }
                ]
            )[0]
        self.assertEqual(uuid.UUID(entry["id"]).version, 4)
        planned = server.PLANNING_DATA.planned_unit().list()[0]
        self.assertEqual(planned["id"], entry["id"])
        self.assertIsNone(planned["external_id"])
        self.assertEqual(planned["sync_status"], "local")

    def test_outstanding_plan_drafts_remain_visible_in_openai_conversation(self):
        draft = server.COACH_PLANNING_TOOLS.training_plan_artifact_service().stage(
            {
                "payload": {
                    "plan_name": "Basis",
                    "goal": "Ausdauer",
                    "workouts": [
                        {
                            "date": "2099-01-01",
                            "sport": "Ride",
                            "name": "Basis",
                            "description": "- 30m 60% easy",
                            "duration_minutes": 30,
                        }
                    ],
                }
            },
            conversation_id="openai-conversation",
            client_turn_id="draft-turn",
        )

        with server.database_manager().unit_of_work() as db:
            server.CHAT_REPOSITORY.add(
                db, "user", "Synthetic draft request", client_turn_id="draft-turn"
            )
        refs = server.APP.coach_conversation.dialogue_read_service().artifact_refs()

        self.assertIn(draft["artifact_id"], [item["id"] for item in refs])

    def test_structured_training_changes_accept_complete_bounded_plan_without_remote_write(
        self,
    ):
        for count in (29, coach_limits.COACH_TRAINING_CHANGE_LIMIT):
            with self.subTest(count=count):
                self.setUp()
                planned = [
                    server.PLANNING_DATA.planned_unit().create(
                        {
                            "date": (
                                date(2098, 1, 1) + timedelta(days=index)
                            ).isoformat(),
                            "sport": "Ride",
                            "name": f"Original {index}",
                            "description": "- 30m 60%",
                            "duration_minutes": 30,
                            "target": "AUTO",
                        }
                    )
                    for index in range(count)
                ]
                result = server.PLANNING_WORKFLOWS.structured_training_change_service().apply(
                    {
                        "changes": [
                            {
                                "local_id": item["id"],
                                "action": "update",
                                "name": f"Changed {index}",
                            }
                            for index, item in enumerate(planned)
                        ],
                    }
                )
                self.assertEqual(len(result["changes"]), count)
                self.assertEqual(
                    [
                        item["name"]
                        for item in server.PLANNING_DATA.planned_unit().list(
                            1000, include_archived=True
                        )
                    ],
                    [f"Changed {index}" for index in range(count)],
                )
                with server.database_manager().unit_of_work() as db:
                    self.assertEqual(
                        db.execute(
                            "SELECT COUNT(*) AS count FROM sync_jobs"
                        ).fetchone()["count"],
                        0,
                    )

    def test_structured_training_changes_move_and_create_in_one_atomic_batch(self):
        wednesday = (server.ATHLETE_CLOCK.now().date() + timedelta(days=20)).isoformat()
        tuesday = (server.ATHLETE_CLOCK.now().date() + timedelta(days=19)).isoformat()
        upper_body = server.PLANNING_DATA.planned_unit().create(
            {
                "date": wednesday,
                "sport": "WeightTraining",
                "name": "Oberkörper Einheit",
                "description": "Krafttraining",
                "duration_minutes": 45,
                "target": "AUTO",
            }
        )
        with patch.object(runtime_events.STATE_EVENT_BUFFER, "publish") as publish:
            result = (
                server.PLANNING_WORKFLOWS.structured_training_change_service().apply(
                    {
                        "changes": [
                            {
                                "local_id": upper_body["id"],
                                "action": "update",
                                "date": tuesday,
                            },
                            {
                                "action": "create",
                                "date": wednesday,
                                "sport": "Run",
                                "name": "Lockerer Lauf",
                                "description": "- 30m 60% locker",
                                "duration_minutes": 30,
                                "target": "AUTO",
                                "rationale": "Test",
                            },
                        ],
                    }
                )
            )
        self.assertTrue(
            any(
                call.args == ("planning", {"status": "changed"})
                for call in publish.call_args_list
            )
        )
        self.assertEqual(result["status"], "applied")
        planned = {
            item["name"]: item for item in server.PLANNING_DATA.planned_unit().list()
        }
        self.assertEqual(planned["Oberkörper Einheit"]["date"], tuesday)
        self.assertEqual(planned["Lockerer Lauf"]["date"], wednesday)
        self.assertEqual(len(result["changes"]), 2)

    def test_structured_training_allows_repeated_updates_for_same_unit(self):
        workout = server.PLANNING_DATA.planned_unit().create(
            {
                "date": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=23)
                ).isoformat(),
                "sport": "Run",
                "name": "Repeated update",
                "description": "- 30m 60% easy",
                "duration_minutes": 30,
                "target": "AUTO",
            }
        )
        result = server.PLANNING_WORKFLOWS.structured_training_change_service().apply(
            {
                "changes": [
                    {
                        "local_id": workout["id"],
                        "action": "update",
                        "name": "First update",
                    },
                    {
                        "local_id": workout["id"],
                        "action": "update",
                        "name": "Second update",
                    },
                ],
            }
        )
        self.assertEqual(result["status"], "applied")
        self.assertEqual(
            server.PLANNING_DATA.planned_unit().list()[0]["name"], "Second update"
        )

    def test_structured_training_restore_rechecks_original_calendar_date(self):
        workout = server.PLANNING_DATA.planned_unit().create(
            {
                "date": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=25)
                ).isoformat(),
                "sport": "Run",
                "name": "Restore conflict",
                "description": "- 30m 60% easy",
                "duration_minutes": 30,
                "target": "AUTO",
            }
        )
        server.PLANNING_DATA.planned_unit().update(workout["id"], {"action": "archive"})
        with (
            patch.object(
                calendar_service.CalendarConflictService,
                "conflicts",
                return_value=[{"name": "Occupied"}],
            ) as conflicts,
            self.assertRaises(AppError) as raised,
        ):
            server.PLANNING_WORKFLOWS.structured_training_change_service().apply(
                {
                    "changes": [{"local_id": workout["id"], "action": "restore"}],
                }
            )
        self.assertEqual(raised.exception.reason, "plan_date_conflict")
        conflicts.assert_called_once()

    def test_named_plan_scope_assigns_create_without_unit_reference(self):
        plan_id = "named-create-plan"
        with server.database_manager().unit_of_work() as db:
            server.TRAINING_PLAN_REPOSITORY.create(
                db,
                plan_id,
                "Named create",
                "Build",
                "2099-04-01",
                "2099-04-30",
                "planned",
                runtime_clock.utc_now(),
            )
        intent = {
            "intent": "local_action",
            "operation": "apply_training_changes",
            "target_system": "local",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": ["local_plan_create", f"training_plan:{plan_id}"],
        }
        result = server.COACH_TOOL_DISPATCH.service().execute(
            "apply_training_changes",
            {
                "changes": [
                    {
                        "action": "create",
                        "date": "2099-04-02",
                        "sport": "Run",
                        "name": "Plan addition",
                        "description": "- 20m 60% easy",
                        "duration_minutes": 20,
                        "target": "AUTO",
                        "rationale": "Test",
                    }
                ]
            },
            intent=intent,
            conversation_id="conversation-plan-create",
            client_turn_id="turn-plan-create",
            session_csrf_hash="",
            sync_job_ids=[],
        )
        created = next(
            item
            for item in server.PLANNING_DATA.planned_unit().list()
            if item["id"] == result["library_entry_ids"][0]
        )
        self.assertEqual(created["plan_id"], plan_id)

    def test_mixed_batch_recomputes_each_affected_plan_bounds(self):
        plan_ids = ["mixed-bounds-a", "mixed-bounds-b"]
        with server.database_manager().unit_of_work() as db:
            for index, plan_id in enumerate(plan_ids):
                server.TRAINING_PLAN_REPOSITORY.create(
                    db,
                    plan_id,
                    f"Mixed {index}",
                    "Build",
                    "2099-06-01",
                    "2099-06-30",
                    "planned",
                    runtime_clock.utc_now(),
                )
        units = [
            server.PLANNING_DATA.planned_unit().create(
                {
                    "date": f"2099-06-{10 + index:02d}",
                    "sport": "Run",
                    "name": f"Plan {index}",
                    "description": "- 30m 60% easy",
                    "duration_minutes": 30,
                    "target": "AUTO",
                    "plan_id": plan_id,
                    "plan_name": f"Mixed {index}",
                }
            )
            for index, plan_id in enumerate(plan_ids)
        ]
        server.PLANNING_WORKFLOWS.structured_training_change_service().apply(
            {
                "changes": [
                    {
                        "local_id": units[0]["id"],
                        "action": "update",
                        "date": "2099-06-15",
                    },
                    {
                        "local_id": units[1]["id"],
                        "action": "update",
                        "date": "2099-06-16",
                    },
                ]
            }
        )
        with server.database_manager().unit_of_work() as db:
            plans = [
                server.TRAINING_PLAN_REPOSITORY.get(db, plan_id) for plan_id in plan_ids
            ]
        self.assertEqual(
            [(plan["start_date"], plan["end_date"]) for plan in plans],
            [
                ("2099-06-15", "2099-06-15"),
                ("2099-06-16", "2099-06-16"),
            ],
        )

    def test_structured_training_change_batch_rolls_back_after_old_boundary(self):
        planned = [
            server.PLANNING_DATA.planned_unit().create(
                {
                    "date": (date(2099, 1, 1) + timedelta(days=index)).isoformat(),
                    "sport": "Ride",
                    "name": f"Original {index}",
                    "description": "- 30m 60%",
                    "duration_minutes": 30,
                    "target": "AUTO",
                }
            )
            for index in range(28)
        ]
        with self.assertRaises(AppError) as raised:
            server.PLANNING_WORKFLOWS.structured_training_change_service().apply(
                {
                    "changes": [
                        *[
                            {
                                "local_id": item["id"],
                                "action": "update",
                                "name": f"Changed {index}",
                            }
                            for index, item in enumerate(planned)
                        ],
                        {
                            "local_id": str(uuid.uuid4()),
                            "action": "update",
                            "date": "2099-01-02",
                            "name": "Missing",
                        },
                    ],
                }
            )
        self.assertEqual(raised.exception.status, 404)
        self.assertEqual(
            [
                item["name"]
                for item in server.PLANNING_DATA.planned_unit().list(
                    100, include_archived=True
                )
            ],
            [f"Original {index}" for index in range(28)],
        )

    def test_build_training_context_serializes_local_plans_once_and_reports_projection_budget(
        self,
    ):
        today = server.ATHLETE_CLOCK.now().date()
        server.PLANNING_DATA.planned_unit().create(
            {
                "date": (today + timedelta(days=1)).isoformat(),
                "sport": "Ride",
                "name": "Local plan fixture",
                "description": "- 60m 60%\n\nlong description " + "x" * 20_000,
                "duration_minutes": 60,
                "target": "easy",
                "source": "coach",
            }
        )
        context = server.COACH_CONTEXT.training_context_service().build()
        self.assertEqual(context.count("LOCAL PLANNED WORKOUTS"), 1)
        self.assertEqual(context.count('"local_planned_workouts"'), 1)
        self.assertLessEqual(len(context), coach_context.COACH_CONTEXT_TOTAL_CHAR_LIMIT)
        structured = server.COACH_CONTEXT.structured_context_service().build()
        self.assertIn("local_planned_workouts", structured)
        self.assertIn('"projection"', context)
        self.assertNotIn("long description", context)

    def test_build_training_context_applies_total_budget_deterministically(self):
        with patch(
            "backend.coach.context.CoachStructuredContextService.build",
            return_value={"source_policy": {"untrusted": "x" * 200_000}},
        ):
            first = server.COACH_CONTEXT.training_context_service().build()
            second = server.COACH_CONTEXT.training_context_service().build()
        self.assertEqual(first, second)
        self.assertLessEqual(len(first), coach_context.COACH_CONTEXT_TOTAL_CHAR_LIMIT)

    def test_complete_plan_replace_archives_selected_plan_without_future_units(self):
        past_plan_id = str(uuid.uuid4())
        past = (server.ATHLETE_CLOCK.now().date() - timedelta(days=10)).isoformat()
        with server.database_manager().unit_of_work() as db:
            server.TRAINING_PLAN_REPOSITORY.create(
                db,
                past_plan_id,
                "Past Plan",
                "",
                past,
                past,
                "planned",
                runtime_clock.utc_now(),
            )
        state = server.PLANNING_WORKFLOWS.structured_training_state_service().read()
        intent = {
            "intent": "local_action",
            "operation": "replace_training_plan",
            "target_system": "local",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": [f"training_plan:{past_plan_id}"],
            "follow_up_operations": [],
        }
        result = server.COACH_TOOL_DISPATCH.service().execute(
            "replace_training_plan",
            {
                "expected_revision": state["planning_revision"],
                "payload": {
                    "plan_name": "Past Plan",
                    "goal": "",
                    "workouts": [
                        {
                            "date": (
                                server.ATHLETE_CLOCK.now().date() + timedelta(days=1)
                            ).isoformat(),
                            "sport": "Ride",
                            "name": "New",
                            "description": "- 40m 60% easy",
                            "duration_minutes": 40,
                            "target": "AUTO",
                            "rationale": "Test",
                        },
                    ],
                },
            },
            intent=intent,
            conversation_id="conversation-past-plan",
            client_turn_id="turn-past-plan",
            session_csrf_hash="",
            sync_job_ids=[],
        )
        self.assertEqual(result["status"], "replaced")
        self.assertEqual(
            next(
                plan
                for plan in server.PLANNING_DATA.training_plan().list()
                if plan["id"] == past_plan_id
            )["status"],
            "archived",
        )

    def test_structured_training_reads_expose_complete_bounded_plan(self):
        for index in range(coach_limits.COACH_TRAINING_CHANGE_LIMIT):
            server.PLANNING_DATA.planned_unit().create(
                {
                    "date": (date(2098, 1, 1) + timedelta(days=index)).isoformat(),
                    "sport": "Ride",
                    "name": f"Session {index}",
                    "description": "- 30m 60% easy",
                }
            )
        intent = {
            "intent": "local_action",
            "operation": "read_training_state",
            "target_system": "local",
            "authorization_scope": [],
        }
        state = server.COACH_TOOL_DISPATCH.service().execute(
            "read_training_state",
            {},
            intent=intent,
            conversation_id="read-plan",
            client_turn_id="read-plan",
            session_csrf_hash="",
            sync_job_ids=[],
        )
        self.assertEqual(
            len(state["planned_units"]), coach_limits.COACH_TRAINING_CHANGE_LIMIT
        )
        listed = server.COACH_TOOL_DISPATCH.service().execute(
            "list_planned_workouts",
            {"limit": coach_limits.COACH_TRAINING_CHANGE_LIMIT},
            intent=intent,
            conversation_id="read-plan",
            client_turn_id="read-plan",
            session_csrf_hash="",
            sync_job_ids=[],
        )
        self.assertEqual(len(listed["local"]), coach_limits.COACH_TRAINING_CHANGE_LIMIT)

    def test_bulk_training_changes_require_revision_and_hashes(self):
        planned = server.PLANNING_DATA.planned_unit().create(
            {
                "date": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=1)
                ).isoformat(),
                "sport": "Ride",
                "name": "Bulk target",
                "description": "- 30m 60% easy",
            }
        )
        intent = {
            "intent": "local_action",
            "operation": "apply_training_changes",
            "target_system": "local",
            "authorization_scope": ["local_plan"],
            "bulk_change": True,
        }
        with self.assertRaises(AppError) as raised:
            server.COACH_TOOL_DISPATCH.service().execute(
                "apply_training_changes",
                {"changes": [{"local_id": planned["id"], "action": "update"}]},
                intent=intent,
                conversation_id="bulk-required",
                client_turn_id="bulk-required",
                session_csrf_hash="",
                sync_job_ids=[],
            )
        self.assertEqual(raised.exception.reason, "planning_revision_required")

    def test_bulk_training_changes_validate_final_schedule_before_writes(self):
        first_date = server.ATHLETE_CLOCK.now().date() + timedelta(days=1)
        second_date = server.ATHLETE_CLOCK.now().date() + timedelta(days=2)
        first = server.PLANNING_DATA.planned_unit().create(
            {
                "date": first_date.isoformat(),
                "sport": "Ride",
                "name": "First",
                "description": "- 30m 60% easy",
            }
        )
        second = server.PLANNING_DATA.planned_unit().create(
            {
                "date": second_date.isoformat(),
                "sport": "Ride",
                "name": "Second",
                "description": "- 30m 60% easy",
            }
        )
        state = server.PLANNING_WORKFLOWS.structured_training_state_service().read()
        refs = {item["local_id"]: item for item in state["planned_units"]}
        intent = {
            "intent": "local_action",
            "operation": "apply_training_changes",
            "target_system": "local",
            "authorization_scope": ["local_plan"],
            "bulk_change": True,
        }
        result = server.COACH_TOOL_DISPATCH.service().execute(
            "apply_training_changes",
            {
                "expected_revision": state["planning_revision"],
                "changes": [
                    {
                        "local_id": first["id"],
                        "action": "update",
                        "date": second_date.isoformat(),
                        "expected_payload_hash": refs[first["id"]][
                            "expected_payload_hash"
                        ],
                    },
                    {
                        "local_id": second["id"],
                        "action": "update",
                        "date": first_date.isoformat(),
                        "expected_payload_hash": refs[second["id"]][
                            "expected_payload_hash"
                        ],
                    },
                ],
            },
            intent=intent,
            conversation_id="bulk-rotation",
            client_turn_id="bulk-rotation",
            session_csrf_hash="",
            sync_job_ids=[],
        )
        self.assertEqual(result["status"], "applied")
        current = {
            item["id"]: item["date"]
            for item in server.PLANNING_DATA.planned_unit().list()
        }
        self.assertEqual(current[first["id"]], second_date.isoformat())
        self.assertEqual(current[second["id"]], first_date.isoformat())

    def test_training_patch_rolls_back_existing_updates_when_creation_fails(self):
        existing = server.PLANNING_DATA.planned_unit().create(
            {
                "date": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=4)
                ).isoformat(),
                "sport": "Ride",
                "name": "Before",
                "description": "- 30m 60% easy",
            }
        )
        revision = server.PLANNING_WORKFLOWS.structured_training_state_service().read()[
            "planning_revision"
        ]
        expected_hash = next(
            item["expected_payload_hash"]
            for item in server.PLANNING_WORKFLOWS.structured_training_state_service().read()[
                "planned_units"
            ]
            if item["local_id"] == existing["id"]
        )
        arguments = {
            "expected_revision": revision,
            "changes": [
                {
                    "local_id": existing["id"],
                    "action": "update",
                    "name": "Changed",
                    "expected_payload_hash": expected_hash,
                }
            ],
            "workouts": [
                {
                    "date": (
                        server.ATHLETE_CLOCK.now().date() + timedelta(days=5)
                    ).isoformat(),
                    "sport": "Run",
                    "name": "New",
                    "description": "- 30m 60% easy",
                    "duration_minutes": 30,
                    "target": "AUTO",
                }
            ],
        }
        with (
            patch.object(
                local_plan_creation_service.LocalTrainingPlanCreationService,
                "save",
                side_effect=RuntimeError("creation failed"),
            ),
            self.assertRaises(RuntimeError),
        ):
            server.COACH_PLANNING_TOOLS.training_patch_service().apply(
                arguments,
                {
                    "authorization_scope": ["local_plan"],
                    "request": {"constraints": []},
                },
            )
        current = {
            item["id"]: item for item in server.PLANNING_DATA.planned_unit().list()
        }
        self.assertEqual(current[existing["id"]]["name"], "Before")
        self.assertEqual(len(current), 1)
        self.assertEqual(
            server.PLANNING_WORKFLOWS.structured_training_state_service().read()[
                "planning_revision"
            ],
            revision,
        )

    def test_structured_athlete_context_persists_competitions(self):
        event_date = (
            server.ATHLETE_CLOCK.now().date() + timedelta(days=60)
        ).isoformat()
        profile = server.ATHLETE_DATA.profile().save(
            {
                "name": "Ada",
                "training_background": "Five years of cycling",
                "typical_weekly_volume": "8 hours",
            },
        )
        result = server.PLANNING_DATA.competition().save(
            {
                "name": "Münsterland Giro",
                "event_date": event_date,
                "sport": "Cycling",
                "priority": "A",
                "distance": "125 km",
                "target": "Finish with the front group",
                "course_profile": "Flat and fast",
                "notes": "",
            }
        )
        self.assertEqual(profile["training_background"], "Five years of cycling")
        self.assertEqual(result["competitions"][0]["priority"], "A")
        context = server.COACH_CONTEXT.structured_context_service().build()
        self.assertEqual(context["target_competitions"][0]["name"], "Münsterland Giro")
        self.assertIn("bestätigte", context["source_policy"]["durable_profile"])

    def test_competition_removal_creates_remote_delete_tombstone(self):
        event_date = (
            server.ATHLETE_CLOCK.now().date() + timedelta(days=60)
        ).isoformat()
        saved = server.PLANNING_DATA.competition().save(
            {"name": "Delete Race", "event_date": event_date}
        )
        local_id = saved["competition"]["id"]
        deleted = []
        stored = {}

        class FakeIntervalsClient:
            def fetch_competition_events(self):
                return []

            def upsert_competition_events(self, events):
                saved = [{**events[0], "id": 888}] if events else []
                stored.update({str(event["id"]): event for event in saved})
                return saved

            def get_event(self, event_id):
                return stored[event_id]

            def bulk_delete_events(self, identifiers):
                deleted.extend(identifiers)
                return len(identifiers)

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
            server.PROVIDER_RESYNC.competition_sync_service().sync(
                "test",
            )
            server.PLANNING_DATA.competition().delete(local_id)
            result = server.PROVIDER_RESYNC.competition_sync_service().sync(
                "test",
            )

        self.assertEqual(result["deleted_remote"], 1)
        self.assertEqual(deleted, [{"id": "888"}])
        self.assertEqual(server.PLANNING_DATA.competition().list(), [])
        self.assertNotEqual(local_id, "")

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
        server.ATHLETE_DATA.profile().save({"name": "Ada", "weight_kg": "71"})
        server.ATHLETE_DATA.profile().save({"name": "Bea", "weight_kg": "72"})
        history = server.HISTORY.change_history_service().list()
        latest = next(item for item in history if item["entity_type"] == "profile")
        self.assertEqual(latest["action"], "update")
        self.assertEqual(latest["diff"]["fields"]["name"], {"changed": True})
        self.assertEqual(latest["diff"]["fields"]["weight_kg"], {"changed": True})
        self.assertNotIn("Ada", json.dumps(latest))
        self.assertNotIn('"before"', json.dumps(latest))
        self.assertNotIn('"after"', json.dumps(latest))
        self.assertNotIn("prompt", json.dumps(latest).casefold())
        preview = self.history_preview(latest["id"])
        confirmed = server.COACH_PROPOSALS.confirmation_service().confirm(
            preview["proposed_action"]["id"], "session-csrf-hash"
        )
        result = server.COACH_PROPOSALS.execution_service().execute(
            confirmed["action_token"],
            "session-csrf-hash",
            confirmed["proposed_action"]["payload_hash"],
        )
        self.assertTrue(result["remote_untouched"])
        self.assertEqual(server.ATHLETE_DATA.profile().get()["name"], "Ada")
        with self.assertRaises(AppError) as replay:
            server.HISTORY.undo_service().preview(latest["id"])
        self.assertEqual(replay.exception.status, 409)

    def test_deleted_local_library_entry_can_be_undone_without_provider_write(self):
        entry = server.PLANNING_DATA.workout_library().create_local_entry(
            {
                "name": "Easy",
                "sport": "Ride",
                "duration_minutes": 30,
                "description": "- 30m 60%",
            }
        )
        created = next(
            item
            for item in server.HISTORY.change_history_service().list()
            if item["entity_id"] == entry["id"] and item["action"] == "create"
        )
        preview = self.history_preview(created["id"])
        confirmed = server.COACH_PROPOSALS.confirmation_service().confirm(
            preview["proposed_action"]["id"], "session-csrf-hash"
        )
        result = server.COACH_PROPOSALS.execution_service().execute(
            confirmed["action_token"],
            "session-csrf-hash",
            confirmed["proposed_action"]["payload_hash"],
        )
        self.assertEqual(result["status"], "undone")
        self.assertFalse(
            server.PLANNING_DATA.workout_library().list(include_archived=True)
        )

    def test_structured_competition_push_is_a_queued_job(self):
        competition_intent = {
            "intent": "remote_sync",
            "operation": "sync_competitions",
            "target_system": "intervals",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": ["local_competitions"],
        }
        with patch.object(
            sync_queue.SyncJobQueueService,
            "enqueue",
            side_effect=[{"id": "job-competition"}],
        ) as enqueue:
            with server.database_manager().reader() as db:
                approval_manifest = competition_push_manifest(db)
            competition = server.COACH_TOOL_DISPATCH.service().execute(
                "sync_competitions",
                {"_approval_manifest": approval_manifest},
                intent=competition_intent,
                conversation_id="conversation-jobs",
                client_turn_id="turn-competition",
                session_csrf_hash="",
                sync_job_ids=[],
            )
        self.assertEqual(competition["sync_job_id"], "job-competition")
        self.assertEqual(
            enqueue.call_args_list[0].args[:2], ("intervals", "competition_push")
        )

    def test_planned_unit_undo_rejects_a_new_date_conflict(self):
        old = server.PLANNING_DATA.planned_unit().create(
            {
                "date": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=1)
                ).isoformat(),
                "starts_at_local": (
                    server.ATHLETE_CLOCK.now().date() + timedelta(days=1)
                ).isoformat()
                + "T07:30:00",
                "sport": "Ride",
                "name": "Old",
                "description": "- 30m 60% easy",
            }
        )
        state = server.PLANNING_WORKFLOWS.structured_training_state_service().read()
        intent = {
            "intent": "local_action",
            "operation": "replace_training_plan",
            "target_system": "local",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": ["local_plan"],
            "follow_up_operations": [],
        }
        server.COACH_TOOL_DISPATCH.service().execute(
            "replace_training_plan",
            {
                "expected_revision": state["planning_revision"],
                "payload": {
                    "plan_name": "Conflict Replacement",
                    "goal": "",
                    "workouts": [
                        {
                            "date": old["date"],
                            "starts_at_local": (
                                server.ATHLETE_CLOCK.now().date() + timedelta(days=1)
                            ).isoformat()
                            + "T07:45:00",
                            "sport": "Ride",
                            "name": "New",
                            "description": "- 40m 60% easy",
                            "duration_minutes": 40,
                            "target": "AUTO",
                            "rationale": "Test",
                        },
                    ],
                },
            },
            intent=intent,
            conversation_id="conversation-undo-conflict",
            client_turn_id="turn-undo-conflict",
            session_csrf_hash="",
            sync_job_ids=[],
        )
        deleted_history = next(
            item
            for item in server.HISTORY.change_history_service().list()
            if item["entity_type"] == "planned_unit"
            and item["entity_id"] == old["id"]
            and item["action"] == "delete"
        )
        with self.assertRaises(AppError) as error:
            server.HISTORY.undo_service().apply(
                {
                    "change_id": deleted_history["id"],
                    "expected_current_hash": deleted_history["after_hash"],
                }
            )
        self.assertEqual(error.exception.reason, "plan_date_conflict")


if __name__ == "__main__":
    unittest.main()
