"""Authenticated athlete check-in feedback POST route."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.athlete.checkins import CheckinService


class FeedbackPostRoutes:
    """Dispatch athlete daily check-in feedback to its domain service."""

    def __init__(
        self,
        checkin_service: Callable[[], CheckinService],
    ) -> None:
        self._checkin_service = checkin_service

    def handle(self, handler: Any, path: str) -> bool:
        if path != "/api/feedback":
            return False

        payload = handler.read_json()
        result = self._checkin_service().save(payload)
        handler.send_json(200, result)
        return True
