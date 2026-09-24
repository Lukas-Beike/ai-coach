"""Read-only Coach tools for recent activities and activity details."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from backend.activities.read_service import ActivityReadService
from backend.athlete.profile import ProfileService
from backend.errors import AppError
from backend.sync.garmin import GarminPayloadService


class CoachActivityReadToolService:
    """Own Coach-specific validation and projections for activity read tools."""

    def __init__(
        self,
        activity_read: ActivityReadService,
        garmin_payload: GarminPayloadService,
        profile: ProfileService,
        today: Callable[[], date],
    ) -> None:
        self._activity_read = activity_read
        self._garmin_payload = garmin_payload
        self._profile = profile
        self._today = today

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        if name == "list_recent_activities":
            days = self._bounded_integer(
                arguments, "days", 30, 3660,
                "Aktivitätszeitraum oder Limit ist ungültig.",
            )
            limit = self._bounded_integer(
                arguments, "limit", 100, 500,
                "Aktivitätszeitraum oder Limit ist ungültig.",
            )
            return {
                "ok": True,
                **self._activity_read.recent(days, limit, today=self._today()),
            }
        if name == "get_activity_details":
            return self._activity_read.detail(
                arguments.get("activity_id"),
                garmin_snapshot=self._garmin_payload.snapshot(),
                profile=self._profile.get(),
                today=self._today(),
            )
        return None

    @staticmethod
    def _bounded_integer(
        arguments: dict[str, Any], key: str, default: int, maximum: int, error: str
    ) -> int:
        try:
            return max(1, min(int(arguments.get(key, default)), maximum))
        except (TypeError, ValueError) as exc:
            raise AppError(400, error, reason="invalid_list_request") from exc
