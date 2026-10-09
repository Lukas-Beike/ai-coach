from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import Any, Protocol


class ProviderSnapshotReader(Protocol):
    def latest_snapshot(self, db: Any) -> dict[str, Any] | None: ...


ProviderOperation = Callable[[], AbstractContextManager[None]]
