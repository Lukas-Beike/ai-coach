"""Focused tests for the planned-unit session focus POST route."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

from support import dispatch_route

from backend import change_history
from backend.errors import AppError
from backend.http_api.planned_unit_focus_post import PlannedUnitFocusPostRoutes

LOCAL_ID = "12345678-1234-5678-1234-567812345678"


class PlannedUnitFocusPostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service = Mock()
        self.service.update.return_value = {"status": "local"}
        self.routes = PlannedUnitFocusPostRoutes(
            lambda: self.service,
            lambda: MagicMock(),
        )

    def handler(self, payload):
        return SimpleNamespace(read_json=Mock(return_value=payload), send_json=Mock())

    def test_sets_only_the_focus_fields(self) -> None:
        handler = self.handler(
            {"session_focus": "legs", "strength_intensity": "heavy", "name": "x"}
        )
        self.assertTrue(
            dispatch_route(
                self.routes,
                handler,
                f"/api/planned-units/{LOCAL_ID}/focus",
                method="POST",
            )
        )
        self.service.update.assert_called_once_with(
            LOCAL_ID, {"session_focus": "legs", "strength_intensity": "heavy"}
        )
        handler.send_json.assert_called_once_with(200, {"status": "local"})

    def test_empty_values_clear_the_focus(self) -> None:
        handler = self.handler({"session_focus": ""})
        dispatch_route(
            self.routes, handler, f"/api/planned-units/{LOCAL_ID}/focus", method="POST"
        )
        self.service.update.assert_called_once_with(
            LOCAL_ID, {"session_focus": "", "strength_intensity": None}
        )

    def test_other_paths_and_bad_bodies(self) -> None:
        other = self.handler({})
        self.assertFalse(
            dispatch_route(self.routes, other, "/api/other", method="POST")
        )
        other.read_json.assert_not_called()
        with self.assertRaises(AppError):
            dispatch_route(
                self.routes,
                self.handler([]),
                f"/api/planned-units/{LOCAL_ID}/focus",
                method="POST",
            )
        self.service.update.assert_not_called()

    def test_date_route_moves_the_unit_and_returns_the_undo_reference(self) -> None:
        change = {"id": "c1", "entity_type": "planned_unit", "after_hash": "h"}

        def move(*_args):
            change_history._collected_changes.get().append(change)
            return {"status": "local", "local_id": LOCAL_ID}

        self.service.move.side_effect = move
        handler = self.handler(
            {"date": "2026-11-14", "expected_payload_hash": "abc", "name": "x"}
        )
        self.assertTrue(
            dispatch_route(
                self.routes,
                handler,
                f"/api/planned-units/{LOCAL_ID}/date",
                method="POST",
            )
        )
        self.service.move.assert_called_once_with(LOCAL_ID, "2026-11-14", "abc")
        handler.send_json.assert_called_once_with(
            200, {"status": "local", "local_id": LOCAL_ID, "change": change}
        )
        with self.assertRaises(AppError):
            dispatch_route(
                self.routes,
                self.handler([]),
                f"/api/planned-units/{LOCAL_ID}/date",
                method="POST",
            )

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
            dispatch_route(
                self.routes,
                handler,
                f"/api/planned-units/{LOCAL_ID}/garmin-exercise",
                method="POST",
            )
        )
        self.service.assign_garmin_exercise.assert_called_once_with(
            LOCAL_ID, 2, "V-grip Cable Row", "abc"
        )
        handler.send_json.assert_called_once_with(200, {"status": "local"})
        with self.assertRaises(AppError):
            dispatch_route(
                self.routes,
                self.handler([]),
                f"/api/planned-units/{LOCAL_ID}/garmin-exercise",
                method="POST",
            )


if __name__ == "__main__":
    unittest.main()
