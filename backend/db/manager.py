"""Small SQLCipher-aware connection manager used by the application.

The manager deliberately owns connections, transaction boundaries, and the
restore drain.  Domain code only receives a DB-API connection and therefore
remains usable with both SQLite test doubles and SQLCipher in production.
"""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from backend.errors import DatabaseBusyError

DATABASE_MANAGER_CLOSED_MESSAGE = "database manager is closed"
DATABASE_MANAGER_UNINITIALIZED_MESSAGE = "database manager is not initialized"
# The application lock coordinates larger transactions and restore work that
# span multiple repositories. DatabaseManager keeps its own connection locks.
DATABASE_LOCK = threading.RLock()

# Foreground writers that are granted the writer while a background writer
# waits; after this many the background writer is served next, so a steady
# stream of short foreground writes can delay but never starve background work.
BACKGROUND_WRITER_BYPASS_LIMIT = 8

_BACKGROUND_WRITER: ContextVar[bool] = ContextVar(
    "database_background_writer", default=False
)


@contextmanager
def background_writer() -> Iterator[None]:
    """Mark writer acquisitions in this context as deferrable background work."""
    token = _BACKGROUND_WRITER.set(True)
    try:
        yield
    finally:
        _BACKGROUND_WRITER.reset(token)


class WriterGate:
    """Re-entrant single-writer gate that serves foreground waiters first.

    A background acquirer waits while any foreground acquirer is waiting, up to
    ``bypass_limit`` foreground grants. The gate only orders acquisitions: a
    held writer is never preempted, so one unit of work stays atomic.
    """

    def __init__(self, bypass_limit: int = BACKGROUND_WRITER_BYPASS_LIMIT) -> None:
        self._condition = threading.Condition(threading.Lock())
        self._bypass_limit = max(1, int(bypass_limit))
        self._owner: int | None = None
        self._depth = 0
        self._foreground_waiting = 0
        self._background_waiting = 0
        self._bypassed = 0

    def _may_take(self, background: bool) -> bool:
        if self._owner is not None:
            return False
        starved = self._bypassed >= self._bypass_limit
        if background:
            return self._foreground_waiting == 0 or starved
        return not (self._background_waiting and starved)

    def _grant(self, background: bool) -> None:
        self._owner = threading.get_ident()
        self._depth = 1
        if background:
            self._bypassed = 0
        elif self._background_waiting:
            self._bypassed += 1

    def acquire(self, timeout: float = -1) -> bool:
        """Take the writer; a negative ``timeout`` waits without limit."""
        background = _BACKGROUND_WRITER.get()
        with self._condition:
            if self._owner == threading.get_ident():
                self._depth += 1
                return True
            if self._may_take(background):
                self._grant(background)
                return True
            if timeout == 0:
                return False
            deadline = None if timeout < 0 else time.monotonic() + timeout
            if background:
                self._background_waiting += 1
            else:
                self._foreground_waiting += 1
            try:
                return self._wait_for_turn(background, deadline)
            finally:
                self._stop_waiting(background)

    def _wait_for_turn(self, background: bool, deadline: float | None) -> bool:
        while True:
            remaining = None if deadline is None else deadline - time.monotonic()
            if remaining is not None and remaining <= 0:
                return False
            self._condition.wait(remaining)
            if self._may_take(background):
                self._grant(background)
                return True

    def _stop_waiting(self, background: bool) -> None:
        if background:
            self._background_waiting -= 1
            if not self._background_waiting:
                # Grants only count against a waiting background writer.
                self._bypassed = 0
        else:
            self._foreground_waiting -= 1
        # A waiter that gave up (or was served) may unblock the others.
        self._condition.notify_all()

    def release(self) -> None:
        with self._condition:
            if self._owner != threading.get_ident():
                raise RuntimeError("cannot release an unowned database writer")
            self._depth -= 1
            if self._depth == 0:
                self._owner = None
                self._condition.notify_all()


class DatabaseManager:
    """One serialized writer plus a bounded pool of read connections."""

    def __init__(
        self,
        path: str | Path,
        backend: Any,
        *,
        password: str = "",
        configure: Callable[[Any, str], None] | None = None,
        row_factory: Callable[[Any, tuple[Any, ...]], Any] | None = None,
        reader_count: int = 4,
        timeout: float = 20.0,
        persist_connections: bool = True,
    ):
        self.path = Path(path)
        self.backend = backend
        self.password = password
        self.configure = configure
        self.row_factory = row_factory
        self.reader_count = max(1, int(reader_count))
        self.timeout = timeout
        self.persist_connections = bool(persist_connections)
        self._writer_lock = WriterGate()
        self._state = threading.Condition(threading.RLock())
        self._readers: queue.LifoQueue[Any] = queue.LifoQueue(maxsize=self.reader_count)
        self._writer: Any | None = None
        self._active = 0
        self._draining = False
        self._closed = False
        self._unit_of_work: ContextVar[Any | None] = ContextVar(
            f"database_manager_uow_{id(self)}", default=None
        )
        self._reader_context: ContextVar[Any | None] = ContextVar(
            f"database_manager_reader_{id(self)}", default=None
        )
        self._snapshot_context: ContextVar[Any | None] = ContextVar(
            f"database_manager_snapshot_{id(self)}", default=None
        )
        self._lease_held: ContextVar[bool] = ContextVar(
            f"database_manager_lease_{id(self)}", default=False
        )
        self._reader_slots = threading.BoundedSemaphore(self.reader_count)

    def _connect(self) -> Any:
        connection = self.backend.connect(
            self.path, timeout=self.timeout, check_same_thread=False
        )
        try:
            if self.password and self.configure:
                self.configure(connection, self.password)
            connection.execute("PRAGMA foreign_keys = ON")
            # Keep a 16 MiB decrypted-page working set per pooled connection:
            # large enough for canonical reads on long athlete histories while
            # bounding the pool's resident cache.
            connection.execute("PRAGMA cache_size = -16384")
            if self.row_factory is not None:
                connection.row_factory = self.row_factory
            return connection
        except Exception:
            connection.close()
            raise

    @contextmanager
    def _lease(self) -> Iterator[None]:
        if self._lease_held.get():
            # A nested lease (a write inside a reader) must not wait for a
            # restore drain that is itself waiting for the outer lease.
            yield
            return
        with self._state:
            if self._closed:
                raise RuntimeError(DATABASE_MANAGER_CLOSED_MESSAGE)
            while self._draining:
                self._state.wait()
                if self._closed:
                    raise RuntimeError(DATABASE_MANAGER_CLOSED_MESSAGE)
            self._active += 1
        token = self._lease_held.set(True)
        try:
            yield
        finally:
            self._lease_held.reset(token)
            with self._state:
                self._active -= 1
                self._state.notify_all()

    @contextmanager
    def unit_of_work(self, *, timeout: float | None = None) -> Iterator[Any]:
        """Lease the single writer and commit or roll back atomically.

        ``timeout`` bounds the wait for the writer; it defaults to the manager
        timeout and ``0`` only tries once. Work started under
        ``background_writer()`` yields to waiting foreground writers. Inside
        ``read_snapshot`` the read-only snapshot is reused, so a nested read
        helper keeps the snapshot while a write fails loudly.
        """
        current = self._unit_of_work.get()
        if current is not None:
            yield current
            return
        current = self._snapshot_context.get()
        if current is not None:
            yield current
            return
        with self._lease():
            wait = self.timeout if timeout is None else timeout
            if not self._writer_lock.acquire(timeout=wait):
                raise DatabaseBusyError("writer")
            try:
                connection = (
                    self._writer if self.persist_connections else self._connect()
                )
                if self.persist_connections and connection is None:
                    connection = self._connect()
                    self._writer = connection
                assert connection is not None
                token = self._unit_of_work.set(connection)
                try:
                    yield connection
                    connection.commit()
                except BaseException:
                    # Also covers KeyboardInterrupt and task cancellation, which
                    # must not leave an open transaction on the persistent writer.
                    connection.rollback()
                    raise
                finally:
                    self._unit_of_work.reset(token)
                    if not self.persist_connections:
                        connection.close()
            finally:
                self._writer_lock.release()

    @contextmanager
    def reader(self) -> Iterator[Any]:
        """Lease a reader, returning it to the pool after the read."""
        current = self._unit_of_work.get()
        if current is not None:
            # A projection inside an active request transaction must observe
            # that transaction and reuse its keyed SQLCipher connection.
            yield current
            return
        current = self._reader_context.get()
        if current is not None:
            yield current
            return
        with self._lease():
            if not self._reader_slots.acquire(timeout=self.timeout):
                raise DatabaseBusyError("reader")
            try:
                try:
                    connection = self._readers.get_nowait()
                except queue.Empty:
                    connection = self._connect()
                token = self._reader_context.set(connection)
                try:
                    yield connection
                finally:
                    self._reader_context.reset(token)
                    reusable = True
                    if getattr(connection, "in_transaction", False):
                        # A write through a reader handle must not stay open
                        # on a pooled connection and hold the database lock.
                        try:
                            connection.rollback()
                        except Exception:  # noqa: BLE001 - a connection that cannot roll back is closed, not pooled
                            reusable = False
                    with self._state:
                        draining = self._draining or self._closed
                    if draining or not reusable or not self.persist_connections:
                        connection.close()
                    else:
                        try:
                            self._readers.put_nowait(connection)
                        except queue.Full:
                            connection.close()
            finally:
                self._reader_slots.release()

    @contextmanager
    def read_snapshot(self) -> Iterator[Any]:
        """Lease a reader pinned to one read-only WAL snapshot.

        Every query in the block sees the same committed state, so a handler
        that composes several reads is consistent without the writer lock. The
        connection is ``query_only`` for the block: a nested ``unit_of_work`` or
        ``reader`` reuses it, and any write fails instead of silently racing.
        Inside a plain ``reader`` that reader is reused as is, without a
        pinned snapshot.
        """
        current = self._unit_of_work.get()
        if current is not None:
            yield current
            return
        current = self._snapshot_context.get() or self._reader_context.get()
        if current is not None:
            yield current
            return
        with self._lease():
            if not self._reader_slots.acquire(timeout=self.timeout):
                raise DatabaseBusyError("reader")
            try:
                try:
                    connection = self._readers.get_nowait()
                except queue.Empty:
                    connection = self._connect()
                reusable = False
                try:
                    connection.execute("PRAGMA query_only = ON")
                    connection.execute("BEGIN")
                    snapshot_token = self._snapshot_context.set(connection)
                    reader_token = self._reader_context.set(connection)
                    try:
                        yield connection
                    finally:
                        self._reader_context.reset(reader_token)
                        self._snapshot_context.reset(snapshot_token)
                        connection.rollback()
                        connection.execute("PRAGMA query_only = OFF")
                        reusable = True
                finally:
                    with self._state:
                        draining = self._draining or self._closed
                    if reusable and self.persist_connections and not draining:
                        try:
                            self._readers.put_nowait(connection)
                        except queue.Full:
                            connection.close()
                    else:
                        connection.close()
            finally:
                self._reader_slots.release()

    def _close_connections(self) -> None:
        if self._writer is not None:
            self._writer.close()
            self._writer = None
        while True:
            try:
                self._readers.get_nowait().close()
            except queue.Empty:
                return

    @contextmanager
    def restore_drain(self) -> Iterator[None]:
        """Stop new leases, wait for active work, and close every connection."""
        with self._state:
            if self._closed:
                raise RuntimeError(DATABASE_MANAGER_CLOSED_MESSAGE)
            self._draining = True
            while self._active:
                self._state.wait()
            self._close_connections()
        try:
            yield
        finally:
            with self._state:
                self._draining = False
                self._state.notify_all()

    def close(self) -> None:
        with self._state:
            self._draining = True
            while self._active:
                self._state.wait()
            self._closed = True
            self._close_connections()
            self._state.notify_all()


class DatabaseManagerCache:
    """Reuse the active manager until its path or encryption key changes."""

    def __init__(self) -> None:
        self.manager: DatabaseManager | None = None
        self.signature: tuple[str, str, bool] | None = None
        self._lock = threading.RLock()
        self._current_manager: ContextVar[DatabaseManager | None] = ContextVar(
            f"database_cache_manager_{id(self)}", default=None
        )

    def get(
        self,
        signature: tuple[str, str, bool],
        path: str | Path,
        backend: Any,
        *,
        password: str = "",
        configure: Callable[[Any, str], None] | None = None,
        row_factory: Callable[[Any, tuple[Any, ...]], Any] | None = None,
        reader_count: int = 4,
        timeout: float = 20.0,
        persist_connections: bool = True,
    ) -> DatabaseManager:
        current = self._current_manager.get()
        if current is not None:
            return current
        with self._lock:
            if self.manager is not None and self.signature != signature:
                self.manager.close()
                self.manager = None
                self.signature = None
            if self.manager is None:
                self.manager = DatabaseManager(
                    path,
                    backend,
                    password=password,
                    configure=configure,
                    row_factory=row_factory,
                    reader_count=reader_count,
                    timeout=timeout,
                    persist_connections=persist_connections,
                )
                self.signature = signature
            return self.manager

    def matches(self, signature: tuple[str, str, bool]) -> bool:
        with self._lock:
            return self.manager is not None and self.signature == signature

    def reset(self) -> None:
        with self._lock:
            manager = self.manager
            self.manager = None
            self.signature = None
        if manager is not None:
            manager.close()

    @contextmanager
    def unit_of_work(self, *, timeout: float | None = None) -> Iterator[Any]:
        """Use the current manager without forcing its construction."""
        manager = self._current_manager.get()
        if manager is None:
            with self._lock:
                manager = self.manager
            if manager is None:
                raise RuntimeError(DATABASE_MANAGER_UNINITIALIZED_MESSAGE)
        token = self._current_manager.set(manager)
        try:
            with manager.unit_of_work(timeout=timeout) as db:
                yield db
        finally:
            self._current_manager.reset(token)

    @contextmanager
    def reader(self) -> Iterator[Any]:
        """Use a read lease without holding the cache lock while waiting."""
        manager = self._current_manager.get()
        if manager is None:
            with self._lock:
                manager = self.manager
            if manager is None:
                raise RuntimeError(DATABASE_MANAGER_UNINITIALIZED_MESSAGE)
        token = self._current_manager.set(manager)
        try:
            with manager.reader() as db:
                yield db
        finally:
            self._current_manager.reset(token)

    @contextmanager
    def read_snapshot(self) -> Iterator[Any]:
        """Use a pinned read-only snapshot on the current manager."""
        manager = self._current_manager.get()
        if manager is None:
            with self._lock:
                manager = self.manager
            if manager is None:
                raise RuntimeError(DATABASE_MANAGER_UNINITIALIZED_MESSAGE)
        token = self._current_manager.set(manager)
        try:
            with manager.read_snapshot() as db:
                yield db
        finally:
            self._current_manager.reset(token)


DATABASE_MANAGER_CACHE = DatabaseManagerCache()
