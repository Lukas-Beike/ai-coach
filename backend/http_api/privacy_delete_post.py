"""HTTP route for explicitly confirmed local privacy deletion."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.privacy import PrivacyDeleteService

_PATHS = frozenset(
    {"/api/privacy/delete", "/api/privacy/gps", "/api/privacy/gps/delete"}
)


class PrivacyDeletePostRoutes:
    """Dispatch the privacy deletion POST to its domain service."""

    def __init__(
        self,
        privacy_delete_service: Callable[[], PrivacyDeleteService],
    ) -> None:
        self._privacy_delete_service = privacy_delete_service

    def handle(self, handler: Any, path: str) -> bool:
        if path not in _PATHS:
            return False

        payload = handler.read_json()
        service = self._privacy_delete_service()
        if path == "/api/privacy/gps":
            result = service.set_gps_tracks(payload.get("enabled"))
        elif path == "/api/privacy/gps/delete":
            result = service.delete_gps_tracks(payload.get("confirm"))
        else:
            result = service.delete(payload.get("confirm"))
        handler.send_json(200, result)
        return True
