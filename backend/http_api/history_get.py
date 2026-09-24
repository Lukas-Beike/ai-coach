"""Authenticated change-history GET route."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend import change_history
from backend.history.service import ChangeHistoryService
from backend.http_api.auth import SessionAuthService


class HistoryGetRoutes:
    """Dispatch local change-history reads through their owning service."""

    def __init__(
        self,
        session_auth_service: Callable[[], SessionAuthService],
        change_history_service: Callable[[], ChangeHistoryService],
    ) -> None:
        self._session_auth_service = session_auth_service
        self._change_history_service = change_history_service

    def handle(self, handler: Any, path: str) -> bool:
        if path != "/api/change-history":
            return False

        self._session_auth_service().require_auth(handler)
        raw_limit = parse_qs(urlparse(handler.path).query).get("limit", ["100"])[0]
        try:
            limit = max(1, min(int(raw_limit), change_history.MAX_ROWS))
        except ValueError:
            limit = 100

        handler.send_json(200, {"changes": self._change_history_service().list(limit)})
        return True
