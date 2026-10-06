"""Authenticated athlete check-in feedback POST route."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from backend.athlete.checkins import CheckinService


class FeedbackPostRoutes:
    """Dispatch athlete daily check-in feedback to its domain service."""

    def __init__(
        self,
        checkin_service: Callable[[], CheckinService],
        activity_feedback_service: Callable[[], Any] | None = None,
    ) -> None:
        self._checkin_service = checkin_service
        self._activity_feedback_service = activity_feedback_service

    def handle(self, handler: Any, path: str) -> bool:
        match = re.fullmatch(r"/api/activities/([^/]+)/feedback", path)
        if match:
            if self._activity_feedback_service is None:
                return False
            activity_id = match.group(1)
            payload = handler.read_json()
            feedback = self._activity_feedback_service()
            has_feedback = isinstance(payload, dict) and bool(
                str(payload.get("notes") or "").strip()
                or payload.get("session_rpe") is not None
                or str(payload.get("deviation_reason") or "").strip()
            )
            result = (
                feedback.save_coach(activity_id, payload)
                if has_feedback
                else feedback.save(activity_id, payload)
            )
            handler.send_json(200, result)
            return True
        if path != "/api/feedback":
            return False

        payload = handler.read_json()
        result = self._checkin_service().save(payload)
        handler.send_json(200, result)
        return True
