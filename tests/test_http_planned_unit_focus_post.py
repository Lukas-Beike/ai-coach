"""Focused tests for the planned-unit session focus POST route."""

from __future__ import annotations

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from backend.errors import AppError
from backend.http_api.planned_unit_focus_post import PlannedUnitFocusPostRoutes

LOCAL_ID = "12345678-1234-5678-1234-567812345678"


class PlannedUnitFocusPostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = Mock()
        self.service.update.return_value = {"status": "local"}
        self.routes = PlannedUnitFocusPostRoutes(lambda: self.service, threading.Lock())

    def handler(self, payload):
        return SimpleNamespace(read_json=Mock(return_value=payload), send_json=Mock())

    def test_sets_only_the_focus_fields(self) -> None:
        handler = self.handler(
            {"session_focus": "legs", "strength_intensity": "heavy", "name": "x"}
        )
        self.assertTrue(
            self.routes.handle(handler, f"/api/planned-units/{LOCAL_ID}/focus")
        )
        self.service.update.assert_called_once_with(
            LOCAL_ID, {"session_focus": "legs", "strength_intensity": "heavy"}
        )
        handler.send_json.assert_called_once_with(200, {"status": "local"})

    def test_empty_values_clear_the_focus(self) -> None:
        handler = self.handler({"session_focus": ""})
        self.routes.handle(handler, f"/api/planned-units/{LOCAL_ID}/focus")
        self.service.update.assert_called_once_with(
            LOCAL_ID, {"session_focus": "", "strength_intensity": None}
        )

    def test_other_paths_and_bad_bodies(self) -> None:
        other = self.handler({})
        self.assertFalse(self.routes.handle(other, "/api/other"))
        other.read_json.assert_not_called()
        with self.assertRaises(AppError):
            self.routes.handle(self.handler([]), f"/api/planned-units/{LOCAL_ID}/focus")
        self.service.update.assert_not_called()

    def test_garmin_exercise_route_passes_the_pick_to_the_service(self) -> None:
        self.service.assign_garmin_exercise.return_value = {"status": "local"}
        handler = self.handler(
            {
                "exercise_index": 2,
                "garmin_exercise": "V-grip Cable Row",
                "expected_payload_hash": "abc",
                "name": "ignored",
            }
        )
        self.assertTrue(
            self.routes.handle(
                handler, f"/api/planned-units/{LOCAL_ID}/garmin-exercise"
            )
        )
        self.service.assign_garmin_exercise.assert_called_once_with(
            LOCAL_ID, 2, "V-grip Cable Row", "abc"
        )
        handler.send_json.assert_called_once_with(200, {"status": "local"})
        with self.assertRaises(AppError):
            self.routes.handle(
                self.handler([]), f"/api/planned-units/{LOCAL_ID}/garmin-exercise"
            )


if __name__ == "__main__":
    unittest.main()
