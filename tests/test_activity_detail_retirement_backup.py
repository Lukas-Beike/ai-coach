"""Retired kv detail records stay exported and restorable through the canonical tables."""

import json
import sqlite3
import unittest
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import legacy_detail_kv
from test_activity_detail_retirement import POINTS, RetirementTestCase

from backend.backup.database import DatabaseBackupConfig, DatabaseBackupService
from backend.backup.export import (
    PrivacyArchiveExportConfig,
    PrivacyArchiveExportService,
)
from backend.backup.restore_validation import (
    DatabaseRestoreValidationConfig,
    DatabaseRestoreValidationService,
)
from backend.canonical.vocabulary import ProviderId
from backend.db import DatabaseManager, row_factory
from backend.db.schema import configure_cipher, database_schema_is_current
from backend.performance.canonical_detail import CanonicalDetailReader
from backend.sync.activity_detail_retirement import STATE_KEY
from backend.sync.canonical_table_reader import CanonicalTableReader

ACTIVITY = "9601"
DATABASE_NAME = "detail.db"


class _Profile:
    def get_from_db(self, _db):
        return {}


class _Competitions:
    def list(self, db=None):
        return []


class _Adaptive:
    def latest_preview(self, db=None):
        return None

    def status(self, db=None):
        return {}


def read_document(manager, activity_id):
    reader = CanonicalDetailReader(
        CanonicalTableReader().session_activities,
        refreshable=lambda: frozenset({ProviderId.INTERVALS}),
    )
    with manager.reader() as db:
        return reader.read(db, activity_id)


class RetiredDetailBackupTests(RetirementTestCase):
    def setUp(self):
        super().setUp()
        self.root = Path(self.directory.name)
        self.record = self.load(ACTIVITY, points=POINTS)
        # Lap sets stored before schema v13 have no maximum speed.
        self.execute("UPDATE activity_laps SET max_speed_mps = NULL")
        counters = self.run_to_completion()
        self.assertEqual((1, 1), (counters["retired"], counters["laps_refilled"]))
        self.assertIsNone(self.kv_record(ACTIVITY))
        self.document = read_document(self.manager, ACTIVITY)
        self.assertEqual("activity_detail.v1", self.document["contract"])

    def export(self):
        config = PrivacyArchiveExportConfig(
            data_dir=self.root,
            database_path=self.root / DATABASE_NAME,
            today=lambda: date(2026, 10, 2),
            utc_now=lambda: "2026-10-02T08:00:00+00:00",
            maximum_bytes=50_000_000,
            minimum_free_bytes=0,
            time_limit_seconds=60,
            monotonic=lambda: 0.0,
            disk_usage=lambda _path: SimpleNamespace(free=10**12),
        )
        service = PrivacyArchiveExportService(
            self.manager,
            self.key_values,
            _Profile(),
            _Competitions(),
            _Adaptive(),
            config,
        )
        with patch(
            "backend.backup.export.planning_season.planning_state", return_value={}
        ):
            path = service.create_file()
        self.addCleanup(path.unlink, missing_ok=True)
        return zipfile.ZipFile(path)

    @staticmethod
    def lines(archive, name):
        return [json.loads(line) for line in archive.read(name).splitlines() if line]

    def test_privacy_export_holds_the_retired_detail_in_the_canonical_files(self):
        with self.export() as archive:
            sets = self.lines(archive, "activity_detail_sets.jsonl")
            channels = self.lines(archive, "activity_stream_channels.jsonl")
            laps = self.lines(archive, "activity_laps.jsonl")
            zones = self.lines(archive, "activity_zone_times.jsonl")
            analysis = self.lines(archive, "activity_detail_analysis.jsonl")
            state = json.loads(archive.read("application_state.json"))
        self.assertEqual(
            ["heart_rate_zones", "laps", "streams"],
            sorted(row["detail_kind"] for row in sets),
        )
        self.assertEqual(
            {row["summary_sha256"] for row in sets}, {self.record["summary_sha256"]}
        )
        streams = {row["channel"]: row["values"] for row in channels}
        self.assertEqual({"time_s", "power_w", "heart_rate_bpm"}, set(streams))
        self.assertEqual(POINTS, len(streams["power_w"]))
        # The refilled lap speed is part of the export.
        self.assertEqual(
            [("work", 11.5), ("recovery", 7.25)],
            [(row["kind"], row["max_speed_mps"]) for row in laps],
        )
        self.assertEqual([300.0, 400.0, 200.0], [row["seconds"] for row in zones])
        self.assertEqual(1, len(analysis))
        self.assertEqual(
            self.record["summary_sha256"], analysis[0]["payload"]["summary_sha256"]
        )
        self.assertNotIn(legacy_detail_kv.key(ACTIVITY), state)
        self.assertFalse([key for key in state if key.startswith("activity_detail:")])
        self.assertIn(STATE_KEY, state)

    def test_restored_backup_serves_the_same_document(self):
        backup = DatabaseBackupService(
            self.manager,
            Mock(),
            DatabaseBackupConfig(
                database_path=self.root / DATABASE_NAME,
                data_dir=self.root,
                maximum_bytes=50_000_000,
                minimum_free_bytes=0,
                time_limit_seconds=60,
                monotonic=lambda: 0.0,
                disk_usage=lambda _path: SimpleNamespace(free=10**12),
            ),
            Mock(),
        ).read_bytes()
        validation = DatabaseRestoreValidationService(
            DatabaseRestoreValidationConfig(
                data_dir=self.root / "restore",
                maximum_bytes=50_000_000,
                app_password="",
                sqlcipher_available=False,
                sqlite_backend=sqlite3,
                configure_cipher=configure_cipher,
                row_factory=row_factory,
                schema_is_current=database_schema_is_current,
            )
        )
        staged = validation.stage(backup)
        self.addCleanup(staged.unlink, missing_ok=True)
        validation.validate(staged)
        restored = DatabaseManager(staged, sqlite3, row_factory=row_factory)
        try:
            self.assertEqual(self.document, read_document(restored, ACTIVITY))
            with restored.reader() as db:
                self.assertIsNone(
                    self.key_values.get(db, legacy_detail_kv.key(ACTIVITY))
                )
        finally:
            restored.close()


if __name__ == "__main__":
    unittest.main()
