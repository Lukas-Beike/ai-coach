"""Focused tests for the authenticated transcription POST route."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from backend.errors import AppError
from backend.http_api.transcribe_post import TranscribePostRoutes


class TranscribePostRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = Mock()
        self.client.transcribe.return_value = {"transcript": "synthetic transcript"}
        self.routes = TranscribePostRoutes(lambda: self.client)
        self.handler = SimpleNamespace(
            headers={"Content-Type": "audio/webm;codecs=opus"},
            read_audio_body=Mock(return_value=b"synthetic audio"),
            send_json=Mock(),
        )

    def test_success_dispatches_audio_to_transcription_client(self) -> None:
        self.assertTrue(self.routes.handle(self.handler, "/api/transcribe"))

        self.handler.read_audio_body.assert_called_once_with()
        self.client.transcribe.assert_called_once_with(
            b"synthetic audio",
            "audio/webm;codecs=opus",
        )
        self.handler.send_json.assert_called_once_with(
            200, {"transcript": "synthetic transcript"}
        )

    def test_unknown_path_does_not_read_audio_or_create_client(self) -> None:
        self.assertFalse(self.routes.handle(self.handler, "/api/other"))

        self.handler.read_audio_body.assert_not_called()
        self.client.transcribe.assert_not_called()
        self.handler.send_json.assert_not_called()

    def test_provider_error_is_preserved_for_outer_http_error_handler(self) -> None:
        error = AppError(502, "Transcription failed", reason="provider_error")
        self.client.transcribe.side_effect = error

        with self.assertRaises(AppError) as raised:
            self.routes.handle(self.handler, "/api/transcribe")

        self.assertIs(raised.exception, error)
        self.handler.send_json.assert_not_called()

    def test_body_validation_error_stops_before_provider_dispatch(self) -> None:
        error = AppError(413, "Die Audioaufnahme ist zu groß.")
        self.handler.read_audio_body.side_effect = error

        with self.assertRaises(AppError) as raised:
            self.routes.handle(self.handler, "/api/transcribe")

        self.assertIs(raised.exception, error)
        self.client.transcribe.assert_not_called()
        self.handler.send_json.assert_not_called()


if __name__ == "__main__":
    unittest.main()
