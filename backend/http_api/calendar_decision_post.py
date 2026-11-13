"""Authenticated POST route that sets the training impact of a calendar event."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.errors import AppError
from backend.http_api.route_table import Access, Route, RouteRequest


class CalendarDecisionPostRoutes:
    """Store the athlete's decision for one external calendar event or series."""

    def __init__(self, decision_service: Callable[[], Any]):
        self._decision_service = decision_service

    def routes(self) -> list[Route]:
        return [
            Route(
                "POST",
                "/api/external-calendar/decisions",
                Access.SESSION_CSRF,
                self._decide,
            )
        ]

    def _decide(self, handler: Any, _request: RouteRequest) -> None:
        """Set or remove how one calendar event affects training; nothing remote.

        Request: JSON body `{"uid": string, "occurrence_start": string|null,
        "impact": "block"|"short"|"easy"|"none"|null}`. `occurrence_start` is the
        event's `start_local` for one occurrence, or `null` for every occurrence
        of the UID (which replaces their single decisions). `impact` `null`
        removes the decision.

        Response: 200 `{"uid", "occurrence_start", "impact", "undecided_upcoming",
        "needs_replan", "replan_changes"}` after the adaptive preview was
        recalculated; `undecided_upcoming` counts the events still without a
        decision from today through 14 days ahead.

        Errors: 400 "Ungültiger Termin." or "Ungültige Einordnung."; 404 "Termin
        nicht gefunden." when no stored event has that UID and start.
        """
        payload = handler.read_json()
        if not isinstance(payload, dict):
            raise AppError(400, "Die Anfrage muss ein Objekt sein.")
        result = self._decision_service().decide(
            payload.get("uid"), payload.get("occurrence_start"), payload.get("impact")
        )
        handler.send_json(200, result)
