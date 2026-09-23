import json
import sqlite3
import unittest
from contextlib import contextmanager

from backend.athlete.context import AthleteContextService
from backend.athlete.profile import ProfileService, normalize_profile
from backend.db.repositories import (
    CompetitionRepository,
    KeyValueRepository,
    ProfileRepository,
)
from backend.errors import AppError


class _Manager:
    def __init__(self, db):
        self.db = db

    @contextmanager
    def unit_of_work(self):
        try:
            yield self.db
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise


def _normalize_competition(value):
    if not isinstance(value, dict):
        raise AppError(400, "Jeder Wettkampf muss ein Objekt sein.")
    return {
        "id": value["id"],
        "name": value.get("name", "Race"),
        "event_date": value.get("event_date", "2026-10-01"),
        "sport": value.get("sport", "Cycling"),
        "priority": value.get("priority", "B"),
        "distance": value.get("distance", ""),
        "target": value.get("target", ""),
        "course_profile": value.get("course_profile", ""),
        "notes": value.get("notes", ""),
        "category": value.get("category", "RACE_B"),
        "start_date_local": value.get("start_date_local", ""),
        "description": value.get("description", ""),
        "moving_time": value.get("moving_time"),
        "external_id": value.get("external_id", ""),
    }


class AthleteContextServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE competitions (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, event_date TEXT NOT NULL,
                sport TEXT NOT NULL, priority TEXT NOT NULL, distance TEXT NOT NULL,
                target TEXT NOT NULL, course_profile TEXT NOT NULL, notes TEXT NOT NULL,
                category TEXT NOT NULL, start_date_local TEXT, description TEXT NOT NULL,
                moving_time INTEGER, intervals_event_id TEXT, external_id TEXT,
                sync_dirty INTEGER NOT NULL, sync_state TEXT NOT NULL,
                sync_conflict TEXT NOT NULL, last_synced_at TEXT, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE competition_sync_tombstones (
                id TEXT PRIMARY KEY, intervals_event_id TEXT, external_id TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE change_history (
                id TEXT PRIMARY KEY, entity_type TEXT NOT NULL, entity_id TEXT NOT NULL,
                action TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL,
                before_hash TEXT NOT NULL, after_hash TEXT NOT NULL, diff TEXT NOT NULL
            );
            """
        )
        self.key_values = KeyValueRepository(lambda: "2026-09-20T12:00:00+00:00")
        self.profile_service = ProfileService(
            _Manager(self.db), ProfileRepository(self.key_values), self.key_values
        )
        self._new_ids = iter(("tombstone-1", "tombstone-2", "tombstone-3"))
        self.service = AthleteContextService(
            manager=_Manager(self.db),
            profile_service=self.profile_service,
            competition_repository=CompetitionRepository(),
            normalize_profile=normalize_profile,
            normalize_competition=_normalize_competition,
            now=lambda: "2026-09-20T12:00:00+00:00",
            new_id=lambda: next(self._new_ids),
        )

    def tearDown(self):
        self.db.close()

    def _insert_competition(
        self, competition_id, *, intervals_event_id=None, external_id=None
    ):
        self.db.execute(
            "INSERT INTO competitions "
            "(id, name, event_date, sport, priority, distance, target, course_profile, "
            "notes, category, start_date_local, description, moving_time, intervals_event_id, "
            "external_id, sync_dirty, sync_state, sync_conflict, last_synced_at, created_at, updated_at) "
            "VALUES (?, 'Old', '2026-10-01', 'Cycling', 'B', '', '', '', '', 'RACE_B', "
            "'', '', NULL, ?, ?, 0, 'synced', '', NULL, 'created-before', 'updated-before')",
            (competition_id, intervals_event_id, external_id),
        )
        self.db.commit()

    def _competition(self, competition_id):
        row = self.db.execute(
            "SELECT * FROM competitions WHERE id = ?", (competition_id,)
        ).fetchone()
        return dict(row) if row else None

    def _history(self, entity_id):
        return [
            dict(row)
            for row in self.db.execute(
                "SELECT * FROM change_history WHERE entity_type='competition' AND entity_id=?",
                (entity_id,),
            )
        ]

    def test_validates_profile_competition_list_and_maximum(self):
        cases = (
            (None, [], "Das Profil muss ein Objekt sein."),
            ({}, None, "Wettkämpfe müssen als Liste übergeben werden."),
            ({}, [{}] * 21, "Es können maximal 20 Wettkämpfe gespeichert werden."),
        )
        for profile, competitions, message in cases:
            with self.subTest(message=message), self.assertRaises(AppError) as error:
                self.service.save(profile, competitions)
            self.assertEqual(error.exception.status, 400)
            self.assertEqual(error.exception.message, message)

    def test_rejects_duplicate_normalized_ids(self):
        with self.assertRaises(AppError) as error:
            self.service.save({}, [{"id": "same"}, {"id": "same"}])
        self.assertEqual(error.exception.status, 400)
        self.assertEqual(
            error.exception.message, "Wettkampf-IDs müssen eindeutig sein."
        )

    def test_create_update_delete_history_and_remote_id_retention(self):
        self._insert_competition(
            "kept", intervals_event_id="remote-kept", external_id="external-kept"
        )
        self._insert_competition("removed-remote", external_id="external-removed")
        self._insert_competition(
            "removed-intervals", intervals_event_id="intervals-only"
        )
        self._insert_competition("removed-local")

        first = self.service.save(
            {"name": " Athlete ", "timezone": "UTC"},
            [{"id": "kept", "name": "Updated", "external_id": ""}, {"id": "new"}],
        )

        kept = self._competition("kept")
        self.assertEqual(first["profile"]["name"], "Athlete")
        self.assertEqual(kept["external_id"], "external-kept")
        self.assertEqual(kept["created_at"], "created-before")
        self.assertEqual(kept["updated_at"], "2026-09-20T12:00:00+00:00")
        self.assertEqual(kept["sync_dirty"], 1)
        self.assertEqual(kept["sync_state"], "local")
        self.assertEqual(kept["sync_conflict"], "")
        self.assertEqual([row["id"] for row in first["competitions"]], ["new", "kept"])
        tombstones = [
            dict(row)
            for row in self.db.execute("SELECT * FROM competition_sync_tombstones")
        ]
        self.assertEqual(
            {(row["intervals_event_id"], row["external_id"]) for row in tombstones},
            {(None, "external-removed"), ("intervals-only", None)},
        )
        self.assertEqual(
            {row["id"] for row in tombstones}, {"tombstone-1", "tombstone-2"}
        )
        self.assertTrue(
            all(row["created_at"] == "2026-09-20T12:00:00+00:00" for row in tombstones)
        )
        self.assertEqual(
            [(row["action"], row["entity_id"]) for row in self._history("new")],
            [("create", "new")],
        )
        self.assertEqual(
            [
                (row["action"], row["entity_id"])
                for row in self._history("removed-remote")
            ],
            [("delete", "removed-remote")],
        )
        self.assertEqual(self._history("removed-local")[0]["action"], "delete")
        create_diff = json.loads(self._history("new")[0]["diff"])
        self.assertFalse(create_diff["before_present"])
        self.assertTrue(create_diff["after_present"])
        delete_diff = json.loads(self._history("removed-remote")[0]["diff"])
        self.assertTrue(delete_diff["before_present"])
        self.assertFalse(delete_diff["after_present"])
        self.assertEqual(
            delete_diff["fields"]["name"], {"before": "Old", "after": None}
        )
        self.assertEqual(
            json.loads(self._history("kept")[0]["diff"])["fields"]["name"],
            {"before": "Old", "after": "Updated"},
        )

        second = self.service.save(
            {"name": "Athlete", "timezone": "UTC"},
            [{"id": "kept", "name": "Changed again", "external_id": ""}],
        )
        self.assertIsNone(self._competition("new"))
        self.assertEqual([row["id"] for row in second["competitions"]], ["kept"])
        self.assertEqual(
            [row["action"] for row in self._history("kept")], ["update", "update"]
        )
        self.assertEqual(self._history("new")[-1]["action"], "delete")

    def test_rolls_back_profile_tombstone_and_prior_upsert_after_later_failure(self):
        self._insert_competition("to-remove", intervals_event_id="remote-id")
        self.db.execute(
            "CREATE TRIGGER reject_later_competition BEFORE INSERT ON competitions "
            "WHEN NEW.id = 'reject' BEGIN SELECT RAISE(ABORT, 'forced failure'); END"
        )
        self.db.commit()

        with self.assertRaises(sqlite3.IntegrityError):
            self.service.save(
                {"name": "Must roll back", "timezone": "UTC"},
                [{"id": "first"}, {"id": "reject"}],
            )

        self.assertIsNone(self.key_values.get(self.db, "profile"))
        self.assertIsNone(self._competition("first"))
        self.assertIsNotNone(self._competition("to-remove"))
        self.assertEqual(
            self.db.execute(
                "SELECT COUNT(*) FROM competition_sync_tombstones"
            ).fetchone()[0],
            0,
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM change_history").fetchone()[0], 0
        )


if __name__ == "__main__":
    unittest.main()
