"""Focused unit tests for the extracted IntervalsClient provider class."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime
from unittest.mock import Mock, patch

from server_test_support import server

from backend.providers import http as provider_http
from backend.providers.intervals_client import IntervalsClient


class IntervalsClientTests(unittest.TestCase):
    def test_server_owned_client_uses_explicit_dependencies(self) -> None:
        config = type(
            "ConfigStub",
            (),
            {
                "intervals_api_key": "test-key",
                "intervals_athlete_id": "test-athlete",
            },
        )()
        request = Mock(return_value=[])
        with patch.object(
            provider_http.JSON_HTTP_CLIENT_CACHE,
            "get",
            return_value=Mock(request=request),
        ):
            client = server.PROVIDER_TRANSPORT.intervals_client(config)
            self.assertIs(client.config, config)
            self.assertEqual(client.get("/health"), [])
        request.assert_called_once()

    def test_direct_intervals_client_instantiation_and_methods(self) -> None:
        config = type(
            "ConfigStub",
            (),
            {
                "intervals_api_key": "test-key",
                "intervals_athlete_id": "test-athlete",
            },
        )()
        request_mock = Mock(return_value=[])
        client = IntervalsClient(config, request=request_mock)
        self.assertIs(client.config, config)
        self.assertEqual(client.get("/test"), [])

    def test_injected_clock_controls_provider_local_date(self) -> None:
        config = type(
            "ConfigStub",
            (),
            {"intervals_api_key": "test-key", "intervals_athlete_id": "test-athlete"},
        )()
        now = datetime(2026, 9, 20, 22, 30, tzinfo=UTC)
        client = IntervalsClient(config, request=Mock(), now=lambda: now)
        self.assertEqual(client.local_today().isoformat(), "2026-09-20")

    def test_pacecraft_folder_wins_over_the_legacy_folder(self) -> None:
        folders = [
            {"id": 77, "name": "Intervals Coach", "type": "FOLDER"},
            {"id": 9, "name": "Plans", "children": [{"id": 88, "name": "Pacecraft"}]},
        ]
        config = type(
            "ConfigStub",
            (),
            {"intervals_api_key": "key", "intervals_athlete_id": "a-1"},
        )()
        client = IntervalsClient(config, request=Mock(return_value=folders))
        with patch.object(client, "post") as post:
            self.assertEqual(client.get_or_create_workout_folder(), 88)
        post.assert_not_called()


if __name__ == "__main__":
    unittest.main()
