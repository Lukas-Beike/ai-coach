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
        return DatabaseManager(
            Path(root) / "test.db", sqlite3, reader_count=4, row_factory=sqlite3.Row
        )

    def test_cache_reuses_replaces_and_resets_the_active_manager(self):
        with tempfile.TemporaryDirectory() as root:
            cache = DatabaseManagerCache()
            first_signature = (str(Path(root) / "first.db"), "", False)
            second_signature = (str(Path(root) / "second.db"), "", False)

            first = cache.get(first_signature, first_signature[0], sqlite3)
            self.assertIs(
                cache.get(first_signature, first_signature[0], sqlite3), first
            )
            self.assertTrue(cache.matches(first_signature))

            second = cache.get(second_signature, second_signature[0], sqlite3)
            self.assertIsNot(second, first)
            self.assertFalse(cache.matches(first_signature))
            with (
                self.assertRaisesRegex(RuntimeError, "database manager is closed"),
                first.unit_of_work(),
            ):
                pass

            cache.reset()
            self.assertFalse(cache.matches(second_signature))
            with (
                self.assertRaisesRegex(RuntimeError, "database manager is closed"),
                second.unit_of_work(),
            ):
                pass

    def test_cache_unit_of_work_uses_the_current_manager_lazily(self):
        with tempfile.TemporaryDirectory() as root:
            cache = DatabaseManagerCache()
            with (
                self.assertRaisesRegex(RuntimeError, "not initialized"),
                cache.unit_of_work(),
            ):
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
            with self.assertRaises(RuntimeError), manager.unit_of_work() as db:
                db.execute("INSERT INTO records(value) VALUES (?)", ("discarded",))
                raise RuntimeError("rollback")
            with manager.reader() as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM records").fetchone()[0], 0
                )
            with manager.reader() as first:
                first_id = id(first)
            with manager.reader() as second:
                self.assertEqual(id(second), first_id)
            manager.close()

    def test_unit_of_work_rolls_back_on_base_exceptions_before_reuse(self):
        class Interrupted(BaseException):
            """Stands in for KeyboardInterrupt or a cancelled task."""

        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        manager = self.make_manager(temporary.name)
        self.addCleanup(manager.close)
        with manager.unit_of_work() as db:
            db.execute("CREATE TABLE records (value TEXT NOT NULL)")
        with self.assertRaises(Interrupted), manager.unit_of_work() as db:
            db.execute("INSERT INTO records(value) VALUES (?)", ("discarded",))
            raise Interrupted
        with manager.unit_of_work() as db:
            self.assertFalse(db.in_transaction)
            self.assertEqual(
                db.execute("SELECT COUNT(*) FROM records").fetchone()[0], 0
            )

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

            threads = [
                threading.Thread(target=write, args=(value,)) for value in (1, 2, 3, 4)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(maximum, 1)
            with manager.reader() as db:
                self.assertEqual(
                    db.execute("SELECT COUNT(*) FROM records").fetchone()[0], 4
                )
            manager.close()

    def test_writer_wait_is_bounded(self):
        with tempfile.TemporaryDirectory() as root:
            manager = DatabaseManager(
                Path(root) / "bounded-writer.db",
                sqlite3,
                timeout=0.05,
                row_factory=sqlite3.Row,
            )
            with manager.unit_of_work() as db:
                db.execute("CREATE TABLE records (value INTEGER NOT NULL)")
            self.assertTrue(manager._writer_lock.acquire())
            try:
                failure = []

                def competing_writer() -> None:
                    try:
                        with manager.unit_of_work():
                            pass
                    except TimeoutError as exc:
                        failure.append(str(exc))

                contender = threading.Thread(target=competing_writer)
                contender.start()
                contender.join(1)
                self.assertFalse(contender.is_alive())
                self.assertEqual(failure, ["database writer limit reached"])
            finally:
                manager._writer_lock.release()
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

    def test_readers_are_bounded_and_nested_reader_calls_reuse_the_lease(self):
        with tempfile.TemporaryDirectory() as root:
            manager = DatabaseManager(
                Path(root) / "bounded.db",
                sqlite3,
                reader_count=1,
                timeout=0.05,
                row_factory=sqlite3.Row,
            )
            self.addCleanup(manager.close)
            with manager.reader() as first:
                with manager.reader() as nested:
                    self.assertIs(first, nested)
                failures = []

                def competing_reader():
                    try:
                        with manager.reader():
                            pass
                    except TimeoutError as exc:
                        failures.append(str(exc))

                contender = threading.Thread(target=competing_reader)
                contender.start()
                contender.join(1)
                self.assertFalse(contender.is_alive())
                self.assertEqual(failures, ["database reader limit reached"])
            manager.close()

    def make_wal_manager(self, **options) -> DatabaseManager:
        root = self.enterContext(tempfile.TemporaryDirectory())
        manager = DatabaseManager(
            Path(root) / "snapshot.db",
            sqlite3,
            row_factory=sqlite3.Row,
            **options,
        )
        self.addCleanup(manager.close)
        with manager.unit_of_work() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE records (value INTEGER NOT NULL)")
            db.execute("INSERT INTO records(value) VALUES (1)")
        return manager

    @staticmethod
    def count(db) -> int:
        return db.execute("SELECT COUNT(*) FROM records").fetchone()[0]

    def test_read_snapshot_is_consistent_across_concurrent_commits(self):
        manager = self.make_wal_manager()
        with manager.read_snapshot() as snapshot:
            self.assertEqual(self.count(snapshot), 1)
            committed = threading.Event()

            def write() -> None:
                with manager.unit_of_work() as db:
                    db.execute("INSERT INTO records(value) VALUES (2)")
                committed.set()

            writer = threading.Thread(target=write)
            writer.start()
            self.assertTrue(committed.wait(5))
            writer.join(5)
            # The commit landed, but the pinned snapshot must not see it.
            self.assertEqual(self.count(snapshot), 1)
        with manager.read_snapshot() as fresh:
            self.assertEqual(self.count(fresh), 2)

    def test_read_snapshot_is_not_blocked_by_a_long_held_writer(self):
        manager = self.make_wal_manager()
        holding = threading.Event()
        release = threading.Event()

        def hold_writer() -> None:
            with manager.unit_of_work() as db:
                db.execute("INSERT INTO records(value) VALUES (2)")
                holding.set()
                release.wait(10)

        writer = threading.Thread(target=hold_writer)
        writer.start()
        try:
            self.assertTrue(holding.wait(5))
            results = []

            def read() -> None:
                with manager.read_snapshot() as db:
                    results.append(self.count(db))

            reader = threading.Thread(target=read)
            reader.start()
            reader.join(5)
            self.assertFalse(reader.is_alive())
            # Only committed data is visible while the writer is open.
            self.assertEqual(results, [1])
        finally:
            release.set()
            writer.join(5)

    def test_read_snapshot_is_read_only_and_restores_the_pooled_connection(self):
        manager = self.make_wal_manager()
        with manager.read_snapshot() as snapshot:
            with manager.unit_of_work() as nested, manager.reader() as again:
                self.assertIs(nested, snapshot)
                self.assertIs(again, snapshot)
                with self.assertRaises(sqlite3.OperationalError):
                    nested.execute("INSERT INTO records(value) VALUES (9)")
            snapshot_id = id(snapshot)
        with manager.reader() as reused:
            self.assertEqual(id(reused), snapshot_id)
            self.assertFalse(reused.in_transaction)
            self.assertEqual(reused.execute("PRAGMA query_only").fetchone()[0], 0)
        with manager.unit_of_work() as db:
            db.execute("INSERT INTO records(value) VALUES (3)")
        with manager.read_snapshot() as db:
            self.assertEqual(self.count(db), 2)

    def test_read_snapshot_releases_its_lease_after_an_error(self):
        manager = self.make_wal_manager(reader_count=1, timeout=0.2)
        with self.assertRaises(RuntimeError), manager.read_snapshot():
            raise RuntimeError("handler failed")
        with manager.read_snapshot() as db:
            self.assertEqual(self.count(db), 1)
        manager.close()

    def test_read_snapshot_nested_in_unit_of_work_reuses_the_writer(self):
        manager = self.make_wal_manager()
        with manager.unit_of_work() as writer:
            writer.execute("INSERT INTO records(value) VALUES (2)")
            with manager.read_snapshot() as nested:
                self.assertIs(nested, writer)
                self.assertEqual(self.count(nested), 2)

    def test_unit_of_work_accepts_a_shorter_writer_wait(self):
        manager = self.make_wal_manager(timeout=30)
        self.assertTrue(manager._writer_lock.acquire())
        try:
            failure = []

            def contender() -> None:
                started = time.monotonic()
                try:
                    with manager.unit_of_work(timeout=0.05):
                        pass
                except TimeoutError as exc:
                    failure.append((str(exc), time.monotonic() - started))

            thread = threading.Thread(target=contender)
            thread.start()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failure[0][0], "database writer limit reached")
            self.assertLess(failure[0][1], 5)
        finally:
            manager._writer_lock.release()

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

    def test_failed_fresh_schema_creation_leaves_no_partial_tables(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        db = sqlite3.connect(Path(temporary.name) / "fresh.db")
        self.addCleanup(db.close)
        # The script creates kv first; a conflicting snapshots table fails it midway.
        db.execute("CREATE TABLE snapshots (blocked INTEGER)")
        db.commit()

        with self.assertRaises(sqlite3.OperationalError):
            initialize_schema(db)

        self.assertFalse(db.in_transaction)
        self.assertEqual(
            {
                row[0]
                for row in db.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                )
            },
            {"snapshots"},
        )


if __name__ == "__main__":
    unittest.main()
