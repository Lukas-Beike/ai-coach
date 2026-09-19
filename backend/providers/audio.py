"""Pure audio MIME-type projections used by provider wire adapters."""

from __future__ import annotations

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
