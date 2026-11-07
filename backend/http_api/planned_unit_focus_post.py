"""Authenticated POST routes that set the focus or a Garmin exercise of a unit."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from backend.canonical.planning_fields import FOCUS_ONLY_KEYS
from backend.errors import AppError

_FOCUS_PATH = re.compile(r"/api/planned-units/([^/]+)/focus")
_GARMIN_EXERCISE_PATH = re.compile(r"/api/planned-units/([^/]+)/garmin-exercise")


class PlannedUnitFocusPostRoutes:
    """Set the focus fields of one unit, or the Garmin exercise of one exercise."""

    def __init__(self, planned_unit_service: Callable[[], Any], database_lock: Any):
        self._planned_unit_service = planned_unit_service
        self._database_lock = database_lock

    def handle(self, handler: Any, path: str) -> bool:
        if (exercise := _GARMIN_EXERCISE_PATH.fullmatch(path)) is not None:
            payload = handler.read_json()
            if not isinstance(payload, dict):
                raise AppError(400, "Die Anfrage muss ein Objekt sein.")
            with self._database_lock:
                result = self._planned_unit_service().assign_garmin_exercise(
                    exercise.group(1),
                    payload.get("exercise_index"),
                    payload.get("garmin_exercise"),
                    payload.get("expected_payload_hash"),
                )
            handler.send_json(200, result)
            return True
        match = _FOCUS_PATH.fullmatch(path)
        if match is None:
            return False
        payload = handler.read_json()
        if not isinstance(payload, dict):
            raise AppError(400, "Die Anfrage muss ein Objekt sein.")
        values = {key: payload.get(key) for key in FOCUS_ONLY_KEYS}
        with self._database_lock:
            result = self._planned_unit_service().update(match.group(1), values)
        handler.send_json(200, result)
        return True
