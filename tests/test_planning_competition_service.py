"""Transactional regression tests for local competition use cases."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.db import DatabaseManager, row_factory
from backend.db.repositories import CompetitionRepository
from backend.db.schema import initialize_schema
from backend.planning.competition_service import CompetitionService

NOW = "2026-09-20T08:00:00+00:00"


class CompetitionServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temporary_directory.name) / "competition.db",
            sqlite3,
            row_factory=row_factory,
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.now = NOW
        self.service = CompetitionService(
            self.manager, CompetitionRepository(), lambda: self.now
        )

    def tearDown(self):
        self.manager.close()
        self.temporary_directory.cleanup()

    @staticmethod
    def competition(**overrides):
        return {
            "name": "Berlin Marathon",
            "event_date": "2027-09-26",
            "sport": "Run",
            "priority": "A",
            "distance": "42.2 km",
            "target": "Sub 3:30",
            "notes": "Fuel plan",
            **overrides,
        }

    def test_create_and_partial_update_share_one_transaction_with_history(self):
        created = self.service.save(self.competition())
        competition_id = created["competition"]["id"]

        self.now = "2026-09-20T09:00:00+00:00"
        updated = self.service.save(
            {"competition_id": competition_id, "name": "Berlin 2027"},
        )

        self.assertEqual(created["status"], "created")
        self.assertEqual(updated["status"], "updated")
        self.assertEqual(updated["competition"]["name"], "Berlin 2027")
        self.assertEqual(updated["competition"]["event_date"], "2027-09-26")
        self.assertEqual(updated["competition"]["notes"], "Fuel plan")
        with self.manager.reader() as db:
            history = db.execute(
                "SELECT action FROM change_history ORDER BY created_at"
            ).fetchall()
        self.assertEqual([row["action"] for row in history], ["create", "update"])

    def test_failed_history_write_rolls_back_competition(self):
        with (
            patch(
                "backend.planning.competition_service.change_history.record_change",
                side_effect=RuntimeError("audit unavailable"),
            ),
            self.assertRaisesRegex(RuntimeError, "audit unavailable"),
        ):
            self.service.save(self.competition())

        self.assertEqual(self.service.list(), [])

    def test_restore_in_transaction_deletes_without_side_effects(self):
        created = self.service.save(self.competition())
        competition_id = created["competition"]["id"]
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE competitions SET intervals_event_id=?, external_id=? WHERE id=?",
                ("42", "ai-coach:competition:test", competition_id),
            )
            db.execute(
                "INSERT INTO public_event_sources(id, name, url, created_at, updated_at) "
                "VALUES ('source', 'Source', 'https://example.test/events', ?, ?)",
                (NOW, NOW),
            )
            db.execute(
                "INSERT INTO public_event_candidates(id, source_id, uid, name, event_date, sport, imported_competition_id, created_at, updated_at) "
                "VALUES ('candidate', 'source', 'uid', 'Race', '2027-09-26', 'Run', ?, ?, ?)",
                (competition_id, NOW, NOW),
            )
            history_before = db.execute(
                "SELECT COUNT(*) AS count FROM change_history"
            ).fetchone()["count"]

        with self.manager.unit_of_work() as db:
            restored = self.service.restore_in_transaction(
                db,
                competition_id,
                self.service._repository.get(db, competition_id),
                None,
            )
            self.assertIsNone(restored)

        with self.manager.reader() as db:
            self.assertIsNone(self.service._repository.get(db, competition_id))
            self.assertEqual(
                db.execute(
                    "SELECT COUNT(*) AS count FROM competition_sync_tombstones"
                ).fetchone()["count"],
                0,
            )
            candidate = db.execute(
                "SELECT imported_competition_id FROM public_event_candidates"
            ).fetchone()
            history_after = db.execute(
                "SELECT COUNT(*) AS count FROM change_history"
            ).fetchone()["count"]
        self.assertEqual(candidate["imported_competition_id"], competition_id)
        self.assertEqual(history_after, history_before)

    def test_restore_in_transaction_updates_and_normalizes_without_history(self):
        created = self.service.save(self.competition())
        competition_id = created["competition"]["id"]
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE competitions SET intervals_event_id=?, external_id=? WHERE id=?",
                ("42", "ai-coach:competition:test", competition_id),
            )
            current = self.service._repository.get(db, competition_id)
        target = {"name": "  Restored Marathon  "}
        current_before = dict(current)
        target_before = dict(target)
        self.now = "2026-09-20T09:00:00+00:00"

        with self.manager.unit_of_work() as db:
            restored = self.service.restore_in_transaction(
                db, competition_id, current, target
            )

        self.assertEqual(restored["id"], competition_id)
        self.assertEqual(restored["name"], "Restored Marathon")
        self.assertEqual(restored["event_date"], "2027-09-26")
        self.assertEqual(restored["notes"], "Fuel plan")
        self.assertEqual(restored["sync_state"], "local")
        self.assertEqual(current, current_before)
        self.assertEqual(target, target_before)
        with self.manager.reader() as db:
            persisted = self.service._repository.get(db, competition_id)
            history_count = db.execute(
                "SELECT COUNT(*) AS count FROM change_history"
            ).fetchone()["count"]
        self.assertEqual(persisted["intervals_event_id"], "42")
        self.assertEqual(persisted["external_id"], "ai-coach:competition:test")
        self.assertEqual(persisted["sync_dirty"], 1)
        self.assertEqual(persisted["sync_state"], "local")
        self.assertEqual(persisted["updated_at"], self.now)
        self.assertEqual(history_count, 1)

    def test_restore_in_transaction_recreates_locally_without_history(self):
        competition_id = "83a79192-a287-4f5d-b041-70e352121c4f"
        target = self.competition(id="wrong-id", name="  Recreated Race ")
        target_before = dict(target)

        with self.manager.unit_of_work() as db:
            restored = self.service.restore_in_transaction(
                db, competition_id, None, target
            )

        self.assertEqual(restored["id"], competition_id)
        self.assertEqual(restored["name"], "Recreated Race")
        self.assertEqual(restored["sync_state"], "local")
        self.assertEqual(target, target_before)
        with self.manager.reader() as db:
            persisted = self.service._repository.get(db, competition_id)
            history_count = db.execute(
                "SELECT COUNT(*) AS count FROM change_history"
            ).fetchone()["count"]
        self.assertEqual(persisted["sync_state"], "local")
        self.assertEqual(persisted["sync_dirty"], 1)
        self.assertIsNone(persisted["external_id"])
        self.assertIsNone(persisted["intervals_event_id"])
        self.assertEqual(persisted["created_at"], NOW)
        self.assertEqual(history_count, 0)

    def test_restore_in_transaction_rolls_back_with_outer_unit_of_work(self):
        created = self.service.save(self.competition())
        competition_id = created["competition"]["id"]
        current = created["competition"]
        with self.manager.reader() as db:
            history_before = db.execute(
                "SELECT COUNT(*) AS count FROM change_history"
            ).fetchone()["count"]

        with (
            self.assertRaisesRegex(RuntimeError, "abort outer undo"),
            self.manager.unit_of_work() as db,
        ):
            self.service.restore_in_transaction(
                db, competition_id, current, {"name": "Not committed"}
            )
            raise RuntimeError("abort outer undo")

        with self.manager.reader() as db:
            persisted = self.service._repository.get(db, competition_id)
            history_after = db.execute(
                "SELECT COUNT(*) AS count FROM change_history"
            ).fetchone()["count"]
        self.assertEqual(persisted["name"], "Berlin Marathon")
        self.assertEqual(history_after, history_before)

    def test_delete_creates_remote_tombstone_and_unlinks_public_candidate(self):
        created = self.service.save(self.competition())
        competition_id = created["competition"]["id"]
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE competitions SET intervals_event_id=?, external_id=? WHERE id=?",
                ("42", "ai-coach:competition:test", competition_id),
            )
            db.execute(
                "INSERT INTO public_event_sources(id, name, url, created_at, updated_at) "
                "VALUES ('source', 'Source', 'https://example.test/events', ?, ?)",
                (NOW, NOW),
            )
            db.execute(
                "INSERT INTO public_event_candidates(id, source_id, uid, name, event_date, sport, imported_competition_id, created_at, updated_at) "
                "VALUES ('candidate', 'source', 'uid', 'Race', '2027-09-26', 'Run', ?, ?, ?)",
                (competition_id, NOW, NOW),
            )

        deleted = self.service.delete(competition_id)

        self.assertTrue(deleted["remote_sync_pending"])
        self.assertEqual(deleted["competitions"], [])
        with self.manager.reader() as db:
            tombstone = db.execute(
                "SELECT intervals_event_id, external_id FROM competition_sync_tombstones"
            ).fetchone()
            candidate = db.execute(
                "SELECT imported_competition_id FROM public_event_candidates"
            ).fetchone()
        self.assertEqual(tombstone["intervals_event_id"], "42")
        self.assertEqual(tombstone["external_id"], "ai-coach:competition:test")
        self.assertIsNone(candidate["imported_competition_id"])

    def test_conflict_resolution_preserves_both_strategies(self):
        created = self.service.save(self.competition())
        competition_id = created["competition"]["id"]
        remote = {
            "id": "81",
            "external_id": "remote-race",
            "name": "Remote Marathon",
            "start_date_local": "2027-09-26T09:00:00",
            "type": "Run",
            "category": "RACE_A",
            "description": "Remote notes",
        }
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE competitions SET sync_state='conflict', sync_conflict=? WHERE id=?",
                (json.dumps({"remote": remote}), competition_id),
            )

        adopted = self.service.resolve_conflict(competition_id, "adopt_remote")
        self.assertEqual(adopted["competition"]["name"], "Remote Marathon")
        self.assertEqual(adopted["competition"]["sync_state"], "synced")
        self.assertEqual(adopted["competition"]["intervals_event_id"], "81")

        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE competitions SET sync_state='conflict', sync_conflict=? WHERE id=?",
                (json.dumps({"remote": remote}), competition_id),
            )
        self.now = "2026-09-20T10:00:00+00:00"
        kept = self.service.resolve_conflict(competition_id, "KEEP_LOCAL")
        self.assertEqual(kept["competition"]["sync_state"], "local_override")
        self.assertEqual(kept["competition"]["sync_dirty"], 1)


if __name__ == "__main__":
    unittest.main()
