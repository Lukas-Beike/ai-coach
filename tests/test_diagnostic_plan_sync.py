"""Plan-sync diagnostics expose job outcomes and unsynced units."""

from __future__ import annotations

import json
import sqlite3
import unittest

from backend.diagnostics.plan_sync import summarize_garmin_removal, summarize_plan_sync


class PlanSyncDiagnosticsTests(unittest.TestCase):
    def test_reports_failed_items_and_unsynced_units_without_error_text(self):
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

        report = summarize_plan_sync(db)

        job = report["recent_jobs"][0]
        self.assertEqual((job["status"], job["entries"]), ("failed", 2))
        self.assertEqual(
            job["items"], [{"status": "failed", "error_class": "conflict"}]
        )
        self.assertNotIn("secret-token", json.dumps(report))
        self.assertEqual(report["unsynced_total"], 1)
        self.assertEqual(
            report["unsynced_units"],
            [
                {
                    "local_id": "u1",
                    "date": "2026-11-10",
                    "sync_state": "sync_error",
                    "has_error": True,
                }
            ],
        )

    def test_a_unit_with_an_invalid_payload_has_no_date_and_does_not_fail(self):
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
            "INSERT INTO planned_units VALUES ('bad','{not json','pending',NULL,0)"
        )

        report = summarize_plan_sync(db)

        self.assertEqual(report["unsynced_total"], 1)
        self.assertIsNone(report["unsynced_units"][0]["date"])


class GarminRemovalDiagnosticsTests(unittest.TestCase):
    """#2408: the past-workout removal's state is visible as counts only."""

    def database(self) -> sqlite3.Connection:
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript(
            """
            CREATE TABLE kv (key, value, updated_at);
            CREATE TABLE remote_links (local_id, provider, entity_kind, remote_id);
            CREATE TABLE planned_units (local_id, payload);
            """
        )
        return db

    def test_reports_counts_and_last_run_without_ids(self):
        db = self.database()
        db.execute(
            "INSERT INTO kv VALUES ('garmin_app_workout_cleanup', ?, 't')",
            (
                json.dumps(
                    {
                        "done": True,
                        "checked": ["701", "702"],
                        "removed": 3,
                        "last_run_at": "2026-11-12T16:23:00+00:00",
                    }
                ),
            ),
        )
        for local_id, day in (("u1", "2000-01-01"), ("u2", "2999-01-01")):
            db.execute(
                "INSERT INTO remote_links VALUES (?, 'garmin', 'planned_unit', ?)",
                (local_id, f"remote-{local_id}"),
            )
            db.execute(
                "INSERT INTO planned_units VALUES (?, ?)",
                (local_id, json.dumps({"date": day})),
            )

        report = summarize_garmin_removal(db)

        self.assertEqual(
            {
                "one_time_done": True,
                "checked": 2,
                "removed": 3,
                "last_run_at": "2026-11-12T16:23:00+00:00",
                "past_links_pending": 1,
            },
            report,
        )
        self.assertNotIn("remote-u1", json.dumps(report))

    def test_a_removal_that_never_ran_reports_no_run(self):
        report = summarize_garmin_removal(self.database())

        self.assertEqual(
            {
                "one_time_done": False,
                "checked": 0,
                "removed": 0,
                "last_run_at": None,
                "past_links_pending": 0,
            },
            report,
        )


if __name__ == "__main__":
    unittest.main()
