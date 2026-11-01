"""Migration of locally stored planning metrics from released schemas."""

import json
import sqlite3
import unittest
from pathlib import Path
from unittest import mock

from backend.db import migrations
from backend.db.planning_metrics_migration import (
    _adjustment,
    _artifact,
    _conflict,
    _detail,
)
from backend.db.schema import CURRENT_SCHEMA_VERSION
from backend.planning.planned_units import planned_unit_payload_hash
from backend.providers.intervals_workouts import planning_fields_from_intervals


class PlanningMetricsMigrationTests(unittest.TestCase):
    def test_nested_planning_records_and_target_snapshots_are_rewritten(self):
        old = {"icu_training_load": 12, "icu_intensity": 0.7}
        new = {"planned_load": 12, "planned_intensity": 0.7}
        self.assertEqual(_conflict({"remote": old}), {"remote": new})
        self.assertEqual(_artifact({"workouts": [old]}), {"workouts": [new]})
        self.assertEqual(
            _adjustment({"changes": [{"payload": old}]}),
            {"changes": [{"payload": new}]},
        )
        detail = {"target_snapshot": {"basis": {"icu_ftp": 250}}, "other": old}
        self.assertEqual(
            _detail(detail),
            {"target_snapshot": {"basis": {"ftp": 250}}, "other": old},
        )

    def test_provider_and_local_payloads_keep_the_same_sync_hash(self):
        provider = {"name": "Tempo", "icu_training_load": 42, "icu_intensity": 0.8}
        local = planning_fields_from_intervals(provider)
        self.assertEqual(
            planned_unit_payload_hash(provider), planned_unit_payload_hash(local)
        )

    def database(self, version):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        self.addCleanup(db.close)
        fixture = Path(__file__).with_name("fixtures") / f"schema_v{version}.sql.txt"
        db.executescript(fixture.read_text(encoding="utf-8"))
        payload = json.dumps(
            {"name": "Tempo", "icu_training_load": 42, "icu_intensity": 0.8}
        )
        db.execute(
            "INSERT INTO planned_units(id, local_id, payload, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("one", "one", payload, "now", "now"),
        )
        db.commit()
        return db

    def test_populated_supported_releases_upgrade_and_restart(self):
        for version in (16, 17, 18):
            with self.subTest(version=version):
                db = self.database(version)
                migrations.migrate_schema(db)
                db.commit()
                row = db.execute(
                    "SELECT payload FROM planned_units WHERE id = 'one'"
                ).fetchone()
                self.assertEqual(
                    json.loads(row[0]),
                    {"name": "Tempo", "planned_load": 42, "planned_intensity": 0.8},
                )
                self.assertEqual(
                    db.execute("PRAGMA user_version").fetchone()[0],
                    CURRENT_SCHEMA_VERSION,
                )
                before = list(db.iterdump())
                migrations.migrate_schema(db)
                self.assertEqual(list(db.iterdump()), before)

    def test_stored_nested_records_and_frozen_targets_survive_upgrade(self):
        db = self.database(18)
        old = {"icu_training_load": 12, "icu_intensity": 0.7}
        db.execute(
            "UPDATE planned_units SET sync_conflict = ? WHERE id = 'one'",
            (json.dumps({"remote": old}),),
        )
        db.execute(
            "INSERT INTO coach_plan_artifacts(id, base_revision, status, payload, created_at, updated_at) VALUES (?, 0, 'draft', ?, 'now', 'now')",
            ("artifact", json.dumps({"workouts": [old]})),
        )
        db.execute(
            "INSERT INTO plan_adjustments(id, payload, status, created_at) VALUES (?, ?, 'preview', 'now')",
            ("adjustment", json.dumps({"changes": [{"payload": old}]})),
        )
        detail = {"target_snapshot": {"basis": {"icu_ftp": 250}}, "activity": old}
        db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, ?, 'now')",
            ("activity_detail:test", json.dumps(detail)),
        )
        db.execute(
            "INSERT INTO activity_sessions(activity_id, primary_provider, primary_provider_activity_id, started_at, created_at, updated_at) VALUES ('act_test', 'intervals', 'test', 'now', 'now', 'now')"
        )
        db.execute(
            "INSERT INTO activity_detail_analysis(activity_id, analysis_version, input_sha256, payload, computed_at, created_at, updated_at) VALUES ('act_test', 1, ?, ?, 'now', 'now', 'now')",
            ("a" * 64, json.dumps(detail)),
        )
        db.commit()
        migrations.migrate_schema(db)
        db.commit()
        expected = {"planned_load": 12, "planned_intensity": 0.7}
        self.assertEqual(
            json.loads(
                db.execute("SELECT sync_conflict FROM planned_units").fetchone()[0]
            )["remote"],
            expected,
        )
        self.assertEqual(
            json.loads(
                db.execute("SELECT payload FROM coach_plan_artifacts").fetchone()[0]
            )["workouts"],
            [expected],
        )
        self.assertEqual(
            json.loads(
                db.execute("SELECT payload FROM plan_adjustments").fetchone()[0]
            )["changes"][0]["payload"],
            expected,
        )
        stored_kv = db.execute(
            "SELECT value FROM kv WHERE key = 'activity_detail:test'"
        ).fetchone()[0]
        self.assertEqual(stored_kv, json.dumps(detail))
        actual = json.loads(
            db.execute(
                "SELECT payload FROM activity_detail_analysis WHERE activity_id = 'act_test'"
            ).fetchone()[0]
        )
        self.assertEqual(actual["target_snapshot"]["basis"], {"ftp": 250})
        self.assertEqual(actual["activity"], old)

    def test_failure_rolls_back_schema_and_data(self):
        db = self.database(18)
        before = list(db.iterdump())

        def fail(connection):
            migrations.rename_planning_metrics(connection)
            raise RuntimeError("injected")

        with (
            mock.patch.dict(
                migrations.UPGRADE_STEPS,
                {migrations.SHAPE_SCHEMA_V18: (migrations.SHAPE_CURRENT, fail)},
            ),
            self.assertRaisesRegex(RuntimeError, "injected"),
        ):
            migrations.migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before)

    def test_retired_releases_are_rejected_without_modification(self):
        for version in range(9, 16):
            with self.subTest(version=version):
                db = sqlite3.connect(":memory:")
                db.row_factory = sqlite3.Row
                self.addCleanup(db.close)
                fixture = (
                    Path(__file__).with_name("fixtures") / f"schema_v{version}.sql.txt"
                )
                db.executescript(fixture.read_text(encoding="utf-8"))
                before = list(db.iterdump())
                with self.assertRaises(RuntimeError):
                    migrations.migrate_schema(db)
                self.assertEqual(list(db.iterdump()), before)

    def test_conflicting_values_roll_back_instead_of_discarding_data(self):
        for old, new in ((42, 99), (True, 1)):
            with self.subTest(old=old, new=new):
                db = self.database(18)
                db.execute(
                    "UPDATE planned_units SET payload = ? WHERE id = 'one'",
                    (json.dumps({"icu_training_load": old, "planned_load": new}),),
                )
                db.commit()
                before = list(db.iterdump())
                with self.assertRaisesRegex(
                    RuntimeError, "Conflicting planning fields"
                ):
                    migrations.migrate_schema(db)
                self.assertEqual(list(db.iterdump()), before)

    def test_unreadable_relevant_payload_is_rejected_unchanged(self):
        db = self.database(18)
        db.execute(
            "INSERT INTO workout_library(id, local_id, payload, updated_at) VALUES (?, ?, ?, ?)",
            ("invalid", "invalid", '{"icu_training_load":', "now"),
        )
        db.commit()
        before = list(db.iterdump())
        with self.assertRaisesRegex(RuntimeError, "Unreadable planning data"):
            migrations.migrate_schema(db)
        self.assertEqual(list(db.iterdump()), before)

    def test_many_records_are_rewritten_across_batches(self):
        db = self.database(18)
        db.executemany(
            "INSERT INTO workout_library(id, local_id, payload, updated_at) VALUES (?, ?, ?, 'now')",
            [
                (str(i), str(i), json.dumps({"icu_training_load": i}))
                for i in range(130)
            ],
        )
        db.execute(
            "INSERT INTO workout_library(id, local_id, payload, updated_at) VALUES ('unchanged', 'unchanged', ?, 'now')",
            ('{ "name": "plain" }',),
        )
        db.commit()
        migrations.migrate_schema(db)
        db.commit()
        rows = db.execute("SELECT id, payload FROM workout_library").fetchall()
        for row in rows:
            if row["id"] == "unchanged":
                self.assertEqual(row["payload"], '{ "name": "plain" }')
            else:
                self.assertEqual(
                    json.loads(row["payload"]), {"planned_load": int(row["id"])}
                )
