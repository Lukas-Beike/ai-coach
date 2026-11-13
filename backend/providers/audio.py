"""Audio validation and provider orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.errors import OPENAI_API_KEY_ERROR, AppError
from backend.providers import http as provider_http
from backend.providers.http import endpoint

if TYPE_CHECKING:
    from backend.providers.state import ProviderStateService

VOICE_AUDIO_TYPES = {
    "audio/webm": ".webm",
    "audio/mp4": ".mp4",
    "audio/ogg": ".ogg",
    "audio/mpeg": ".mp3",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/mpga": ".mpga",
    "audio/m4a": ".m4a",
}


def normalized_audio_type(content_type: str) -> str:
    return str(content_type or "").split(";", 1)[0].strip().casefold()


def audio_suffix(content_type: str) -> str | None:
    return VOICE_AUDIO_TYPES.get(normalized_audio_type(content_type))


TRANSCRIPTION_PROMPT = (
    "Deutsche Trainingsfrage an einen Ausdauercoach. Fachbegriffe: Intervals.icu, "
    "Garmin, FTP, HRV, TSB, ATL, CTL, VO2max, Watt, Pace, Laktat, Radfahren, Laufen."
)


TRANSCRIPTION_MODEL_ERROR = (
    "Für den Transkriptionsserver fehlt TRANSCRIPTION_MODEL in der Konfiguration."
)


class AudioTranscriptionClient:
    """Validate one transient voice note and send it to the transcription endpoint.

    The endpoint is OpenAI unless `local_endpoint` names a separately configured
    OpenAI-compatible server; then its key is optional and no OpenAI usage is kept.
    """

    def __init__(
        self,
        *,
        max_audio_bytes: int,
        api_key: str | None,
        base_url: str,
        default_base_url: str,
        model: str,
        response_timeout_seconds: int,
        http_client: provider_http.JsonHttpClient,
        provider_state: ProviderStateService | None = None,
        local_endpoint: bool = False,
    ) -> None:
        self.max_audio_bytes = max_audio_bytes
        self.api_key = api_key
        self.base_url = base_url
        self.default_base_url = default_base_url
        self.model = model
        self.response_timeout_seconds = response_timeout_seconds
        self.http_client = http_client
        self.provider_state = provider_state
        self.local_endpoint = local_endpoint
        # What differs between OpenAI and a local server, fixed once per client.
        self._not_configured = ""
        if local_endpoint and not model:
            self._not_configured = TRANSCRIPTION_MODEL_ERROR
        elif not local_endpoint and not api_key:
            self._not_configured = OPENAI_API_KEY_ERROR
        # Whisper servers take the single `language` field; OpenAI keeps `languages[]`.
        self._language_field = "language" if local_endpoint else "languages[]"
        self._service = "transcription" if local_endpoint else "openai"
        self._label = "Der Transkriptionsserver" if local_endpoint else "OpenAI"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    def transcribe(self, audio: bytes, content_type: str) -> dict[str, str]:
        """Transcribe audio without retaining the uploaded bytes or provider payload."""
        if not isinstance(audio, bytes) or not audio:
            raise AppError(400, "Die Audioaufnahme ist leer.")
        if len(audio) > self.max_audio_bytes:
            raise AppError(413, "Die Audioaufnahme ist zu groß.")
        audio_type = normalized_audio_type(content_type)
        suffix = audio_suffix(audio_type)
        if not suffix:
            raise AppError(
                415,
                "Nicht unterstütztes Audioformat. Erlaubt sind WebM, MP4, OGG, MP3 und WAV.",
            )

        if self._not_configured:
            raise AppError(503, self._not_configured, reason="not_configured")
        body, multipart_type = provider_http.multipart_form_data(
            [
                ("model", self.model),
                (self._language_field, "de"),
                ("prompt", TRANSCRIPTION_PROMPT),
            ],
            "file",
            "voice" + suffix,
            audio_type,
            audio,
        )
        result = self.http_client.request(
            "POST",
            endpoint(
                self.base_url,
                "/audio/transcriptions",
                default_base_url=self.default_base_url,
            ),
            headers=self._headers,
            timeout=self.response_timeout_seconds,
            service=self._service,
            raw_body=body,
            content_type=multipart_type,
        )
        if self.provider_state is not None and self._service == "openai":
            # Only counters are kept; neither the audio nor the transcript is stored.
            self.provider_state.record_usage("openai", result, "transcription")
        text = result.get("text") if isinstance(result, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise AppError(502, f"{self._label} hat kein Transkript zurückgegeben.")
        return {"transcript": text.strip()}
