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
        """Record equipment maintenance."""
        handler.send_json(200, self._equipment_service().maintain(handler.read_json()))
