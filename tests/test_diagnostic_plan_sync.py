"""Plan-sync diagnostics expose job outcomes and unsynced units."""

from __future__ import annotations

import json
import sqlite3
import unittest

from backend.diagnostics.plan_sync import summarize_plan_sync


class PlanSyncDiagnosticsTests(unittest.TestCase):
    def test_reports_failed_items_and_unsynced_units_redacted(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript(
            """
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
        db.execute(
            "INSERT INTO sync_jobs VALUES ('j1','intervals','plan_push','failed',?,"
            "'coach',1,NULL,NULL,'t2','conflict','t1','t2')",
            (json.dumps({"entries": [{"a": 1}, {"a": 2}]}),),
        )
        db.execute(
            "INSERT INTO sync_job_items VALUES ('j1-0','j1','a','plan_push',NULL,"
            "'failed',1,'conflict','secret-token boom','t1','t1')"
        )
        db.execute(
            "INSERT INTO planned_units VALUES ('u1',?,'sync_error','secret-token',0)",
            (json.dumps({"date": "2026-11-10"}),),
        )
        db.execute(
            "INSERT INTO planned_units VALUES ('u2',?,'synced',NULL,0)",
            (json.dumps({"date": "2026-11-11"}),),
        )

        report = summarize_plan_sync(db, lambda text: text.replace("secret-token", "X"))

        job = report["recent_jobs"][0]
        self.assertEqual((job["status"], job["entries"]), ("failed", 2))
        self.assertEqual(job["items"][0]["error_detail"], "X boom")
        self.assertEqual(report["unsynced_total"], 1)
        self.assertEqual(
            report["unsynced_units"],
            [
                {
                    "local_id": "u1",
                    "date": "2026-11-10",
                    "sync_state": "sync_error",
                    "sync_error": "X",
                }
            ],
        )


if __name__ == "__main__":
    unittest.main()
