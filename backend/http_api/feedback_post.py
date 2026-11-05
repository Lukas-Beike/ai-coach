"""Authenticated athlete feedback and activity session correction POST routes."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from backend.athlete.checkins import CheckinService
from backend.errors import AppError
from backend.http_api.session_load_response import with_session_load


class FeedbackPostRoutes:
    """Dispatch athlete feedback and session corrections to their domain services."""

    def __init__(
        self,
        checkin_service: Callable[[], CheckinService],
        activity_feedback_service: Callable[[], Any] | None = None,
        session_rpe_load: Callable[[str], Any] | None = None,
        session_corrections: Callable[[], Any] | None = None,
    ) -> None:
        self._checkin_service = checkin_service
        self._activity_feedback_service = activity_feedback_service
        self._session_rpe_load = session_rpe_load
        self._session_corrections = session_corrections

    def handle(self, handler: Any, path: str) -> bool:
        session = re.fullmatch(r"/api/activities/([^/]+)/session", path)
        if session and self._session_corrections is not None:
            handler.send_json(
                200, self._correct_session(session.group(1), handler.read_json())
            )
            return True
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
            result = with_session_load(result, self._session_rpe_load, activity_id)
            handler.send_json(200, result)
            return True
        if path != "/api/feedback":
            return False

        payload = handler.read_json()
        result = self._checkin_service().save(payload)
        handler.send_json(200, result)
        return True

    def _correct_session(self, activity_id: str, payload: Any) -> dict[str, Any]:
        """Confirm, split or merge one session; the response carries its new bundle."""
        if not isinstance(payload, dict):
            raise AppError(400, "Die Korrektur muss ein Objekt sein.")
        service = self._session_corrections()
        action = payload.get("action")
        if action == "confirm":
            result = service.confirm(activity_id)
        elif action == "split":
            result = service.split(activity_id, str(payload.get("member_id") or ""))
        elif action == "merge":
            result = service.merge(activity_id, str(payload.get("other_id") or ""))
        else:
            raise AppError(400, "Unbekannte Korrektur.")
        return {**result, "session_bundle": service.bundle(result["activity_id"])}
