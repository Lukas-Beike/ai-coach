"""Pure projections for public Intervals.icu connection and library-sync state."""

from typing import Any


def latest_library_timestamp(*values: str | None) -> str | None:
    """Return the newest library import/push ISO timestamp, if any."""
    texts = [value for value in values if isinstance(value, str) and value]
    return max(texts) if texts else None


def connection_state(
    configured: bool,
    running: bool,
    error: str | None,
    last_library_sync_at: str | None,
) -> str:
    if not configured:
        return "not_configured"
    if running:
        return "syncing"
    if error:
        return "error"
    if last_library_sync_at:
        return "connected"
    return "configured"


def public_state(
    *,
    configured: bool,
    running: bool,
    last_library_sync_at: str | None,
    last_library_sync_error: str | None,
    library_sync_state: dict[str, Any],
) -> dict[str, Any]:
    return {
        "configured": configured,
        "state": connection_state(
            configured, running, last_library_sync_error, last_library_sync_at
        ),
        "running": running,
        "last_error": last_library_sync_error,
        "library_sync": {
            "last_sync_at": last_library_sync_at,
            "last_error": last_library_sync_error,
            "state": library_sync_state,
        },
    }
