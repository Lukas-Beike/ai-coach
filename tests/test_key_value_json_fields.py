import json
import sqlite3
import unittest
from contextlib import closing

from backend.db.repositories import KeyValueRepository


class KeyValueJsonFieldsTests(unittest.TestCase):
    def test_selected_fields_keep_types_and_omit_large_unrelated_content(self):
        repository = KeyValueRepository(lambda: "fixed-time")
        with closing(sqlite3.connect(":memory:")) as db:
            db.row_factory = sqlite3.Row
            db.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
            )
            payload = {
                "morning_body_battery": {"status": "ready", "value": 84, "ok": True},
                "source_freshness": {"sleep": {"synced_start": "2026-01-01"}},
                "boolean": True,
                "text": "synthetic",
                "number": 3.5,
                "missing": None,
                "array": [True, 1, "text"],
                "large_unrelated_data": "synthetic-unused" * 100000,
            }
            serialized = json.dumps(payload)
            repository.set(db, "garmin_snapshot", serialized)
            selected = repository.get_json_fields(
                db, "garmin_snapshot", ("morning_body_battery", "source_freshness")
            )
            self.assertEqual(
                json.loads(selected),
                {
                    key: payload[key]
                    for key in ("morning_body_battery", "source_freshness")
                },
            )
            self.assertLess(len(selected), 250)
            scalars = json.loads(
                repository.get_json_fields(
                    db,
                    "garmin_snapshot",
                    ("boolean", "text", "number", "missing", "array"),
                )
            )
            self.assertIs(scalars["boolean"], True)
            self.assertEqual(scalars, {field: payload[field] for field in scalars})
            self.assertEqual(repository.get(db, "garmin_snapshot"), serialized)

    def test_missing_invalid_and_non_object_snapshots_are_safe(self):
        repository = KeyValueRepository(lambda: "fixed-time")
        with closing(sqlite3.connect(":memory:")) as db:
            db.row_factory = sqlite3.Row
            db.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
            )
            self.assertIsNone(repository.get_json_fields(db, "missing", ("value",)))
            for value in ("not-json", "[]", "null", "{}"):
                with self.subTest(value=value):
                    repository.set(db, "snapshot", value)
                    selected = repository.get_json_fields(db, "snapshot", ("value",))
                    self.assertEqual(
                        json.loads(selected)["value"] if selected else None, None
                    )
            self.assertEqual(repository.get_json_fields(db, "snapshot", ()), "{}")

    def test_key_and_field_names_are_bound_as_data(self):
        repository = KeyValueRepository(lambda: "fixed-time")
        with closing(sqlite3.connect(":memory:")) as db:
            db.row_factory = sqlite3.Row
            db.execute(
                "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
            )
            key = "synthetic' OR 1=1 --"
            repository.set(db, key, '{"value": 7}')
            self.assertEqual(
                json.loads(repository.get_json_fields(db, key, ("value",))),
                {"value": 7},
            )
            self.assertIsNone(repository.get_json_fields(db, "other", ("value",)))
