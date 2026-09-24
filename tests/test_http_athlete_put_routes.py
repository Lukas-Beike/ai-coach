from __future__ import annotations

import unittest
from unittest.mock import Mock, call

from backend.errors import AppError
from backend.http_api.athlete_put import AthletePutRoutes


class AthletePutRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.context = Mock()
        self.profile = Mock()
        self.context_factory = Mock(return_value=self.context)
        self.profile_factory = Mock(return_value=self.profile)
        self.handler = Mock()
        self.routes = AthletePutRoutes(self.context_factory, self.profile_factory)

    def test_athlete_context_route_maps_profile_and_competitions(self) -> None:
        payload = {"profile": {"name": "Example"}, "competitions": [{"id": "race-1"}]}
        result = {"profile": payload["profile"], "competitions": payload["competitions"]}
        self.handler.read_json.return_value = payload
        self.context.save.return_value = result

        self.assertTrue(self.routes.handle(self.handler, "/api/athlete-context"))

        self.context_factory.assert_called_once_with()
        self.context.save.assert_called_once_with(payload["profile"], payload["competitions"])
        self.profile_factory.assert_not_called()
        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, result)

    def test_profile_route_passes_whole_payload(self) -> None:
        payload = {"name": "Example", "timezone": "Europe/Berlin"}
        result = {"name": "Example", "timezone": "Europe/Berlin"}
        self.handler.read_json.return_value = payload
        self.profile.save.return_value = result

        self.assertTrue(self.routes.handle(self.handler, "/api/profile"))

        self.profile_factory.assert_called_once_with()
        self.profile.save.assert_called_once_with(payload)
        self.context_factory.assert_not_called()
        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, result)

    def test_unknown_path_has_no_side_effects(self) -> None:
        self.assertFalse(self.routes.handle(self.handler, "/api/other"))

        self.handler.read_json.assert_not_called()
        self.handler.send_json.assert_not_called()
        self.context_factory.assert_not_called()
        self.profile_factory.assert_not_called()

    def test_service_factories_are_resolved_per_request(self) -> None:
        first_context, second_context = Mock(), Mock()
        first_result, second_result = {"id": "first"}, {"id": "second"}
        first_context.save.return_value = first_result
        second_context.save.return_value = second_result
        self.context_factory.side_effect = [first_context, second_context]
        payloads = [
            {"profile": {"name": "First"}, "competitions": []},
            {"profile": {"name": "Second"}, "competitions": [{"id": "race"}]},
        ]
        self.handler.read_json.side_effect = payloads

        self.assertTrue(self.routes.handle(self.handler, "/api/athlete-context"))
        self.assertTrue(self.routes.handle(self.handler, "/api/athlete-context"))

        self.context_factory.assert_has_calls([call(), call()])
        first_context.save.assert_called_once_with(
            payloads[0]["profile"], payloads[0]["competitions"]
        )
        second_context.save.assert_called_once_with(
            payloads[1]["profile"], payloads[1]["competitions"]
        )
        self.assertEqual(self.handler.read_json.call_count, 2)
        self.handler.send_json.assert_has_calls(
            [call(200, first_result), call(200, second_result)]
        )

    def test_service_app_error_propagates_without_response(self) -> None:
        self.handler.read_json.return_value = {"name": "invalid"}
        self.profile.save.side_effect = AppError(400, "invalid profile")

        with self.assertRaisesRegex(AppError, "invalid profile"):
            self.routes.handle(self.handler, "/api/profile")

        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
