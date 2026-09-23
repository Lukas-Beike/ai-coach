"""Audio validation and provider orchestration."""

from __future__ import annotations

import base64

from backend.errors import GEMINI_API_KEY_ERROR, OPENAI_API_KEY_ERROR, AppError
from backend.providers import gemini as gemini_provider
from backend.providers import http as provider_http
from backend.providers import openai as openai_provider

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


class AudioTranscriptionClient:
    """Validate one transient voice note and send it to the selected provider."""

    def __init__(
        self,
        *,
        max_audio_bytes: int,
        openai_api_key: str | None,
        gemini_api_key: str | None,
        openai_base_url: str,
        default_openai_base_url: str,
        openai_transcription_model: str,
        response_timeout_seconds: int,
        http_client: provider_http.JsonHttpClient,
        gemini_client: gemini_provider.GeminiJsonClient,
    ) -> None:
        self.max_audio_bytes = max_audio_bytes
        self.openai_api_key = openai_api_key
        self.gemini_api_key = gemini_api_key
        self.openai_base_url = openai_base_url
        self.default_openai_base_url = default_openai_base_url
        self.openai_transcription_model = openai_transcription_model
        self.response_timeout_seconds = response_timeout_seconds
        self.http_client = http_client
        self.gemini_client = gemini_client

    def transcribe(self, audio: bytes, content_type: str, *, provider: str, model: str) -> dict[str, str]:
        """Transcribe audio without retaining the uploaded bytes or provider payload."""
        if not isinstance(audio, bytes) or not audio:
            raise AppError(400, "Die Audioaufnahme ist leer.")
        if len(audio) > self.max_audio_bytes:
            raise AppError(413, "Die Audioaufnahme ist zu groß.")
        audio_type = normalized_audio_type(content_type)
        suffix = audio_suffix(audio_type)
        if not suffix:
            raise AppError(415, "Nicht unterstütztes Audioformat. Erlaubt sind WebM, MP4, OGG, MP3 und WAV.")

        if str(provider or "").casefold() == "gemini":
            if not self.gemini_api_key:
                raise AppError(503, GEMINI_API_KEY_ERROR)
            result = self.gemini_client.generate(
                model,
                {
                    "contents": [{"role": "user", "parts": [
                        {"inlineData": {"mimeType": audio_type, "data": base64.b64encode(audio).decode("ascii")}},
                        {"text": "Transkribiere diese deutsche Trainingsfrage wortgetreu. Gib ausschließlich das Transkript zurück."},
                    ]}],
                    "generationConfig": {"temperature": 0},
                },
                operation="transcription",
            )
            transcript = gemini_provider.response_text(result)
            if not transcript:
                raise AppError(502, "Gemini hat kein Transkript zurückgegeben.")
            return {"transcript": transcript}

        if not self.openai_api_key:
            raise AppError(503, OPENAI_API_KEY_ERROR)
        body, multipart_type = provider_http.multipart_form_data(
            [
                ("model", self.openai_transcription_model),
                ("languages[]", "de"),
                ("prompt", "Deutsche Trainingsfrage an einen Ausdauercoach. Fachbegriffe: Intervals.icu, Garmin, FTP, HRV, TSB, ATL, CTL, VO2max, Watt, Pace, Laktat, Radfahren, Laufen."),
            ],
            "file",
            "voice" + suffix,
            audio_type,
            audio,
        )
        result = self.http_client.request(
            "POST",
            openai_provider.endpoint(
                self.openai_base_url,
                "/audio/transcriptions",
                default_base_url=self.default_openai_base_url,
            ),
            headers={"Authorization": f"Bearer {self.openai_api_key}"},
            timeout=self.response_timeout_seconds,
            service="openai",
            raw_body=body,
            content_type=multipart_type,
        )
        text = result.get("text") if isinstance(result, dict) else None
        if not isinstance(text, str) or not text.strip():
            raise AppError(502, "OpenAI hat kein Transkript zurückgegeben.")
        return {"transcript": text.strip()}
