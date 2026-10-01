"""Interrupt blocking socket operations at an absolute elapsed-time limit."""

from __future__ import annotations

import socket
import threading
import time
from types import TracebackType
from typing import Self


class SocketDeadline:
    def __init__(self, connection: socket.socket, seconds: float) -> None:
        self._connection = connection
        self._seconds = seconds
        self._expired = threading.Event()
        self._finished = False
        self._deadline = 0.0
        self._timer = threading.Timer(seconds, self._interrupt)
        self._timer.daemon = True

    def _interrupt(self) -> None:
        self._expired.set()
        try:
            self._connection.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    def __enter__(self) -> Self:
        self._deadline = time.monotonic() + self._seconds
        self._timer.start()
        return self

    def cancel(self) -> None:
        if not self._finished:
            self._timer.cancel()
            self._timer.join()
            self._finished = True
            if time.monotonic() >= self._deadline:
                self._expired.set()
        if self._expired.is_set():
            raise TimeoutError("socket operation deadline exceeded")

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.cancel()
