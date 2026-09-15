import unittest

from test_server import server


class IntervalsClientTests(unittest.TestCase):
    def test_server_owned_client_uses_explicit_dependencies(self):
        config = type("ConfigStub", (), {
            "intervals_api_key": "test-key",
            "intervals_athlete_id": "test-athlete",
        })()
        client = server.IntervalsClient(config, request=lambda *args, **kwargs: [])
        self.assertIs(client.config, config)
        self.assertEqual(client.get("/health"), [])


if __name__ == "__main__":
    unittest.main()
