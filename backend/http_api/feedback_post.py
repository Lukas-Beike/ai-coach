"""Authenticated activity feedback and session correction POST routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.errors import AppError
from backend.http_api.route_table import Access, Route, RouteRequest
from backend.http_api.session_load_response import with_session_load


class FeedbackPostRoutes:
    """Dispatch activity feedback and session corrections to their domain services."""

    def __init__(
        self,
        activity_feedback_service: Callable[[], Any] | None = None,
        session_rpe_load: Callable[[str], Any] | None = None,
        session_corrections: Callable[[], Any] | None = None,
    ) -> None:
        self._activity_feedback_service = activity_feedback_service
        self._session_rpe_load = session_rpe_load
        self._session_corrections = session_corrections

    def routes(self) -> list[Route]:
        routes = []
        if self._session_corrections is not None:
            routes.append(
                Route(
                    "POST",
                    "/api/activities/{id}/session",
                    Access.SESSION_CSRF,
                    self._session,
                )
            )
        if self._activity_feedback_service is not None:
            routes.append(
                Route(
                    "POST",
                    "/api/activities/{id}/feedback",
                    Access.SESSION_CSRF,
                    self._feedback,
                )
            )
        return routes

    def _session(self, handler: Any, request: RouteRequest) -> None:
        handler.send_json(
            200, self._correct_session(request.params["id"], handler.read_json())
        )

    def _feedback(self, handler: Any, request: RouteRequest) -> None:
        if self._activity_feedback_service is None:
            raise AppError(404, "Nicht gefunden.")
        activity_id = request.params["id"]
        payload = handler.read_json()
        feedback = self._activity_feedback_service()
        has_feedback = isinstance(payload, dict) and bool(
            str(payload.get("notes") or "").strip()
            or payload.get("session_rpe") is not None
            or str(payload.get("deviation_reason") or "").strip()
            or payload.get("purpose") not in (None, "")
        )
        result = (
            feedback.save_coach(activity_id, payload)
            if has_feedback
            else feedback.save(activity_id, payload)
        )
        result = with_session_load(result, self._session_rpe_load, activity_id)
        handler.send_json(200, result)

    def _correct_session(self, activity_id: str, payload: Any) -> dict[str, Any]:
        """Confirm, split or merge one session; the response carries its new bundle."""
        if not isinstance(payload, dict):
            raise AppError(400, "Die Korrektur muss ein Objekt sein.")
        if self._session_corrections is None:
            raise AppError(404, "Nicht gefunden.")
        service = self._session_corrections()
        action = payload.get("action")
        if action == "confirm":
            result = service.confirm(activity_id)
        elif action == "split":
            result = service.split(activity_id, str(payload.get("member_id") or ""))
        elif action == "delete":
            if payload.get("confirmed") is not True:
                raise AppError(409, "Das Löschen muss bestätigt werden.")
            result = service.delete(activity_id)
        elif action == "merge":
            result = service.merge(activity_id, str(payload.get("other_id") or ""))
        else:
            raise AppError(400, "Unbekannte Korrektur.")
        return {**result, "session_bundle": service.bundle(result["activity_id"])}
