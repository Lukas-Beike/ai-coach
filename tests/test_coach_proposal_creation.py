"""Tests for session-owned Coach action proposal creation."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import unittest
from typing import Any
from unittest.mock import Mock
from uuid import UUID

from support import temp_database

from backend.coach import proposal_creation
from backend.coach.proposal_creation import (
    CoachProposalCreationService,
    remote_removal_lines,
)
from backend.coach.proposal_models import COACH_ACTION_TTL_SECONDS, coach_action_hash
from backend.db import row_factory
from backend.db.repositories import CompetitionRepository
from backend.errors import AppError
from backend.planning.planned_units import plan_push_payload_hash

_LOCAL_IDS = {"act_wahoo": "wahoo-1", "act_garmin": "garmin-1"}


class _LocalIds:
    def resolve(self, reference: object) -> object:
        if not isinstance(reference, str):
            return reference
        return _LOCAL_IDS.get(reference, reference)

    def local_ids(self, provider_activity_ids: object) -> dict[str, str]:
        return {}


class CoachProposalCreationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database_manager = temp_database(
            self, "coach-proposals.sqlite", row_factory=row_factory, schema=True
        )

    def _service(self, **overrides: Any) -> CoachProposalCreationService:
        options: dict[str, Any] = {
            "now": lambda: 100.0,
            "utc_now": lambda: "2026-09-23T10:11:12+00:00",
            "uuid_factory": lambda: UUID("abc12345-6789-4abc-8def-0123456789ab"),
        }
        options.update(overrides)
        return CoachProposalCreationService(
            self.database_manager,
            **options,
        )

    def _undo(self) -> dict[str, object]:
        return {
            "action_type": "undo_change",
            "target_system": "local",
            "object_ids": ["change-1"],
            "diff": [{"type": "restore", "label": "Änderung"}],
            "payload": {"change_id": "change-1", "secret": "private"},
        }

    def _rows(self) -> list[dict[str, object]]:
        with self.database_manager.reader() as db:
            return db.execute("SELECT * FROM coach_action_proposals").fetchall()

    def test_creation_prunes_expired_proposals_on_the_write_path(self) -> None:
        with self.database_manager.unit_of_work() as db:
            for proposal_id, expires_at in (("expired", 100), ("live", 101)):
                db.execute(
                    "INSERT INTO coach_action_proposals "
                    "(id, session_csrf_hash, action_type, target_system, object_ids, "
                    "diff, payload, payload_hash, status, expires_at, created_at) "
                    "VALUES (?, 's', 'undo_change', 'local', '[]', '[]', '{}', 'h', "
                    "'preview', ?, '2026-09-23T00:00:00Z')",
                    (proposal_id, expires_at),
                )

        self._service().create(self._undo(), "session-csrf-hash")

        self.assertEqual(
            sorted(row["id"] for row in self._rows()),
            ["abc12345-6789-4abc-8def-0123456789ab", "live"],
        )

    def test_competition_remote_write_binds_dirty_rows_and_tombstones_to_approval(
        self,
    ) -> None:
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO competitions (id, name, event_date, sport, priority, distance, target, "
                "course_profile, notes, created_at, updated_at) "
                "VALUES ('race-1', 'Race', '2026-10-01', 'Run', 'A', '', '', '', '', 'now', 'now')"
            )
            db.execute(
                "INSERT INTO competition_sync_tombstones (id, intervals_event_id, external_id, created_at) "
                "VALUES ('deleted-1', 'remote-1', NULL, 'now')"
            )
        intent = {
            "operation": "sync_competitions",
            "intent": "remote_sync",
            "target_system": "intervals",
            "authorization_scope": ["local_competitions", "intervals_sync"],
            "request": {"remote_write": True, "source_message_ids": [7]},
        }

        result = self._service().create_remote_write(
            "sync_competitions",
            {"reason": "approved request"},
            intent,
            conversation_id="conversation-1",
            client_turn_id="turn-1",
            session_csrf_hash="session-1",
        )

        payload = json.loads(str(self._rows()[0]["payload"]))
        manifest = payload["arguments"]["_approval_manifest"]
        self.assertEqual(
            {(item["type"], item["id"]) for item in manifest},
            {("competition", "race-1"), ("tombstone", "deleted-1")},
        )
        self.assertTrue(all(len(item["sha256"]) == 64 for item in manifest))
        self.assertEqual(
            result["proposed_action"]["diff"],
            [
                {"name": "Race", "date": "2026-10-01", "sport": "Run", "id": "race-1"},
                {
                    "name": "Remote-Wettkampfeintrag löschen",
                    "date": "Freigegebene Löschmarkierung",
                    "id": "remote-1",
                },
            ],
        )

    def test_competition_tombstone_card_names_the_deleted_race(self) -> None:
        with self.database_manager.unit_of_work() as db:
            CompetitionRepository().add_tombstone(
                db,
                "deleted-1",
                "remote-1",
                None,
                "now",
                name="Frühjahrsklassiker",
                event_date="2026-04-12",
            )
        intent = {
            "operation": "sync_competitions",
            "intent": "remote_sync",
            "target_system": "intervals",
            "authorization_scope": ["local_competitions", "intervals_sync"],
            "request": {"remote_write": True, "source_message_ids": [7]},
        }

        result = self._service().create_remote_write(
            "sync_competitions",
            {"reason": "approved request"},
            intent,
            conversation_id="conversation-1",
            client_turn_id="turn-1",
            session_csrf_hash="session-1",
        )

        self.assertEqual(
            result["proposed_action"]["diff"],
            [
                {
                    "name": "Frühjahrsklassiker",
                    "date": "2026-04-12",
                    "sport": "Wird bei Intervals.icu entfernt",
                    "id": "remote-1",
                }
            ],
        )
        # Without a card the receipt names the same deletion (#2342).
        self.assertEqual(
            remote_removal_lines(result["proposed_action"]["diff"]),
            ["Wird bei Intervals.icu entfernt: Frühjahrsklassiker 2026-04-12"],
        )
        # A deletion marker gone or changed before approval reads German (#2134).
        with self.database_manager.reader() as db:
            for item in (
                {"type": "tombstone", "id": "missing", "sha256": "0" * 64},
                {"type": "tombstone", "id": "deleted-1", "sha256": "0" * 64},
            ):
                with self.subTest(id=item["id"]), self.assertRaises(AppError) as raised:
                    proposal_creation._competition_detail(db, item)
                self.assertEqual(
                    (raised.exception.status, raised.exception.message),
                    (409, "Der Wettkampfbestand hat sich vor der Freigabe geändert."),
                )

    def _stored_preview(self, **pause: Any) -> None:
        payload = {
            "changes": [{"library_workout_id": "unit-1"}, {"library_workout_id": "u2"}],
            "illness_pause": {
                "illness": "Synthetic cold",
                "start_date": "2026-09-23",
                "end_date": "2026-09-27",
                **pause,
            },
        }
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO plan_adjustments (id, payload, status, created_at) "
                "VALUES ('adjustment-1', ?, 'preview', '2026-09-23T10:00:00+00:00')",
                (json.dumps(payload),),
            )

    def _illness_sync(self, **arguments: Any) -> dict[str, Any]:
        intent = {
            "operation": "apply_adaptive_replan",
            "intent": "remote_sync",
            "target_system": "intervals",
            "authorization_scope": ["adaptive_replan:adjustment-1", "intervals_sync"],
            "request": {"remote_write": True, "source_message_ids": [7]},
        }
        return self._service().create_remote_write(
            "apply_adaptive_replan",
            {"adjustment_id": "adjustment-1", "sync_illness_to_intervals": True}
            | arguments,
            intent,
            conversation_id="conversation-1",
            client_turn_id="turn-1",
            session_csrf_hash="session-1",
        )

    def test_illness_sync_proposal_is_built_from_the_stored_preview(self) -> None:
        self._stored_preview()
        result = self._illness_sync(
            illness_pause={"start_date": "2030-01-01", "end_date": "2030-12-31"},
            changes=[{"library_workout_id": "other"}],
            sync_all=True,
        )

        stored = json.loads(str(self._rows()[0]["payload"]))["arguments"]
        self.assertEqual(
            stored,
            {
                "adjustment_id": "adjustment-1",
                "sync_illness_to_intervals": True,
                "_approval_manifest": {
                    "adjustment_id": "adjustment-1",
                    "changes": 2,
                    "illness_pause": {
                        "start_date": "2026-09-23",
                        "end_date": "2026-09-27",
                    },
                },
            },
        )
        shown = json.dumps(result["proposed_action"]["diff"])
        self.assertIn("2026-09-23", shown)
        self.assertIn("2026-09-27", shown)
        self.assertNotIn("2030", shown)

    def test_illness_sync_proposal_rejects_a_preview_that_is_not_the_latest(
        self,
    ) -> None:
        self._stored_preview()
        with self.assertRaises(AppError) as raised:
            self._illness_sync(adjustment_id="adjustment-older")
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self._rows(), [])

    def test_illness_sync_proposal_needs_a_pending_pause_in_the_preview(
        self,
    ) -> None:
        self._stored_preview(approved=True)
        with self.assertRaises(AppError) as raised:
            self._illness_sync()
        self.assertEqual(raised.exception.status, 409)
        self.assertEqual(self._rows(), [])

    def test_plan_approval_shows_each_concrete_workout(self) -> None:
        raw_payload = json.dumps(
            {"name": "Tempo ride", "date": "2026-10-02", "sport": "Ride"}
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(id, local_id, payload, created_at, updated_at) "
                "VALUES ('11111111-1111-4111-8111-111111111111', '11111111-1111-4111-8111-111111111111', ?, 'now', 'now')",
                (raw_payload,),
            )
        intent = {
            "operation": "start_intervals_plan_sync",
            "intent": "remote_sync",
            "target_system": "intervals",
            "authorization_scope": ["intervals_sync"],
            "request": {
                "remote_write": True,
                "source_message_ids": [7],
                "sync_scope": "selected",
            },
        }
        result = self._service().create_remote_write(
            "start_intervals_plan_sync",
            {
                "entries": [
                    {
                        "library_workout_id": "11111111-1111-4111-8111-111111111111",
                        "expected_payload_hash": hashlib.sha256(
                            raw_payload.encode()
                        ).hexdigest(),
                    }
                ]
            },
            intent,
            conversation_id="conversation-1",
            client_turn_id="turn-1",
            session_csrf_hash="session-1",
        )
        self.assertEqual(
            result["proposed_action"]["diff"],
            [
                {
                    "name": "Tempo ride",
                    "date": "2026-10-02",
                    "sport": "Ride",
                    "id": "11111111-1111-4111-8111-111111111111",
                }
            ],
        )
        stored = json.loads(str(self._rows()[0]["payload"]))["intent"]
        self.assertEqual(
            ["intervals_sync", "planned_unit:11111111-1111-4111-8111-111111111111"],
            stored["authorization_scope"],
        )
        self.assertEqual(["intervals_sync"], intent["authorization_scope"])

    def test_all_pending_plan_approval_freezes_and_displays_pending_entries(
        self,
    ) -> None:
        raw_payload = json.dumps(
            {"name": "Recovery run", "date": "2999-10-03", "sport": "Run"}
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(id, local_id, payload, created_at, updated_at) "
                "VALUES ('unit-2', 'unit-2', ?, 'now', 'now')",
                (raw_payload,),
            )
        intent = {
            "operation": "start_intervals_plan_sync",
            "intent": "remote_sync",
            "target_system": "intervals",
            "authorization_scope": ["intervals_sync"],
            "request": {
                "remote_write": True,
                "source_message_ids": [8],
                "sync_scope": "all_pending",
            },
            "_sync_all_pending": True,
        }
        result = self._service().create_remote_write(
            "start_intervals_plan_sync",
            {},
            intent,
            conversation_id="conversation-1",
            client_turn_id="turn-2",
            session_csrf_hash="session-2",
        )
        payload = json.loads(str(self._rows()[0]["payload"]))
        self.assertEqual(
            payload["arguments"]["entries"],
            [
                {
                    "library_workout_id": "unit-2",
                    "expected_payload_hash": plan_push_payload_hash(raw_payload),
                },
            ],
        )
        self.assertEqual(
            result["proposed_action"]["diff"],
            [
                {
                    "name": "Recovery run",
                    "date": "2999-10-03",
                    "sport": "Run",
                    "id": "unit-2",
                },
            ],
        )

    def test_nutrition_remote_write_freezes_dates_revisions_and_aggregates(
        self,
    ) -> None:
        nutrition = Mock()
        manifest = [
            {
                "date": "2026-09-24",
                "revision": 4,
                "total_kcal": 2200,
                "total_carbs_g": 250.0,
                "total_protein_g": 130.0,
                "total_fat_g": 65.0,
                "entry_count": 3,
                "sha256": "a" * 64,
            }
        ]
        nutrition.sync_status.approval_manifest.return_value = manifest
        intent = {
            "operation": "sync_nutrition",
            "intent": "remote_sync",
            "target_system": "intervals",
            "authorization_scope": ["local_nutrition", "intervals_sync"],
            "request": {"remote_write": True, "source_message_ids": [7]},
        }
        self._service(nutrition_diary_service=lambda: nutrition).create_remote_write(
            "sync_nutrition",
            {"pending_limit": 3},
            intent,
            conversation_id="conversation-1",
            client_turn_id="turn-1",
            session_csrf_hash="session-1",
        )
        payload = json.loads(str(self._rows()[0]["payload"]))
        self.assertEqual(payload["arguments"]["_approval_manifest"], manifest)
        self.assertEqual(
            payload["arguments"],
            {
                "pending_limit": 3,
                "_approval_manifest": manifest,
            },
        )
        self.assertEqual(
            nutrition.sync_status.approval_manifest.call_args.kwargs,
            {"pending_limit": 3},
        )

    def test_distinct_session_keys_own_distinct_proposals(self) -> None:
        self._service().create(self._undo(), "session-a")
        other_id = UUID("def12345-6789-4abc-8def-0123456789ab")
        self._service(uuid_factory=lambda: other_id).create(self._undo(), "session-b")

        self.assertEqual(
            {row["session_csrf_hash"] for row in self._rows()},
            {"session-a", "session-b"},
        )

    def test_database_failure_rolls_back_insert(self) -> None:
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TRIGGER reject_proposal BEFORE INSERT ON coach_action_proposals "
                "BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self._service().create(self._undo(), "session")

        self.assertEqual(self._rows(), [])

    def test_undo_creation_persists_session_ttl_hash_and_safe_view(self) -> None:
        payload = self._undo()["payload"]
        result = self._service().create(self._undo(), "session-csrf-hash")

        self.assertEqual(COACH_ACTION_TTL_SECONDS, 600)
        self.assertEqual(result["status"], "preview")
        self.assertEqual(
            result["proposed_action"],
            {
                "id": "abc12345-6789-4abc-8def-0123456789ab",
                "action_type": "undo_change",
                "target_system": "local",
                "object_ids": ["change-1"],
                "diff": [{"type": "restore", "label": "Änderung"}],
                "payload_hash": coach_action_hash(payload),
                "expires_at": 100 + COACH_ACTION_TTL_SECONDS,
                "status": "preview",
            },
        )
        self.assertNotIn("payload", result["proposed_action"])
        row = self._rows()[0]
        self.assertEqual(row["session_csrf_hash"], "session-csrf-hash")
        expected_hash = hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                ensure_ascii=False,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(row["payload_hash"], expected_hash)
        self.assertEqual(row["payload"], '{"change_id":"change-1","secret":"private"}')
        self.assertEqual(row["diff"], '[{"type":"restore","label":"Änderung"}]')
        self.assertEqual(row["created_at"], "2026-09-23T10:11:12+00:00")
        self.assertNotIn("private", repr(result))

    def test_invalid_inputs_reject_before_inspection_or_insert(self) -> None:
        invalid_values = [
            None,
            {},
            {**self._undo(), "diff": []},
            {**self._undo(), "target_system": "intervals"},
        ]
        for values in invalid_values:
            with self.subTest(values=values), self.assertRaises(AppError):
                self._service().create(values, "session")

        self.assertEqual(self._rows(), [])


if __name__ == "__main__":
    unittest.main()
