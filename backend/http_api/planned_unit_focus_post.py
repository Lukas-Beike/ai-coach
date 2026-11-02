"""Authenticated POST route that sets the session focus of a planned unit."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from backend.canonical.planning_fields import SESSION_FOCUS_KEYS
from backend.errors import AppError

_FOCUS_PATH = re.compile(r"/api/planned-units/([^/]+)/focus")


class PlannedUnitFocusPostRoutes:
    """Set or clear ``session_focus`` and ``strength_intensity`` of one unit."""

    def __init__(self, planned_unit_service: Callable[[], Any], database_lock: Any):
        self._planned_unit_service = planned_unit_service
        self._database_lock = database_lock

    def handle(self, handler: Any, path: str) -> bool:
        match = _FOCUS_PATH.fullmatch(path)
        if match is None:
            return False
        payload = handler.read_json()
        if not isinstance(payload, dict):
            raise AppError(400, "Die Anfrage muss ein Objekt sein.")
        values = {key: payload.get(key) for key in SESSION_FOCUS_KEYS}
        with self._database_lock:
            result = self._planned_unit_service().update(match.group(1), values)
        handler.send_json(200, result)
        return True
