"""Focused unit tests for the extracted IntervalsClient provider class."""

from __future__ import annotations

import unittest
from unittest.mock import Mock

import server
from backend.providers.intervals_client import IntervalsClient


class IntervalsClientTests(unittest.TestCase):
    def test_server_owned_client_uses_explicit_dependencies(self) -> None:
        config = type("ConfigStub", (), {
            "intervals_api_key": "test-key",
            "intervals_athlete_id": "test-athlete",
        })()
        client = server.IntervalsClient(config, request=lambda *args, **kwargs: [])
        self.assertIs(client.config, config)
        self.assertEqual(client.get("/health"), [])

    def test_direct_intervals_client_instantiation_and_methods(self) -> None:
        config = type("ConfigStub", (), {
            "intervals_api_key": "test-key",
            "intervals_athlete_id": "test-athlete",
        })()
        request_mock = Mock(return_value=[])
        client = IntervalsClient(config, request=request_mock)
        self.assertIs(client.config, config)
        self.assertEqual(client.get("/test"), [])
        self.assertIsInstance(client.pagination, dict)


if __name__ == "__main__":
    unittest.main()
