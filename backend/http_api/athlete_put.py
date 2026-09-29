"""Authenticated local athlete PUT routes."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from backend.athlete.context import AthleteContextService
from backend.athlete.profile import ProfileService


class AthletePutRoutes:
    """Dispatch athlete writes through their existing domain services."""

    def __init__(
        self,
        athlete_context_service: Callable[[], AthleteContextService],
        profile_service: Callable[[], ProfileService],
        database_lock: Any | None = None,
    ) -> None:
        self._athlete_context_service = athlete_context_service
        self._profile_service = profile_service
        self._database_lock = database_lock

    def handle(self, handler: Any, path: str) -> bool:
        if path not in {"/api/athlete-context", "/api/profile"}:
            return False

        payload = handler.read_json()
        with self._database_lock or nullcontext():
            if path == "/api/athlete-context":
                result = self._athlete_context_service().save(
                    payload.get("profile"), payload.get("competitions")
                )
            else:
                result = self._profile_service().save(payload)

        handler.send_json(200, result)
        return True
