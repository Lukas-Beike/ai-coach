"""Bounded request-body parsing for the HTTP application boundary.

The request handler owns the socket and application error type.  These helpers
receive both explicitly and keep body limits, content-type validation, and JSON
shape validation independent of ``server.py``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
import json
from typing import Any


ReadBytes = Callable[[int], bytes]
ErrorFactory = Callable[[int, str], Exception]
AudioTypeNormalizer = Callable[[str], str]


def _content_length(headers: Mapping[str, Any], error: ErrorFactory) -> int:
    try:
        return int(headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise error(400, "Ungültige Content-Length.") from exc


def read_body(
    headers: Mapping[str, Any],
    read_bytes: ReadBytes,
    max_bytes: int,
    *,
    error: ErrorFactory,
    too_large_status_threshold: int | None = None,
) -> bytes:
    """Read one bounded body while preserving the API's size errors."""
    size = _content_length(headers, error)
    if size <= 0 or size > max_bytes:
        threshold = max_bytes if too_large_status_threshold is None else too_large_status_threshold
        raise error(413 if size > threshold else 400, "Ungültige Größe des Anfrageinhalts.")
    return read_bytes(size)


def read_audio_body(
    headers: Mapping[str, Any],
    read_bytes: ReadBytes,
    *,
    allowed_types: Mapping[str, str],
    normalize_type: AudioTypeNormalizer,
    max_bytes: int,
    error: ErrorFactory,
) -> bytes:
    """Validate and read a bounded audio body for short-lived transcription."""
    content_type = normalize_type(str(headers.get("Content-Type", "")))
    if content_type not in allowed_types:
        raise error(415, "Nicht unterstütztes Audioformat. Erlaubt sind WebM, MP4, OGG, MP3 und WAV.")
    size = _content_length(headers, error)
    if size <= 0 or size > max_bytes:
        raise error(413 if size > max_bytes else 400, "Ungültige Größe der Audioaufnahme.")
    audio = read_bytes(size)
    if len(audio) != size:
        raise error(400, "Die Audioaufnahme wurde unvollständig übertragen.")
    return audio


def read_json(
    headers: Mapping[str, Any],
    read_bytes: ReadBytes,
    max_bytes: int,
    *,
    error: ErrorFactory,
    too_large_status_threshold: int | None = None,
) -> dict[str, Any]:
    """Read an object-shaped JSON request with the standard body limit."""
    if "application/json" not in str(headers.get("Content-Type", "")):
        raise error(415, "Content-Type muss application/json sein.")
    try:
        payload = json.loads(
            read_body(
                headers,
                read_bytes,
                max_bytes,
                error=error,
                too_large_status_threshold=too_large_status_threshold,
            )
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise error(400, "Ungültiges JSON.") from exc
    if not isinstance(payload, dict):
        raise error(400, "Der JSON-Inhalt muss ein Objekt sein.")
    return payload
