"""Frozen released schema signatures, upgrade steps and version-to-shape lookup."""

import sqlite3
import unittest
from pathlib import Path

from backend.db.migrations import UPGRADE_STEPS, migrate_schema
from backend.db.schema import (
    CURRENT_SCHEMA_VERSION,
    current_schema_signature,
    database_schema_signature,
    initialize_schema,
)
from backend.db.schema_history import (
    ACCEPTED_SHAPES_BY_VERSION,
    RELEASED_SHAPE_DIGESTS,
    SHAPE_CURRENT,
    SHAPE_RELEASE_1_12_19,
    SHAPE_SCHEMA_V2,
    SHAPE_SCHEMA_V3_V4,
    released_shape,
    signature_digest,
)

FIXTURES = Path(__file__).with_name("fixtures")
FIXTURE_BY_SHAPE = {
    SHAPE_RELEASE_1_12_19: "schema_1_12_19.sql.txt",
    SHAPE_SCHEMA_V2: "schema_v2.sql.txt",
    SHAPE_SCHEMA_V3_V4: "schema_v4.sql.txt",
}
RELEASED_SHAPES = tuple(FIXTURE_BY_SHAPE)
ALL_SHAPES = (*RELEASED_SHAPES, SHAPE_CURRENT)
NEXT_SHAPE_BY_SHAPE = {
    SHAPE_RELEASE_1_12_19: SHAPE_SCHEMA_V2,
    SHAPE_SCHEMA_V2: SHAPE_SCHEMA_V3_V4,
    SHAPE_SCHEMA_V3_V4: SHAPE_CURRENT,
}
UNSUPPORTED_VERSIONS = (6, 99)


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class SchemaHistoryTests(unittest.TestCase):
    def connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        return db

    def database_for_shape(self, shape: str) -> sqlite3.Connection:
        db = self.connect()
        if shape == SHAPE_CURRENT:
            initialize_schema(db)
        else:
            db.executescript(read_fixture(FIXTURE_BY_SHAPE[shape]))
        db.commit()
        return db

    def set_user_version(self, db: sqlite3.Connection, version: int) -> None:
        db.execute(f"PRAGMA user_version = {version}")
        db.commit()

    def user_version(self, db: sqlite3.Connection) -> int:
        return int(db.execute("PRAGMA user_version").fetchone()[0])

    def test_frozen_digests_match_their_fixture_signatures(self) -> None:
        for shape in RELEASED_SHAPES:
            with self.subTest(shape=shape):
                db = self.database_for_shape(shape)
                signature = database_schema_signature(db)
                self.assertEqual(
                    signature_digest(signature), RELEASED_SHAPE_DIGESTS[shape]
                )
                self.assertEqual(released_shape(signature), shape)

    def test_release_1_12_26_fixture_shares_the_schema_v3_v4_digest(self) -> None:
        db = self.connect()
        db.executescript(read_fixture("schema_1_12_26.sql.txt"))
        self.assertEqual(
            released_shape(database_schema_signature(db)), SHAPE_SCHEMA_V3_V4
        )

    def test_live_schema_is_derived_from_code_not_frozen(self) -> None:
        self.assertIsNone(released_shape(current_schema_signature()))
        self.assertNotIn(
            signature_digest(current_schema_signature()),
            RELEASED_SHAPE_DIGESTS.values(),
        )

    def test_released_digests_are_distinct(self) -> None:
        self.assertEqual(
            len(set(RELEASED_SHAPE_DIGESTS.values())), len(RELEASED_SHAPE_DIGESTS)
        )

    def test_upgrade_steps_form_one_chain_to_the_live_schema(self) -> None:
        self.assertEqual(
            {shape: next_shape for shape, (next_shape, _) in UPGRADE_STEPS.items()},
            NEXT_SHAPE_BY_SHAPE,
        )

    def test_every_released_shape_reaches_the_live_schema_without_cycles(self) -> None:
        self.assertEqual(set(UPGRADE_STEPS), set(RELEASED_SHAPE_DIGESTS))
        for shape in RELEASED_SHAPE_DIGESTS:
            with self.subTest(shape=shape):
                visited = {shape}
                pending = shape
                while pending != SHAPE_CURRENT:
                    pending, _ = UPGRADE_STEPS[pending]
                    self.assertNotIn(pending, visited)
                    visited.add(pending)
                self.assertIn(SHAPE_CURRENT, visited)

    def test_each_upgrade_step_advances_its_shape_to_the_next(self) -> None:
        for shape in RELEASED_SHAPES:
            with self.subTest(shape=shape):
                db = self.database_for_shape(shape)
                _, step = UPGRADE_STEPS[shape]
                step(db)
                db.commit()
                signature = database_schema_signature(db)
                next_shape = NEXT_SHAPE_BY_SHAPE[shape]
                if next_shape == SHAPE_CURRENT:
                    self.assertEqual(signature, current_schema_signature())
                else:
                    self.assertEqual(released_shape(signature), next_shape)

    def test_accepted_shapes_by_version_are_exact(self) -> None:
        self.assertEqual(
            {
                version: set(shapes)
                for version, shapes in ACCEPTED_SHAPES_BY_VERSION.items()
            },
            {
                0: set(ALL_SHAPES),
                1: {SHAPE_RELEASE_1_12_19},
                2: {SHAPE_SCHEMA_V2},
                3: {SHAPE_SCHEMA_V3_V4},
                4: {SHAPE_SCHEMA_V3_V4},
                CURRENT_SCHEMA_VERSION: {SHAPE_CURRENT},
            },
        )

    def test_every_accepted_version_and_shape_pair_upgrades_to_current(self) -> None:
        for version, shapes in ACCEPTED_SHAPES_BY_VERSION.items():
            for shape in sorted(shapes):
                with self.subTest(version=version, shape=shape):
                    db = self.database_for_shape(shape)
                    self.set_user_version(db, version)
                    migrate_schema(db)
                    db.commit()
                    self.assertEqual(
                        database_schema_signature(db), current_schema_signature()
                    )
                    self.assertEqual(self.user_version(db), CURRENT_SCHEMA_VERSION)

    def test_shapes_outside_the_accepted_set_are_rejected_without_changes(self) -> None:
        for version in (*range(CURRENT_SCHEMA_VERSION + 1), *UNSUPPORTED_VERSIONS):
            accepted = ACCEPTED_SHAPES_BY_VERSION.get(version, frozenset())
            for shape in ALL_SHAPES:
                if shape in accepted:
                    continue
                with self.subTest(version=version, shape=shape):
                    db = self.database_for_shape(shape)
                    self.set_user_version(db, version)
                    before = list(db.iterdump())
                    with self.assertRaises(RuntimeError):
                        migrate_schema(db)
                    self.assertEqual(list(db.iterdump()), before)
                    self.assertEqual(self.user_version(db), version)

    def test_unknown_schema_shapes_are_rejected_without_changes(self) -> None:
        variants = {
            "released shape with an extra column": (
                read_fixture("schema_1_12_19.sql.txt")
                + "\nALTER TABLE messages ADD COLUMN unknown TEXT;"
            ),
            "schema version 2 with an extra column": (
                read_fixture("schema_v2.sql.txt")
                + "\nALTER TABLE kv ADD COLUMN unknown TEXT;"
            ),
            "schema version 4 with an unknown trigger": (
                read_fixture("schema_v4.sql.txt")
                + "\nCREATE TRIGGER sqlitecustom AFTER INSERT ON kv "
                "BEGIN SELECT 1; END;"
            ),
        }
        for label, script in variants.items():
            for version in (0, 1, 2, 3, 4, CURRENT_SCHEMA_VERSION):
                with self.subTest(shape=label, version=version):
                    db = self.connect()
                    db.executescript(script)
                    db.commit()
                    self.assertIsNone(released_shape(database_schema_signature(db)))
                    self.set_user_version(db, version)
                    before = list(db.iterdump())
                    with self.assertRaises(RuntimeError):
                        migrate_schema(db)
                    self.assertEqual(list(db.iterdump()), before)
                    self.assertEqual(self.user_version(db), version)


if __name__ == "__main__":
    unittest.main()
