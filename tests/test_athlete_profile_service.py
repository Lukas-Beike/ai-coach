import json
import sqlite3
import unittest
from contextlib import contextmanager

from backend.athlete.profile import DEFAULT_PROFILE, ProfileService
from backend.db.repositories import KeyValueRepository, ProfileRepository
from backend.errors import AppError
from backend.weather import cache as weather_cache


class _Manager:
    def __init__(self, db):
        self.db = db

    @contextmanager
    def unit_of_work(self):
        try:
            yield self.db
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise


class ProfileServiceTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE kv (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT)"
        )
        self.db.execute(
            "CREATE TABLE change_history ("
            "id TEXT PRIMARY KEY, entity_type TEXT, entity_id TEXT, action TEXT, "
            "source TEXT, created_at TEXT, before_hash TEXT, after_hash TEXT, diff TEXT)"
        )
        self.key_values = KeyValueRepository(lambda: "2026-09-20T00:00:00+00:00")
        self.service = ProfileService(
            _Manager(self.db), ProfileRepository(self.key_values), self.key_values
        )

    def tearDown(self):
        self.db.close()

    def test_get_returns_default_for_missing_or_malformed_payload(self):
        self.assertEqual(self.service.get(), DEFAULT_PROFILE)
        self.key_values.set(self.db, "profile", "not-json")
        self.assertEqual(self.service.get(), DEFAULT_PROFILE)

    def test_save_normalizes_audits_and_invalidates_changed_location(self):
        self.key_values.set(self.db, weather_cache.CACHE_KEY, "cached")
        self.key_values.set(self.db, weather_cache.FAILURE_KEY, "failed")

        saved = self.service.save(
            {"name": " Ada ", "timezone": "UTC", "weather_location": " Berlin "}
        )

        self.assertEqual(saved["name"], "Ada")
        self.assertEqual(saved["weather_location"], "Berlin")
        self.assertEqual(
            json.loads(self.key_values.get(self.db, "profile"))["timezone"], "UTC"
        )
        self.assertEqual(self.key_values.get(self.db, weather_cache.CACHE_KEY), "")
        self.assertEqual(self.key_values.get(self.db, weather_cache.FAILURE_KEY), "")
        history = self.db.execute("SELECT * FROM change_history").fetchall()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["entity_type"], "profile")

    def test_same_location_keeps_weather_cache_and_skips_unchanged_history(self):
        self.service.save({"weather_location": "Berlin", "timezone": "UTC"})
        self.key_values.set(self.db, weather_cache.CACHE_KEY, "cached")
        self.key_values.set(self.db, weather_cache.FAILURE_KEY, "failed")
        before_count = self.db.execute(
            "SELECT COUNT(*) FROM change_history"
        ).fetchone()[0]

        self.service.save({"weather_location": "Berlin", "timezone": "UTC"})

        self.assertEqual(
            self.key_values.get(self.db, weather_cache.CACHE_KEY), "cached"
        )
        self.assertEqual(
            self.key_values.get(self.db, weather_cache.FAILURE_KEY), "failed"
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM change_history").fetchone()[0],
            before_count,
        )

    def test_invalid_timezone_rolls_back_without_cache_or_history_changes(self):
        self.key_values.set(self.db, weather_cache.CACHE_KEY, "cached")
        with self.assertRaises(AppError):
            self.service.save(
                {"timezone": "Mars/Invalid", "weather_location": "Berlin"}
            )
        self.assertIsNone(self.key_values.get(self.db, "profile"))
        self.assertEqual(
            self.key_values.get(self.db, weather_cache.CACHE_KEY), "cached"
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM change_history").fetchone()[0], 0
        )

    def test_restore_in_transaction_merges_normalizes_and_persists_without_history(
        self,
    ):
        current = {**DEFAULT_PROFILE, "name": "Current", "goals": " Keep "}
        target = {"name": " Restored ", "timezone": "Mars/Invalid"}
        current_before = dict(current)
        target_before = dict(target)

        restored = self.service.restore_in_transaction(self.db, current, target)

        self.assertEqual(restored["name"], "Restored")
        self.assertEqual(restored["goals"], "Keep")
        self.assertEqual(restored["timezone"], DEFAULT_PROFILE["timezone"])
        self.assertEqual(json.loads(self.key_values.get(self.db, "profile")), restored)
        self.assertEqual(current, current_before)
        self.assertEqual(target, target_before)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM change_history").fetchone()[0], 0
        )

    def test_restore_in_transaction_with_none_target_restores_legacy_defaults(self):
        current = {**DEFAULT_PROFILE, "name": "Current", "sports": "Running"}

        restored = self.service.restore_in_transaction(self.db, current, None)

        self.assertEqual(restored, DEFAULT_PROFILE)
        self.assertEqual(
            json.loads(self.key_values.get(self.db, "profile")), DEFAULT_PROFILE
        )
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM change_history").fetchone()[0], 0
        )

    def test_restore_in_transaction_rolls_back_with_outer_unit_of_work(self):
        original = {**DEFAULT_PROFILE, "name": "Before"}
        self.key_values.set(
            self.db, "profile", json.dumps(original, ensure_ascii=False)
        )
        self.db.commit()

        with (
            self.assertRaisesRegex(RuntimeError, "abort outer undo"),
            self.service._manager.unit_of_work() as db,
        ):
            self.service.restore_in_transaction(db, original, {"name": "Restored"})
            raise RuntimeError("abort outer undo")

        self.assertEqual(json.loads(self.key_values.get(self.db, "profile")), original)
        self.assertEqual(
            self.db.execute("SELECT COUNT(*) FROM change_history").fetchone()[0], 0
        )


if __name__ == "__main__":
    unittest.main()
