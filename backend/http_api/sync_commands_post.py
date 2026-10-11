"""HTTP transport for explicit synchronization commands."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.sync_commands import (
    SyncCommandEndpoint,
    handles_sync_path,
    needs_sync_body,
)
from backend.sync.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry


class SyncCommandPostRoute:
    """Read the request body and write the result for a sync command."""

    def __init__(
        self,
        endpoint: Callable[[], SyncCommandEndpoint],
        *,
        registry: ProviderRegistry = DEFAULT_PROVIDER_REGISTRY,
    ) -> None:
        self._endpoint = endpoint
        self._registry = registry

    def handle(self, handler: Any, path: str) -> bool:
        if not handles_sync_path(self._registry, path):
            return False
        payload = handler.read_json() if needs_sync_body(self._registry, path) else None
        endpoint = self._endpoint()
        status, result = endpoint.execute(path, payload)
        handler.send_json(status, result)
        return True
