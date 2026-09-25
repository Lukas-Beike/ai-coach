"""HTTP route for explicitly confirmed local privacy deletion."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.privacy import PrivacyDeleteService


class PrivacyDeletePostRoutes:
    """Dispatch the privacy deletion POST to its domain service."""

    def __init__(
        self,
        privacy_delete_service: Callable[[], PrivacyDeleteService],
    ) -> None:
        self._privacy_delete_service = privacy_delete_service

    def handle(self, handler: Any, path: str) -> bool:
        if path != "/api/privacy/delete":
            return False

        payload = handler.read_json()
        result = self._privacy_delete_service().delete(payload.get("confirm"))
        handler.send_json(200, result)
        return True
