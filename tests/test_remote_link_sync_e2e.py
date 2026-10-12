"""Library sync keeps remote links and legacy slots in step on an upgraded database."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import Mock

from backend.canonical.vocabulary import ProviderId, RemoteEntityKind
from backend.config import Config
from backend.db import row_factory
from backend.db.manager import DatabaseManager
from backend.db.migrations import migrate_schema
from backend.db.repositories import KeyValueRepository
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    configure_cipher,
    database_schema_is_current,
)
from backend.errors import AppError
from backend.observability import Redactor
from backend.sync.intervals_workout_export import IntervalsWorkoutExport
from backend.sync.library import (
    WorkoutLibrarySyncService,
    WorkoutLibrarySyncStateService,
)

try:
    from sqlcipher3 import dbapi2 as cipher_backend
except ImportError:
    cipher_backend = None

SCHEMA_V7 = Path(__file__).with_name("fixtures") / "schema_v7.sql.txt"
NOW = "2026-10-12T08:00:00+00:00"
SYNCED_ID = "12345678-1234-5678-1234-567812345678"
LOCAL_ID = "87654321-4321-8765-4321-876543218765"
INTERVALS = ProviderId.INTERVALS.value
LIBRARY = RemoteEntityKind.LIBRARY_WORKOUT.value


def workout(name: str) -> dict[str, Any]:
    return {
        "sport": "WeightTraining",
        "type": "WeightTraining",
        "name": name,
        "description": "Three sets of ten.",
        "duration_minutes": 30,
    }


@unittest.skipIf(
    cipher_backend is None, "SQLCipher requires the Docker runtime on Windows"
)
class RemoteLinkLibrarySyncEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        self.path = Path(self.root.name) / "encrypted.db"

    def open(self) -> DatabaseManager:
        manager = DatabaseManager(
            self.path,
            cipher_backend,
            password="synthetic-e2e-test-key",
            configure=configure_cipher,
            row_factory=row_factory,
        )
        self.addCleanup(manager.close)
        return manager

    @staticmethod
    def service(manager: DatabaseManager, client: Mock) -> WorkoutLibrarySyncService:
        config = Config(
            port=8090,
            openai_api_key="",
            openai_base_url="",
            openai_model="",
            intervals_api_key="fake-key",
            intervals_athlete_id="0",
            garmin_email="",
            garmin_password="",
            garmin_tokenstore="",
            garmin_fixture_path="",
            calendar_ical_url="",
            app_password="x" * 12,
            secure_cookies=False,
            data_retention_days=-1,
        )
        state = WorkoutLibrarySyncStateService(
            manager,
            Redactor(lambda: config),
            KeyValueRepository(lambda: NOW),
            lambda: NOW,
        )
        return WorkoutLibrarySyncService(
            config, IntervalsWorkoutExport(lambda: client), state, None
        )

    @staticmethod
    def state(db: Any) -> dict[str, Any]:
        slots = {
            row["local_id"]: row["external_id"]
            for row in db.execute(
                "SELECT local_id, external_id FROM workout_library"
            ).fetchall()
        }
        links = {
            row["local_id"]: (row["remote_external_id"], row["sync_state"])
            for row in db.execute(
                "SELECT local_id, remote_external_id, sync_state FROM remote_links "
                "WHERE provider=? AND entity_kind=?",
                (INTERVALS, LIBRARY),
            ).fetchall()
        }
        return {"slots": slots, "links": links}

    def test_upgraded_database_keeps_slot_and_link_in_one_transaction(self) -> None:
        manager = self.open()
        with manager.unit_of_work() as db:
            db.executescript(SCHEMA_V7.read_text(encoding="utf-8"))
            for local_id, external_id, name in (
                (SYNCED_ID, "ext-old", "Strength A"),
                (LOCAL_ID, None, "Strength B"),
            ):
                db.execute(
                    "INSERT INTO workout_library(id, local_id, external_id, payload, "
                    "sync_dirty, sync_state, updated_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
                    (
                        f"workout-{local_id}",
                        local_id,
                        external_id,
                        json.dumps(workout(name)),
                        "sync_error" if external_id else "local",
                        NOW,
                    ),
                )
        with manager.unit_of_work() as db:
            migrate_schema(db)
            self.assertTrue(database_schema_is_current(db))
            self.assertEqual(
                db.execute("PRAGMA user_version").fetchone()["user_version"],
                CURRENT_SCHEMA_VERSION,
            )
            upgraded = self.state(db)
        self.assertEqual(upgraded["links"], {SYNCED_ID: ("ext-old", "pending")})

        # A failing provider call changes neither slot nor link.
        client = Mock()
        client.local_today.return_value = date(2026, 10, 12)
        client.update_library_workout.side_effect = RuntimeError("provider down")
        service = self.service(manager, client)
        with self.assertRaisesRegex(RuntimeError, "provider down"):
            service.sync_entry(SYNCED_ID)
        with manager.reader() as db:
            self.assertEqual(self.state(db), upgraded)

        # A sync that assigns a new remote id updates slot and link together.
        client.get_workout_library.return_value = []
        client.create_library_workouts.return_value = [
            {**workout("Strength B"), "id": "ext-new"}
        ]
        service.sync_entry(LOCAL_ID)
        with manager.reader() as db:
            after_create = self.state(db)
        self.assertEqual(after_create["slots"][LOCAL_ID], "ext-new")
        self.assertEqual(after_create["links"][LOCAL_ID][0], "ext-new")
        self.assertEqual(after_create["slots"][SYNCED_ID], "ext-old")
        self.assertEqual(after_create["links"][SYNCED_ID][0], "ext-old")
        manager.close()

        # Re-opening neither duplicates nor changes any link.
        reopened = self.open()
        with reopened.unit_of_work() as db:
            migrate_schema(db)
            final = self.state(db)
            count = db.execute("SELECT COUNT(*) AS n FROM remote_links").fetchone()["n"]
        self.assertEqual(final, after_create)
        self.assertEqual(count, 2)

    def test_explicit_sync_edit_resync_and_readback_on_a_migrated_database(
        self,
    ) -> None:
        manager = self.open()
        with manager.unit_of_work() as db:
            db.executescript(SCHEMA_V7.read_text(encoding="utf-8"))
            db.execute(
                "INSERT INTO workout_library(id, local_id, external_id, payload, "
                "sync_dirty, sync_state, updated_at) VALUES (?, ?, NULL, ?, 1, 'local', ?)",
                (
                    f"workout-{LOCAL_ID}",
                    LOCAL_ID,
                    json.dumps(workout("Strength B")),
                    NOW,
                ),
            )
            migrate_schema(db)
        client = Mock()
        client.local_today.return_value = date(2026, 10, 12)
        client.get_workout_library.return_value = []
        client.create_library_workouts.return_value = [
            {**workout("Strength B"), "id": "ext-1"}
        ]
        service = self.service(manager, client)

        # Nothing reaches the provider before the explicit sync action.
        client.create_library_workouts.assert_not_called()

        # Create: the remote id lands in slot, payload and link together.
        service.sync_entry(LOCAL_ID)
        client.create_library_workouts.assert_called_once()
        with manager.reader() as db:
            created = self.state(db)
        self.assertEqual(created["slots"][LOCAL_ID], "ext-1")
        self.assertEqual(created["links"][LOCAL_ID], ("ext-1", "pending"))

        # Edit: a local edit reopens the entry; the resync updates the same id.
        edited = workout("Strength B edited")
        with manager.unit_of_work() as db:
            db.execute(
                "UPDATE workout_library SET payload=?, sync_dirty=1, "
                "sync_state='local' WHERE local_id=?",
                (json.dumps({**edited, "external_id": "ext-1"}), LOCAL_ID),
            )
        client.update_library_workout.return_value = {**edited, "id": "ignored"}
        service.sync_entry(LOCAL_ID)
        client.update_library_workout.assert_called_once()
        self.assertEqual(client.update_library_workout.call_args.args[0], "ext-1")
        client.create_library_workouts.assert_called_once()
        with manager.reader() as db:
            resynced = self.state(db)
            row = db.execute(
                "SELECT sync_state, sync_dirty, payload FROM workout_library "
                "WHERE local_id=?",
                (LOCAL_ID,),
            ).fetchone()
        self.assertEqual(resynced, created)
        self.assertEqual((row["sync_state"], row["sync_dirty"]), ("synced", 0))
        self.assertEqual(json.loads(row["payload"])["name"], "Strength B edited")

        # Readback: a wrongly confirmed sport keeps the identity and flags the error.
        with manager.unit_of_work() as db:
            db.execute(
                "UPDATE workout_library SET sync_dirty=1, sync_state='local' "
                "WHERE local_id=?",
                (LOCAL_ID,),
            )
        client.update_library_workout.return_value = {**edited, "type": "Run"}
        with self.assertRaises(AppError) as mismatch:
            service.sync_entry(LOCAL_ID)
        self.assertEqual(mismatch.exception.status, 502)
        with manager.reader() as db:
            failed = self.state(db)
            state = db.execute(
                "SELECT sync_state FROM workout_library WHERE local_id=?", (LOCAL_ID,)
            ).fetchone()["sync_state"]
        self.assertEqual(state, "sync_error")
        self.assertEqual(failed, created)

        # The flow never deletes remotely.
        client.delete.assert_not_called()
        client.delete_event.assert_not_called()


if __name__ == "__main__":
    unittest.main()
