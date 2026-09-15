from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from backend.config import Config
from backend.sync.freshness import (
    PROVIDER_REFRESH_LABELS,
    provider_freshness_state,
)

NOW = datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc)


def _config(**values: str) -> Config:
    defaults = {
        "port": 8090, "openai_api_key": "", "openai_base_url": "https://api.openai.com/v1",
        "openai_model": "model", "gemini_api_key": "", "gemini_model": "gemini",
        "ai_provider": "", "intervals_api_key": "", "intervals_athlete_id": "0",
        "garmin_email": "", "garmin_password": "", "garmin_tokenstore": "unused",
        "garmin_fixture_path": "", "calendar_ical_url": "", "app_password": "",
        "secure_cookies": False, "data_retention_days": -1,
    }
    defaults.update(values)
    return Config(**defaults)


def _db() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE provider_refresh_history (
            id TEXT PRIMARY KEY, provider TEXT NOT NULL, area TEXT NOT NULL,
            operation_id TEXT NOT NULL, trigger TEXT NOT NULL, started_at TEXT NOT NULL,
            finished_at TEXT, phase TEXT NOT NULL, status TEXT NOT NULL,
            error_code TEXT, next_retry_at TEXT
        );
        CREATE TABLE sync_jobs (
            id TEXT PRIMARY KEY, provider TEXT NOT NULL, type TEXT NOT NULL,
            status TEXT NOT NULL, payload TEXT, requested_by TEXT, attempts INTEGER,
            progress_total INTEGER, progress_completed INTEGER, error_class TEXT,
            available_at TEXT, started_at TEXT, finished_at TEXT, created_at TEXT,
            updated_at TEXT
        );
        """
    )
    db.commit()
    return db


def _values(values: dict[str, str]):
    return lambda key: values.get(key)


def _item(result, provider: str, area: str) -> dict:
    return next(item for item in result if (item["provider"], item["area"]) == (provider, area))


class ProviderFreshnessTests(unittest.TestCase):
    def test_order_labels_configuration_and_read_only_contract(self):
        db = _db()
        result = provider_freshness_state(
            db, config=_config(intervals_api_key="intervals", garmin_email="athlete@example.test", calendar_ical_url="https://calendar.test/i.ics"),
            get_value=_values({}), profile={"weather_location": ""}, garmin_has_core_error=False,
            garmin_tokenstore_exists=False, now=NOW,
        )
        self.assertEqual([(item["provider"], item["area"]) for item in result], list(PROVIDER_REFRESH_LABELS))
        self.assertEqual([item["label"] for item in result], list(PROVIDER_REFRESH_LABELS.values()))
        self.assertTrue(all(item["configured"] for item in result[:3]))
        self.assertTrue(_item(result, "garmin", "data")["configured"])
        self.assertFalse(_item(result, "weather", "forecast")["configured"])
        self.assertTrue(_item(result, "calendar", "events")["configured"])
        self.assertFalse(_item(result, "intervals", "competitions")["read_only"])
        self.assertTrue(_item(result, "intervals", "activities")["read_only"])
        self.assertTrue(all(item["state"] == "never_loaded" for item in result if item["configured"]))
        self.assertEqual(_item(result, "weather", "forecast")["state"], "not_configured")

    def test_central_states_and_last_error_are_preserved(self):
        db = _db()
        rows = [
            ("running", "intervals", "activities", NOW - timedelta(minutes=2), None, "loading", None),
            ("partial", "intervals", "competitions", NOW - timedelta(hours=1), NOW - timedelta(minutes=59), "complete", None),
            ("error", "intervals", "performance", NOW - timedelta(minutes=3), None, "request", "timeout"),
            ("success", "garmin", "data", NOW - timedelta(hours=1), NOW - timedelta(minutes=59), "complete", None),
            ("error-weather", "weather", "forecast", NOW - timedelta(hours=1), None, "request", "weather_down"),
        ]
        for row_id, provider, area, started, finished, phase, error in rows:
            db.execute(
                "INSERT INTO provider_refresh_history VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (row_id, provider, area, "op", "test", started.isoformat(), finished.isoformat() if finished else None, phase, "error" if error else ("running" if "running" in row_id else "partial" if "partial" in row_id else "success"), error, None),
            )
        values = {"last_sync_error": "old_sync_error", "weather_failure": "fallback_weather_error"}
        result = provider_freshness_state(
            db, config=_config(intervals_api_key="yes", garmin_email="athlete@example.test"), get_value=_values(values), profile={"weather_location": "Köln"},
            garmin_has_core_error=False, garmin_tokenstore_exists=False, now=NOW,
        )
        self.assertEqual(_item(result, "intervals", "activities")["state"], "syncing")
        self.assertEqual(_item(result, "intervals", "competitions")["state"], "partial")
        self.assertEqual(_item(result, "intervals", "performance")["state"], "error")
        self.assertEqual(_item(result, "intervals", "performance")["error_code"], "timeout")
        self.assertEqual(_item(result, "garmin", "data")["state"], "fresh")
        self.assertEqual(_item(result, "weather", "forecast")["state"], "error")
        self.assertEqual(_item(result, "weather", "forecast")["error_code"], "weather_down")

        unconfigured = provider_freshness_state(
            db, config=_config(), get_value=_values({"last_sync_error": "old_sync_error"}), profile={},
            garmin_has_core_error=False, garmin_tokenstore_exists=False, now=NOW,
        )
        self.assertEqual(_item(unconfigured, "intervals", "activities")["state"], "not_configured")
        self.assertEqual(_item(unconfigured, "intervals", "activities")["error_code"], "provider_error")

    def test_fresh_stale_malformed_and_z_timestamps(self):
        db = _db()
        for row_id, area, finished in (
            ("fresh", "activities", "2026-09-15T10:00:00Z"),
            ("stale", "competitions", "2026-09-12T10:00:00+00:00"),
            ("malformed", "performance", "not-a-time"),
        ):
            db.execute(
                "INSERT INTO provider_refresh_history VALUES (?, 'intervals', ?, 'op', 'test', ?, ?, 'complete', 'success', NULL, NULL)",
                (row_id, area, finished, finished),
            )
        result = provider_freshness_state(
            db, config=_config(intervals_api_key="yes"), get_value=_values({}), profile={},
            garmin_has_core_error=False, garmin_tokenstore_exists=False, now=NOW,
        )
        self.assertEqual(_item(result, "intervals", "activities")["state"], "fresh")
        self.assertEqual(_item(result, "intervals", "competitions")["state"], "stale")
        self.assertEqual(_item(result, "intervals", "performance")["state"], "stale")
        self.assertTrue(_item(result, "intervals", "performance")["has_last_good"])

    def test_only_future_queued_retry_is_projected_and_fallbacks_configure(self):
        db = _db()
        db.executemany(
            "INSERT INTO sync_jobs VALUES (?, ?, 'refresh', 'queued', '{}', NULL, 0, 0, 0, NULL, ?, NULL, NULL, ?, ?)",
            [("past", "intervals", "2026-09-15T11:00:00+00:00", NOW.isoformat(), NOW.isoformat()),
             ("future", "intervals", "2026-09-15T13:00:00Z", NOW.isoformat(), NOW.isoformat())],
        )
        result = provider_freshness_state(
            db, config=_config(intervals_api_key="yes", garmin_tokenstore="unused"),
            get_value=_values({"weather_cache": json.dumps({"fetched_at": "2026-09-15T11:30:00Z"}), "last_garmin_error": "ignored"}),
            profile={"weather_location": "Berlin"}, garmin_has_core_error=True, garmin_tokenstore_exists=True, now=NOW,
        )
        self.assertEqual(_item(result, "intervals", "activities")["next_retry_at"], "2026-09-15T13:00:00+00:00")
        self.assertEqual(_item(result, "weather", "forecast")["state"], "fresh")
        self.assertTrue(_item(result, "garmin", "data")["configured"])
        self.assertEqual(_item(result, "garmin", "data")["error_code"], "provider_error")

    def test_cleanup_is_bounded_and_uses_caller_transaction(self):
        db = _db()
        old = NOW - timedelta(days=31)
        db.execute(
            "INSERT INTO provider_refresh_history VALUES ('old', 'intervals', 'activities', 'op', 'test', ?, ?, 'complete', 'success', NULL, NULL)",
            (old.isoformat(), old.isoformat()),
        )
        for index in range(201):
            stamp = (NOW - timedelta(minutes=index)).isoformat()
            db.execute(
                "INSERT INTO provider_refresh_history VALUES (?, 'intervals', 'activities', 'op', 'test', ?, ?, 'complete', 'success', NULL, NULL)",
                (f"recent-{index}", stamp, stamp),
            )
        db.commit()
        result = provider_freshness_state(
            db, config=_config(intervals_api_key="yes"), get_value=_values({}), profile={},
            garmin_has_core_error=False, garmin_tokenstore_exists=False, now=NOW,
        )
        self.assertEqual(db.execute("SELECT COUNT(*) FROM provider_refresh_history").fetchone()[0], 200)
        self.assertIsNotNone(_item(result, "intervals", "activities")["last_success_at"])
        db.rollback()
        self.assertEqual(db.execute("SELECT COUNT(*) FROM provider_refresh_history").fetchone()[0], 202)

    def test_import_smoke_from_empty_cwd_without_bytecode(self):
        package_root = Path(__import__("backend").__file__).resolve().parent.parent
        with tempfile.TemporaryDirectory() as temp_dir:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(package_root)
            completed = subprocess.run(
                [sys.executable, "-B", "-c", "import backend.sync.freshness"],
                cwd=temp_dir, env=env, capture_output=True, text=True, check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertEqual(list(Path(temp_dir).rglob("*.pyc")), [])


if __name__ == "__main__":
    unittest.main()
