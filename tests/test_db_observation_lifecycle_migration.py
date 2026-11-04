"""Schema version 21: the observation lifecycle, upgraded in place from v20.

The only production database runs schema v20 (release 1.13.40), so v20 is the
only starting point this step is tested from. A populated v20 database keeps
every observation value and makes each row active. Rows whose raw record is
known exactly get it as their owner: Intervals.icu
wellness and Wahoo threshold rows by their source record id, other Intervals.icu
rows by the athlete record. Garmin rows and rows without a stored raw record keep
no owner. A failure rolls back to the unchanged release and a restart changes
nothing. Temporary databases and synthetic rows only.
"""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from backend.db import migrations
from backend.db.migrations import migrate_schema
from backend.db.schema import CURRENT_SCHEMA_VERSION, database_schema_is_current
from backend.db.schema_history import SHAPE_CURRENT, SHAPE_SCHEMA_V20

FIXTURES = Path(__file__).with_name("fixtures")
RELEASES = (20,)
STAMP = "2026-11-04T08:00:00+00:00"
DAY = "2026-11-01"
RAW = (
    "INSERT INTO provider_records(provider, record_kind, source_record_id, payload, "
    "payload_hash, fetched_at, mapped_version, created_at, updated_at) "
    "VALUES (?, ?, ?, '{}', ?, ?, 1, ?, ?)"
)
OBSERVATION = (
    "INSERT INTO observations(natural_key, metric, value, unit, source_kind, "
    "recorded_by, provider, source_record_id, observed_on, mapper_version, "
    "created_at, updated_at) VALUES (?, ?, ?, ?, 'provider_reported', 'unknown', "
    "?, ?, ?, 1, ?, ?)"
)
COLUMNS = (
    "natural_key, metric, value, unit, provider, source_record_id, observed_on, "
    "mapper_version, created_at, updated_at"
)
# natural key -> owner the upgrade assigns
EXPECTED_OWNERS = {
    "wellness": DAY,
    "athlete-ftp": "athlete",
    "athlete-unnamed": "athlete",
    "wellness-without-raw": None,
    "wahoo": "z1",
    "garmin": None,
}


def populated(version: int) -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        (FIXTURES / f"schema_v{version}.sql.txt").read_text(encoding="utf-8")
    )
    for provider, kind, source_id in (
        ("intervals", "wellness", DAY),
        ("intervals", "athlete", "athlete"),
        ("wahoo", "power_zones", "z1"),
        ("garmin", "health", f"resting_hr/{DAY}"),
    ):
        db.execute(RAW, (provider, kind, source_id, "0" * 64, STAMP, STAMP, STAMP))
    for key, metric, value, unit, owner_provider, observed_source in (
        ("wellness", "resting_hr", 48, "bpm", "intervals", DAY),
        ("athlete-ftp", "ftp", 250, "W", "intervals", "i1"),
        ("athlete-unnamed", "weight", 70, "kg", "intervals", None),
        ("wellness-without-raw", "resting_hr", 47, "bpm", "intervals", "2026-10-31"),
        ("wahoo", "ftp", 240, "W", "wahoo", "z1"),
        ("garmin", "resting_hr", 49, "bpm", "garmin", f"resting_hr:{DAY}"),
    ):
        db.execute(
            OBSERVATION,
            (
                key,
                metric,
                value,
                unit,
                owner_provider,
                observed_source,
                DAY,
                STAMP,
                STAMP,
            ),
        )
    db.commit()
    return db


def rows(db: sqlite3.Connection) -> list[tuple]:
    return [
        tuple(row)
        for row in db.execute(f"SELECT {COLUMNS} FROM observations ORDER BY id")
    ]


class ObservationLifecycleMigrationTests(unittest.TestCase):
    def test_every_supported_release_upgrades_with_active_owned_rows(self) -> None:
        for version in RELEASES:
            with self.subTest(version=version):
                db = populated(version)
                self.addCleanup(db.close)
                before = rows(db)
                migrate_schema(db)
                db.commit()
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    CURRENT_SCHEMA_VERSION,
                )
                self.assertTrue(database_schema_is_current(db))
                self.assertEqual(rows(db), before)
                lifecycle = {
                    row["natural_key"]: (row["state"], row["owner_record_id"])
                    for row in db.execute(
                        "SELECT natural_key, state, owner_record_id FROM observations"
                    )
                }
                self.assertEqual(
                    lifecycle,
                    {key: ("active", owner) for key, owner in EXPECTED_OWNERS.items()},
                )
                after = list(db.iterdump())
                migrate_schema(db)
                self.assertEqual(list(db.iterdump()), after)

    def test_state_accepts_only_the_projection_states(self) -> None:
        db = populated(20)
        self.addCleanup(db.close)
        migrate_schema(db)
        db.execute(
            "UPDATE observations SET state = 'retired' WHERE natural_key = 'garmin'"
        )
        with self.assertRaises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE observations SET state = 'deleted' WHERE natural_key = 'garmin'"
            )

    def test_failed_upgrade_leaves_the_release_unchanged(self) -> None:
        def failing(connection: sqlite3.Connection) -> None:
            migrations._upgrade_v20_to_v21(connection)
            raise RuntimeError("injected migration failure")

        for version in RELEASES:
            with self.subTest(version=version):
                db = populated(version)
                self.addCleanup(db.close)
                before = list(db.iterdump())
                with (
                    mock.patch.dict(
                        migrations.UPGRADE_STEPS,
                        {SHAPE_SCHEMA_V20: (SHAPE_CURRENT, failing)},
                    ),
                    self.assertRaisesRegex(RuntimeError, "injected"),
                ):
                    migrate_schema(db)
                db.rollback()
                self.assertEqual(list(db.iterdump()), before)
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0], version
                )


if __name__ == "__main__":
    unittest.main()
