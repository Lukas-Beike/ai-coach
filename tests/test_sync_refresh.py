import unittest
from datetime import datetime, timezone

from backend.sync.refresh import retry_at


class SyncRefreshTests(unittest.TestCase):
    def test_retry_at_is_bounded_and_stops_for_configuration_errors(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        retry = retry_at(
            [{"status": "error", "error_code": "timeout"}],
            current_error_code="timeout", now=now, base_seconds=10, max_seconds=25,
        )
        self.assertEqual(retry, "2026-01-01T00:00:20+00:00")
        self.assertIsNone(retry_at([], current_error_code="auth_required", now=now, base_seconds=10, max_seconds=25))


if __name__ == "__main__":
    unittest.main()
