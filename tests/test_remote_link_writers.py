"""Remote-link maintenance by the writers of the legacy Intervals.icu slots."""

from __future__ import annotations

import json
import sqlite3
import unittest
from typing import Any
from unittest.mock import Mock

from backend.canonical.vocabulary import ProviderId, RemoteEntityKind
from backend.db.remote_links import RemoteLinkRepository
from backend.db.repositories import CompetitionRepository
from backend.db.schema import initialize_schema
from backend.planning.planned_unit_service import PlannedUnitService

NOW = "2026-10-12T08:00:00+00:00"
INTERVALS = ProviderId.INTERVALS.value
REPOSITORY = RemoteLinkRepository()


def memory_database(schema: str | None = None) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    if schema is None:
        initialize_schema(db)
    else:
        db.executescript(schema)
    return db


def link(db: Any, kind: RemoteEntityKind, local_id: str) -> tuple[Any, ...] | None:
    row = db.execute(
        "SELECT remote_id, remote_external_id, sync_state FROM remote_links "
        "WHERE entity_kind=? AND local_id=? AND provider=?",
        (kind.value, local_id, INTERVALS),
    ).fetchone()
    return tuple(row) if row else None


def insert_competition(db: Any, competition_id: str, **slots: Any) -> None:
    db.execute(
        "INSERT INTO competitions(id, name, event_date, sport, priority, distance, "
        "target, course_profile, notes, intervals_event_id, external_id, created_at, "
        "updated_at) VALUES (?, 'Race', '2026-11-01', 'Run', 'B', '', '', '', '', "
        "?, ?, ?, ?)",
        (
            competition_id,
            slots.get("intervals_event_id"),
            slots.get("external_id"),
            NOW,
            NOW,
        ),
    )


class CompetitionWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = memory_database()
        self.addCleanup(self.db.close)
        self.kind = RemoteEntityKind.COMPETITION

    def test_assign_change_and_clear_keep_the_link_consistent(self) -> None:
        insert_competition(self.db, "c1")
        REPOSITORY.refresh_from_slots(self.db, self.kind, "c1")
        self.assertIsNone(link(self.db, self.kind, "c1"))

        self.db.execute("UPDATE competitions SET intervals_event_id='501'")
        REPOSITORY.refresh_from_slots(self.db, self.kind, "c1")
        self.assertEqual(link(self.db, self.kind, "c1"), ("501", None, "synced"))

        self.db.execute("UPDATE competitions SET intervals_event_id=' 502 '")
        REPOSITORY.refresh_from_slots(self.db, self.kind, "c1")
        self.assertEqual(link(self.db, self.kind, "c1"), ("502", None, "synced"))

        self.db.execute(
            "UPDATE competitions SET intervals_event_id=NULL, external_id='ext'"
        )
        REPOSITORY.refresh_from_slots(self.db, self.kind, "c1")
        self.assertEqual(link(self.db, self.kind, "c1"), (None, "ext", "pending"))

        self.db.execute("UPDATE competitions SET external_id=NULL")
        REPOSITORY.refresh_from_slots(self.db, self.kind, "c1")
        self.assertIsNone(link(self.db, self.kind, "c1"))

    def test_deleting_the_record_removes_the_link(self) -> None:
        insert_competition(self.db, "c1", intervals_event_id="501")
        REPOSITORY.refresh_from_slots(self.db, self.kind, "c1")
        CompetitionRepository().delete(self.db, "c1")
        self.assertIsNone(link(self.db, self.kind, "c1"))
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM competitions").fetchone()[0], 0
        )

    def test_a_remote_id_moves_to_the_record_that_now_holds_it(self) -> None:
        insert_competition(self.db, "c1", intervals_event_id="501")
        insert_competition(self.db, "c2")
        REPOSITORY.refresh_from_slots(self.db, self.kind, "c1")
        self.db.execute("UPDATE competitions SET intervals_event_id=NULL WHERE id='c1'")
        self.db.execute(
            "UPDATE competitions SET intervals_event_id='501' WHERE id='c2'"
        )
        REPOSITORY.refresh_from_slots(self.db, self.kind, "c2")
        REPOSITORY.refresh_from_slots(self.db, self.kind, "c1")
        self.assertIsNone(link(self.db, self.kind, "c1"))
        self.assertEqual(link(self.db, self.kind, "c2"), ("501", None, "synced"))

    def test_rollback_restores_slot_and_link_together(self) -> None:
        insert_competition(self.db, "c1", intervals_event_id="501")
        REPOSITORY.refresh_from_slots(self.db, self.kind, "c1")
        self.db.commit()
        self.db.execute("UPDATE competitions SET intervals_event_id='900'")
        REPOSITORY.refresh_from_slots(self.db, self.kind, "c1")
        self.assertEqual(link(self.db, self.kind, "c1"), ("900", None, "synced"))
        self.db.rollback()
        self.assertEqual(link(self.db, self.kind, "c1"), ("501", None, "synced"))
        self.assertEqual(
            self.db.execute("SELECT intervals_event_id FROM competitions").fetchone()[
                0
            ],
            "501",
        )

    def test_resolve_prefers_the_link_and_falls_back_to_the_slot(self) -> None:
        insert_competition(self.db, "c1", intervals_event_id="501")
        self.assertEqual(
            REPOSITORY.resolve_remote_id(self.db, self.kind, "c1", "501"), "501"
        )
        REPOSITORY.refresh_from_slots(self.db, self.kind, "c1")
        self.db.execute("UPDATE remote_links SET remote_id='777'")
        self.assertEqual(
            REPOSITORY.resolve_remote_id(self.db, self.kind, "c1", "501"), "777"
        )

    def test_a_pending_link_does_not_revive_a_rejected_duplicate_id(self) -> None:
        insert_competition(self.db, "c1", intervals_event_id="501", external_id="x")
        insert_competition(self.db, "c2", intervals_event_id="501", external_id="y")
        REPOSITORY.refresh_from_slots(self.db, self.kind, "c1")
        REPOSITORY.refresh_from_slots(self.db, self.kind, "c2")
        self.assertEqual(link(self.db, self.kind, "c2"), (None, "y", "pending"))
        self.assertIsNone(REPOSITORY.resolve_remote_id(self.db, self.kind, "c2", "501"))
        self.assertEqual(
            REPOSITORY.resolve_remote_external_id(self.db, self.kind, "c2", "z"), "y"
        )


class PlannedUnitWriterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = memory_database()
        self.addCleanup(self.db.close)
        self.kind = RemoteEntityKind.PLANNED_UNIT
        self.service = PlannedUnitService(
            Mock(),
            Mock(),
            lambda: NOW,
            Mock(),
            Mock(),
            lambda text: text,
            Mock(),
            lambda: None,
        )

    def entry(self, local_id: str, **values: Any) -> dict[str, Any]:
        return {"id": local_id, "date": "2026-11-01", "name": "Run", **values}

    def test_insert_links_a_remote_event_and_ignores_local_entries(self) -> None:
        self.service.insert(self.db, self.entry("u1", remote_event_id="900"))
        self.service.insert(self.db, self.entry("u2"))
        self.assertEqual(link(self.db, self.kind, "u1"), ("900", None, "synced"))
        self.assertIsNone(link(self.db, self.kind, "u2"))

    def test_external_id_alone_is_pending(self) -> None:
        self.service.insert(self.db, self.entry("u1", external_id="ext-1"))
        self.assertEqual(link(self.db, self.kind, "u1"), (None, "ext-1", "pending"))

    def test_restore_delete_removes_the_link(self) -> None:
        self.service.insert(self.db, self.entry("u1", remote_event_id="900"))
        self.service.restore_in_transaction(self.db, "u1", None, None, "undo")
        self.assertIsNone(link(self.db, self.kind, "u1"))

    def test_clearing_and_changing_the_payload_slot_follow_the_link(self) -> None:
        self.service.insert(self.db, self.entry("u1", remote_event_id="900"))
        for new_id, expected in (
            (901, ("901", None, "synced")),
            (None, None),
        ):
            payload = json.loads(
                self.db.execute(
                    "SELECT payload FROM planned_units WHERE local_id='u1'"
                ).fetchone()[0]
            )
            payload["remote_event_id"] = new_id
            self.db.execute(
                "UPDATE planned_units SET payload=? WHERE local_id='u1'",
                (json.dumps(payload),),
            )
            REPOSITORY.refresh_from_slots(self.db, self.kind, "u1")
            self.assertEqual(link(self.db, self.kind, "u1"), expected)


if __name__ == "__main__":
    unittest.main()
