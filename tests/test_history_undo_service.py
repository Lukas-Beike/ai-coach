"""Tests for the transactional local history undo orchestrator."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from backend import change_history
from backend.db import DatabaseManager, row_factory
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.history.undo_service import HistoryUndoService

_CHANGE_ID = "12345678-1234-1234-1234-123456789abc"
_ENTITY_ID = "entity-1"
_TYPES = (
    "profile",
    "workout_library",
    "competition",
    "planned_unit",
    "training_plan",
)
_STALE_ERROR = (
    "Die lokale Änderung wurde inzwischen weiter geändert; Undo wurde abgebrochen."
)


class _CountingManager:
    def __init__(self, manager):
        self.manager = manager
        self.unit_of_work_count = 0

    @contextmanager
    def unit_of_work(self):
        self.unit_of_work_count += 1
        with self.manager.unit_of_work() as db:
            yield db


class _HistoryService:
    def __init__(self, current=None):
        self.current_value = current or {"id": _ENTITY_ID, "name": "after"}
        self.current_calls = 0
        self.target_calls = 0

    def current(self, _db, entity_type, _entity_id):
        self.current_calls += 1
        try:
            projection = change_history.audit_projection(
                entity_type, self.current_value
            )
        except ValueError:
            projection = {"name": self.current_value.get("name")}
        return self.current_value, projection

    def target(self, row):
        self.target_calls += 1
        return change_history_target(row)


def change_history_target(row):
    fields = json.loads(row["diff"])["fields"]
    if row["action"] == "create":
        return None, None
    target = {
        field: change["before"]
        for field, change in fields.items()
        if "before" in change
    }
    return target, target


class _RestoreService:
    def __init__(self, entity_type, entity_id=_ENTITY_ID, error=None):
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.error = error
        self.calls = []

    def restore_in_transaction(self, db, *args):
        self.calls.append(args)
        db.execute(
            "INSERT INTO undo_effects(entity_type, entity_id) VALUES (?, ?)",
            (self.entity_type, self.entity_id),
        )
        if self.error:
            raise self.error
        return args[-1] if self.entity_type != "planned_unit" else args[-2]


class _RevisionService:
    def __init__(self, error=None):
        self.error = error
        self.calls = 0

    def bump(self, db):
        self.calls += 1
        db.execute(
            "INSERT INTO undo_effects(entity_type, entity_id) VALUES ('revision', 'revision')"
        )
        if self.error:
            raise self.error


class HistoryUndoServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        raw_manager = DatabaseManager(
            Path(self.temporary_directory.name) / "history.sqlite",
            sqlite3,
            row_factory=row_factory,
        )
        with raw_manager.unit_of_work() as db:
            initialize_schema(db)
            db.execute("CREATE TABLE undo_effects(entity_type TEXT, entity_id TEXT)")
        self.raw_manager = raw_manager
        self.manager = _CountingManager(raw_manager)
        self.history = _HistoryService()
        self.services = {
            entity_type: _RestoreService(entity_type) for entity_type in _TYPES
        }
        self.revision = _RevisionService()
        self.service = self._service()

    def tearDown(self):
        self.raw_manager.close()
        self.temporary_directory.cleanup()

    def _service(self, *, history=None, services=None, revision=None):
        services = services or self.services
        return HistoryUndoService(
            self.manager,
            history or self.history,
            services["profile"],
            services["workout_library"],
            services["competition"],
            services["planned_unit"],
            services["training_plan"],
            revision or self.revision,
        )

    def _insert_history(
        self,
        entity_type="profile",
        *,
        action="update",
        history_id=_CHANGE_ID,
        current=None,
        target=None,
    ):
        current = current or {"id": _ENTITY_ID, "name": "after"}
        target = target or {"id": _ENTITY_ID, "name": "before"}
        try:
            current_projection = change_history.audit_projection(entity_type, current)
            target_projection = change_history.audit_projection(entity_type, target)
        except ValueError:
            current_projection = {"name": current.get("name")}
            target_projection = {"name": target.get("name")}
        diff = change_history.audit_diff(target_projection, current_projection)
        if action == "create":
            diff = change_history.audit_diff(None, current_projection)
        row = (
            history_id,
            entity_type,
            _ENTITY_ID,
            action,
            "local",
            "2026-09-20T00:00:00+00:00",
            change_history.audit_hash(target_projection),
            change_history.audit_hash(current_projection),
            json.dumps(diff),
        )
        with self.raw_manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO change_history "
                "(id, entity_type, entity_id, action, source, created_at, "
                "before_hash, after_hash, diff) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row,
            )
        self.history.current_value = current
        return current_projection, target_projection

    def _counts(self):
        with self.raw_manager.reader() as db:
            history_count = db.execute(
                "SELECT COUNT(*) AS count FROM change_history"
            ).fetchone()["count"]
            undo_count = db.execute(
                "SELECT COUNT(*) AS count FROM change_history WHERE action='undo'"
            ).fetchone()["count"]
            effects = db.execute(
                "SELECT entity_type, entity_id FROM undo_effects ORDER BY rowid"
            ).fetchall()
        return (
            history_count,
            undo_count,
            [(row["entity_type"], row["entity_id"]) for row in effects],
        )

    def test_preview_returns_safe_proposal_and_opens_one_uow(self):
        current_projection, target_projection = self._insert_history()
        start_count = self.manager.unit_of_work_count

        result = self.service.preview(f"  {_CHANGE_ID}  ")

        self.assertEqual(self.manager.unit_of_work_count - start_count, 1)
        public = change_history.public_view(
            {
                "id": _CHANGE_ID,
                "entity_type": "profile",
                "entity_id": _ENTITY_ID,
                "action": "update",
                "source": "local",
                "created_at": "2026-09-20T00:00:00+00:00",
                "before_hash": change_history.audit_hash(target_projection),
                "after_hash": change_history.audit_hash(current_projection),
                "diff": json.dumps(
                    change_history.audit_diff(target_projection, current_projection)
                ),
            }
        )
        self.assertEqual(
            result,
            {
                "status": "preview",
                "change": public,
                "undo_target_hash": change_history.audit_hash(target_projection),
                "proposal": {
                    "action_type": "undo_change",
                    "target_system": "local",
                    "object_ids": {"change_id": _CHANGE_ID},
                    "diff": public["diff"],
                    "payload": {
                        "change_id": _CHANGE_ID,
                        "expected_current_hash": change_history.audit_hash(
                            current_projection
                        ),
                    },
                },
            },
        )
        self.assertEqual(self.history.target_calls, 1)
        self.assertEqual(self._counts(), (1, 0, []))

    def test_preview_rejects_changed_current_hash(self):
        self._insert_history()
        self.history.current_value = {"id": _ENTITY_ID, "name": "changed again"}

        with self.assertRaises(AppError) as raised:
            self.service.preview(_CHANGE_ID)

        self.assertEqual(
            (raised.exception.status, raised.exception.message), (409, _STALE_ERROR)
        )
        self.assertEqual(self.history.target_calls, 0)

    def test_apply_dispatches_all_entity_restores_and_records_once(self):
        for entity_type in _TYPES:
            with self.subTest(entity_type=entity_type):
                with self.raw_manager.unit_of_work() as db:
                    db.execute("DELETE FROM change_history")
                    db.execute("DELETE FROM undo_effects")
                self.history = _HistoryService()
                self.services = {
                    current_type: _RestoreService(current_type)
                    for current_type in _TYPES
                }
                self.revision = _RevisionService()
                self.service = self._service()
                action = "delete" if entity_type == "planned_unit" else "update"
                self._insert_history(entity_type, action=action)
                history_count_before, _, _ = self._counts()
                start_count = self.manager.unit_of_work_count
                payload = {
                    "change_id": _CHANGE_ID,
                    "expected_current_hash": change_history.audit_hash(
                        change_history.audit_projection(
                            entity_type, self.history.current_value
                        )
                    ),
                }

                result = self.service.apply(payload)

                self.assertEqual(self.manager.unit_of_work_count - start_count, 1)
                self.assertEqual(
                    result,
                    {
                        "status": "undone",
                        "change_id": _CHANGE_ID,
                        "entity_type": entity_type,
                        "entity_id": _ENTITY_ID,
                        "remote_untouched": True,
                    },
                )
                self.assertEqual(len(self.services[entity_type].calls), 1)
                call = self.services[entity_type].calls[-1]
                if entity_type == "profile":
                    self.assertEqual(
                        call, (self.history.current_value, {"name": "before"})
                    )
                else:
                    self.assertEqual(call[:1], (_ENTITY_ID,))
                    self.assertEqual(
                        call[1:3], (self.history.current_value, {"name": "before"})
                    )
                if entity_type == "planned_unit":
                    self.assertEqual(call[-1], "delete")
                self.assertEqual(
                    self.revision.calls,
                    1 if entity_type in {"planned_unit", "training_plan"} else 0,
                )
                history_count, undo_count, effects = self._counts()
                self.assertEqual(history_count, history_count_before + 1)
                self.assertEqual(undo_count, 1)
                expected_effects = [(entity_type, _ENTITY_ID)]
                if entity_type in {"planned_unit", "training_plan"}:
                    expected_effects.append(("revision", "revision"))
                self.assertEqual(effects, expected_effects)

    def test_apply_rejects_stale_hash_before_domain_restore(self):
        current_projection, _ = self._insert_history()
        changed = {"id": _ENTITY_ID, "name": "changed again"}
        self.history.current_value = changed

        with self.assertRaises(AppError) as raised:
            self.service.apply(
                {
                    "change_id": _CHANGE_ID,
                    "expected_current_hash": change_history.audit_hash(
                        current_projection
                    ),
                }
            )

        self.assertEqual(
            (raised.exception.status, raised.exception.message), (409, _STALE_ERROR)
        )
        self.assertEqual(self.services["profile"].calls, [])

    def test_create_action_applies_with_missing_target(self):
        self._insert_history(action="create")
        expected_hash = change_history.audit_hash(
            change_history.audit_projection("profile", self.history.current_value)
        )

        result = self.service.apply(
            {
                "change_id": _CHANGE_ID,
                "expected_current_hash": expected_hash,
            }
        )

        self.assertEqual(result["status"], "undone")
        self.assertIsNone(self.services["profile"].calls[0][1])
        self.assertEqual(self._counts()[1], 1)

    def test_unknown_entity_is_rejected(self):
        self._insert_history("unknown")

        with self.assertRaises(AppError) as raised:
            self.service.apply(
                {
                    "change_id": _CHANGE_ID,
                    "expected_current_hash": change_history.audit_hash(
                        {"name": "after"}
                    ),
                }
            )

        self.assertEqual(
            (raised.exception.status, raised.exception.message),
            (400, "Unbekannte lokale Änderung."),
        )
        self.assertEqual(self._counts(), (1, 0, []))

    def test_invalid_missing_and_repeated_change_ids_are_rejected(self):
        with self.assertRaises(AppError) as invalid:
            self.service.preview("A" * 36)
        self.assertEqual(
            (invalid.exception.status, invalid.exception.message),
            (400, "Ungültige Änderungshistorie-ID."),
        )
        with self.assertRaises(AppError) as missing:
            self.service.preview(_CHANGE_ID)
        self.assertEqual(
            (missing.exception.status, missing.exception.message),
            (404, "Änderung nicht gefunden."),
        )
        self._insert_history(action="undo")
        with self.assertRaises(AppError) as repeated:
            self.service.apply(
                {
                    "change_id": _CHANGE_ID,
                    "expected_current_hash": "unused",
                }
            )
        self.assertEqual(
            (repeated.exception.status, repeated.exception.message),
            (409, "Eine Undo-Aktion kann nicht erneut zurückgenommen werden."),
        )
        self.assertEqual(self.history.current_calls, 0)

    def test_apply_requires_preview_hash_even_when_current_is_unchanged(self):
        self._insert_history()

        with self.assertRaises(AppError) as raised:
            self.service.apply(
                {"change_id": _CHANGE_ID, "expected_current_hash": "wrong"}
            )

        self.assertEqual(
            (raised.exception.status, raised.exception.message), (409, _STALE_ERROR)
        )
        self.assertEqual(self.services["profile"].calls, [])

    def test_domain_restore_failure_rolls_back_effects(self):
        self._insert_history()
        failing_services = dict(self.services)
        failing_services["profile"] = _RestoreService(
            "profile", error=RuntimeError("restore failed")
        )
        service = self._service(services=failing_services)

        with self.assertRaisesRegex(RuntimeError, "restore failed"):
            service.apply(
                {
                    "change_id": _CHANGE_ID,
                    "expected_current_hash": change_history.audit_hash(
                        change_history.audit_projection(
                            "profile", self.history.current_value
                        )
                    ),
                }
            )

        self.assertEqual(self._counts(), (1, 0, []))

    def test_revision_failure_rolls_back_restore_and_revision(self):
        self._insert_history("planned_unit")
        failing_revision = _RevisionService(RuntimeError("revision failed"))
        service = self._service(revision=failing_revision)

        with self.assertRaisesRegex(RuntimeError, "revision failed"):
            service.apply(
                {
                    "change_id": _CHANGE_ID,
                    "expected_current_hash": change_history.audit_hash(
                        change_history.audit_projection(
                            "planned_unit", self.history.current_value
                        )
                    ),
                }
            )

        self.assertEqual(failing_revision.calls, 1)
        self.assertEqual(self._counts(), (1, 0, []))

    def test_history_failure_rolls_back_restore_and_revision(self):
        self._insert_history("training_plan")

        def fail_after_insert(db, *args, **kwargs):
            db.execute(
                "INSERT INTO change_history "
                "(id, entity_type, entity_id, action, source, created_at, before_hash, after_hash, diff) "
                "VALUES ('undo-row', 'training_plan', 'entity-1', 'undo', 'undo', 'now', 'a', 'b', '{}')"
            )
            raise RuntimeError("history failed")

        with (
            patch(
                "backend.history.undo_service.change_history.record_change",
                side_effect=fail_after_insert,
            ),
            self.assertRaisesRegex(RuntimeError, "history failed"),
        ):
            self.service.apply(
                {
                    "change_id": _CHANGE_ID,
                    "expected_current_hash": change_history.audit_hash(
                        change_history.audit_projection(
                            "training_plan", self.history.current_value
                        )
                    ),
                }
            )

        self.assertEqual(self.revision.calls, 1)
        self.assertEqual(self._counts(), (1, 0, []))


if __name__ == "__main__":
    unittest.main()
