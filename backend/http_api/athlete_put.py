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
        zone_service: Callable[[], Any] | None = None,
    ) -> None:
        self._athlete_context_service = athlete_context_service
        self._profile_service = profile_service
        self._database_lock = database_lock
        self._zone_service = zone_service

    def handle(self, handler: Any, path: str) -> bool:
        if path in {"/api/zones", "/api/zones/remove"}:
            return self._handle_zones(handler, path)
        if path not in {"/api/athlete-context", "/api/profile"}:
            return False

        payload = handler.read_json()
        with self._database_lock or nullcontext():
            if path == "/api/athlete-context":
                result = self._athlete_context_service().save(
                    payload.get("profile"), payload.get("competitions")
                )
            else:
                result = self._profile_service().patch(payload)

        handler.send_json(200, result)
        return True

    def _handle_zones(self, handler: Any, path: str) -> bool:
        """Save one local zone configuration or remove one after confirmation."""
        if self._zone_service is None:
            return False
        payload = handler.read_json()
        with self._database_lock or nullcontext():
            service = self._zone_service()
            result = (
                service.save(payload)
                if path == "/api/zones"
                else service.remove(payload)
            )
        handler.send_json(200, result)
        return True
