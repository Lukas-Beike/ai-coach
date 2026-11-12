"""The real composition root resolves every service of the builder domains (#2069).

It replaces the mock-identity assembly tests: server.py builds the application
context and calls the domain builders on a temporary database, and each
service is resolved through the real wiring. Each builder step adds its
domain here.
"""

from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

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

    def test_weather_services_resolve(self) -> None:
        self.assertIsInstance(server.WEATHER.service(), WeatherService)
        self.assertIsInstance(server.WEATHER_SYNC(), WeatherSyncService)

    def test_the_context_reads_the_live_configuration_and_database(self) -> None:
        replaced = replace(server.CONFIG, calendar_ical_url="https://example.invalid")
        with patch.object(server, "CONFIG", replaced):
            self.assertIs(replaced, server.APP.config())
        self.assertIs(server.database_manager(), server.APP.database())


if __name__ == "__main__":
    unittest.main()
