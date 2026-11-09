"""Diagnostics show the last sync and plan sync of each active provider."""

from __future__ import annotations

import json
import sqlite3
import unittest

from backend.diagnostics.plan_sync import summarize_plan_sync
from backend.diagnostics.provider_sync import summarize_provider_sync


def _database() -> sqlite3.Connection:
    db = sqlite3.connect(":memory:")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        CREATE TABLE provider_refresh_history (provider, area, status, finished_at);
        CREATE TABLE sync_jobs (id, provider, type, status, payload,
            requested_by, attempts, available_at, started_at, finished_at,
            error_class, created_at, updated_at);
        CREATE TABLE sync_job_items (id, job_id, item_key, operation,
            remote_id, status, attempts, error_class, error_detail,
            created_at, updated_at);
        CREATE TABLE planned_units (local_id, payload, sync_state,
            sync_error, tombstone);
        """
    )
    return db


def _job(db, job_id, provider, job_type, status, finished_at, created_at="t0"):
    db.execute(
        "INSERT INTO sync_jobs VALUES (?, ?, ?, ?, ?, 'coach', 1, NULL, NULL, ?, "
        "NULL, ?, ?)",
        (
            job_id,
            provider,
            job_type,
            status,
            json.dumps({"entries": [{"a": 1}]}),
            finished_at,
            created_at,
            created_at,
        ),
    )


class ProviderSyncDiagnosticsTests(unittest.TestCase):
    def test_reports_last_refresh_and_plan_sync_per_provider(self) -> None:
        db = _database()
        self.addCleanup(db.close)
        db.executemany(
            "INSERT INTO provider_refresh_history VALUES (?, 'data', ?, ?)",
            [
                ("garmin", "success", "2026-11-09T06:00:00Z"),
                ("garmin", "partial", "2026-11-08T06:00:00Z"),
                ("garmin", "error", "2026-11-09T09:00:00Z"),
                ("wahoo", "success", "2026-11-07T06:00:00Z"),
                ("weather", "success", "2026-11-09T07:00:00Z"),
            ],
        )
        _job(db, "g1", "garmin", "plan_push", "completed", "2026-11-05T10:00:00Z")
        _job(db, "g2", "garmin", "plan_push", "failed", "2026-11-09T10:00:00Z")
        _job(db, "i1", "intervals", "plan_push", "completed", "2026-11-02T10:00:00Z")
        _job(
            db, "i2", "intervals", "nutrition_sync", "completed", "2026-11-06T10:00:00Z"
        )
        _job(db, "w1", "wahoo", "refresh", "completed", "2026-11-09T11:00:00Z")

        self.assertEqual(
            {
                "garmin": {
                    "last_sync_at": "2026-11-09T06:00:00Z",
                    "last_plan_sync_at": "2026-11-05T10:00:00Z",
                },
                "wahoo": {
                    "last_sync_at": "2026-11-07T06:00:00Z",
                    "last_plan_sync_at": None,
                },
                "intervals": {
                    "last_sync_at": "2026-11-06T10:00:00Z",
                    "last_plan_sync_at": "2026-11-02T10:00:00Z",
                },
            },
            summarize_provider_sync(db),
        )

    def test_a_provider_that_never_synced_reports_none(self) -> None:
        db = _database()
        self.addCleanup(db.close)

        self.assertEqual(
            {"last_sync_at": None, "last_plan_sync_at": None},
            summarize_provider_sync(db)["wahoo"],
        )

    def test_plan_sync_lists_the_plan_push_jobs_of_every_provider(self) -> None:
        db = _database()
        self.addCleanup(db.close)
        _job(db, "g1", "garmin", "plan_push", "completed", "t5", created_at="t1")
        _job(db, "i1", "intervals", "plan_push", "completed", "t6", created_at="t2")
        _job(db, "w1", "wahoo", "plan_push", "completed", "t7", created_at="t3")
        _job(db, "x1", "garmin", "refresh", "completed", "t8", created_at="t4")

        report = summarize_plan_sync(db)

        self.assertEqual(
            [("w1", "wahoo"), ("i1", "intervals"), ("g1", "garmin")],
            [(job["id"], job["provider"]) for job in report["recent_jobs"]],
        )


if __name__ == "__main__":
    unittest.main()
