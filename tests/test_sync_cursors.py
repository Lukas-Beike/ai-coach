import sqlite3
import unittest

from backend.sync.cursors import read_cursor, write_cursor


class SyncCursorTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE provider_sync_cursors (provider TEXT NOT NULL, stream TEXT NOT NULL, "
            "cursor TEXT, high_water_mark TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(provider, stream))"
        )

    def tearDown(self):
        self.db.close()

    def test_read_returns_empty_contract_and_write_round_trips(self):
        self.assertEqual(read_cursor(self.db, "intervals", "activities")["cursor"], None)
        write_cursor(self.db, "intervals", "activities", "newest", "high", "now")
        self.assertEqual(read_cursor(self.db, "intervals", "activities"), {
            "provider": "intervals", "stream": "activities", "cursor": "newest",
            "high_water_mark": "high", "updated_at": "now",
        })


if __name__ == "__main__":
    unittest.main()
