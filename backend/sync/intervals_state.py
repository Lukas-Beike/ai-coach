"""Pure projections for public Intervals.icu connection and library-sync state."""

from datetime import UTC, datetime
from typing import Any

# Stamps of the last Intervals.icu output job that reached the provider
# (backend/sync/executor.py): one after a success, one after a provider failure.
INTERVALS_OUTPUT_OK_KEY = "intervals_last_output_ok_at"
INTERVALS_OUTPUT_FAILED_KEY = "intervals_last_output_failed_at"


def _stamp(value: str | None) -> datetime | None:
    """An aware time, None for a missing or unreadable stamp."""
    try:
        parsed = datetime.fromisoformat(str(value))
    except TypeError, ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


def _latest(*values: str | None) -> str | None:
    """The newest readable stamp, as stored."""
    readable = [(parsed, value) for value in values if (parsed := _stamp(value))]
    return max(readable, key=lambda pair: pair[0])[1] if readable else None


def connection_state(
    configured: bool,
    running: bool,
    error: str | None,
    last_used_at: str | None,
    last_failed_at: str | None = None,
) -> str:
    """Connected after a successful export, error when the last attempt failed.

    The legacy library error text has no time: it counts only while no export
    has succeeded, so a stale text never hides a later success.
    """
    if not configured:
        return "not_configured"
    if running:
        return "syncing"
    used, failed = _stamp(last_used_at), _stamp(last_failed_at)
    if (failed and (not used or failed > used)) or (error and not used):
        return "error"
    return "connected" if used else "configured"


def public_state(
    *,
    configured: bool,
    running: bool,
    last_library_sync_at: str | None,
    last_library_sync_error: str | None,
    library_sync_state: dict[str, Any],
    last_output_ok_at: str | None = None,
    last_output_failed_at: str | None = None,
) -> dict[str, Any]:
    """``last_used_at`` is the last successful export: library push or output job."""
    used_at = _latest(last_library_sync_at, last_output_ok_at)
    return {
        "configured": configured,
        "state": connection_state(
            configured,
            running,
            last_library_sync_error,
            used_at,
            last_output_failed_at,
        ),
        "running": running,
        "last_error": last_library_sync_error,
        "last_used_at": used_at,
        "library_sync": {
            "last_sync_at": last_library_sync_at,
            "last_error": last_library_sync_error,
            "state": library_sync_state,
        },
    }
