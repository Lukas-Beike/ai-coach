import unittest

from backend.sync.jobs import (
    aggregate_job_status,
    bounded_progress,
    is_retryable_error,
    retry_delay,
    validate_job_request,
)


class SyncJobContractTests(unittest.TestCase):
    def test_request_contract_normalizes_provider_and_type(self):
        result = validate_job_request(" Garmin ", " REFRESH ", {"days": 30})
        self.assertEqual(result, {"provider": "garmin", "type": "refresh", "payload": {"days": 30}})

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


if __name__ == "__main__":
    unittest.main()
