"""HTTP dispatch for transient voice transcription requests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.http_api.route_table import Access, Route, RouteRequest
from backend.runtime.ports import AudioTranscriber


class TranscribePostRoutes:
    """Route audio uploads to the selected transcription provider."""

    def __init__(self, audio_client: Callable[[], AudioTranscriber]) -> None:
        self._audio_client = audio_client

    def routes(self) -> list[Route]:
        return [Route("POST", "/api/transcribe", Access.SESSION_CSRF, self._transcribe)]

    def _transcribe(self, handler: Any, _request: RouteRequest) -> None:
        """Transcribe short-lived voice input."""
        content_type = handler.headers.get("Content-Type", "")
        audio = handler.read_audio_body()
        result = self._audio_client().transcribe(audio, content_type)
        handler.send_json(200, result)
