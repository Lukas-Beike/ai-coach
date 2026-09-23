"""Transactional tests for local workout-library use cases."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
import uuid
from copy import deepcopy
from itertools import count
from pathlib import Path
from typing import Any
from unittest.mock import Mock, patch

from backend.db import DatabaseManager, row_factory
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.planning.library_service import WorkoutLibraryService

NOW = "2026-09-20T08:00:00+00:00"


class WorkoutLibraryServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "library.sqlite",
            sqlite3,
            row_factory=row_factory,
        )
        with self.database_manager.unit_of_work() as db:
            initialize_schema(db)
        self._ids = count(1)
        self.publish_change = Mock()
        self.service = WorkoutLibraryService(
            self.database_manager,
            lambda: NOW,
            lambda: str(uuid.UUID(int=next(self._ids))),
            self.publish_change,
        )

    def tearDown(self) -> None:
        self.database_manager.close()
        self.temporary_directory.cleanup()

    @staticmethod
    def _workout(**overrides):
        return {
            "name": "Einheit ä",
            "description": "- 20m Z2 Easy",
            "duration_minutes": 20,
            "sport": "Cycling",
            "target": "AUTO",
            **overrides,
        }

    def _insert_payload(self, row_id: str, payload: str) -> None:
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO workout_library(id, local_id, payload, updated_at) "
                "VALUES (?, ?, ?, ?)",
                (row_id, row_id, payload, NOW),
            )

    def _library_row(self, local_id: str) -> dict[str, Any] | None:
        with self.database_manager.reader() as db:
            row = db.execute(
                "SELECT payload, external_id FROM workout_library WHERE local_id=?",
                (local_id,),
            ).fetchone()
        return dict(row) if row else None

    def test_restore_delete_uses_outer_transaction_without_history(self) -> None:
        local_id = str(uuid.UUID(int=101))
        self._insert_payload(
            local_id,
            json.dumps({"id": local_id, "type": "Ride", "name": "Before"}),
        )
        current = self._library_row(local_id)

        with self.database_manager.unit_of_work() as db:
            result = self.service.restore_in_transaction(db, local_id, current, None)
            self.assertTrue(db.in_transaction)
            self.assertIsNone(
                db.execute(
                    "SELECT local_id FROM workout_library WHERE local_id=?",
                    (local_id,),
                ).fetchone()
            )
            self.assertEqual(
                db.execute("SELECT COUNT(*) AS count FROM change_history").fetchone()[
                    "count"
                ],
                0,
            )

        self.assertIsNone(result)

    def test_restore_recreates_missing_entry_as_local_without_history(self) -> None:
        local_id = str(uuid.UUID(int=102))
        target = {
            "id": local_id,
            "type": "Run",
            "name": "Recreated",
            "moving_time": 1800,
            "sync_status": "synced",
        }

        with self.database_manager.unit_of_work() as db:
            restored = self.service.restore_in_transaction(db, local_id, None, target)
            row = db.execute(
                "SELECT id, local_id, external_id, payload, sync_dirty, sync_state, "
                "updated_at FROM workout_library WHERE local_id=?",
                (local_id,),
            ).fetchone()
            self.assertEqual(
                db.execute("SELECT COUNT(*) AS count FROM change_history").fetchone()[
                    "count"
                ],
                0,
            )

        self.assertEqual(restored["id"], local_id)
        self.assertIsNone(restored["external_id"])
        self.assertEqual(restored["sync_status"], "local")
        self.assertEqual(row["id"], local_id)
        self.assertEqual(row["local_id"], local_id)
        self.assertIsNone(row["external_id"])
        self.assertEqual(row["sync_dirty"], 1)
        self.assertEqual(row["sync_state"], "local")
        self.assertEqual(row["updated_at"], NOW)
        self.assertEqual(json.loads(row["payload"]), restored)

    def test_restore_updates_external_entry_locally_without_history(self) -> None:
        local_id = str(uuid.UUID(int=103))
        self._insert_payload(
            local_id,
            json.dumps({"id": local_id, "type": "Ride", "name": "Current"}),
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE workout_library SET external_id=?, sync_dirty=0, "
                "sync_state='synced', sync_error='old error' WHERE local_id=?",
                ("remote-103", local_id),
            )
        current = self._library_row(local_id)

        with self.database_manager.unit_of_work() as db:
            restored = self.service.restore_in_transaction(
                db, local_id, current, {"name": "Snapshot"}
            )
            row = db.execute(
                "SELECT payload, external_id, sync_dirty, sync_state, sync_error, "
                "updated_at FROM workout_library WHERE local_id=?",
                (local_id,),
            ).fetchone()
            self.assertEqual(
                db.execute("SELECT COUNT(*) AS count FROM change_history").fetchone()[
                    "count"
                ],
                0,
            )

        self.assertEqual(restored["name"], "Snapshot")
        self.assertEqual(restored["external_id"], "remote-103")
        self.assertEqual(restored["sync_status"], "local")
        self.assertEqual(json.loads(row["payload"]), restored)
        self.assertEqual(row["external_id"], "remote-103")
        self.assertEqual(
            (row["sync_dirty"], row["sync_state"], row["sync_error"]),
            (1, "local", None),
        )
        self.assertEqual(row["updated_at"], NOW)

    def test_restore_rejects_corrupt_current_payload_with_conflict(self) -> None:
        for index, payload in enumerate(("{", "null")):
            with self.subTest(payload=payload):
                local_id = str(uuid.UUID(int=104 + index))
                self._insert_payload(local_id, payload)
                current = self._library_row(local_id)

                with (
                    self.assertRaises(AppError) as raised,
                    self.database_manager.unit_of_work() as db,
                ):
                    self.service.restore_in_transaction(
                        db, local_id, current, {"name": "Snapshot"}
                    )

                self.assertEqual(raised.exception.status, 409)
                self.assertEqual(
                    raised.exception.message,
                    "Die Bibliothekseinheit kann nicht wiederhergestellt werden.",
                )
                self.assertEqual(self._library_row(local_id)["payload"], payload)
                with self.database_manager.reader() as db:
                    self.assertEqual(
                        db.execute(
                            "SELECT COUNT(*) AS count FROM change_history"
                        ).fetchone()["count"],
                        0,
                    )
                with self.database_manager.unit_of_work() as db:
                    db.execute(
                        "DELETE FROM workout_library WHERE local_id=?", (local_id,)
                    )

    def test_restore_does_not_mutate_current_or_target(self) -> None:
        local_id = str(uuid.UUID(int=105))
        current = {
            "payload": json.dumps({"id": local_id, "type": "Ride", "name": "Current"}),
            "external_id": "remote-105",
        }
        target = {"name": "Snapshot", "metadata": {"tags": ["easy"]}}
        current_before = deepcopy(current)
        target_before = deepcopy(target)

        with self.database_manager.unit_of_work() as db:
            self.service.restore_in_transaction(db, local_id, current, target)

        self.assertEqual(current, current_before)
        self.assertEqual(target, target_before)

    def test_restore_rolls_back_with_outer_transaction(self) -> None:
        local_id = str(uuid.UUID(int=106))
        self._insert_payload(
            local_id,
            json.dumps({"id": local_id, "type": "Ride", "name": "Before"}),
        )
        original = self._library_row(local_id)
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE workout_library SET sync_dirty=0, sync_state='synced' "
                "WHERE local_id=?",
                (local_id,),
            )
        with self.database_manager.reader() as db:
            original_state = dict(
                db.execute(
                    "SELECT payload, sync_dirty, sync_state, sync_error, updated_at "
                    "FROM workout_library WHERE local_id=?",
                    (local_id,),
                ).fetchone()
            )

        with (
            self.assertRaisesRegex(RuntimeError, "abort outer undo"),
            self.database_manager.unit_of_work() as db,
        ):
            self.service.restore_in_transaction(
                db, local_id, original, {"name": "Restored"}
            )
            raise RuntimeError("abort outer undo")

        with self.database_manager.reader() as db:
            rolled_back = dict(
                db.execute(
                    "SELECT payload, sync_dirty, sync_state, sync_error, updated_at "
                    "FROM workout_library WHERE local_id=?",
                    (local_id,),
                ).fetchone()
            )
            history_count = db.execute(
                "SELECT COUNT(*) AS count FROM change_history"
            ).fetchone()["count"]
        self.assertEqual(rolled_back, original_state)
        self.assertEqual(history_count, 0)

    def test_create_normalizes_inserts_local_sync_state_and_audits(self) -> None:
        entry = self.service.create_local_entry(self._workout())

        self.assertEqual(entry["id"], "00000000-0000-0000-0000-000000000001")
        self.assertEqual(entry["type"], "Ride")
        self.assertEqual(entry["moving_time"], 1200)
        self.assertEqual(entry["sync_status"], "local")
        with self.database_manager.reader() as db:
            row = db.execute(
                "SELECT id, local_id, payload, sync_dirty, sync_state, updated_at "
                "FROM workout_library"
            ).fetchone()
            audit = db.execute(
                "SELECT entity_type, entity_id, action FROM change_history"
            ).fetchone()
        self.assertEqual(row["id"], entry["id"])
        self.assertEqual(row["local_id"], entry["id"])
        self.assertEqual(row["sync_dirty"], 1)
        self.assertEqual(row["sync_state"], "local")
        self.assertEqual(row["updated_at"], NOW)
        self.assertIn("ä", row["payload"])
        self.assertEqual(json.loads(row["payload"]), entry)
        self.assertEqual(
            dict(audit),
            {
                "entity_type": "workout_library",
                "entity_id": entry["id"],
                "action": "create",
            },
        )

    def test_create_uses_ride_fallback_and_rejects_planning_date(self) -> None:
        entry = self.service.create_local_entry(self._workout(sport=None, type="Run"))
        self.assertEqual(entry["type"], "Ride")

        with self.assertRaisesRegex(AppError, "kein Planungsdatum"):
            self.service.create_local_entry(self._workout(date="2026-09-20"))
        self.assertEqual(self.service.list(), [entry])

    def test_external_db_is_used_without_opening_or_committing_a_second_uow(
        self,
    ) -> None:
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        initialize_schema(connection)
        connection.execute("BEGIN")
        manager = Mock()
        manager.unit_of_work.side_effect = AssertionError("unexpected unit of work")
        manager.reader.side_effect = AssertionError("unexpected reader")
        service = WorkoutLibraryService(
            manager, lambda: NOW, lambda: uuid.UUID(int=2), Mock()
        )
        try:
            entry = service.create_local_entry(self._workout(), db=connection)
            listed = service.list(db=connection)

            self.assertEqual(listed, [entry])
            self.assertTrue(connection.in_transaction)
            manager.unit_of_work.assert_not_called()
            manager.reader.assert_not_called()
            connection.rollback()
            self.assertEqual(
                connection.execute("SELECT count(*) FROM workout_library").fetchone()[
                    0
                ],
                0,
            )
            self.assertEqual(
                connection.execute("SELECT count(*) FROM change_history").fetchone()[0],
                0,
            )
        finally:
            connection.close()

    def test_audit_failure_rolls_back_insert(self) -> None:
        with (
            patch(
                "backend.planning.library_service.change_history.record_change",
                side_effect=RuntimeError("audit unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "audit unavailable"),
        ):
            self.service.create_local_entry(self._workout())

        with self.database_manager.reader() as db:
            self.assertEqual(
                db.execute("SELECT count(*) AS count FROM workout_library").fetchone()[
                    "count"
                ],
                0,
            )
            self.assertEqual(
                db.execute("SELECT count(*) AS count FROM change_history").fetchone()[
                    "count"
                ],
                0,
            )

    def test_validation_failure_does_not_persist(self) -> None:
        with self.assertRaises(AppError):
            self.service.create_local_entry(self._workout(description="- 10m Z2 Easy"))
        self.assertEqual(self.service.list(), [])

    def test_template_defaults_and_own_create_use_case(self) -> None:
        with patch(
            "backend.planning.library_service.workouts.validate_workout_description"
        ) as validate:
            entry = self.service.create_template({})

        self.assertEqual(entry["type"], "Ride")
        self.assertEqual(entry["name"], "Coach-Vorlage")
        self.assertEqual(entry["description"], "")
        self.assertEqual(entry["duration_minutes"], 30)
        self.assertEqual(entry["moving_time"], 1800)
        self.assertEqual(entry["target"], "AUTO")
        self.assertEqual(entry["source"], "coach")
        self.assertEqual(self.service.list(), [entry])
        validate.assert_called_once()

    def test_template_duration_sport_object_and_date_validation(self) -> None:
        entry = self.service.create_template(
            {
                "sport": "WeightTraining",
                "duration_minutes": "45",
                "name": "Strength",
                "target": "HR",
            }
        )
        self.assertEqual(entry["type"], "WeightTraining")
        self.assertEqual(entry["duration_minutes"], 45)
        self.assertEqual(entry["moving_time"], 2700)
        self.assertEqual(entry["target"], "HR")
        self.assertEqual(entry["source"], "coach")

        with self.assertRaisesRegex(AppError, "ganze Zahl"):
            self.service.create_template({"duration_minutes": "bad"})
        for duration in (4, 1441):
            with (
                self.subTest(duration=duration),
                self.assertRaisesRegex(AppError, "zwischen 5 und 1440"),
            ):
                self.service.create_template({"duration_minutes": duration})
        with self.assertRaisesRegex(AppError, "Ungueltige Sportart"):
            self.service.create_template({"sport": "Hike"})
        for invalid in (None, [], {"date": "2026-09-20"}):
            with (
                self.subTest(workout=invalid),
                self.assertRaisesRegex(AppError, "Bibliotheksvorlage"),
            ):
                self.service.create_template(invalid)
        self.assertEqual(self.service.list(), [entry])

    def test_list_sorts_filters_archive_and_skips_non_dict_payloads(self) -> None:
        self._insert_payload("z-run", json.dumps({"type": "Run", "name": "Zed"}))
        self._insert_payload("b-ride", json.dumps({"type": "ride", "name": "beta"}))
        self._insert_payload("a-ride", json.dumps({"type": "Ride", "name": "Alpha"}))
        self._insert_payload(
            "archived",
            json.dumps({"type": "Ride", "name": "Old", "archived": True}),
        )
        self._insert_payload(
            "dated", json.dumps({"type": "Ride", "date": "2026-09-20"})
        )
        self._insert_payload("array", "[]")
        self._insert_payload("null", "null")

        active = self.service.list(limit=20)
        all_entries = self.service.list(limit=20, include_archived=True)

        self.assertEqual([entry["name"] for entry in active], ["Alpha", "beta", "Zed"])
        self.assertEqual(
            [entry["name"] for entry in all_entries], ["Alpha", "beta", "Old", "Zed"]
        )

    def test_list_preserves_sqlite_error_for_malformed_json(self) -> None:
        self._insert_payload("malformed", "{")

        with self.assertRaises(sqlite3.OperationalError):
            self.service.list()

    def test_list_clamps_limit_and_doubles_fetch_limit_for_archived_entries(
        self,
    ) -> None:
        with self.database_manager.unit_of_work() as db:
            db.executemany(
                "INSERT INTO workout_library(id, local_id, payload, updated_at) "
                "VALUES (?, ?, ?, ?)",
                [
                    (
                        f"entry-{index:04d}",
                        f"entry-{index:04d}",
                        json.dumps({"type": "Ride", "name": f"Entry {index:04d}"}),
                        NOW,
                    )
                    for index in range(1001)
                ],
            )

        self.assertEqual(len(self.service.list(limit=501)), 501)
        self.assertEqual(len(self.service.list(limit=501, include_archived=True)), 1000)
        self.assertEqual(len(self.service.list(limit=0)), 1)

    def test_update_persists_local_sync_columns_and_history_status_transition(
        self,
    ) -> None:
        entry = self.service.create_local_entry(self._workout())
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE workout_library SET sync_state='synced' WHERE local_id=?",
                (entry["id"],),
            )
        self.publish_change.reset_mock()

        result = self.service.update(entry["id"], {"name": "Aktualisiert"})

        self.assertEqual(result["status"], "local")
        self.assertEqual(result["local_id"], entry["id"])
        self.assertEqual(result["library_entry"]["name"], "Aktualisiert")
        with self.database_manager.reader() as db:
            row = db.execute(
                "SELECT payload, sync_dirty, sync_state, sync_error "
                "FROM workout_library WHERE local_id=?",
                (entry["id"],),
            ).fetchone()
            history = db.execute(
                "SELECT action, diff FROM change_history WHERE entity_id=? "
                "ORDER BY created_at DESC LIMIT 1",
                (entry["id"],),
            ).fetchone()
        self.assertEqual(
            (row["sync_dirty"], row["sync_state"], row["sync_error"]),
            (1, "local", None),
        )
        self.assertEqual(json.loads(row["payload"]), result["library_entry"])
        self.assertEqual(history["action"], "update")
        diff = json.loads(history["diff"])
        self.assertEqual(
            diff["fields"]["name"], {"before": "Einheit ä", "after": "Aktualisiert"}
        )
        self.assertEqual(
            diff["fields"]["sync_status"], {"before": "synced", "after": "local"}
        )
        self.publish_change.assert_called_once_with()

    def test_archive_and_restore_update_payload_sync_state_and_history(self) -> None:
        entry = self.service.create_local_entry(self._workout())
        self.publish_change.reset_mock()

        archived = self.service.update(entry["id"], {"action": " ARCHIVE "})
        restored = self.service.update(entry["id"], {"action": "RESTORE"})

        self.assertTrue(archived["library_entry"]["archived"])
        self.assertFalse(restored["library_entry"]["archived"])
        self.assertEqual(self.publish_change.call_count, 2)
        with self.database_manager.reader() as db:
            rows = db.execute(
                "SELECT payload, sync_dirty, sync_state, sync_error "
                "FROM workout_library WHERE local_id=?",
                (entry["id"],),
            ).fetchall()
            history = db.execute(
                "SELECT diff FROM change_history WHERE entity_id=? AND action='update' "
                "ORDER BY created_at",
                (entry["id"],),
            ).fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(
            (rows[0]["sync_dirty"], rows[0]["sync_state"], rows[0]["sync_error"]),
            (1, "local", None),
        )
        self.assertFalse(json.loads(rows[0]["payload"])["archived"])
        self.assertEqual(len(history), 2)
        archive_diff, restore_diff = [json.loads(row["diff"]) for row in history]
        self.assertEqual(
            archive_diff["fields"]["archived"], {"before": False, "after": True}
        )
        self.assertEqual(
            restore_diff["fields"]["archived"], {"before": True, "after": False}
        )

    def test_delete_is_physical_and_records_before_history_after_commit(self) -> None:
        entry = self.service.create_local_entry(self._workout())
        self.publish_change.reset_mock()
        observed = []

        def observe_committed_delete() -> None:
            with self.database_manager.reader() as db:
                row = db.execute(
                    "SELECT count(*) AS count FROM workout_library WHERE local_id=?",
                    (entry["id"],),
                ).fetchone()
                history = db.execute(
                    "SELECT count(*) AS count FROM change_history WHERE entity_id=? AND action='delete'",
                    (entry["id"],),
                ).fetchone()
            observed.append((row["count"], history["count"]))

        self.publish_change.side_effect = observe_committed_delete
        result = self.service.update(entry["id"], {"action": "delete"})

        self.assertEqual(result, {"status": "deleted", "local_id": entry["id"]})
        self.assertEqual(observed, [(0, 1)])
        self.publish_change.assert_called_once_with()
        with self.database_manager.reader() as db:
            history = db.execute(
                "SELECT diff FROM change_history WHERE entity_id=? AND action='delete'",
                (entry["id"],),
            ).fetchone()
        diff = json.loads(history["diff"])
        self.assertTrue(diff["before_present"])
        self.assertFalse(diff["after_present"])
        self.assertEqual(diff["fields"]["sync_status"]["before"], "local")

    def test_synchronized_entry_cannot_be_deleted_but_can_be_archived(self) -> None:
        local_id = str(uuid.UUID(int=80))
        self._insert_payload(
            local_id,
            json.dumps({"id": local_id, "type": "Ride", "name": "Remote"}),
        )
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE workout_library SET external_id=?, sync_state='synced' WHERE local_id=?",
                ("remote-80", local_id),
            )
        self.publish_change.reset_mock()

        with self.assertRaisesRegex(AppError, "Archiviere sie stattdessen") as raised:
            self.service.update(local_id, {"action": "delete"})

        self.assertEqual(raised.exception.status, 409)
        self.publish_change.assert_not_called()
        archived = self.service.update(local_id, {"action": "archive"})
        self.assertTrue(archived["library_entry"]["archived"])
        self.assertEqual(archived["library_entry"]["sync_status"], "local")
        with self.database_manager.reader() as db:
            row = db.execute(
                "SELECT external_id, sync_dirty, sync_state, sync_error "
                "FROM workout_library WHERE local_id=?",
                (local_id,),
            ).fetchone()
            history = db.execute(
                "SELECT diff FROM change_history WHERE entity_id=? AND action='update'",
                (local_id,),
            ).fetchone()
        self.assertEqual(row["external_id"], "remote-80")
        self.assertEqual(
            (row["sync_dirty"], row["sync_state"], row["sync_error"]),
            (1, "local", None),
        )
        self.assertEqual(
            json.loads(history["diff"])["fields"]["sync_status"],
            {"before": "synced", "after": "local"},
        )
        self.publish_change.assert_called_once_with()

    def test_update_rejects_non_dict_values(self) -> None:
        with self.assertRaisesRegex(AppError, "als Objekt gesendet") as raised:
            self.service.update(str(uuid.UUID(int=1)), [])

        self.assertEqual(raised.exception.status, 400)
        self.publish_change.assert_not_called()

    def test_update_missing_corrupt_and_dated_rows_preserve_errors_and_state(
        self,
    ) -> None:
        missing_id = str(uuid.UUID(int=90))
        corrupt_id = str(uuid.UUID(int=91))
        non_object_id = str(uuid.UUID(int=93))
        dated_id = str(uuid.UUID(int=92))
        self._insert_payload(corrupt_id, "{")
        self._insert_payload(non_object_id, "[]")
        self._insert_payload(
            dated_id,
            json.dumps({"id": dated_id, "type": "Ride", "date": "2026-09-20"}),
        )
        self.publish_change.reset_mock()

        cases = (
            (missing_id, 404, "Bibliothekseinheit nicht gefunden"),
            (corrupt_id, 500, "Bibliothekseinheit ist beschädigt"),
            (non_object_id, 500, "Bibliothekseinheit ist beschädigt"),
            (dated_id, 409, "im Kalender bearbeitet"),
        )
        for local_id, status, message in cases:
            with self.subTest(local_id=local_id):
                with self.assertRaisesRegex(AppError, message) as raised:
                    self.service.update(local_id, {"name": "changed"})
                self.assertEqual(raised.exception.status, status)
        self.publish_change.assert_not_called()
        with self.database_manager.reader() as db:
            row = db.execute(
                "SELECT payload FROM workout_library WHERE local_id=?", (dated_id,)
            ).fetchone()
        self.assertEqual(json.loads(row["payload"])["date"], "2026-09-20")

    def test_audit_failure_rolls_back_update_and_suppresses_event(self) -> None:
        entry = self.service.create_local_entry(self._workout())
        self.publish_change.reset_mock()

        with (
            patch(
                "backend.planning.library_service.change_history.record_change",
                side_effect=RuntimeError("audit unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "audit unavailable"),
        ):
            self.service.update(entry["id"], {"name": "Should roll back"})

        with self.database_manager.reader() as db:
            row = db.execute(
                "SELECT payload, sync_dirty, sync_state, sync_error "
                "FROM workout_library WHERE local_id=?",
                (entry["id"],),
            ).fetchone()
            history_count = db.execute(
                "SELECT count(*) AS count FROM change_history WHERE entity_id=?",
                (entry["id"],),
            ).fetchone()["count"]
        self.assertEqual(json.loads(row["payload"])["name"], "Einheit ä")
        self.assertEqual(
            (row["sync_dirty"], row["sync_state"], row["sync_error"]),
            (1, "local", None),
        )
        self.assertEqual(history_count, 1)
        self.publish_change.assert_not_called()


if __name__ == "__main__":
    unittest.main()
