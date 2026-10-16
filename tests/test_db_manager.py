import sqlite3
import tempfile
import threading
import time
import unittest
from pathlib import Path

from backend.db.manager import (
    DATABASE_BUSY_MESSAGE,
    DatabaseBusyError,
    DatabaseManager,
    DatabaseManagerCache,
    WriterGate,
    background_writer,
)
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
                    except DatabaseBusyError as exc:
                        failure.append(exc.resource)

                contender = threading.Thread(target=competing_writer)
                contender.start()
                contender.join(1)
                self.assertFalse(contender.is_alive())
                self.assertEqual(failure, ["writer"])
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
                    except DatabaseBusyError as exc:
                        failures.append(exc.resource)

                contender = threading.Thread(target=competing_reader)
                contender.start()
                contender.join(1)
                self.assertFalse(contender.is_alive())
                self.assertEqual(failures, ["reader"])
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
                except DatabaseBusyError as exc:
                    failure.append((exc.resource, time.monotonic() - started))

            thread = threading.Thread(target=contender)
            thread.start()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failure[0][0], "writer")
            self.assertLess(failure[0][1], 5)
        finally:
            manager._writer_lock.release()

    def test_write_nested_in_reader_finishes_while_restore_drains(self):
        manager = self.make_wal_manager(timeout=5)
        drained = threading.Event()
        errors: list[BaseException] = []

        def drain() -> None:
            with manager.restore_drain():
                drained.set()

        drainer = threading.Thread(target=drain, daemon=True)
        self.addCleanup(drainer.join, 5)

        def read_then_write() -> None:
            try:
                with manager.reader() as db:
                    self.assertEqual(self.count(db), 1)
                    drainer.start()
                    deadline = time.monotonic() + 5
                    while not manager._draining:
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(0.005)
                    # The nested write reuses the outer lease instead of
                    # waiting for the drain, which waits for that lease.
                    with manager.unit_of_work() as writer:
                        writer.execute("INSERT INTO records(value) VALUES (2)")
                    self.assertFalse(drained.is_set())
            except BaseException as exc:  # noqa: BLE001 - reported by the test thread
                errors.append(exc)

        worker = threading.Thread(target=read_then_write, daemon=True)
        worker.start()
        worker.join(5)
        if worker.is_alive():
            # Unblock the deadlocked write so the test fails instead of hanging.
            with manager._state:
                manager._draining = False
                manager._state.notify_all()
            worker.join(5)
            self.fail("a write nested in a reader waited for the restore drain")
        if errors:
            raise errors[0]
        drainer.join(5)
        self.assertTrue(drained.is_set())
        with manager.reader() as db:
            self.assertEqual(self.count(db), 2)

    def test_reader_rolls_back_a_write_left_open_on_its_connection(self):
        manager = self.make_wal_manager(reader_count=1)
        with manager.reader() as db:
            db.execute("INSERT INTO records(value) VALUES (2)")
            self.assertTrue(db.in_transaction)
            pooled = id(db)
        with manager.reader() as db:
            self.assertEqual(id(db), pooled)
            self.assertFalse(db.in_transaction)
            self.assertEqual(self.count(db), 1)
        # The pooled reader no longer holds the database write lock.
        with manager.unit_of_work(timeout=0.2) as db:
            db.execute("INSERT INTO records(value) VALUES (3)")

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


class WriterGateTests(unittest.TestCase):
    def wait_until(self, condition) -> None:
        deadline = time.monotonic() + 5
        while not condition():
            self.assertLess(time.monotonic(), deadline, "condition never became true")
            time.sleep(0.005)

    def contender(self, gate: WriterGate, order: list[str], kind: str, **options):
        """Start a thread that takes the gate, records ``kind`` and releases."""

        def run() -> None:
            def take() -> None:
                if gate.acquire(**options):
                    order.append(kind)
                    gate.release()
                else:
                    order.append(f"{kind}-timeout")

            if kind.startswith("bg"):
                with background_writer():
                    take()
            else:
                take()

        thread = threading.Thread(target=run)
        thread.start()
        self.addCleanup(thread.join, 5)
        return thread

    def test_foreground_beats_a_waiting_background_writer(self):
        gate = WriterGate()
        order: list[str] = []
        self.assertTrue(gate.acquire())
        background = self.contender(gate, order, "bg")
        self.wait_until(lambda: gate._background_waiting == 1)
        foreground = self.contender(gate, order, "fg")
        self.wait_until(lambda: gate._foreground_waiting == 1)
        gate.release()
        foreground.join(5)
        background.join(5)
        self.assertEqual(order, ["fg", "bg"])

    def test_background_writer_takes_an_idle_gate_immediately(self):
        gate = WriterGate()
        with background_writer():
            self.assertTrue(gate.acquire(timeout=0))
            gate.release()

    def test_background_writer_is_not_starved_by_foreground_writers(self):
        gate = WriterGate(bypass_limit=2)
        order: list[str] = []
        self.assertTrue(gate.acquire())
        background = self.contender(gate, order, "bg")
        self.wait_until(lambda: gate._background_waiting == 1)
        foregrounds = [self.contender(gate, order, "fg") for _ in range(3)]
        self.wait_until(lambda: gate._foreground_waiting == 3)
        gate.release()
        for thread in (background, *foregrounds):
            thread.join(5)
        # Two foreground writers may pass the waiting background writer; it is next.
        self.assertEqual(order, ["fg", "fg", "bg", "fg"])

    def test_reentrant_acquire_needs_a_release_per_acquire(self):
        gate = WriterGate()
        self.assertTrue(gate.acquire())
        self.assertTrue(gate.acquire(timeout=0))
        results: list[bool] = []

        def other() -> None:
            got = gate.acquire(timeout=0)
            results.append(got)
            if got:
                gate.release()

        def run_other() -> None:
            thread = threading.Thread(target=other)
            thread.start()
            thread.join(5)

        gate.release()
        run_other()
        gate.release()
        run_other()
        self.assertEqual(results, [False, True])

    def test_release_by_a_thread_that_does_not_own_the_gate_is_rejected(self):
        gate = WriterGate()
        with self.assertRaises(RuntimeError):
            gate.release()
        self.assertTrue(gate.acquire())
        errors: list[BaseException] = []

        def other() -> None:
            try:
                gate.release()
            except RuntimeError as exc:
                errors.append(exc)

        thread = threading.Thread(target=other)
        thread.start()
        thread.join(5)
        gate.release()
        self.assertEqual(len(errors), 1)
        # The failed release did not disturb ownership.
        self.assertTrue(gate.acquire(timeout=0))
        gate.release()

    def test_acquire_times_out_without_leaving_a_waiter_behind(self):
        gate = WriterGate()
        held = threading.Event()
        release = threading.Event()

        def hold() -> None:
            gate.acquire()
            held.set()
            release.wait(10)
            gate.release()

        holder = threading.Thread(target=hold)
        holder.start()
        try:
            self.assertTrue(held.wait(5))
            self.assertFalse(gate.acquire(timeout=0))
            started = time.monotonic()
            self.assertFalse(gate.acquire(timeout=0.05))
            self.assertGreaterEqual(time.monotonic() - started, 0.04)
            with background_writer():
                self.assertFalse(gate.acquire(timeout=0.05))
            self.assertEqual(gate._foreground_waiting, 0)
            self.assertEqual(gate._background_waiting, 0)
        finally:
            release.set()
            holder.join(5)
        self.assertTrue(gate.acquire(timeout=0))
        gate.release()

    def test_negative_timeout_waits_until_the_writer_is_released(self):
        gate = WriterGate()
        order: list[str] = []
        self.assertTrue(gate.acquire())
        waiter = self.contender(gate, order, "fg", timeout=-1)
        self.wait_until(lambda: gate._foreground_waiting == 1)
        time.sleep(0.05)
        self.assertEqual(order, [])
        gate.release()
        waiter.join(5)
        self.assertEqual(order, ["fg"])

    def test_a_timed_out_foreground_waiter_frees_the_background_writer(self):
        gate = WriterGate()
        order: list[str] = []
        self.assertTrue(gate.acquire())
        background = self.contender(gate, order, "bg")
        self.wait_until(lambda: gate._background_waiting == 1)
        # The foreground waiter gives up while the writer is still held.
        foreground = self.contender(gate, order, "fg", timeout=0.05)
        foreground.join(5)
        self.assertEqual(order, ["fg-timeout"])
        gate.release()
        background.join(5)
        self.assertEqual(order, ["fg-timeout", "bg"])

    def test_a_timed_out_background_waiter_does_not_leave_its_bypass_count(self):
        gate = WriterGate(bypass_limit=1)
        order: list[str] = []
        granted = threading.Event()
        release = threading.Event()
        self.assertTrue(gate.acquire())
        background = self.contender(gate, order, "bg", timeout=0.2)
        self.wait_until(lambda: gate._background_waiting == 1)

        def hold() -> None:
            gate.acquire()
            granted.set()
            release.wait(5)
            gate.release()

        holder = threading.Thread(target=hold)
        holder.start()
        self.addCleanup(holder.join, 5)
        self.wait_until(lambda: gate._foreground_waiting == 1)
        gate.release()
        # The foreground writer passes the waiting background writer, which
        # then gives up while the writer is still held.
        self.assertTrue(granted.wait(5))
        background.join(5)
        self.assertEqual(order, ["bg-timeout"])
        self.assertEqual(gate._bypassed, 0)
        # A new background writer waits behind a waiting foreground writer.
        late = self.contender(gate, order, "bg")
        self.wait_until(lambda: gate._background_waiting == 1)
        foreground = self.contender(gate, order, "fg")
        self.wait_until(lambda: gate._foreground_waiting == 1)
        release.set()
        for thread in (holder, foreground, late):
            thread.join(5)
        self.assertEqual(order, ["bg-timeout", "fg", "bg"])

    def test_unit_of_work_background_writes_yield_to_waiting_foreground_writes(self):
        manager = self.make_manager()
        order: list[str] = []
        holding = threading.Event()
        release = threading.Event()

        def hold() -> None:
            with manager.unit_of_work() as db:
                db.execute("INSERT INTO records(value) VALUES (0)")
                holding.set()
                release.wait(10)

        def write(kind: str, value: int) -> None:
            def run() -> None:
                with manager.unit_of_work() as db:
                    db.execute("INSERT INTO records(value) VALUES (?)", (value,))
                    order.append(kind)

            if kind == "bg":
                with background_writer():
                    run()
            else:
                run()

        holder = threading.Thread(target=hold)
        holder.start()
        self.assertTrue(holding.wait(5))
        gate = manager._writer_lock
        background = threading.Thread(target=write, args=("bg", 1))
        background.start()
        self.wait_until(lambda: gate._background_waiting == 1)
        foreground = threading.Thread(target=write, args=("fg", 2))
        foreground.start()
        self.wait_until(lambda: gate._foreground_waiting == 1)
        release.set()
        for thread in (holder, background, foreground):
            thread.join(5)
        self.assertEqual(order, ["fg", "bg"])
        with manager.unit_of_work() as db:
            values = [row[0] for row in db.execute("SELECT value FROM records")]
        self.assertEqual(sorted(values), [0, 1, 2])

    def test_cache_passes_the_writer_wait_to_the_manager(self):
        root = self.enterContext(tempfile.TemporaryDirectory())
        cache = DatabaseManagerCache()
        signature = (str(Path(root) / "cache.db"), "", False)
        manager = cache.get(signature, signature[0], sqlite3)
        self.addCleanup(manager.close)
        held = threading.Event()
        release = threading.Event()

        def hold() -> None:
            with cache.unit_of_work():
                held.set()
                release.wait(10)

        holder = threading.Thread(target=hold)
        holder.start()
        try:
            self.assertTrue(held.wait(5))
            failure: list[str] = []

            def contender() -> None:
                try:
                    with cache.unit_of_work(timeout=0):
                        pass
                except DatabaseBusyError as exc:
                    failure.append(exc.resource)

            thread = threading.Thread(target=contender)
            thread.start()
            thread.join(5)
            self.assertFalse(thread.is_alive())
            self.assertEqual(failure, ["writer"])
        finally:
            release.set()
            holder.join(5)

    def make_manager(self) -> DatabaseManager:
        root = self.enterContext(tempfile.TemporaryDirectory())
        manager = DatabaseManager(
            Path(root) / "gate.db", sqlite3, row_factory=sqlite3.Row
        )
        self.addCleanup(manager.close)
        with manager.unit_of_work() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE records (value INTEGER NOT NULL)")
        return manager


class DatabaseBusyErrorTests(unittest.TestCase):
    def test_busy_error_is_a_timeout_with_a_displayable_message(self):
        error = DatabaseBusyError("writer")

        self.assertIsInstance(error, TimeoutError)
        self.assertEqual(str(error), DATABASE_BUSY_MESSAGE)
        self.assertEqual(error.reason, "database_busy")
        self.assertEqual(error.resource, "writer")


if __name__ == "__main__":
    unittest.main()
