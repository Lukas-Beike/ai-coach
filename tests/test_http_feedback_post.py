"""Focused unit tests for the authenticated athlete feedback POST route."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from backend.errors import AppError
from backend.http_api.feedback_post import FeedbackPostRoutes


class FeedbackPostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.checkin_service = Mock()
        self.checkin_service.save.return_value = {"status": "saved"}
        self.routes = FeedbackPostRoutes(lambda: self.checkin_service)
        self.handler = SimpleNamespace(
            read_json=Mock(return_value={"soreness": 3, "notes": "Feeling great"}),
            send_json=Mock(),
        )

    def test_success_dispatches_payload_to_checkin_service(self) -> None:
        handled = self.routes.handle(self.handler, "/api/feedback")
        self.assertTrue(handled)
        self.handler.read_json.assert_called_once_with()
        self.checkin_service.save.assert_called_once_with(
            {"soreness": 3, "notes": "Feeling great"}
        )
        self.handler.send_json.assert_called_once_with(200, {"status": "saved"})

    def test_wrong_path_returns_false_without_side_effects(self) -> None:
        handled = self.routes.handle(self.handler, "/api/other")
        self.assertFalse(handled)
        self.handler.read_json.assert_not_called()
        self.checkin_service.save.assert_not_called()
        self.handler.send_json.assert_not_called()

    def test_preserves_app_error_for_outer_handler(self) -> None:
        error = AppError(400, "Validation failed")
        self.checkin_service.save.side_effect = error
        with self.assertRaises(AppError) as raised:
            self.routes.handle(self.handler, "/api/feedback")
        self.assertIs(raised.exception, error)
        self.handler.send_json.assert_not_called()


class ActivityFeedbackPostRouteTests(unittest.TestCase):
    def test_activity_feedback_route_uses_existing_service(self) -> None:
        service = Mock()
        service.save_coach.return_value = {
            "status": "ok",
            "activity_feedback": {"session_rpe": 6},
        }
        handler = SimpleNamespace(
            read_json=Mock(return_value={"session_rpe": 6}), send_json=Mock()
        )
        route = FeedbackPostRoutes(lambda: Mock(), lambda: service)

        self.assertTrue(route.handle(handler, "/api/activities/ride-1/feedback"))
        service.save_coach.assert_called_once_with("ride-1", {"session_rpe": 6})
        handler.send_json.assert_called_once_with(
            200, {"status": "ok", "activity_feedback": {"session_rpe": 6}}
        )
