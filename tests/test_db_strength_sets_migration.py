"""Schema version 22: executed strength sets, upgraded in place from v21.

Releases 1.13.41 to 1.13.44 wrote v21, the oldest supported schema; the only
production database runs release 1.13.44. The upgrade rebuilds the four detail set tables so
the kind CHECK accepts ``strength_sets``. With foreign keys enforced, as the
application connects, every stream, lap, zone and analysis row stays exactly as
it was; a failure rolls back to the unchanged release and a restart changes
nothing. Temporary databases and synthetic rows only.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
import zlib
from pathlib import Path
from typing import Any
from unittest import mock

from support import connect

from backend.db import migrations
from backend.db.migrations import migrate_schema
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    database_schema_is_current,
    database_schema_signature,
)
from backend.db.schema_history import (
    SHAPE_CURRENT,
    SHAPE_SCHEMA_V21,
    released_shape,
)

FIXTURES = Path(__file__).with_name("fixtures")
RELEASES = (21,)
STAMP = "2026-11-07T08:00:00+00:00"
DIGEST = "d" * 64
TABLES = (
    "activity_detail_sets",
    "activity_stream_channels",
    "activity_laps",
    "activity_zone_times",
    "activity_detail_analysis",
)
# The columns of the v21 release; the upgrade adds set_source only.
V21_SET_COLUMNS = (
    "provider, provider_activity_id, detail_kind, mapper_version, origin, "
    "source_kind, recorded_by, source_record_id, resolution, lap_source, "
    "zone_boundary_source, summary_sha256, content_sha256, fetched_at, "
    "created_at, updated_at"
)


def populate(db: sqlite3.Connection, version: int) -> None:
    db.executescript(
        (FIXTURES / f"schema_v{version}.sql.txt").read_text(encoding="utf-8")
    )
    # executescript() runs its own transaction; enforcement applies afterwards.
    db.execute("PRAGMA foreign_keys = ON")
    populate_detail_rows(db)


def populate_detail_rows(db: Any) -> None:
    """Two sessions with streams, laps, both zone kinds and an analysis row."""
    for activity_id, provider, provider_id in (
        ("act_1", "garmin", "g1"),
        ("act_2", "wahoo", "w1"),
    ):
        db.execute(
            "INSERT INTO activity_sessions(activity_id, primary_provider, "
            "primary_provider_activity_id, started_at, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (activity_id, provider, provider_id, STAMP, STAMP, STAMP),
        )
        db.execute(
            "INSERT INTO activity_records(provider, provider_activity_id, activity_id, "
            "state, mapper_version, source_kind, recorded_by, sport, environment, "
            "started_at, load_model, fetched_at, created_at, updated_at) "
            "VALUES (?, ?, ?, 'active', 1, 'provider_reported', ?, 'ride', 'outdoor', "
            "?, 'unknown', ?, ?, ?)",
            (provider, provider_id, activity_id, provider, STAMP, STAMP, STAMP, STAMP),
        )
        for kind, resolution, lap_source, boundary in (
            ("streams", "full", None, None),
            ("laps", None, "device_laps", None),
            ("power_zones", None, None, "provider_reported"),
            ("heart_rate_zones", None, None, "profile"),
        ):
            db.execute(
                f"INSERT INTO activity_detail_sets({V21_SET_COLUMNS}) VALUES "
                "(?, ?, ?, 3, 'fetch', 'provider_reported', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    provider,
                    provider_id,
                    kind,
                    provider,
                    provider_id,
                    resolution,
                    lap_source,
                    boundary,
                    DIGEST,
                    DIGEST,
                    STAMP,
                    STAMP,
                    STAMP,
                ),
            )
        for channel, points in (("time_s", 3), ("power_w", 3)):
            db.execute(
                "INSERT INTO activity_stream_channels(provider, provider_activity_id, "
                "channel, point_count, valid_count, data) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    provider,
                    provider_id,
                    channel,
                    points,
                    points,
                    zlib.compress(bytes(8 * points)),
                ),
            )
        for index in range(2):
            db.execute(
                "INSERT INTO activity_laps(provider, provider_activity_id, lap_index, "
                "kind, start_offset_s, end_offset_s, avg_power, max_speed_mps) "
                "VALUES (?, ?, ?, 'lap', ?, ?, ?, ?)",
                (
                    provider,
                    provider_id,
                    index,
                    index * 60.0,
                    index * 60.0 + 60.0,
                    200.0 + index,
                    9.5,
                ),
            )
        for kind in ("power_zones", "heart_rate_zones"):
            for zone in (1, 2):
                db.execute(
                    "INSERT INTO activity_zone_times(provider, provider_activity_id, "
                    "detail_kind, zone_index, seconds, lower_bound, upper_bound, label) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        provider,
                        provider_id,
                        kind,
                        zone,
                        30.0 * zone,
                        zone * 100.0,
                        zone * 100.0 + 99,
                        f"Z{zone}",
                    ),
                )
        db.execute(
            "INSERT INTO activity_detail_analysis(activity_id, analysis_version, "
            "input_sha256, payload, computed_at, created_at, updated_at) "
            "VALUES (?, 1, ?, '{\"ok\": true}', ?, ?, ?)",
            (activity_id, DIGEST, STAMP, STAMP, STAMP),
        )
    db.commit()


def detail_rows(db: sqlite3.Connection) -> dict[str, list[tuple[Any, ...]]]:
    rows: dict[str, list[tuple[Any, ...]]] = {}
    for table in TABLES:
        columns = V21_SET_COLUMNS if table == "activity_detail_sets" else "*"
        rows[table] = [
            tuple(row)
            for row in db.execute(f"SELECT {columns} FROM {table} ORDER BY 1, 2, 3")
        ]
    return rows


class StrengthSetMigrationTests(unittest.TestCase):
    def released(self, version: int) -> sqlite3.Connection:
        db = connect()
        self.addCleanup(db.close)
        populate(db, version)
        return db

    def test_frozen_v21_fixture_is_the_recorded_released_shape(self) -> None:
        db = connect()
        self.addCleanup(db.close)
        db.executescript((FIXTURES / "schema_v21.sql.txt").read_text(encoding="utf-8"))
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V21
        )

    def test_every_supported_release_keeps_every_detail_row(self) -> None:
        for version in RELEASES:
            with self.subTest(version=version):
                db = self.released(version)
                before = detail_rows(db)
                self.assertEqual(len(before["activity_stream_channels"]), 4)
                migrate_schema(db)
                db.commit()
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    CURRENT_SCHEMA_VERSION,
                )
                self.assertTrue(database_schema_is_current(db))
                self.assertEqual(detail_rows(db), before)
                self.assertEqual(
                    {
                        row[0]
                        for row in db.execute(
                            "SELECT set_source FROM activity_detail_sets"
                        )
                    },
                    {None},
                )
                self.assertEqual(db.execute("PRAGMA foreign_key_check").fetchall(), [])
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM activity_strength_sets"
                    ).fetchone()[0],
                    0,
                )
                # Cascades still reach the rebuilt children.
                db.execute(
                    "DELETE FROM activity_detail_sets WHERE provider = 'wahoo' "
                    "AND detail_kind = 'laps'"
                )
                self.assertEqual(
                    db.execute(
                        "SELECT COUNT(*) FROM activity_laps WHERE provider = 'wahoo'"
                    ).fetchone()[0],
                    0,
                )
                db.rollback()

    def test_upgraded_database_accepts_strength_sets(self) -> None:
        db = self.released(21)
        migrate_schema(db)
        db.execute(
            "INSERT INTO activity_detail_sets(provider, provider_activity_id, detail_kind, "
            "mapper_version, origin, source_kind, recorded_by, set_source, content_sha256, "
            "fetched_at, created_at, updated_at) VALUES ('garmin', 'g1', 'strength_sets', "
            "4, 'fetch', 'provider_reported', 'garmin', 'fit_set_messages', ?, ?, ?, ?)",
            (DIGEST, STAMP, STAMP, STAMP),
        )
        db.execute(
            "INSERT INTO activity_strength_sets(provider, provider_activity_id, set_index, "
            "set_type, exercise_category, reps, weight_kg) "
            "VALUES ('garmin', 'g1', 0, 'active', 'squat', 5, 80.0)"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO activity_strength_sets(provider, provider_activity_id, "
                "set_index, set_type) VALUES ('garmin', 'missing', 0, 'active')"
            )

    def test_failed_upgrade_leaves_the_release_unchanged(self) -> None:
        def failing(connection: sqlite3.Connection) -> None:
            migrations._upgrade_v21_to_v22(connection)
            raise RuntimeError("injected migration failure")

        for version in RELEASES:
            with self.subTest(version=version):
                db = self.released(version)
                before = list(db.iterdump())
                with (
                    mock.patch.dict(
                        migrations.UPGRADE_STEPS,
                        {SHAPE_SCHEMA_V21: (SHAPE_CURRENT, failing)},
                    ),
                    self.assertRaisesRegex(RuntimeError, "injected"),
                ):
                    migrate_schema(db)
                db.rollback()
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], version
                )

    def test_an_orphaned_detail_row_fails_the_upgrade_without_changes(self) -> None:
        db = self.released(21)
        db.execute("PRAGMA foreign_keys = OFF")
        db.execute(
            "INSERT INTO activity_laps(provider, provider_activity_id, lap_index, kind, "
            "start_offset_s, end_offset_s) VALUES ('garmin', 'gone', 0, 'lap', 0, 1)"
        )
        db.commit()
        before = list(db.iterdump())
        with self.assertRaisesRegex(RuntimeError, "validiert"):
            migrate_schema(db)
        db.rollback()
        self.assertEqual(list(db.iterdump()), before)

    def test_upgraded_database_restarts_with_the_same_build_unchanged(self) -> None:
        for version in RELEASES:
            with self.subTest(version=version), tempfile.TemporaryDirectory() as root:
                path = Path(root) / "upgrade.db"
                db = connect(path)
                try:
                    populate(db, version)
                    migrate_schema(db)
                    db.commit()
                    upgraded = list(db.iterdump())
                finally:
                    db.close()
                reopened = connect(path)
                try:
                    migrate_schema(reopened)
                    self.assertEqual(list(reopened.iterdump()), upgraded)
                finally:
                    reopened.close()


if __name__ == "__main__":
    unittest.main()
