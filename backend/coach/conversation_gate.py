"""Process-wide bounded serialization gate for Coach conversations."""

from __future__ import annotations

import threading
from collections.abc import Callable
from functools import wraps
from typing import Any, TypeVar

from backend.errors import AppError

CHAT_QUEUE_LIMIT = 3
CHAT_LOCK_TIMEOUT_SECONDS = 30

_ReturnT = TypeVar("_ReturnT")


class CoachConversationGate:
    """Bound chat concurrency and serialize requests with the reset workflow."""

    def __init__(
        self,
        *,
        queue_limit: int = CHAT_QUEUE_LIMIT,
        lock_timeout_seconds: float = CHAT_LOCK_TIMEOUT_SECONDS,
    ) -> None:
        self._lock = threading.RLock()
        self._queue = threading.BoundedSemaphore(queue_limit)
        self._lock_timeout_seconds = lock_timeout_seconds

    @property
    def lock(self) -> threading.RLock:
        return self._lock

    def wrap(self, function: Callable[..., _ReturnT]) -> Callable[..., _ReturnT]:
        @wraps(function)
        def wrapped(*args: Any, **kwargs: Any) -> _ReturnT:
            if not self._queue.acquire(blocking=False):
                raise AppError(
                    429,
                    "Der Coach ist gerade ausgelastet. Bitte später erneut versuchen.",
                    reason="chat_queue_full",
                )
            acquired = self._lock.acquire(timeout=self._lock_timeout_seconds)
            if not acquired:
                self._queue.release()
                raise AppError(
                    409,
                    "Die vorherige Coach-Anfrage läuft noch. Bitte erneut versuchen.",
                    reason="chat_request_timeout",
                )
            try:
                return function(*args, **kwargs)
            finally:
                self._lock.release()
                self._queue.release()

        return wrapped
