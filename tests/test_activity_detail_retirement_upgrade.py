"""Populated released schemas upgrade, then retire the kv detail records canonical proves."""

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from typing import ClassVar
from unittest.mock import Mock, patch

import legacy_detail_kv
from activity_row_support import FixedActivityRows
from canonical_detail_support import NOW, open_manager, seed_intervals_activity
from test_activity_detail_retirement import (
    POINTS,
    RecordingWriter,
    provider_detail,
    provider_streams,
)

from backend.activities.detail_contract import ACTIVITY_DETAIL_CONTRACT
from backend.activities.detail_store import ActivityDetailStore
from backend.canonical.vocabulary import LapKind, ProviderId
from backend.db import DatabaseManager, row_factory
from backend.db.activity_detail_store import detail_sets_for
from backend.db.migrations import migrate_schema
from backend.db.repositories import KeyValueRepository
from backend.db.schema import CURRENT_SCHEMA_VERSION, configure_cipher
from backend.performance.canonical_detail import CanonicalDetailReader
from backend.providers.intervals_activity_detail_projection import _downsample_series
from backend.runtime.maintenance import MaintenanceGate
from backend.sync import activity_detail_retirement
from backend.sync.activity_detail_retirement import STATE_KEY
from backend.sync.activity_details import ActivityDetailRefreshService
from backend.sync.canonical_backfill_assembly import build_canonical_backfill
from backend.sync.canonical_backfill_worker import CanonicalBackfillWorker
from backend.sync.canonical_table_reader import CanonicalTableReader

try:
    from sqlcipher3 import dbapi2 as cipher_backend
except ImportError:
    cipher_backend = None

FIXTURES = Path(__file__).with_name("fixtures")
RELEASED_VERSIONS = (9, 10, 11, 12, 13)
PASSWORD = "synthetic-retirement-upgrade-key"
FULL = "9501"
DOWNSAMPLED = "9502"
PRE_V13_LAPS = "9503"
UNVERIFIABLE = "9504"
UNLINKED = "9599"
RETIRED_IDS = (FULL, DOWNSAMPLED, PRE_V13_LAPS)
SEEDED_IDS = (*RETIRED_IDS, UNVERIFIABLE)
# Parents first, so the copied rows keep their references.
COPIED_TABLES = (
    "activity_sessions",
    "activity_records",
    "activity_detail_sets",
    "activity_stream_channels",
    "activity_laps",
    "activity_zone_times",
    "activity_detail_analysis",
)
CANONICAL_TABLES = COPIED_TABLES[2:]
DETAIL_PREFIX = "activity_detail:"


def _columns(db, table):
    return [row[1] for row in db.execute(f"PRAGMA table_info({table})")]


class ReleasedSource:
    """Detail data as the current build stores it, ready to copy into an older schema."""

    def __init__(self, directory):
        self.manager = open_manager(directory, "source.db")
        self.store = ActivityDetailStore(self.manager)
        self.records = {}
        self.load(FULL, POINTS)
        record = self.load(DOWNSAMPLED, POINTS)
        # An earlier release kept the projection's downsampled series.
        record["activity"]["streams"] = {
            key: _downsample_series(values)
            for key, values in record["activity"]["streams"].items()
        }
        record["full_resolution"] = False
        self.load(PRE_V13_LAPS, 12)
        record = self.load(UNVERIFIABLE, 12)
        # Two aliases of one channel: deleting the record would lose one series.
        record["activity"]["streams"]["temp"] = [14] * 12
        record["activity"]["streams"]["temperature"] = [15] * 12
        unlinked = json.loads(json.dumps(self.records[FULL]))
        unlinked["activity_id"] = UNLINKED
        self.records[UNLINKED] = unlinked

    def load(self, activity_id, points):
        seed_intervals_activity(self.manager, activity_id)
        responses = {
            f"/activity/{activity_id}": provider_detail(activity_id),
            f"/activity/{activity_id}/streams.json": provider_streams(points),
        }
        api = Mock()
        api.get.side_effect = lambda path, params=None: responses[path]
        writer = RecordingWriter()
        ActivityDetailRefreshService(
            api_client=api,
            database_manager=self.manager,
            row_reader=FixedActivityRows([{"id": activity_id}]),
            store=self.store,
            utc_now=lambda: "2026-10-02T08:00:00Z",
            configured=True,
            canonical=writer,
        ).refresh(activity_id)
        self.records[activity_id] = writer.records[activity_id]
        return self.records[activity_id]

    def copy_into(self, target):
        """Insert the source rows a released schema can hold, plus the kv records."""
        with self.manager.reader() as db:
            for table in COPIED_TABLES:
                columns = _columns(target, table)
                if not columns:
                    continue
                for row in db.execute(f"SELECT * FROM {table}"):
                    names = [name for name in columns if name in row]
                    target.execute(
                        f"INSERT INTO {table} ({', '.join(names)}) "
                        f"VALUES ({', '.join('?' * len(names))})",
                        [row[name] for name in names],
                    )
        for activity_id, record in self.records.items():
            target.execute(
                "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, ?)",
                (legacy_detail_kv.key(activity_id), json.dumps(record), NOW),
            )


class RetirementUpgradeTestCase(unittest.TestCase):
    backend = sqlite3
    options: ClassVar[dict] = {}

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = ReleasedSource(self.directory.name)
        self.addCleanup(self.source.manager.close)
        self.key_values = KeyValueRepository(lambda: NOW)

    def connect(self, path):
        db = self.backend.connect(str(path))
        if self.options:
            configure_cipher(db, PASSWORD)
        return db

    def released_database(self, version):
        path = Path(self.directory.name) / f"released_v{version}.db"
        with closing(self.connect(path)) as db:
            fixture = FIXTURES / f"schema_v{version}.sql.txt"
            db.executescript(fixture.read_text(encoding="utf-8"))
            self.source.copy_into(db)
            if version == 13:
                # A lap set stored before v13 gained the column but no value.
                db.execute(
                    "UPDATE activity_laps SET max_speed_mps = NULL "
                    "WHERE provider_activity_id = ?",
                    (PRE_V13_LAPS,),
                )
            db.commit()
        return path

    def open(self, path):
        manager = DatabaseManager(
            path, self.backend, row_factory=row_factory, **self.options
        )
        with manager.unit_of_work() as db:
            migrate_schema(db)
            version = db.execute("PRAGMA user_version").fetchone()["user_version"]
        self.assertEqual(CURRENT_SCHEMA_VERSION, version)
        return manager

    def assembly(self, manager):
        return build_canonical_backfill(
            database=lambda: manager,
            key_values=self.key_values,
            zone_provider=lambda: None,
            maintenance_gate=MaintenanceGate(),
            clock=lambda: NOW,
        )

    def dump(self, manager):
        """Canonical rows and every kv value except the stage states."""
        with manager.reader() as db:
            tables = [
                [
                    tuple(row.values())
                    for row in db.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3")
                ]
                for table in CANONICAL_TABLES
            ]
            kv = [
                (row["key"], row["value"])
                for row in db.execute(
                    "SELECT key, value FROM kv WHERE key NOT LIKE '%_state' ORDER BY key"
                )
            ]
        return tables, kv

    def detail_keys(self, manager):
        return {
            key for key, _ in self.dump(manager)[1] if key.startswith(DETAIL_PREFIX)
        }

    def counters(self, manager):
        with manager.reader() as db:
            return json.loads(self.key_values.get(db, STATE_KEY))

    def interrupt_retirement(self, manager):
        """Copy the kv-only records, then fail the retirement in its first batch."""
        assembly = self.assembly(manager)
        CanonicalBackfillWorker(
            backfill=assembly.status_reader,
            database=lambda: manager,
            maintenance_gate=MaintenanceGate(),
            poll_seconds=0,
            followups=(assembly.detail_backfill,),
        ).run_loop()
        before = self.dump(manager)
        real = activity_detail_retirement._retire
        calls = []

        def retire(db, record, now):
            calls.append(record)
            if len(calls) == 2:
                raise RuntimeError("simulated retirement failure")
            return real(db, record, now)

        with (
            patch.object(activity_detail_retirement, "_retire", retire),
            self.assertLogs("backend.sync.canonical_backfill_worker", "ERROR"),
        ):
            self.assembly(manager).worker.run_loop()
        self.assertEqual(2, len(calls))
        self.assertEqual(before, self.dump(manager))
        state = self.counters(manager)
        self.assertEqual(("failed", "", 0), (state["status"], state["cursor"], state["batches"]))

    def assert_retired(self, manager, version):
        keys = {legacy_detail_kv.key(item) for item in (UNVERIFIABLE, UNLINKED)}
        self.assertEqual(keys, self.detail_keys(manager))
        state = self.counters(manager)
        self.assertEqual("complete", state["status"])
        counters = {name: value for name, value in state["counters"].items() if value}
        # Before v13 no lap set had a maximum speed; v13 lacks it only for one.
        refilled = {9: 0, 13: 1}.get(version, len(RETIRED_IDS))
        expected = {"retired": 3, "unmapped_stream": 1, "no_record": 1}
        if refilled:
            expected["laps_refilled"] = refilled
        self.assertEqual(expected, counters)
        reader = CanonicalDetailReader(
            CanonicalTableReader().session_activities,
            refreshable=lambda: frozenset({ProviderId.INTERVALS}),
        )
        with manager.reader() as db:
            for activity_id in SEEDED_IDS:
                document = reader.read(db, activity_id)
                self.assertEqual(ACTIVITY_DETAIL_CONTRACT, document["contract"])
                self.assertTrue(document["streams"])
                self.assertEqual(2, len(document["laps"]["laps"]))
                self.assertTrue(document["zones"])
            laps = {
                item.detail.kind.value: item.detail
                for item in detail_sets_for(db, ProviderId.INTERVALS.value, PRE_V13_LAPS)
            }["laps"].laps
            origins = {
                row["origin"]
                for row in db.execute("SELECT DISTINCT origin FROM activity_detail_sets")
            }
        self.assertEqual([11.5, 7.25], [lap.max_speed_mps for lap in laps])
        if version == 9:
            # The schema had no detail tables, so the detail backfill copied kv.
            self.assertEqual({"legacy_backfill"}, origins)
        else:
            self.assertEqual([LapKind.WORK, LapKind.RECOVERY], [lap.kind for lap in laps])
            self.assertEqual({"fetch"}, origins)

    def run_upgrade(self, version):
        path = self.released_database(version)
        manager = self.open(path)
        try:
            self.interrupt_retirement(manager)
            self.assembly(manager).worker.run_loop()
            self.assert_retired(manager, version)
            after = self.dump(manager)
        finally:
            manager.close()
        # A same-build restart migrates nothing and retires nothing again.
        manager = self.open(path)
        try:
            self.assembly(manager).worker.run_loop()
            self.assertEqual(after, self.dump(manager))
            self.assert_retired(manager, version)
        finally:
            manager.close()
        return path

    def test_released_schemas_upgrade_and_retire_proven_records(self):
        for version in RELEASED_VERSIONS:
            with self.subTest(schema=version):
                self.run_upgrade(version)


@unittest.skipIf(
    cipher_backend is None, "SQLCipher requires the Docker runtime on Windows"
)
class EncryptedRetirementUpgradeTests(RetirementUpgradeTestCase):
    backend = cipher_backend
    options: ClassVar[dict] = {"password": PASSWORD, "configure": configure_cipher}

    def test_released_schemas_upgrade_and_retire_proven_records(self):
        for version in RELEASED_VERSIONS:
            with self.subTest(schema=version):
                path = self.run_upgrade(version)
                self.assertNotEqual(path.read_bytes()[:16], b"SQLite format 3\x00")


if __name__ == "__main__":
    unittest.main()
