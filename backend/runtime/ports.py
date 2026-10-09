from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, Protocol


class ProviderSnapshotReader(Protocol):
    def latest_snapshot(self, db: Any) -> dict[str, Any] | None: ...


class ProviderStateReader(Protocol):
    def summary(self, provider: str) -> dict[str, Any]: ...


class AudioTranscriber(Protocol):
    def transcribe(self, audio: bytes, content_type: str) -> dict[str, str]: ...


ProviderOperation = Callable[[], AbstractContextManager[None]]
