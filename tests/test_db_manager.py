import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from backend.db.manager import DatabaseManager


class DatabaseManagerTests(unittest.TestCase):
    def make_manager(self, root: str) -> DatabaseManager:
        return DatabaseManager(Path(root) / "test.db", sqlite3, reader_count=4)

    def test_unit_of_work_rolls_back_and_reader_pool_reuses_connections(self):
        with tempfile.TemporaryDirectory() as root:
            manager = self.make_manager(root)
            self.addCleanup(manager.close)
            with manager.unit_of_work() as db:
                db.execute("CREATE TABLE records (value TEXT NOT NULL)")
            with self.assertRaises(RuntimeError):
                with manager.unit_of_work() as db:
                    db.execute("INSERT INTO records(value) VALUES (?)", ("discarded",))
                    raise RuntimeError("rollback")
            with manager.reader() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM records").fetchone()[0], 0)
            with manager.reader() as first:
                first_id = id(first)
            with manager.reader() as second:
                self.assertEqual(id(second), first_id)
            manager.close()

    def test_writer_is_serialized(self):
        with tempfile.TemporaryDirectory() as root:
            manager = self.make_manager(root)
            self.addCleanup(manager.close)
            with manager.unit_of_work() as db:
                db.execute("CREATE TABLE records (value INTEGER NOT NULL)")
            active = 0
            maximum = 0
            state_lock = threading.Lock()

            def write(value: int) -> None:
                nonlocal active, maximum
                with manager.unit_of_work() as db:
                    with state_lock:
                        active += 1
                        maximum = max(maximum, active)
                    time.sleep(0.02)
                    db.execute("INSERT INTO records(value) VALUES (?)", (value,))
                    with state_lock:
                        active -= 1

            threads = [threading.Thread(target=write, args=(value,)) for value in (1, 2, 3, 4)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(maximum, 1)
            with manager.reader() as db:
                self.assertEqual(db.execute("SELECT COUNT(*) FROM records").fetchone()[0], 4)
            manager.close()

    def test_session_cache_invalidation_and_restore_drain(self):
        with tempfile.TemporaryDirectory() as root:
            manager = self.make_manager(root)
            self.addCleanup(manager.close)
            manager.session_cache.put("session", {"csrf": "test"}, now=10)
            self.assertEqual(manager.session_cache.get("session", now=11)["csrf"], "test")
            manager.session_cache.invalidate("session")
            self.assertIsNone(manager.session_cache.get("session", now=11))
            with manager.unit_of_work() as db:
                db.execute("CREATE TABLE records (value TEXT NOT NULL)")
            with manager.restore_drain():
                self.assertIsNone(manager._writer)
            with manager.unit_of_work() as db:
                db.execute("INSERT INTO records(value) VALUES ('restored')")
            manager.close()


if __name__ == "__main__":
    unittest.main()
