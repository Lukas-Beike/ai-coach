"""Authenticated local equipment POST route."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.athlete.equipment import EquipmentService
from backend.http_api.route_table import Access, Route, RouteRequest


class EquipmentPostRoutes:
    """Record equipment maintenance through the equipment domain service."""

    def __init__(self, equipment_service: Callable[[], EquipmentService]) -> None:
        self._equipment_service = equipment_service

    def routes(self) -> list[Route]:
        return [
            Route(
                "POST",
                "/api/equipment/maintenance",
                Access.SESSION_CSRF,
                self._maintain,
            )
        ]

    def _maintain(self, handler: Any, _request: RouteRequest) -> None:
        """Record one maintenance entry for a piece of equipment, stored locally.

        Request: JSON body `{"equipment_id": string, "date": "YYYY-MM-DD", "notes":
        string}` and no other key; `notes` is optional and cut to 1000 characters.
        The date must not be before the item's `start_date` or in the future.

        Response: 200 `{"ok": true, "stored_locally": true, "maintenance": {"id",
        "equipment_id", "date", "notes", "distance_km", "observed_at"}, "change"}`;
        `change` is the undo reference. `distance_km` is the item's usage so far,
        `null` for a past date of a Garmin-linked item.

        Errors: 400 "Ungültige Wartung." for an unknown body key; 400
        "Wartungsdatum ungültig." for a `date` that is not an ISO date; 400
        "Wartungsgegenstand oder Datum ungültig." for an empty or unmatched
        `equipment_id` or a date outside the item's range; 404 "Ausrüstung nicht
        gefunden." for a non-empty unknown `equipment_id`.
        """
        handler.send_json(200, self._equipment_service().maintain(handler.read_json()))
