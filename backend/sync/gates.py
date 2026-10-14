"""Single-flight gates for provider operations and full resynchronization."""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from functools import wraps
from typing import Any, TypeVar, cast

from backend.errors import AppError
from backend.providers.descriptors import (
    DEFAULT_PROVIDER_DESCRIPTORS,
    GARMIN_ID,
    INTERVALS_ID,
    WAHOO_ID,
)

_Function = TypeVar("_Function", bound=Callable[..., Any])


class ProviderResyncGate:
    """Coordinate one provider reset with all ordinary provider operations."""

    def __init__(self, provider: str):
        self.provider = provider
        self.condition = threading.Condition()
        self.active = 0
        self.resetting = False
        self.owner_thread_id: int | None = None
        self._held = threading.local()

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
                self._held.count = getattr(self._held, "count", 0) + 1
        try:
            yield
        finally:
            with self.condition:
                if not self.resetting or self.owner_thread_id != current_thread_id:
                    self._held.count = getattr(self._held, "count", 1) - 1
                    self.active -= 1
                    self.condition.notify_all()

    def begin_reset(self) -> bool:
        with self.condition:
            if getattr(self._held, "count", 0) > 0:
                # Waiting for our own counted operation to finish can never end.
                raise RuntimeError(
                    "A provider reset cannot start inside a provider operation."
                )
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


_PROVIDER_LABELS = {
    descriptor.provider_id: descriptor.label
    for descriptor in DEFAULT_PROVIDER_DESCRIPTORS
}
INTERVALS_RESYNC_GATE = ProviderResyncGate(_PROVIDER_LABELS[INTERVALS_ID])
GARMIN_RESYNC_GATE = ProviderResyncGate(_PROVIDER_LABELS[GARMIN_ID])
WAHOO_RESYNC_GATE = ProviderResyncGate(_PROVIDER_LABELS[WAHOO_ID])
DEFAULT_RESYNC_GATES: Mapping[str, ProviderResyncGate] = {
    INTERVALS_ID: INTERVALS_RESYNC_GATE,
    GARMIN_ID: GARMIN_RESYNC_GATE,
    WAHOO_ID: WAHOO_RESYNC_GATE,
}


def resync_gate(
    provider: str, gates: Mapping[str, ProviderResyncGate] | None = None
) -> ProviderResyncGate:
    """Return a provider's gate; a provider without a mapped gate is rejected.

    Callers name only providers with a registered handler, so the rejection
    matches the unknown-provider error of the full resync service.
    """
    mapping = DEFAULT_RESYNC_GATES if gates is None else gates
    gate = mapping.get(provider)
    if gate is None:
        raise AppError(400, "Unbekannte Anbindung.")
    return gate


def provider_operation(provider: str) -> AbstractContextManager[None]:
    return resync_gate(provider).operation()


def _operation_guard(provider: str) -> Callable[[_Function], _Function]:
    def decorate(function: _Function) -> _Function:
        @wraps(function)
        def guarded(*args: Any, **kwargs: Any) -> Any:
            with provider_operation(provider):
                return function(*args, **kwargs)

        return cast(_Function, guarded)

    return decorate


intervals_operation = _operation_guard(INTERVALS_ID)
garmin_operation = _operation_guard(GARMIN_ID)
