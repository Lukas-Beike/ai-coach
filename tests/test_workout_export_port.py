"""Planned-calendar orchestration driven only through the WorkoutExportPort.

The fake target below contains no Intervals.icu code. These tests pin that the
use cases write remotely only from explicit sync_entry/repair_entry calls and
reach the target exclusively through the port methods.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import date
from pathlib import Path
from typing import cast

from backend.config import Config
from backend.db import DatabaseManager, row_factory
from backend.observability import Redactor
from backend.planning import library
from backend.planning.revision import PlanningRevisionService
from backend.sync.planned_calendar import (
    PlannedCalendarRepairService,
    PlannedCalendarSyncService,
)
from backend.sync.reconcile import PlannedUnitSyncStateWriter
from backend.sync.workout_export import WorkoutExportCapabilities, WorkoutExportPort

TODAY = date(2026, 9, 20)
LOCAL_ID = "12345678-1234-5678-1234-567812345678"


class RedactorStub:
    def redact_text(self, value: str) -> str:
        return value


class RevisionCounterStub:
    def bump(self, _db) -> None:
        return None


class FakeExportTarget:
    """Records every port call; never touches a remote service."""

    capabilities = WorkoutExportCapabilities(planned_events=True)

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.upserts: list[list[dict]] = []
        self.deleted: list[str] = []
        self.remote: dict[str, dict] = {}

    def serialize(self, local_id, workout, *, today):
        self.calls.append("serialize")
        return {
            "external_id": f"intervals-coach-{local_id}",
            "name": workout["name"],
            "type": workout["sport"],
            "start_date_local": f"{workout['date']}T06:00:00",
        }

    def upsert(self, payloads):
        self.calls.append("upsert")
        self.upserts.append(payloads)
        saved = []
        for payload in payloads:
            event = {**payload, "id": "remote-1", "type": "WeightTraining"}
            self.remote["remote-1"] = event
            saved.append(event)
        return saved

    def delete(self, remote_id):
        self.calls.append("delete")
        self.deleted.append(remote_id)
        self.remote.pop(remote_id, None)

    def read_event(self, remote_id):
        self.calls.append("read_event")
        return self.remote.get(remote_id)

    def list_window(self, *, oldest, newest):
        self.calls.append("list_window")
        return list(self.remote.values())

    def verify_readback(self, workout, remote):
        self.calls.append("verify_readback")


class WorkoutExportPortOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.temporary_directory.name) / "port.db",
            sqlite3,
            row_factory=row_factory,
        )
        with self.manager.unit_of_work() as db:
            db.execute(
                "CREATE TABLE planned_units (id TEXT, local_id TEXT PRIMARY KEY, payload TEXT NOT NULL, "
                "sync_dirty INTEGER NOT NULL DEFAULT 1, sync_state TEXT NOT NULL DEFAULT 'local', "
                "sync_error TEXT, sync_conflict TEXT NOT NULL DEFAULT '', external_id TEXT, "
                "baseline_hash TEXT, last_synced_at TEXT, created_at TEXT, updated_at TEXT)"
            )
        self.target = FakeExportTarget()
        self.writer = PlannedUnitSyncStateWriter(
            cast(PlanningRevisionService, RevisionCounterStub()),
            cast(Redactor, RedactorStub()),
        )
        self.config = Config(
            port=8090,
            openai_api_key="",
            openai_base_url="https://api.openai.com/v1",
            openai_model="test",
            intervals_api_key="api-key",
            intervals_athlete_id="athlete/1",
            garmin_email="",
            garmin_password="",
            garmin_tokenstore="",
            garmin_fixture_path="",
            calendar_ical_url="",
            app_password="",
            secure_cookies=False,
            data_retention_days=365,
        )

    def tearDown(self) -> None:
        self.manager.close()
        self.temporary_directory.cleanup()

    def sync_service(self) -> PlannedCalendarSyncService:
        return PlannedCalendarSyncService(
            self.config,
            self.manager,
            self.target,
            self.writer,
            lambda: "2026-09-20T12:00:00+00:00",
            lambda: TODAY,
        )

    def repair_service(self) -> PlannedCalendarRepairService:
        return PlannedCalendarRepairService(
            self.manager,
            self.target,
            self.writer,
            lambda: "2026-09-20T12:00:00+00:00",
            lambda: TODAY,
            35,
        )

    def add_unit(self, **changes) -> None:
        payload = {
            "date": TODAY.isoformat(),
            "sport": "WeightTraining",
            "name": "Strength",
            "description": "Oberkoerperkraft: 3x8 Wiederholungen",
            "duration_minutes": 35,
            "target": "AUTO",
            **changes,
        }
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO planned_units(local_id, payload, sync_state) VALUES (?, ?, 'local')",
                (LOCAL_ID, json.dumps(payload, ensure_ascii=False)),
            )

    def unit(self):
        with self.manager.reader() as db:
            return db.execute(
                "SELECT * FROM planned_units WHERE local_id=?", (LOCAL_ID,)
            ).fetchone()

    def test_constructing_services_and_creating_batches_never_writes(self):
        self.add_unit()
        self.sync_service()
        repair = self.repair_service()
        repair.create_batch([{"library_workout_id": LOCAL_ID}])
        self.assertEqual(self.target.calls, [])
        self.assertEqual(self.unit()["sync_state"], "local")

    def test_sync_entry_is_the_explicit_write_path(self):
        self.add_unit()
        self.assertIsInstance(self.target, WorkoutExportPort)
        result = self.sync_service().sync_entry(LOCAL_ID)

        self.assertEqual(result["id"], "remote-1")
        self.assertEqual(len(self.target.upserts), 1)
        self.assertEqual(self.target.deleted, [])
        self.assertEqual(self.unit()["sync_state"], "synced")
        self.assertEqual(
            json.loads(self.unit()["payload"])["remote_event_id"], "remote-1"
        )

    def test_archived_unit_deletes_only_after_explicit_sync_call(self):
        self.add_unit(archived=True, remote_event_id="remote-1")
        self.target.remote["remote-1"] = {
            "id": "remote-1",
            "category": "WORKOUT",
            "start_date_local": TODAY.isoformat() + "T06:00:00",
        }
        service = self.sync_service()
        self.assertEqual(self.target.deleted, [])

        self.assertIsNone(service.sync_entry(LOCAL_ID))
        self.assertEqual(self.target.deleted, ["remote-1"])
        self.assertEqual(self.target.upserts, [])

    def test_repair_entry_writes_only_when_called(self):
        self.add_unit()
        service = self.repair_service()
        batch = service.create_batch([{"library_workout_id": LOCAL_ID}])
        self.assertEqual(self.target.upserts, [])

        service.repair_entry(LOCAL_ID, self.payload_hash(), batch=batch)
        self.assertEqual(len(self.target.upserts), 1)
        self.assertIn("list_window", self.target.calls)
        self.assertEqual(self.target.deleted, [])

    def payload_hash(self) -> str:
        return library.library_payload_hash(self.unit()["payload"])


if __name__ == "__main__":
    unittest.main()
