"""Schema version 17: the canonical power curve table, upgraded in place.

Populated databases of every released schema (v9 to v16) hold synthetic
snapshots, the newest with a stored Intervals.icu power curve. The upgrade adds
the empty ``power_curve_points`` table and keeps that curve as an unmapped raw
record; every other row stays exactly as it was. A failure rolls back to the
unchanged release, a restart changes nothing, an older backup restores through
validation, and an installation whose backfill completed before the upgrade
shows the same chart points afterwards. Temporary databases and synthetic rows
only.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest import mock
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from test_power_curve_canonical import ENVELOPE, chart, legacy_chart

from backend.backup.restore_validation import (
    DatabaseRestoreValidationConfig,
    DatabaseRestoreValidationService,
)
from backend.db import DatabaseManager, migrations, row_factory
from backend.db.migrations import migrate_schema
from backend.db.repositories import KeyValueRepository
from backend.db.schema import CURRENT_SCHEMA_VERSION, database_schema_is_current
from backend.db.schema_history import SHAPE_CURRENT, SHAPE_SCHEMA_V16
from backend.performance.canonical_inputs import read_performance_inputs
from backend.providers.canonical_plans import current_mapper_versions
from backend.providers.intervals_power_curve_mapping import map_intervals_power_curve
from backend.sync.canonical_backfill import (
    COUNTER_NAMES,
    STATE_KEY,
    CanonicalBackfill,
    ReadState,
    read_state,
)
from backend.sync.canonical_read_selector import CanonicalReadSelector
from backend.sync.canonical_table_reader import CanonicalTableReader

FIXTURES = Path(__file__).with_name("fixtures")
RELEASED = {
    version: FIXTURES / f"schema_v{version}.sql.txt" for version in range(9, 17)
}
V16_FIXTURE = RELEASED[16]
ZONE = ZoneInfo("Europe/Berlin")
TODAY = date(2026, 10, 20)
SYNCED_AT = "2026-10-20T06:00:00+00:00"
OLDER_SYNC = "2026-10-19T06:00:00+00:00"
OLDER_CURVE = {**ENVELOPE, "points": ENVELOPE["points"][:1]}
NEWEST_SNAPSHOT = {
    "synced_at": SYNCED_AT,
    "raw_provider_data": {"wellness": []},
    "cycling_power_profile": ENVELOPE,
}
POWER_CURVE_VERSION_KEY = "intervals.power_curve"


def insert_snapshot(db: Any, payload: dict[str, Any]) -> None:
    db.execute(
        "INSERT INTO snapshots(payload, created_at, synced_at, recent_activity_count) "
        "VALUES (?, ?, ?, 0)",
        (json.dumps(payload), payload["synced_at"], payload["synced_at"]),
    )


def populated_power_curve_database(db: Any, fixture: Path = V16_FIXTURE) -> Any:
    """A released database whose newest snapshot stores a power curve."""
    db.executescript(fixture.read_text(encoding="utf-8"))
    db.execute(
        "INSERT INTO messages(role, content, created_at) VALUES ('user', 'Hallo', ?)",
        (SYNCED_AT,),
    )
    insert_snapshot(
        db,
        {
            "synced_at": OLDER_SYNC,
            "raw_provider_data": {"wellness": []},
            "cycling_power_profile": OLDER_CURVE,
        },
    )
    insert_snapshot(db, NEWEST_SNAPSHOT)
    db.commit()
    return db


def connect(path: Path | str = ":memory:") -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
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


def raw_curve_rows(db: Any) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in db.execute(
            "SELECT provider, source_record_id, payload, mapped_version, fetched_at, "
            "state FROM provider_records WHERE record_kind = 'power_curve'"
        )
    ]


class PowerCurveMigrationTests(unittest.TestCase):
    def released(self, fixture: Path = V16_FIXTURE) -> sqlite3.Connection:
        db = connect()
        self.addCleanup(db.close)
        return populated_power_curve_database(db, fixture)

    def test_every_populated_release_keeps_its_rows_and_its_newest_curve(self):
        for version, fixture in RELEASED.items():
            with self.subTest(version=version):
                db = self.released(fixture)
                before = all_rows(db)
                migrate_schema(db)
                db.commit()
                self.assertTrue(database_schema_is_current(db))
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    CURRENT_SCHEMA_VERSION,
                )
                after = all_rows(db)
                for table, rows in before.items():
                    if table != "provider_records":
                        self.assertEqual(after[table], rows, table)
                self.assertEqual(before["provider_records"], [])
                self.assertEqual(after["power_curve_points"], [])
                (raw,) = raw_curve_rows(db)
                self.assertEqual(json.loads(raw.pop("payload")), ENVELOPE)
                self.assertEqual(
                    raw,
                    {
                        "provider": "intervals",
                        "source_record_id": "power_curve",
                        "mapped_version": 0,
                        "fetched_at": SYNCED_AT,
                        "state": "active",
                    },
                )
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_a_release_without_a_stored_curve_only_adds_the_empty_table(self):
        for payload in (
            None,
            {"synced_at": SYNCED_AT},
            {**NEWEST_SNAPSHOT, "cycling_power_profile": {}},
        ):
            with self.subTest(payload=payload):
                db = connect()
                self.addCleanup(db.close)
                db.executescript(V16_FIXTURE.read_text(encoding="utf-8"))
                if payload is not None:
                    insert_snapshot(db, payload)
                db.commit()
                migrate_schema(db)
                db.commit()
                self.assertEqual(raw_curve_rows(db), [])
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM power_curve_points").fetchone()[0],
                    0,
                )

    def test_failure_after_the_step_rolls_back_to_the_unchanged_release(self):
        for version in (16, 9):
            with self.subTest(version=version):
                db = self.released(RELEASED[version])
                before = list(db.iterdump())
                copied = []

                def failing_step(connection, copied=copied):
                    migrations._upgrade_v16_to_v17(connection)
                    copied.extend(raw_curve_rows(connection))
                    raise RuntimeError("injected migration failure")

                with (
                    mock.patch.dict(
                        migrations.UPGRADE_STEPS,
                        {SHAPE_SCHEMA_V16: (SHAPE_CURRENT, failing_step)},
                    ),
                    self.assertRaisesRegex(RuntimeError, "injected"),
                ):
                    migrate_schema(db)
                db.rollback()
                self.assertEqual(len(copied), 1)
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], version
                )

    def test_upgraded_database_restarts_with_the_same_build_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "upgrade.db"
            with closing(connect(path)) as db:
                populated_power_curve_database(db)
                migrate_schema(db)
                db.commit()
                upgraded = list(db.iterdump())
            with closing(connect(path)) as reopened:
                migrate_schema(reopened)
                self.assertEqual(list(reopened.iterdump()), upgraded)

    def test_v16_version_and_shape_must_belong_together(self):
        for version in (CURRENT_SCHEMA_VERSION, 15):
            with self.subTest(version=version):
                db = self.released()
                db.execute(f"PRAGMA user_version = {version}")
                db.commit()
                before = list(db.iterdump())
                with self.assertRaises(RuntimeError):
                    migrate_schema(db)
                self.assertEqual(list(db.iterdump()), before)

    def test_restore_of_a_populated_v16_backup_upgrades_through_validation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "backup.db"
            with closing(connect(path)) as db:
                populated_power_curve_database(db)
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
                self.assertEqual(len(raw_curve_rows(db)), 1)


class CompletedBackfillUpgradeTests(unittest.TestCase):
    """An installation whose backfill completed under schema 16 keeps its chart."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "installed.db"
        with closing(connect(path)) as db:
            populated_power_curve_database(db)
        self.manager = DatabaseManager(path, sqlite3, row_factory=row_factory)
        self.addCleanup(self.manager.close)
        self.key_values = KeyValueRepository(lambda: SYNCED_AT)

    def completed_v16_state(self) -> dict[str, Any]:
        versions = current_mapper_versions()
        del versions[POWER_CURVE_VERSION_KEY]
        return {
            "status": "complete",
            "phase": "reproject",
            "garmin_done": True,
            "snapshot_before": 1,
            "newest_id": 2,
            "current": None,
            "reproject_after": 0,
            "reproject_current": None,
            "batches": 3,
            "counters": {
                provider: dict.fromkeys(COUNTER_NAMES, 0)
                for provider in ("intervals", "garmin")
            },
            "versions": versions,
            "zone": str(ZONE),
            "reproject_all": False,
            "completed_once": True,
            "first_completed_at": OLDER_SYNC,
        }

    def test_the_chart_shows_the_snapshot_curve_after_the_backfill(self) -> None:
        with self.manager.unit_of_work() as db:
            migrate_schema(db)
            self.key_values.set(db, STATE_KEY, json.dumps(self.completed_v16_state()))
        selector = CanonicalReadSelector(
            table=CanonicalTableReader(),
            reprojecting_table=CanonicalTableReader(),
            key_values=self.key_values,
            zone=lambda _db: ZONE,
            compact_only=lambda _db: False,
        )
        with self.manager.reader() as db:
            self.assertIs(
                read_state(self.key_values, db, zone=ZONE),
                ReadState.TABLES_REPROJECTING,
            )
        backfill = CanonicalBackfill(
            key_values=self.key_values,
            zone_provider=lambda: ZONE,
            clock=lambda: SYNCED_AT,
        )
        for _ in range(100):
            with self.manager.unit_of_work() as db:
                if backfill.run_batch(db).done:
                    break
        with self.manager.reader() as db:
            self.assertIs(read_state(self.key_values, db, zone=ZONE), ReadState.TABLES)
            inputs = read_performance_inputs(
                selector, db, activity_reader=selector, as_of=TODAY
            )
            self.assertEqual(
                raw_curve_rows(db)[0]["mapped_version"],
                current_mapper_versions()[POWER_CURVE_VERSION_KEY],
            )
        assert inputs is not None
        self.assertEqual(
            inputs.power_curve,
            map_intervals_power_curve(
                ENVELOPE,
                source_record_id="power_curve",
                fetched_at=datetime.fromisoformat(SYNCED_AT),
                zone=ZONE,
            ),
        )
        start = TODAY - timedelta(days=89)
        self.assertEqual(
            chart(inputs.power_curve), legacy_chart(NEWEST_SNAPSHOT, start, TODAY)
        )


if __name__ == "__main__":
    unittest.main()
