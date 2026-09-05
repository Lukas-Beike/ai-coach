"""Small SQLCipher-aware connection manager used by the application.

The manager deliberately owns connections, transaction boundaries, and the
restore drain.  Domain code only receives a DB-API connection and therefore
remains usable with both SQLite test doubles and SQLCipher in production.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
import queue
import threading
from typing import Any, Callable, Iterator


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
        self._writer_lock = threading.RLock()
        self._state = threading.Condition(threading.RLock())
        self._readers: queue.LifoQueue[Any] = queue.LifoQueue(maxsize=self.reader_count)
        self._writer: Any | None = None
        self._active = 0
        self._draining = False
        self._closed = False
        self._unit_of_work: ContextVar[Any | None] = ContextVar(
            f"database_manager_uow_{id(self)}", default=None
        )

    def _connect(self) -> Any:
        connection = self.backend.connect(self.path, timeout=self.timeout, check_same_thread=False)
        try:
            if self.password and self.configure:
                self.configure(connection, self.password)
            connection.execute("PRAGMA foreign_keys = ON")
            if self.row_factory is not None:
                connection.row_factory = self.row_factory
            return connection
        except Exception:
            connection.close()
            raise

    @contextmanager
    def _lease(self) -> Iterator[None]:
        with self._state:
            while self._draining:
                self._state.wait()
            if self._closed:
                raise RuntimeError("database manager is closed")
            self._active += 1
        try:
            yield
        finally:
            with self._state:
                self._active -= 1
                self._state.notify_all()

    @contextmanager
    def unit_of_work(self) -> Iterator[Any]:
        """Lease the single writer and commit or roll back atomically."""
        current = self._unit_of_work.get()
        if current is not None:
            yield current
            return
        with self._lease(), self._writer_lock:
            connection = self._writer if self.persist_connections else self._connect()
            if self.persist_connections and connection is None:
                connection = self._connect()
                self._writer = connection
            token = self._unit_of_work.set(connection)
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                self._unit_of_work.reset(token)
                if not self.persist_connections:
                    connection.close()

    @contextmanager
    def reader(self) -> Iterator[Any]:
        """Lease a reader, returning it to the pool after the read."""
        with self._lease():
            try:
                connection = self._readers.get_nowait()
            except queue.Empty:
                connection = self._connect()
            try:
                yield connection
            finally:
                with self._state:
                    draining = self._draining or self._closed
                if draining or not self.persist_connections:
                    connection.close()
                else:
                    try:
                        self._readers.put_nowait(connection)
                    except queue.Full:
                        connection.close()

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
                raise RuntimeError("database manager is closed")
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
