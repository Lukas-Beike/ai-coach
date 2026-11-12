"""The real composition root resolves every service of the builder domains (#2069).

It replaces the mock-identity assembly tests: server.py builds the application
context and calls the domain builders on a temporary database, and each
service is resolved through the real wiring. Each builder step adds its
domain here.
"""

from __future__ import annotations

import unittest

from server_test_support import ServerTestCase, server

from backend.history.service import ChangeHistoryService
from backend.history.undo_service import HistoryUndoService
from backend.sync.weather import WeatherSyncService
from backend.weather.service import WeatherService


class CompositionRootTests(ServerTestCase):
    def test_history_services_resolve_over_the_current_database(self) -> None:
        history = server.HISTORY

        self.assertIsInstance(history.change_history_service(), ChangeHistoryService)
        self.assertIsInstance(history.undo_service(), HistoryUndoService)

    def test_weather_services_resolve_and_the_service_is_cached_per_database(
        self,
    ) -> None:
        weather = server.WEATHER_ASSEMBLY

        self.assertIsInstance(weather.service(), WeatherService)
        self.assertIs(weather.service(), weather.service())
        self.assertIsInstance(server.WEATHER_SYNC(), WeatherSyncService)

    def test_the_context_reads_the_live_configuration_and_database(self) -> None:
        self.assertIs(server.CONFIG, server.APP.config())
        self.assertIs(server.database_manager(), server.APP.database())


if __name__ == "__main__":
    unittest.main()
