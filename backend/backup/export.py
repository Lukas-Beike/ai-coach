"""Bounded serialization helpers for privacy exports.

Database ownership, application limits, and error types stay at the server
boundary.  This module only converts rows to export records and writes the
already-selected records to an archive through explicit callbacks.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
import json
from typing import Any


PayloadDecoder = Callable[[Any], Any]
Clock = Callable[[], float]
TimeoutErrorFactory = Callable[[], Exception]


def decode_payload(value: Any) -> Any:
    """Decode a JSON payload, returning an empty object for invalid input."""
    try:
        return json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}


def iter_workout_drafts(db: Any, *, decode: PayloadDecoder = decode_payload) -> Iterable[dict[str, Any]]:
    """Yield the bounded, flattened legacy workout-draft export records."""
    for row in db.execute(
        "SELECT id, status, intervals_event_id, error, created_at, updated_at, payload "
        "FROM workout_drafts ORDER BY created_at DESC LIMIT 50"
    ):
        payload = decode(row["payload"])
        if not isinstance(payload, dict):
            payload = {}
        yield {
            "id": row["id"],
            "status": row["status"],
            "intervals_event_id": row["intervals_event_id"],
            "error": row["error"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            **payload,
        }


def iter_workout_library(db: Any, *, decode: PayloadDecoder = decode_payload) -> Iterable[dict[str, Any]]:
    """Yield bounded workout-library payloads in the established order."""
    for row in db.execute(
        "SELECT payload FROM workout_library "
        "ORDER BY lower(json_extract(payload, '$.type')), lower(json_extract(payload, '$.name')) LIMIT 1000"
    ):
        payload = decode(row["payload"])
        if isinstance(payload, dict):
            yield payload


def application_state(
    db: Any,
    *,
    excluded_keys: set[str],
    excluded_suffixes: tuple[str, ...] = ("_running", "_status"),
    decode: PayloadDecoder = decode_payload,
) -> dict[str, Any]:
    """Project exportable KV state while omitting sensitive/transient keys."""
    state: dict[str, Any] = {}
    for row in db.execute("SELECT key, value FROM kv ORDER BY key"):
        key = str(row["key"])
        if key in excluded_keys or key.endswith(excluded_suffixes):
            continue
        value = decode(row["value"])
        state[key] = value if value != {} or row["value"] == "{}" else row["value"]
    return state


def write_jsonl_rows(
    archive: Any,
    name: str,
    rows: Iterable[Mapping[str, Any]],
    deadline: float,
    *,
    now: Clock,
    timeout_error: TimeoutErrorFactory,
) -> None:
    """Write rows incrementally, preserving the export time limit."""
    with archive.open(name, "w", force_zip64=True) as output:
        for row in rows:
            if now() > deadline:
                raise timeout_error()
            output.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n")


def manifest(
    archive_names: Iterable[str],
    *,
    schema_version: int,
    exported_at: str,
    format_version: int,
    jsonl_files: Iterable[str],
) -> dict[str, Any]:
    """Build the stable privacy-export manifest from archive names."""
    return {
        "format": "intervals-coach-privacy-export",
        "format_version": format_version,
        "schema_version": schema_version,
        "exported_at": exported_at,
        "status": "complete",
        "categories": sorted(name.rsplit(".", 1)[0] for name in archive_names if name != "manifest.json"),
        "jsonl_files": sorted(jsonl_files),
    }
