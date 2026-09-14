import unittest

from backend.sync.snapshots import latest_snapshot, save_snapshot


class _Repository:
    def __init__(self):
        self.payload = None

    def latest_payload(self, db):
        return self.payload

    def save(self, db, snapshot, created_at):
        self.payload = __import__("json").dumps(snapshot)


class SyncSnapshotTests(unittest.TestCase):
    def test_snapshot_operations_use_caller_connection_and_store(self):
        repository = _Repository()
        values = {}
        snapshot = {"synced_at": "2026-01-01T00:00:00+00:00", "activities": []}

        save_snapshot(
            object(), snapshot, repository, update_full_sync=True, activity_days=14,
            set_value=lambda key, value, db: values.__setitem__(key, value),
        )

        self.assertEqual(latest_snapshot(object(), repository), snapshot)
        self.assertEqual(values["last_sync_at"], snapshot["synced_at"])
        self.assertEqual(values["last_sync_activity_days"], "14")


if __name__ == "__main__":
    unittest.main()
