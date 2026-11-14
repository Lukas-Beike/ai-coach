from __future__ import annotations

import unittest
from threading import RLock
from unittest.mock import MagicMock, Mock, call

from support import dispatch_route

from backend.errors import AppError
from backend.http_api.athlete_put import AthletePutRoutes


class AthletePutRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile = Mock()
        self.profile.mutation_coordinator = RLock()
        self.profile_factory = Mock(return_value=self.profile)
        self.handler = Mock()
        self.manager = MagicMock()
        self.routes = AthletePutRoutes(self.profile_factory, lambda: self.manager)

    def test_profile_write_runs_in_one_unit_of_work(self) -> None:
        payload = {"name": "Example", "timezone": "Europe/Berlin"}
        self.handler.read_json.return_value = payload
        unit_of_work = self.manager.unit_of_work.return_value
        self.profile.patch.side_effect = lambda _value: (
            {"name": "Example"}
            if unit_of_work.__enter__.called
            else self.fail("profile writes must run in a unit of work")
        )
        self.handler.send_json.side_effect = lambda *_args: (
            unit_of_work.__exit__.assert_called_once()
        )

        self.assertTrue(
            dispatch_route(self.routes, self.handler, "/api/profile", method="PUT")
        )
        unit_of_work.__exit__.assert_called_once()

    def test_athlete_context_route_is_gone(self) -> None:
        self.assertFalse(
            dispatch_route(
                self.routes, self.handler, "/api/athlete-context", method="PUT"
            )
        )

        self.handler.read_json.assert_not_called()
        self.handler.send_json.assert_not_called()

    def test_profile_route_passes_submitted_fields_as_patch(self) -> None:
        payload = {"name": "Example", "timezone": "Europe/Berlin"}
        result = {"name": "Example", "timezone": "Europe/Berlin"}
        self.handler.read_json.return_value = payload
        self.profile.patch.return_value = result

        self.assertTrue(
            dispatch_route(self.routes, self.handler, "/api/profile", method="PUT")
        )

        self.profile_factory.assert_called_once_with()
        self.profile.patch.assert_called_once_with(payload)
        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_called_once_with(200, result)

    def test_zone_routes_save_and_remove_through_the_zone_service(self) -> None:
        zones = Mock()
        zones.save.return_value = {"change": "saved"}
        zones.remove.return_value = {"change": "removed"}
        routes = AthletePutRoutes(
            self.profile_factory,
            lambda: self.manager,
            Mock(return_value=zones),
        )
        self.handler.read_json.return_value = {
            "key": "|power|ride||",
            "confirmed": True,
        }

        self.assertTrue(
            dispatch_route(routes, self.handler, "/api/zones", method="PUT")
        )
        self.assertTrue(
            dispatch_route(routes, self.handler, "/api/zones/remove", method="PUT")
        )

        zones.remove.assert_called_once_with(
            {"key": "|power|ride||", "confirmed": True}
        )
        self.handler.send_json.assert_has_calls(
            [call(200, {"change": "saved"}), call(200, {"change": "removed"})]
        )

    def test_zone_routes_are_absent_without_the_zone_service(self) -> None:
        self.assertFalse(
            dispatch_route(self.routes, self.handler, "/api/zones", method="PUT")
        )
        self.handler.read_json.assert_not_called()

    def test_unknown_path_has_no_side_effects(self) -> None:
        self.assertFalse(
            dispatch_route(self.routes, self.handler, "/api/other", method="PUT")
        )

        self.handler.read_json.assert_not_called()
        self.handler.send_json.assert_not_called()
        self.profile_factory.assert_not_called()

    def test_service_app_error_propagates_without_response(self) -> None:
        self.handler.read_json.return_value = {"name": "invalid"}
        self.profile.patch.side_effect = AppError(400, "invalid profile")

        with self.assertRaisesRegex(AppError, "invalid profile"):
            dispatch_route(self.routes, self.handler, "/api/profile", method="PUT")

        self.handler.read_json.assert_called_once_with()
        self.handler.send_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
