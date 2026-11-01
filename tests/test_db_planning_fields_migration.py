"""Schema version 16: provider-neutral planning field names, upgraded in place.

Populated v15 and v9 databases hold synthetic planning records under the former
Intervals.icu field names. The upgrade renames them in every stored planning
record and keeps ids, values, row counts and audit history; a failure rolls back
to the unchanged release, a restart changes nothing, undo of a change recorded
before the upgrade still works, and a recorded remote baseline still matches.
Temporary databases and synthetic rows only.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import threading
import unittest
import uuid
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from legacy_planning_fixture import (
    rename_planning_fields,
    rename_planning_fields_in_database,
)

from backend import change_history
from backend.backup.restore_validation import (
    DatabaseRestoreValidationConfig,
    DatabaseRestoreValidationService,
)
from backend.db import DatabaseManager, row_factory
from backend.db.migrations import migrate_schema
from backend.db.repositories import CompetitionRepository, PlanningStateRepository
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    database_schema_is_current,
)
from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService
from backend.planning import planned_units
from backend.planning.calendar_service import CalendarConflictService
from backend.planning.competition_service import CompetitionService
from backend.planning.planned_unit_service import PlannedUnitService
from backend.planning.revision import PlanningRevisionService
from backend.providers.intervals_workouts import (
    intervals_fields_from_planning,
    planning_fields_from_intervals,
)

FIXTURES = Path(__file__).with_name("fixtures")
V9_FIXTURE = FIXTURES / "schema_v9.sql.txt"
V15_FIXTURE = FIXTURES / "schema_v15.sql.txt"
STAMP = "2026-10-30T08:00:00+00:00"
TODAY = date(2026, 10, 30)

REMOTE_UNIT = "00000000-0000-4000-8000-000000000001"
LOCAL_UNIT = "00000000-0000-4000-8000-000000000002"
LIST_UNIT = "00000000-0000-4000-8000-000000000003"
LIBRARY_ENTRY = "00000000-0000-4000-8000-000000000011"
LIBRARY_TEXT_ONLY = "00000000-0000-4000-8000-000000000012"
COMPETITION = "00000000-0000-4000-8000-000000000021"
COMPETITION_EMPTY = "00000000-0000-4000-8000-000000000022"
UNIT_CHANGE = "00000000-0000-4000-8000-000000000031"
COMPETITION_CHANGE = "00000000-0000-4000-8000-000000000032"
PENDING_UNDO = "00000000-0000-4000-8000-000000000041"
USED_UNDO = "00000000-0000-4000-8000-000000000042"
DUPLICATE_PROPOSAL = "00000000-0000-4000-8000-000000000043"

# The Intervals.icu event a v15 build imported as REMOTE_UNIT.
REMOTE_EVENT = {
    "id": 77,
    "category": "WORKOUT",
    "start_date_local": "2026-11-02T07:30:00",
    "type": "Run",
    "name": "Lockerer Lauf",
    "description": "- 45m 65%",
    "moving_time": 2700,
    "external_id": "intervals-event-77",
}
LEGACY_NAMES = {
    "starts_at_local": "start_date_local",
    "planned_duration_s": "moving_time",
}
CURRENT_NAMES = {legacy: current for current, legacy in LEGACY_NAMES.items()}


def legacy(record: dict[str, Any]) -> dict[str, Any]:
    """Return a current record under the field names a v15 build stored."""
    return {LEGACY_NAMES.get(key, key): value for key, value in record.items()}


def remote_unit_payload() -> dict[str, Any]:
    prepared = planned_units.remote_planned_unit_payload(
        planning_fields_from_intervals(REMOTE_EVENT), today=TODAY
    )
    assert prepared is not None
    payload, _remote_id, _identity = prepared
    return {**payload, "id": REMOTE_UNIT}


def local_unit_payload(name: str, start: str) -> dict[str, Any]:
    return planned_units.normalize_planned_unit(
        {
            "date": "2026-11-03",
            "sport": "Run",
            "name": name,
            "description": "- 60m 60% locker",
            "duration_minutes": 60,
            "starts_at_local": start,
            "rationale": "Grundlage",
        },
        local_id=LOCAL_UNIT,
        sync_status="local",
    )


def legacy_change(
    entity_type: str, change_id: str, entity_id: str, before: Any, after: Any
) -> tuple[Any, ...]:
    """A change-history row exactly as a v15 build recorded it.

    ``before`` and ``after`` use the current names; the recorded projections,
    hashes and diff carry the former ones, as v15 wrote them.
    """
    before_projection = legacy(
        change_history.audit_projection(entity_type, before) or {}
    )
    after_projection = legacy(change_history.audit_projection(entity_type, after) or {})
    return (
        change_id,
        entity_type,
        entity_id,
        "update",
        "coach",
        STAMP,
        change_history.audit_hash(before_projection),
        change_history.audit_hash(after_projection),
        json.dumps(
            change_history.audit_diff(before_projection, after_projection),
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )


def competition_row(**values: Any) -> dict[str, Any]:
    row = {
        "id": COMPETITION,
        "name": "Stadtlauf",
        "event_date": "2026-11-15",
        "sport": "run",
        "environment": "outdoor",
        "sport_detail": None,
        "priority": "A",
        "distance": "10000",
        "target": "",
        "course_profile": "",
        "notes": "",
        "category": "RACE_A",
        "start_date_local": "2026-11-15T10:00:00",
        "description": "",
        "moving_time": 2700,
        "intervals_event_id": None,
        "external_id": None,
        "sync_dirty": 1,
        "sync_state": "local",
        "sync_conflict": "",
        "last_synced_at": None,
        "created_at": STAMP,
        "updated_at": STAMP,
    }
    row.update(values)
    return row


COMPETITION_BEFORE = competition_row(
    name="Stadtlauf", start_date_local="2026-11-15T09:00:00", moving_time=3000
)
COMPETITION_AFTER = competition_row(
    sync_conflict=json.dumps(
        {
            "type": "remote_changed",
            "remote": {
                "intervals_event_id": "88",
                "name": "Stadtlauf",
                "event_date": "2026-11-15",
                "start_date_local": "2026-11-15T10:30:00",
                "moving_time": 2400,
                "external_id": "intervals-coach-competition-x",
            },
            "detected_at": STAMP,
        },
        ensure_ascii=False,
    )
)


def insert(db: Any, table: str, row: dict[str, Any]) -> None:
    columns = ", ".join(row)
    marks = ", ".join("?" for _ in row)
    db.execute(f"INSERT INTO {table}({columns}) VALUES ({marks})", tuple(row.values()))


def populated_planning_database(db: Any, fixture: Path = V15_FIXTURE) -> Any:
    """A released database with planning records under the former field names."""
    db.executescript(fixture.read_text(encoding="utf-8"))
    remote = legacy(remote_unit_payload())
    current_before = local_unit_payload("Lauf", "2026-11-03T10:00:00")
    current_after = local_unit_payload("Neu", "2026-11-03T08:15:00")
    local_after = legacy(current_after)
    unit_row = {
        "external_id": None,
        "sync_dirty": 0,
        "sync_state": "synced",
        "sync_error": None,
        "last_synced_at": STAMP,
        "created_at": STAMP,
        "updated_at": STAMP,
    }
    insert(
        db,
        "planned_units",
        {
            **unit_row,
            "id": REMOTE_UNIT,
            "local_id": REMOTE_UNIT,
            "external_id": "intervals-event-77",
            "payload": json.dumps(remote, ensure_ascii=False),
            "sync_conflict": json.dumps(
                {
                    "type": "remote_changed",
                    "remote": {**remote, "moving_time": 3000},
                    "detected_at": STAMP,
                },
                ensure_ascii=False,
            ),
            "baseline_hash": planned_units.planned_unit_payload_hash(remote),
        },
    )
    insert(
        db,
        "planned_units",
        {
            **unit_row,
            "id": LOCAL_UNIT,
            "local_id": LOCAL_UNIT,
            "payload": json.dumps(local_after, ensure_ascii=False),
            "sync_dirty": 1,
            "sync_state": "local",
            "sync_conflict": "",
        },
    )
    insert(
        db,
        "planned_units",
        {
            **unit_row,
            "id": LIST_UNIT,
            "local_id": LIST_UNIT,
            # Not an object, so no planning record: it keeps its exact bytes.
            "payload": '["moving_time", "start_date_local"]',
            "sync_conflict": "",
        },
    )
    for local_id, payload in (
        (
            LIBRARY_ENTRY,
            {
                "id": LIBRARY_ENTRY,
                "name": "Intervalle",
                "description": "- 60m 70%",
                "sport": "ride",
                "environment": "outdoor",
                "moving_time": 3600,
                "duration_minutes": 60,
                "external_id": "4711",
                "sync_status": "synced",
            },
        ),
        (
            LIBRARY_TEXT_ONLY,
            {
                "id": LIBRARY_TEXT_ONLY,
                "name": "Notiz",
                "description": "moving_time steht nur im Text",
                "duration_minutes": 30,
            },
        ),
    ):
        insert(
            db,
            "workout_library",
            {
                "id": local_id,
                "local_id": local_id,
                "external_id": payload.get("external_id"),
                "payload": json.dumps(payload, ensure_ascii=False),
                "sync_dirty": 0,
                "sync_state": "synced",
                "updated_at": STAMP,
            },
        )
    insert(db, "competitions", COMPETITION_AFTER)
    insert(
        db,
        "competitions",
        competition_row(
            id=COMPETITION_EMPTY,
            name="Ohne Zeit",
            start_date_local=None,
            moving_time=None,
        ),
    )
    insert(
        db,
        "coach_plan_artifacts",
        {
            "id": "artifact-1",
            "conversation_id": "conversation-1",
            "client_turn_id": "turn-1",
            "base_revision": 3,
            "status": "draft",
            "payload": json.dumps(
                {
                    "plan_name": "Block",
                    "goal": "10 km",
                    "workouts": [
                        {
                            "date": "2026-11-04",
                            "sport": "Run",
                            "name": "Tempo",
                            "start_date_local": "2026-11-04T06:00:00",
                            "duration_minutes": 40,
                        },
                        {"date": "2026-11-05", "sport": "Run", "name": "Ruhe"},
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            "created_at": STAMP,
            "updated_at": STAMP,
        },
    )
    insert(
        db,
        "plan_adjustments",
        {
            "id": "adjustment-1",
            "payload": json.dumps(
                {
                    "changes": [
                        {
                            "library_workout_id": REMOTE_UNIT,
                            "date": "2026-11-02",
                            "before": {"duration_minutes": 45},
                            "after": {"duration_minutes": 30},
                            "source_fingerprint": "f" * 64,
                            "payload": {**remote, "duration_minutes": 30},
                        }
                    ],
                    "illness_pause": None,
                },
                ensure_ascii=False,
            ),
            "status": "preview",
            "created_at": STAMP,
            "applied_at": None,
        },
    )
    history = (
        legacy_change(
            "planned_unit",
            UNIT_CHANGE,
            LOCAL_UNIT,
            {"payload": json.dumps(current_before), "sync_state": "local"},
            {"payload": json.dumps(current_after), "sync_state": "local"},
        ),
        legacy_change(
            "competition",
            COMPETITION_CHANGE,
            COMPETITION,
            {CURRENT_NAMES.get(k, k): v for k, v in COMPETITION_BEFORE.items()},
            {CURRENT_NAMES.get(k, k): v for k, v in COMPETITION_AFTER.items()},
        ),
    )
    for row in history:
        db.execute(
            "INSERT INTO change_history(id, entity_type, entity_id, action, source, "
            "created_at, before_hash, after_hash, diff) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )
    undo_diff = json.dumps(
        {
            "fields": {
                "name": {"changed": True},
                "start_date_local": {"changed": True},
            },
            "before_present": True,
            "after_present": True,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    undo_payload: dict[str, Any] = {
        "change_id": UNIT_CHANGE,
        "expected_current_hash": history[0][7],
    }
    duplicate_diff = json.dumps(
        [{"start_date_local": "2026-10-29T07:00:00", "moving_time": 1800}],
        separators=(",", ":"),
    )
    proposals: tuple[tuple[str, str, str, str, dict[str, Any]], ...] = (
        (PENDING_UNDO, "undo_change", "ready", undo_diff, undo_payload),
        (USED_UNDO, "undo_change", "used", undo_diff, undo_payload),
        (
            DUPLICATE_PROPOSAL,
            "delete_duplicate_intervals_activity",
            "preview",
            duplicate_diff,
            {"canonical_id": "1", "duplicate_id": "2"},
        ),
    )
    for proposal_id, action_type, status, diff, payload in proposals:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        insert(
            db,
            "coach_action_proposals",
            {
                "id": proposal_id,
                "session_csrf_hash": "c" * 64,
                "action_type": action_type,
                "target_system": "local",
                "object_ids": json.dumps({"change_id": UNIT_CHANGE}),
                "diff": diff,
                "payload": encoded,
                "payload_hash": hashlib.sha256(
                    json.dumps(
                        payload,
                        sort_keys=True,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ).encode("utf-8")
                ).hexdigest(),
                "action_token_hash": "t" * 64 if status == "ready" else None,
                "status": status,
                "expires_at": 4102444800.0,
                "created_at": STAMP,
                "used_at": STAMP if status == "used" else None,
            },
        )
    db.execute(
        "INSERT OR REPLACE INTO planning_state(id, revision, updated_at) VALUES (1, 3, ?)",
        (STAMP,),
    )
    db.commit()
    return db


def populated_v16_planning_database(db: Any) -> Any:
    """Construct a synthetic v16 database retaining pre-v16 audit history."""
    populated_planning_database(db)
    rename_planning_fields_in_database(db)
    for unit_id in (REMOTE_UNIT, LOCAL_UNIT):
        payload = json.loads(stored(db, "planned_units", "payload", unit_id))
        payload.update({"icu_training_load": 42, "icu_intensity": 0.8})
        db.execute(
            "UPDATE planned_units SET payload = ? WHERE id = ?",
            (json.dumps(payload), unit_id),
        )
        if unit_id == REMOTE_UNIT:
            db.execute(
                "UPDATE planned_units SET baseline_hash = ? WHERE id = ?",
                (planned_units.planned_unit_payload_hash(payload), unit_id),
            )
    db.execute("PRAGMA user_version = 16")
    db.commit()
    return db


def all_rows(db: Any) -> dict[str, list[tuple[Any, ...]]]:
    tables = [
        row[0]
        for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    ]
    return {
        table: sorted(
            (tuple(row) for row in db.execute(f"SELECT * FROM {table}")), key=repr
        )
        for table in tables
    }


# Tables whose rows the upgrade rewrites; every other table keeps its exact rows.
REWRITTEN_TABLES = {
    "competitions",
    "planned_units",
    "workout_library",
    "coach_plan_artifacts",
    "plan_adjustments",
    "coach_action_proposals",
}


def connect(path: Path | str = ":memory:") -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    return db


def stored(db: Any, table: str, column: str, row_id: str) -> Any:
    row = db.execute(
        f"SELECT {column} AS value FROM {table} WHERE id=?", (row_id,)
    ).fetchone()
    return row["value"]


class PlanningFieldsMigrationTests(unittest.TestCase):
    def released(self, fixture: Path = V15_FIXTURE) -> sqlite3.Connection:
        db = connect()
        self.addCleanup(db.close)
        return populated_v16_planning_database(db)

    def test_populated_v16_upgrade_preserves_unrelated_rows_and_unit_metadata(self):
        db = self.released()
        tables = [
            row[0]
            for row in db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        columns = {
            table: [row[1] for row in db.execute(f"PRAGMA table_info({table})")]
            for table in tables
        }
        before = {
            table: sorted(
                (
                    tuple(row)
                    for row in db.execute(
                        f"SELECT {', '.join(columns[table])} FROM {table}"
                    )
                ),
                key=repr,
            )
            for table in tables
            if table != "planned_units"
        }
        metadata = sorted(
            (
                tuple(row)
                for row in db.execute(
                    "SELECT id, local_id, external_id, sync_dirty, sync_state, baseline_hash, revision, tombstone FROM planned_units"
                )
            ),
            key=repr,
        )
        migrate_schema(db)
        db.commit()
        for table, rows in before.items():
            with self.subTest(table=table):
                after = sorted(
                    (
                        tuple(row)
                        for row in db.execute(
                            f"SELECT {', '.join(columns[table])} FROM {table}"
                        )
                    ),
                    key=repr,
                )
                self.assertEqual(after, rows)
        self.assertEqual(
            sorted(
                (
                    tuple(row)
                    for row in db.execute(
                        "SELECT id, local_id, external_id, sync_dirty, sync_state, baseline_hash, revision, tombstone FROM planned_units"
                    )
                ),
                key=repr,
            ),
            metadata,
        )

    def test_recorded_remote_baseline_still_matches_after_the_upgrade(self):
        db = self.released()
        migrate_schema(db)
        db.commit()
        row = dict(
            db.execute(
                "SELECT * FROM planned_units WHERE id=?", (REMOTE_UNIT,)
            ).fetchone()
        )
        incoming = remote_unit_payload()
        incoming.update({"planned_load": 42, "planned_intensity": 0.8})
        incoming_hash = planned_units.planned_unit_payload_hash(incoming)
        self.assertEqual(row["baseline_hash"], incoming_hash)
        self.assertEqual(
            planned_units.planned_unit_payload_hash(
                intervals_fields_from_planning(incoming)
            ),
            incoming_hash,
        )
        _current, state = planned_units.remote_planned_unit_existing_state(
            row, incoming_hash
        )
        self.assertEqual(state, "unchanged")

    def test_upgraded_database_restarts_with_the_same_build_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "upgrade.db"
            with closing(connect(path)) as db:
                populated_v16_planning_database(db)
                migrate_schema(db)
                db.commit()
                upgraded = list(db.iterdump())
            with closing(connect(path)) as reopened:
                migrate_schema(reopened)
                self.assertEqual(list(reopened.iterdump()), upgraded)

    def test_v16_version_and_shape_must_belong_together(self):
        db = self.released()
        db.execute(f"PRAGMA user_version = {CURRENT_SCHEMA_VERSION}")
        db.commit()
        before = list(db.iterdump())
        with self.assertRaises(RuntimeError):
            migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before)

    def test_restore_of_a_populated_v16_backup_upgrades_through_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.db"
            with closing(connect(path)) as db:
                populated_v16_planning_database(db)
            DatabaseRestoreValidationService(
                DatabaseRestoreValidationConfig(
                    data_dir=Path(directory),
                    maximum_bytes=10_000_000,
                    app_password="",
                    sqlcipher_available=False,
                    sqlite_backend=sqlite3,
                    configure_cipher=Mock(),
                    row_factory=sqlite3.Row,
                    schema_is_current=database_schema_is_current,
                    migrate_schema=migrate_schema,
                )
            ).validate(path)
            with closing(connect(path)) as db:
                self.assertTrue(database_schema_is_current(db))
                self.assertEqual(
                    json.loads(stored(db, "planned_units", "payload", REMOTE_UNIT))[
                        "planned_duration_s"
                    ],
                    2700,
                )

    def test_the_rename_keeps_order_and_a_present_neutral_value(self):
        self.assertEqual(
            list(rename_planning_fields({"a": 1, "moving_time": 2, "b": 3})),
            ["a", "planned_duration_s", "b"],
        )
        self.assertEqual(
            rename_planning_fields({"moving_time": 2, "planned_duration_s": 5}),
            {"planned_duration_s": 5},
        )
        self.assertEqual(rename_planning_fields(["moving_time"]), ["moving_time"])


class PreUpgradeUndoTests(unittest.TestCase):
    """A change recorded before the upgrade is still undone afterwards."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "undo.db"
        with closing(connect(path)) as db:
            populated_v16_planning_database(db)
        self.manager = DatabaseManager(path, sqlite3, row_factory=row_factory)
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            migrate_schema(db)
        self.revisions = PlanningRevisionService(
            PlanningStateRepository(), lambda: STAMP
        )
        external = Mock()
        external.list_events.return_value = []
        ids = (uuid.UUID(int=number) for number in range(100, 200))
        self.planned = PlannedUnitService(
            self.manager,
            self.revisions,
            lambda: STAMP,
            lambda: TODAY,
            lambda: next(ids),
            lambda value: value,
            CalendarConflictService(self.manager, external),
            lambda: None,
        )
        self.competitions = CompetitionService(
            self.manager, CompetitionRepository(), lambda: STAMP
        )
        self.undo = HistoryUndoService(
            self.manager,
            ChangeHistoryService(self.manager, None),
            None,
            None,
            self.competitions,
            self.planned,
            None,
            self.revisions,
            profile_mutation_coordinator=threading.RLock(),
        )

    def test_planned_unit_change_from_v15_is_undone_with_the_current_names(self):
        preview = self.undo.preview(UNIT_CHANGE)
        self.assertEqual(
            sorted(preview["change"]["diff"]["fields"]), ["name", "starts_at_local"]
        )
        self.undo.apply(preview["proposal"]["payload"])
        with self.manager.reader() as db:
            payload = json.loads(stored(db, "planned_units", "payload", LOCAL_UNIT))
        self.assertEqual(payload["name"], "Lauf")
        self.assertEqual(payload["starts_at_local"], "2026-11-03T10:00:00")
        self.assertEqual(
            (payload["planned_load"], payload["planned_intensity"]), (42, 0.8)
        )
        self.assertNotIn("start_date_local", payload)

    def test_pending_undo_proposal_from_v15_still_applies(self):
        with self.manager.reader() as db:
            payload = json.loads(
                stored(db, "coach_action_proposals", "payload", PENDING_UNDO)
            )
        self.undo.apply(payload)
        with self.manager.reader() as db:
            unit = json.loads(stored(db, "planned_units", "payload", LOCAL_UNIT))
        self.assertEqual(unit["starts_at_local"], "2026-11-03T10:00:00")

    def test_competition_change_from_v15_is_undone_into_the_renamed_columns(self):
        preview = self.undo.preview(COMPETITION_CHANGE)
        self.assertIn("starts_at_local", preview["change"]["diff"]["fields"])
        self.assertIn("planned_duration_s", preview["change"]["diff"]["fields"])
        self.undo.apply(preview["proposal"]["payload"])
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT starts_at_local, planned_duration_s FROM competitions WHERE id=?",
                (COMPETITION,),
            ).fetchone()
        self.assertEqual(row["starts_at_local"], "2026-11-15T09:00:00")
        self.assertEqual(row["planned_duration_s"], 3000)


if __name__ == "__main__":
    unittest.main()
