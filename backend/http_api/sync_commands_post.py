"""HTTP transport for explicit synchronization commands."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.sync_commands import SyncCommandEndpoint


class SyncCommandPostRoute:
    """Read the request body and write the result for a sync command."""

    def __init__(self, endpoint: Callable[[], SyncCommandEndpoint]) -> None:
        self._endpoint = endpoint

    def handle(self, handler: Any, path: str) -> bool:
        if not SyncCommandEndpoint.handles(path):
            return False
        payload = handler.read_json() if SyncCommandEndpoint.needs_body(path) else None
        endpoint = self._endpoint()
        status, result = endpoint.execute(path, payload)
        handler.send_json(status, result)
        return True
