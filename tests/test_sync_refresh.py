import unittest
import sqlite3
from datetime import datetime, timezone

from backend.sync.refresh import create_refresh_record, finish_refresh_record, retry_at


class SyncRefreshTests(unittest.TestCase):
    def test_retry_at_is_bounded_and_stops_for_configuration_errors(self):
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        retry = retry_at(
            [{"status": "error", "error_code": "timeout"}],
            current_error_code="timeout", now=now, base_seconds=10, max_seconds=25,
        )
        self.assertEqual(retry, "2026-01-01T00:00:20+00:00")
        self.assertIsNone(retry_at([], current_error_code="auth_required", now=now, base_seconds=10, max_seconds=25))

    def test_refresh_records_use_caller_owned_connection(self):
        db = sqlite3.connect(":memory:")
        db.row_factory = sqlite3.Row
        db.execute(
            "CREATE TABLE provider_refresh_history (id TEXT, provider TEXT, area TEXT, operation_id TEXT, "
            "trigger TEXT, started_at TEXT, phase TEXT, status TEXT, finished_at TEXT, error_code TEXT, next_retry_at TEXT)"
        )
        create_refresh_record(
            db, refresh_id="refresh-1", provider="garmin", area="data",
            operation_id="op-1", trigger="test", started_at="2026-01-01T00:00:00+00:00",
        )
        provider_area = finish_refresh_record(
            db, refresh_id="refresh-1", finished_at="2026-01-01T00:01:00+00:00",
            phase="complete", status="success", error_code=None,
            now=datetime(2026, 1, 1, tzinfo=timezone.utc), base_seconds=10, max_seconds=25,
        )
        self.assertEqual(provider_area, ("garmin", "data"))
        self.assertEqual(db.execute("SELECT status FROM provider_refresh_history").fetchone()[0], "success")
        db.close()


if __name__ == "__main__":
    unittest.main()
