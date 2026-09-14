import unittest
import sqlite3

from backend.sync.jobs import (
    aggregate_job_status,
    bounded_progress,
    job_dto,
    is_retryable_error,
    has_active_job,
    list_jobs,
    read_job,
    retry_delay,
    validate_job_request,
)


class SyncJobContractTests(unittest.TestCase):
    def test_request_contract_normalizes_provider_and_type(self):
        result = validate_job_request(" Garmin ", " REFRESH ", {"days": 30})
        self.assertEqual(result, {"provider": "garmin", "type": "refresh", "payload": {"days": 30}})
        with self.assertRaisesRegex(ValueError, "Unsupported job type"):
            validate_job_request("garmin", "body_battery_retry", {})

    def test_status_aggregation_distinguishes_partial_and_running(self):
        self.assertEqual(aggregate_job_status([]), "completed")
        self.assertEqual(aggregate_job_status([{"status": "running"}]), "running")
        self.assertEqual(aggregate_job_status([{"status": "completed"}, {"status": "failed"}]), "partial")
        self.assertEqual(aggregate_job_status([{"status": "failed"}, {"status": "failed"}]), "failed")
        self.assertEqual(bounded_progress([{"status": "completed"}, {"status": "queued"}]), (1, 2))

    def test_retry_backoff_is_bounded_and_classified(self):
        self.assertEqual(retry_delay(1, base_seconds=10, max_seconds=25), 10)
        self.assertEqual(retry_delay(4, base_seconds=10, max_seconds=25), 25)
        self.assertTrue(is_retryable_error("network_error"))
        self.assertFalse(is_retryable_error("auth_required"))

    def test_job_dto_decodes_payload_and_bounds_item_projection(self):
        result = job_dto(
            {"id": "job-1", "provider": "garmin", "type": "refresh", "payload": '{"days": 7}'},
            [{"id": 1, "item_key": "activities", "operation": "read", "status": "completed", "attempts": 1}],
        )
        self.assertEqual(result["payload"], {"days": 7})
        self.assertEqual(result["progress"], {"completed": 1, "total": 1})
        self.assertEqual(set(result["items"][0]), {
            "id", "item_key", "operation", "remote_id", "status", "attempts",
            "error_class", "error_detail", "created_at", "updated_at",
        })

    def test_persistence_helpers_use_caller_owned_connection(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.executescript(
            "CREATE TABLE sync_jobs (id TEXT, provider TEXT, type TEXT, status TEXT, payload TEXT, requested_by TEXT, attempts INTEGER, available_at TEXT, started_at TEXT, finished_at TEXT, error_class TEXT, created_at TEXT, updated_at TEXT);"
            "CREATE TABLE sync_job_items (id INTEGER, job_id TEXT, item_key TEXT, operation TEXT, remote_id TEXT, status TEXT, attempts INTEGER, error_class TEXT, error_detail TEXT, created_at TEXT, updated_at TEXT);"
        )
        db.execute("INSERT INTO sync_jobs VALUES ('j1','garmin','refresh','queued','{}','test',0,NULL,NULL,NULL,NULL,'1','1')")
        db.execute("INSERT INTO sync_job_items VALUES (1,'j1','data','read',NULL,'queued',0,NULL,NULL,'1','1')")
        db.commit()
        job, items = read_job(db, "j1")
        self.assertEqual(job["id"], "j1")
        self.assertEqual(list_jobs(db, 1)[0]["id"], "j1")
        self.assertTrue(has_active_job(db, "garmin", "refresh"))
        db.close()

    def test_projection_tolerates_malformed_persisted_payload(self):
        result = job_dto(
            {"id": "job-2", "provider": "weather", "type": "refresh", "payload": "not-json"},
            [],
        )
        self.assertEqual(result["payload"], {})
        self.assertEqual(result["status"], "completed")


if __name__ == "__main__":
    unittest.main()
