import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from backend.db.manager import DatabaseManager, DatabaseManagerCache
from backend.db.schema import database_schema_is_current, initialize_schema


class DatabaseManagerTests(unittest.TestCase):
    def make_manager(self, root: str) -> DatabaseManager:
        return DatabaseManager(Path(root) / "test.db", sqlite3, reader_count=4, row_factory=sqlite3.Row)

    def test_cache_reuses_replaces_and_resets_the_active_manager(self):
        with tempfile.TemporaryDirectory() as root:
            cache = DatabaseManagerCache()
            first_signature = (str(Path(root) / "first.db"), "", False)
            second_signature = (str(Path(root) / "second.db"), "", False)

            first = cache.get(first_signature, first_signature[0], sqlite3)
            self.assertIs(cache.get(first_signature, first_signature[0], sqlite3), first)
            self.assertTrue(cache.matches(first_signature))

            second = cache.get(second_signature, second_signature[0], sqlite3)
            self.assertIsNot(second, first)
            self.assertFalse(cache.matches(first_signature))
            with self.assertRaisesRegex(RuntimeError, "database manager is closed"):
                with first.unit_of_work():
                    pass

            cache.reset()
            self.assertFalse(cache.matches(second_signature))
            with self.assertRaisesRegex(RuntimeError, "database manager is closed"):
                with second.unit_of_work():
                    pass

    def test_cache_unit_of_work_uses_the_current_manager_lazily(self):
        with tempfile.TemporaryDirectory() as root:
            cache = DatabaseManagerCache()
            with self.assertRaisesRegex(RuntimeError, "not initialized"):
                with cache.unit_of_work():
                    pass

            first_signature = (str(Path(root) / "first.db"), "", False)
            second_signature = (str(Path(root) / "second.db"), "", False)
            cache.get(first_signature, first_signature[0], sqlite3)
            with cache.unit_of_work() as db:
                db.execute("CREATE TABLE records (value TEXT NOT NULL)")

            cache.get(second_signature, second_signature[0], sqlite3)
            with cache.unit_of_work() as db:
                db.execute("CREATE TABLE records (value TEXT NOT NULL)")
                db.execute("INSERT INTO records(value) VALUES ('current')")
                self.assertEqual(
                    db.execute("SELECT value FROM records").fetchone()[0],
                    "current",
                )
            cache.reset()

    def test_cache_replacement_waits_for_leased_unit_of_work(self):
        with tempfile.TemporaryDirectory() as root:
            cache = DatabaseManagerCache()
            first_signature = (str(Path(root) / "first.db"), "", False)
            second_signature = (str(Path(root) / "second.db"), "", False)
            cache.get(first_signature, first_signature[0], sqlite3)
            entered = threading.Event()
            release = threading.Event()
            replaced = threading.Event()

            def use_manager():
                with cache.unit_of_work():
                    entered.set()
                    release.wait(2)

            def replace_manager():
                cache.get(second_signature, second_signature[0], sqlite3)
                replaced.set()

            user = threading.Thread(target=use_manager)
            user.start()
            self.assertTrue(entered.wait(1))
            replacement = threading.Thread(target=replace_manager)
            replacement.start()
            self.assertFalse(replaced.wait(0.05))
            release.set()
            user.join(2)
            replacement.join(2)
            self.assertFalse(user.is_alive())
            self.assertFalse(replacement.is_alive())
            self.assertTrue(replaced.is_set())
            cache.reset()

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

    def test_reader_nested_in_unit_of_work_reuses_writer_and_sees_uncommitted_row(self):
        with tempfile.TemporaryDirectory() as root:
            manager = self.make_manager(root)
            with manager.unit_of_work() as writer:
                writer.execute("CREATE TABLE records (value TEXT NOT NULL)")
                writer.execute("INSERT INTO records(value) VALUES ('pending')")
                with manager.reader() as reader:
                    self.assertIs(reader, writer)
                    self.assertEqual(
                        reader.execute("SELECT value FROM records").fetchone()[0],
                        "pending",
                    )
            manager.close()

    def test_restore_drain_closes_connections_and_resumes_current_database(self):
        with tempfile.TemporaryDirectory() as root:
            manager = self.make_manager(root)
            self.addCleanup(manager.close)
            with manager.unit_of_work() as db:
                db.execute("CREATE TABLE records (value TEXT NOT NULL)")
            with manager.restore_drain():
                self.assertIsNone(manager._writer)
            with manager.unit_of_work() as db:
                db.execute("INSERT INTO records(value) VALUES ('restored')")
            manager.close()

    def test_initialize_schema_creates_the_current_schema_contract(self):
        with tempfile.TemporaryDirectory() as root:
            manager = self.make_manager(root)
            self.addCleanup(manager.close)
            with manager.unit_of_work() as db:
                initialize_schema(db)
                self.assertTrue(database_schema_is_current(db))
            manager.close()


if __name__ == "__main__":
    unittest.main()
