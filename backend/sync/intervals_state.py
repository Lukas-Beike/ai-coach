"""Pure projections for public Intervals.icu connection and library-sync state."""

from datetime import datetime
from typing import Any


def _later(*stamps: str | None) -> str | None:
    """The latest of the given ISO timestamps, None when there are none."""
    return max(
        (stamp for stamp in stamps if stamp),
        key=datetime.fromisoformat,
        default=None,
    )


def connection_state(
    configured: bool,
    running: bool,
    error: str | None,
    last_library_sync_at: str | None,
    last_job_failed_at: str | None = None,
) -> str:
    """Connected after a successful export, error when the last attempt failed."""
    if not configured:
        return "not_configured"
    if running:
        return "syncing"
    if error or (
        last_job_failed_at
        and _later(last_job_failed_at, last_library_sync_at) == last_job_failed_at
    ):
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
    last_job_ok_at: str | None = None,
    last_job_failed_at: str | None = None,
) -> dict[str, Any]:
    """``last_used_at`` is the last successful export: library push or push job."""
    used_at = _later(last_library_sync_at, last_job_ok_at)
    return {
        "configured": configured,
        "state": connection_state(
            configured,
            running,
            last_library_sync_error,
            used_at,
            last_job_failed_at,
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
