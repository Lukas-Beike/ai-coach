"""Authenticated local equipment POST route."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.athlete.equipment import EquipmentService


class EquipmentPostRoutes:
    """Record equipment maintenance through the equipment domain service."""

    def __init__(self, equipment_service: Callable[[], EquipmentService]) -> None:
        self._equipment_service = equipment_service

    def handle(self, handler: Any, path: str) -> bool:
        if path != "/api/equipment/maintenance":
            return False
        handler.send_json(200, self._equipment_service().maintain(handler.read_json()))
        return True
