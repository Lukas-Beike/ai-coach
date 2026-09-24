"""Single-flight gates for provider operations and full resynchronization."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from functools import wraps
from typing import Any, TypeVar, cast

from backend.errors import AppError

_Function = TypeVar("_Function", bound=Callable[..., Any])


class ProviderResyncGate:
    """Coordinate one provider reset with all ordinary provider operations."""

    def __init__(self, provider: str):
        self.provider = provider
        self.condition = threading.Condition()
        self.active = 0
        self.resetting = False
        self.owner_thread_id: int | None = None

    @contextmanager
    def operation(self) -> Iterator[None]:
        current_thread_id = threading.get_ident()
        with self.condition:
            if self.resetting and self.owner_thread_id != current_thread_id:
                raise AppError(
                    409,
                    f"Der vollständige {self.provider}-Resync läuft bereits. Bitte warten.",
                )
            if not self.resetting:
                self.active += 1
        try:
            yield
        finally:
            with self.condition:
                if not self.resetting or self.owner_thread_id != current_thread_id:
                    self.active -= 1
                    self.condition.notify_all()

    def begin_reset(self) -> bool:
        with self.condition:
            if self.resetting:
                return False
            self.resetting = True
            self.owner_thread_id = threading.get_ident()
            while self.active:
                self.condition.wait()
            return True

    def end_reset(self) -> None:
        with self.condition:
            self.resetting = False
            self.owner_thread_id = None
            self.condition.notify_all()

    def is_resetting(self) -> bool:
        with self.condition:
            return self.resetting


INTERVALS_RESYNC_GATE = ProviderResyncGate("Intervals.icu")
GARMIN_RESYNC_GATE = ProviderResyncGate("Garmin")


def provider_operation(provider: str) -> AbstractContextManager[None]:
    gate = INTERVALS_RESYNC_GATE if provider == "intervals" else GARMIN_RESYNC_GATE
    return gate.operation()


def _operation_guard(provider: str) -> Callable[[_Function], _Function]:
    def decorate(function: _Function) -> _Function:
        @wraps(function)
        def guarded(*args: Any, **kwargs: Any) -> Any:
            with provider_operation(provider):
                return function(*args, **kwargs)

        return cast(_Function, guarded)

    return decorate


intervals_operation = _operation_guard("intervals")
garmin_operation = _operation_guard("garmin")
