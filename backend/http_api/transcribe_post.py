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
        """Transcribe short-lived voice input.

        Request: the raw audio bytes as body, not JSON. `Content-Type` is one of
        `audio/webm`, `audio/mp4`, `audio/ogg`, `audio/mpeg`, `audio/wav`,
        `audio/x-wav`, `audio/mpga`, `audio/m4a` (parameters after `;` are ignored);
        `Content-Length` 1 to 8 000 000 bytes. The audio is never stored.

        Response: 200 `{"transcript": string}`.

        Errors: 415 "Nicht unterstütztes Audioformat. Erlaubt sind WebM, MP4, OGG,
        MP3 und WAV."; 400 "Ungültige Content-Length."; 400 "Ungültige Größe der
        Audioaufnahme." for an empty body, 413 with the same message above 8 000 000
        bytes; 400 "Die Audioaufnahme wurde unvollständig übertragen."; 503
        `not_configured` "OpenAI ist nicht eingerichtet. Zugangsdaten unter Mehr →
        Anbindungen hinterlegen."; 502 "OpenAI hat kein Transkript
        zurückgegeben." when the provider returns no text; 502 `network_error`,
        `http_error` or `client_error` when the OpenAI request fails ("OpenAI ist
        nicht erreichbar." and similar). With `TRANSCRIPTION_BASE_URL` set, no key
        is required; 503 `not_configured` "Für den Transkriptionsserver fehlt
        TRANSCRIPTION_MODEL in der Konfiguration." without a model; 502 "Der
        Transkriptionsserver hat kein Transkript zurückgegeben." or "Der
        Transkriptionsserver ist nicht erreichbar." with the `provider_*` reasons;
        an HTTP error status gives "Anfrage an externen Dienst fehlgeschlagen
        (status).".
        """
        content_type = handler.headers.get("Content-Type", "")
        audio = handler.read_audio_body()
        result = self._audio_client().transcribe(audio, content_type)
        handler.send_json(200, result)
