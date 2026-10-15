"""Bounded request-body parsing for the HTTP application boundary.

The request handler owns the socket and application error type.  These helpers
receive both explicitly and keep body limits, content-type validation, and JSON
shape validation independent of ``server.py``.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Mapping
from typing import Any, Protocol


class HeaderLookup(Protocol):
    """The read-only header access used by body helpers (``Mapping`` or ``Message``)."""

    def get(self, name: str, default: Any = None, /) -> Any: ...


HeaderSource = Mapping[str, Any] | HeaderLookup
ReadBytes = Callable[[int], bytes]
ErrorFactory = Callable[[int, str], Exception]
AudioTypeNormalizer = Callable[[str], str]

# Large bodies (database restore uploads) are read in pieces of this size, so a
# whole upload never has to be held in memory at once.
STREAM_CHUNK_BYTES = 1024 * 1024


def _content_length(headers: HeaderSource, error: ErrorFactory) -> int:
    try:
        return int(headers.get("Content-Length", "0"))
    except ValueError as exc:
        raise error(400, "Ungültige Content-Length.") from exc


def _validated_size(
    headers: HeaderSource,
    max_bytes: int,
    *,
    error: ErrorFactory,
    too_large_status_threshold: int | None,
) -> int:
    size = _content_length(headers, error)
    if size <= 0 or size > max_bytes:
        threshold = (
            max_bytes
            if too_large_status_threshold is None
            else too_large_status_threshold
        )
        raise error(
            413 if size > threshold else 400, "Ungültige Größe des Anfrageinhalts."
        )
    return size


def read_body(
    headers: HeaderSource,
    read_bytes: ReadBytes,
    max_bytes: int,
    *,
    error: ErrorFactory,
    too_large_status_threshold: int | None = None,
) -> bytes:
    """Read one bounded body while preserving the API's size errors."""
    size = _validated_size(
        headers,
        max_bytes,
        error=error,
        too_large_status_threshold=too_large_status_threshold,
    )
    return read_bytes(size)


def read_body_stream(
    headers: HeaderSource,
    read_bytes: ReadBytes,
    max_bytes: int,
    *,
    error: ErrorFactory,
    too_large_status_threshold: int | None = None,
    chunk_size: int = STREAM_CHUNK_BYTES,
) -> Iterator[bytes]:
    """Validate one bounded body up front, then yield it in chunks.

    The size checks run here, before any byte is read, with the same errors as
    ``read_body``. The returned iterator reads at most ``chunk_size`` bytes per
    step and raises the API's 400 error if the connection ends before the
    declared length.
    """
    size = _validated_size(
        headers,
        max_bytes,
        error=error,
        too_large_status_threshold=too_large_status_threshold,
    )
    return _body_chunks(size, read_bytes, chunk_size, error)


def _body_chunks(
    size: int, read_bytes: ReadBytes, chunk_size: int, error: ErrorFactory
) -> Iterator[bytes]:
    remaining = size
    while remaining:
        chunk = read_bytes(min(chunk_size, remaining))
        if not chunk:
            raise error(400, "Der Anfrageinhalt wurde unvollständig übertragen.")
        remaining -= len(chunk)
        yield chunk


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
        raise error(
            415,
            "Nicht unterstütztes Audioformat. Erlaubt sind WebM, MP4, OGG, MP3 und WAV.",
        )
    size = _content_length(headers, error)
    if size <= 0 or size > max_bytes:
        raise error(
            413 if size > max_bytes else 400, "Ungültige Größe der Audioaufnahme."
        )
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
