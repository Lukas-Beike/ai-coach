"""Authenticated local route that adopts the first threshold estimate."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from typing import Any

from backend.athlete.first_threshold import FirstThresholdService
from backend.athlete.profile import ProfileService

ADOPT_PATH = "/api/profile/first-threshold/adopt"


class FirstThresholdPostRoutes:
    """Store the shown estimate as the first threshold on the athlete's request."""

    def __init__(
        self,
        first_threshold_service: Callable[[], FirstThresholdService],
        profile_service: Callable[[], ProfileService],
        database_lock: Any | None = None,
    ) -> None:
        self._first_threshold_service = first_threshold_service
        self._profile_service = profile_service
        self._database_lock = database_lock

    def handle(self, handler: Any, path: str) -> bool:
        if path != ADOPT_PATH:
            return False
        payload = handler.read_json()
        with (
            self._profile_service().mutation_coordinator,
            self._database_lock or nullcontext(),
        ):
            result = self._first_threshold_service().adopt(payload)
        handler.send_json(200, result)
        return True
