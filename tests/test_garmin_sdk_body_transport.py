"""Pinned Garmin SDK transport behavior with fake responses, no network."""

import threading
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.sync.garmin_profile_body_export import _upload_with_deadline

try:
    from garminconnect.client import Client
except ImportError:
    Client = None


@unittest.skipIf(Client is None, "garminconnect is not installed")
class GarminSdkBodyTransportTests(unittest.TestCase):
    def client(self, responses):
        session = Mock()
        session.request.side_effect = responses
        return SimpleNamespace(
            _token_lock=threading.RLock(),
            is_authenticated=False,
            _refresh_session=Mock(),
            _resolve_url=lambda _path: "https://synthetic.invalid/upload",
            get_api_headers=dict,
            _api_session=session,
        )

    def test_401_refreshes_once_and_replays_body(self):
        fake = self.client(
            [SimpleNamespace(status_code=401), SimpleNamespace(status_code=200)]
        )
        result = Client._run_request(
            fake, "POST", "/upload", files={"file": ("body.fit", b"synthetic")}
        )
        self.assertEqual(result.status_code, 200)
        fake._refresh_session.assert_called_once()
        self.assertEqual(fake._api_session.request.call_count, 2)
        for call in fake._api_session.request.call_args_list:
            self.assertEqual(call.kwargs["timeout"], 15)
            self.assertEqual(call.kwargs["files"]["file"][1], b"synthetic")

    def test_401_replay_does_not_start_after_upload_deadline(self):
        transport = self.client(
            [SimpleNamespace(status_code=401), SimpleNamespace(status_code=200)]
        )
        original = transport._api_session.request
        client = SimpleNamespace(
            client=transport,
            garmin_connect_upload="/upload",
            add_body_composition=lambda **_kwargs: Client._run_request(
                transport, "POST", "/upload", files={"file": ("body.fit", b"synthetic")}
            ),
        )
        with (
            patch(
                "backend.sync.garmin_profile_body_export.monotonic", side_effect=[9, 11]
            ),
            self.assertRaises(TimeoutError),
        ):
            _upload_with_deadline(client, "2026-01-01T00:00:00+00:00", 70, 15, 10)
        original.assert_called_once()
        self.assertEqual(original.call_args.kwargs["timeout"], 1)
        transport._refresh_session.assert_called_once()
        self.assertIs(transport._api_session.request, original)

    def test_timeout_is_not_retried(self):
        fake = self.client([TimeoutError("synthetic")])
        with self.assertRaises(TimeoutError):
            Client._run_request(
                fake, "POST", "/upload", files={"file": ("body.fit", b"synthetic")}
            )
        fake._api_session.request.assert_called_once()
        fake._refresh_session.assert_not_called()


if __name__ == "__main__":
    unittest.main()
