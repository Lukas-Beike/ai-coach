"""Focused unit tests for the activity feedback POST routes."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from support import dispatch_route

from backend.http_api.feedback_post import FeedbackPostRoutes


class FeedbackPostRoutesTests(unittest.TestCase):
    def test_athlete_feedback_post_is_not_registered(self) -> None:
        # Check-ins are saved by the Coach and read from GET /api/feedback.
        handler = SimpleNamespace(read_json=Mock(), send_json=Mock())
        routes = FeedbackPostRoutes()

        self.assertFalse(
            dispatch_route(routes, handler, "/api/feedback", method="POST")
        )
        self.assertFalse(dispatch_route(routes, handler, "/api/other", method="POST"))
        handler.read_json.assert_not_called()
        handler.send_json.assert_not_called()


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
        route = FeedbackPostRoutes(lambda: service)

        self.assertTrue(
            dispatch_route(
                route, handler, "/api/activities/ride-1/feedback", method="POST"
            )
        )
        service.save_coach.assert_called_once_with("ride-1", {"session_rpe": 6})
        handler.send_json.assert_called_once_with(
            200, {"status": "ok", "activity_feedback": {"session_rpe": 6}}
        )

    def test_activity_feedback_save_returns_the_session_load(self) -> None:
        service = Mock()
        service.save_coach.return_value = {"status": "ok"}
        load = Mock(return_value={"value": 300})
        handler = SimpleNamespace(
            read_json=Mock(return_value={"session_rpe": 6}), send_json=Mock()
        )
        route = FeedbackPostRoutes(lambda: service, load)

        self.assertTrue(
            dispatch_route(
                route, handler, "/api/activities/ride-1/feedback", method="POST"
            )
        )
        load.assert_called_once_with("ride-1")
        handler.send_json.assert_called_once_with(
            200, {"status": "ok", "session_rpe_load": {"value": 300}}
        )

    def test_failed_load_read_keeps_the_committed_save_response(self) -> None:
        service = Mock()
        service.save_coach.return_value = {"status": "ok"}
        handler = SimpleNamespace(
            read_json=Mock(return_value={"session_rpe": 6}), send_json=Mock()
        )
        route = FeedbackPostRoutes(
            lambda: service, Mock(side_effect=OSError("synthetic"))
        )

        self.assertTrue(
            dispatch_route(
                route, handler, "/api/activities/ride-1/feedback", method="POST"
            )
        )
        handler.send_json.assert_called_once_with(200, {"status": "ok"})


class ActivityPurposePostRouteTests(unittest.TestCase):
    def post(self, payload: dict) -> Mock:
        service = Mock()
        handler = SimpleNamespace(
            read_json=Mock(return_value=payload), send_json=Mock()
        )
        route = FeedbackPostRoutes(lambda: service)
        self.assertTrue(
            dispatch_route(
                route, handler, "/api/activities/ride-1/feedback", method="POST"
            )
        )
        return service

    def test_marking_a_purpose_needs_a_live_session(self) -> None:
        service = self.post({"purpose": "commute"})

        service.save_coach.assert_called_once_with("ride-1", {"purpose": "commute"})
        service.save.assert_not_called()

    def test_removing_a_purpose_needs_no_live_session(self) -> None:
        for payload in ({"purpose": None}, {"purpose": ""}):
            with self.subTest(payload=payload):
                service = self.post(payload)

                service.save.assert_called_once_with("ride-1", payload)
                service.save_coach.assert_not_called()
