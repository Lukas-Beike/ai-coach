"""Regression tests for explicit local sync-authority decisions."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from backend.db import DatabaseManager, row_factory
from backend.db.repositories import KeyValueRepository, PlanningStateRepository
from backend.planning.revision import PlanningRevisionService
from backend.sync.authority import PlanningAuthorityService
from backend.sync.library import WorkoutLibrarySyncStateService

NOW = "2026-09-20T12:00:00+00:00"


class TestRedactor:
    @staticmethod
    def redact_text(value: str) -> str:
        return value


class PlanningAuthorityServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "authority.db",
            sqlite3,
            row_factory=row_factory,
        )
        self.planning_revision_service = PlanningRevisionService(
            PlanningStateRepository(), lambda: NOW
        )
        self.workout_library_sync_state_service = WorkoutLibrarySyncStateService(
            self.database_manager,
            TestRedactor(),
            KeyValueRepository(lambda: NOW),
            lambda: NOW,
        )
        self.service = PlanningAuthorityService(
            self.database_manager,
            self.workout_library_sync_state_service,
            self.planning_revision_service,
            lambda: NOW,
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE workout_library (id TEXT NOT NULL, local_id TEXT PRIMARY KEY, "
                "external_id TEXT, payload TEXT NOT NULL, sync_dirty INTEGER NOT NULL, "
                "sync_state TEXT NOT NULL, sync_error TEXT, last_synced_at TEXT, "
                "updated_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE planned_units (local_id TEXT PRIMARY KEY, external_id TEXT, "
                "payload TEXT NOT NULL, sync_dirty INTEGER NOT NULL, sync_state TEXT NOT NULL, "
                "sync_error TEXT, sync_conflict TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE planning_state (id INTEGER PRIMARY KEY, revision INTEGER NOT NULL, "
                "updated_at TEXT NOT NULL)"
            )
            db.execute(
                "INSERT INTO planning_state(id, revision, updated_at) VALUES (1, 4, 'old')"
            )
            db.execute(
                "CREATE TABLE competitions (id TEXT PRIMARY KEY, intervals_event_id TEXT, "
                "sync_dirty INTEGER NOT NULL, sync_state TEXT NOT NULL, "
                "sync_conflict TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )

    def tearDown(self) -> None:
        self.database_manager.close()
        self.temporary_directory.cleanup()

    @staticmethod
    def _payload(payload: object) -> str:
        return payload if isinstance(payload, str) else json.dumps(payload)

    def add_planned(
        self,
        local_id: str,
        *,
        state: str = "local",
        payload: object = None,
        dirty: int = 1,
        error: str | None = None,
        conflict: str = "",
        updated_at: str = "old",
    ) -> None:
        if payload is None:
            payload = {"name": local_id}
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(local_id, external_id, payload, sync_dirty, sync_state, "
                "sync_error, sync_conflict, updated_at) VALUES (?, NULL, ?, ?, ?, ?, ?, ?)",
                (
                    local_id,
                    self._payload(payload),
                    dirty,
                    state,
                    error,
                    conflict,
                    updated_at,
                ),
            )

    def planned(self, local_id: str) -> dict[str, object]:
        with self.database_manager.reader() as db:
            return db.execute(
                "SELECT * FROM planned_units WHERE local_id=?", (local_id,)
            ).fetchone()

    def revision(self) -> int:
        with self.database_manager.reader() as db:
            return self.planning_revision_service.read(db)

    def add_competition(
        self,
        competition_id: str,
        *,
        event_id: str | None,
        dirty: int,
        state: str,
        conflict: str = "",
        updated_at: str = "old",
    ) -> None:
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO competitions(id, intervals_event_id, sync_dirty, sync_state, "
                "sync_conflict, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (competition_id, event_id, dirty, state, conflict, updated_at),
            )

    def competition(self, competition_id: str) -> dict[str, object]:
        with self.database_manager.reader() as db:
            return db.execute(
                "SELECT * FROM competitions WHERE id=?", (competition_id,)
            ).fetchone()

    def test_pending_manifest_has_only_required_fields_and_skips_empty_values(
        self,
    ) -> None:
        preview = Mock(
            return_value=(
                {},
                [
                    {
                        "local_id": "plan-1",
                        "payload_hash": "hash-1",
                        "entity": "planned",
                    },
                    {"local_id": "", "payload_hash": "ignored"},
                    {"local_id": "plan-2", "payload_hash": None},
                    {"local_id": None, "payload_hash": "ignored"},
                ],
                "fingerprint",
            )
        )
        self.workout_library_sync_state_service.preview = preview

        result = self.service.pending_plan_push_entries()

        self.assertEqual(
            result,
            [
                {
                    "library_workout_id": "plan-1",
                    "expected_payload_hash": "hash-1",
                }
            ],
        )
        self.assertEqual(
            set(result[0]), {"library_workout_id", "expected_payload_hash"}
        )
        preview.assert_called_once_with()

    def test_missing_or_empty_ids_select_only_open_planning_states(self) -> None:
        self.add_planned("conflict", state="conflict")
        self.add_planned("missing", state="remote_missing")
        self.add_planned("error", state="sync_error")
        self.add_planned("local", state="local")
        self.add_planned("synced", state="synced", dirty=0)

        changed = self.service.mark_planning_authoritative([])

        self.assertEqual(changed, 3)
        self.assertEqual(
            {
                key
                for key in ("conflict", "missing", "error")
                if self.planned(key)["sync_state"] == "local"
            },
            {"conflict", "missing", "error"},
        )
        self.assertEqual(self.planned("local")["updated_at"], "old")
        self.assertEqual(self.planned("synced")["updated_at"], "old")
        self.assertEqual(self.revision(), 5)

    def test_explicit_ids_are_trimmed_and_deduplicated(self) -> None:
        self.add_planned("selected", state="synced", dirty=0)
        self.add_planned("other", state="conflict")

        changed = self.service.mark_planning_authoritative(
            [" selected ", "selected", " selected "]
        )

        self.assertEqual(changed, 1)
        self.assertEqual(self.planned("selected")["sync_state"], "local")
        self.assertEqual(self.planned("other")["sync_state"], "conflict")
        self.assertEqual(self.revision(), 5)

    def test_invalid_json_is_recovered_and_deleted_rows_are_not_marked(self) -> None:
        self.add_planned("invalid", state="conflict", payload="not-json")
        self.add_planned("deleted", state="sync_error", payload={"local_deleted": True})

        changed = self.service.mark_planning_authoritative(["invalid", "deleted"])

        self.assertEqual(changed, 1)
        self.assertEqual(self.planned("invalid")["sync_state"], "local")
        self.assertEqual(json.loads(self.planned("invalid")["payload"]), {"sync_status": "local"})
        self.assertEqual(self.planned("deleted")["sync_state"], "sync_error")
        self.assertEqual(self.revision(), 5)

    def test_revision_bumps_once_per_authority_request_even_for_same_payload(self) -> None:
        self.add_planned("change", state="conflict", payload={"name": "Run"})
        self.add_planned(
            "unchanged",
            payload={"name": "Done", "sync_status": "local"},
            dirty=1,
            updated_at=NOW,
        )

        self.assertEqual(self.service.mark_planning_authoritative(["change"]), 1)
        self.assertEqual(self.revision(), 5)
        self.assertEqual(self.service.mark_planning_authoritative(["change"]), 1)
        self.assertEqual(self.service.mark_planning_authoritative(["unchanged"]), 1)
        self.assertEqual(self.revision(), 7)
        self.assertEqual(
            json.loads(self.planned("change")["payload"])["sync_status"], "local"
        )

    def test_revision_failure_rolls_back_planning_update_atomically(self) -> None:
        self.add_planned("rollback", state="conflict", payload={"name": "Run"})
        with (
            patch.object(
                self.planning_revision_service,
                "bump",
                side_effect=RuntimeError("revision failed"),
            ),
            self.assertRaisesRegex(RuntimeError, "revision failed"),
        ):
            self.service.mark_planning_authoritative(["rollback"])

        row = self.planned("rollback")
        self.assertEqual(row["sync_state"], "conflict")
        self.assertEqual(row["updated_at"], "old")
        self.assertNotIn("sync_status", json.loads(row["payload"]))
        self.assertEqual(self.revision(), 4)

    def test_competitions_preserve_existing_ids_except_for_verified_missing_events(
        self,
    ) -> None:
        self.add_competition("ordinary", event_id="event-1", dirty=1, state="local")
        self.add_competition(
            "missing-state", event_id="event-2", dirty=1, state="remote_missing"
        )
        self.add_competition(
            "missing-conflict",
            event_id="event-3",
            dirty=0,
            state="conflict",
            conflict='{"type":"remote_missing"}',
        )
        self.add_competition(
            "other-conflict",
            event_id="event-4",
            dirty=0,
            state="conflict",
            conflict='{"type":"identity_changed"}',
        )
        self.add_competition("clean", event_id="event-5", dirty=0, state="local")

        changed = self.service.mark_competitions_authoritative()

        self.assertEqual(changed, 4)
        for competition_id in (
            "ordinary",
            "missing-state",
            "missing-conflict",
            "other-conflict",
        ):
            row = self.competition(competition_id)
            self.assertEqual(row["sync_dirty"], 1)
            self.assertEqual(row["sync_state"], "local_override")
            self.assertEqual(row["sync_conflict"], "")
            self.assertEqual(row["updated_at"], NOW)
        self.assertEqual(self.competition("ordinary")["intervals_event_id"], "event-1")
        self.assertIsNone(self.competition("missing-state")["intervals_event_id"])
        self.assertIsNone(self.competition("missing-conflict")["intervals_event_id"])
        self.assertEqual(
            self.competition("other-conflict")["intervals_event_id"], "event-4"
        )
        self.assertEqual(self.competition("clean")["updated_at"], "old")

    def test_competition_updates_share_one_rollback_boundary(self) -> None:
        self.add_competition("first", event_id="event-1", dirty=1, state="local")
        self.add_competition("fail", event_id="event-2", dirty=1, state="local")
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "CREATE TRIGGER reject_competition_update BEFORE UPDATE ON competitions "
                "WHEN OLD.id='fail' BEGIN SELECT RAISE(ABORT, 'reject'); END"
            )

        with self.assertRaises(sqlite3.IntegrityError):
            self.service.mark_competitions_authoritative()

        for competition_id in ("first", "fail"):
            row = self.competition(competition_id)
            self.assertEqual(row["sync_state"], "local")
            self.assertEqual(row["updated_at"], "old")


if __name__ == "__main__":
    unittest.main()
