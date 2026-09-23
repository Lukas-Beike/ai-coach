"""Public performance and athlete-feedback state projections."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from backend.performance import context as performance_context


class PublicPerformanceStateService:
    """Project persisted performance and Garmin data into public API state."""

    def __init__(
        self,
        sync_state_repository: Any,
        garmin_payload_service: Any,
        profile_service: Any,
        garmin_projection_service: Any,
        today: Callable[[], date],
    ) -> None:
        self._sync_state_repository = sync_state_repository
        self._garmin_payload_service = garmin_payload_service
        self._profile_service = profile_service
        self._garmin_projection_service = garmin_projection_service
        self._today = today

    def performance_state(self) -> dict[str, Any]:
        return self.from_snapshot(self._sync_state_repository.latest_snapshot())

    def from_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        """Project a snapshot already read by a larger state request."""
        return {
            "performance": performance_context.current_performance_context(
                snapshot,
                self._garmin_payload_service.snapshot(),
                self._profile_service.get(),
                self._today(),
            ),
            "garmin": self._garmin_projection_service.public_state(),
        }


class PublicFeedbackStateService:
    """Project local check-ins and activity feedback into public API state."""

    def __init__(self, checkin_service: Any, activity_feedback_service: Any) -> None:
        self._checkin_service = checkin_service
        self._activity_feedback_service = activity_feedback_service

    def feedback_state(self, checkins: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        return {
            "checkins": checkins if checkins is not None else self._checkin_service.list(30),
            "local_feedback": self._checkin_service.context(),
            "activity_feedback": self._activity_feedback_service.context(),
        }
