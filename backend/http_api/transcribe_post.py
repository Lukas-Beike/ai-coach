"""HTTP dispatch for transient voice transcription requests."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.providers.audio import AudioTranscriptionClient
from backend.settings import SettingsService


class TranscribePostRoutes:
    """Route audio uploads to the selected transcription provider."""

    def __init__(
        self,
        settings: SettingsService,
        audio_client: Callable[[], AudioTranscriptionClient],
    ) -> None:
        self._settings = settings
        self._audio_client = audio_client

    def handle(self, handler: Any, path: str) -> bool:
        if path != "/api/transcribe":
            return False
        content_type = handler.headers.get("Content-Type", "")
        audio = handler.read_audio_body()
        result = self._audio_client().transcribe(
            audio,
            content_type,
            provider=self._settings.selected_ai_provider(),
            model=self._settings.selected_model(),
        )
        handler.send_json(200, result)
        return True
