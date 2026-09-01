"""Dependency-light projection and persistence of synchronization status."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def persist_sync_operation_state(
    operation_id: str,
    status: str,
    phase: str,
    progress: int,
    message: str,
    error: str | None = None,
    *,
    set_value: Callable[[str, str], None],
    redact: Callable[[str], str],
) -> None:
    """Persist bounded, non-athlete-facing state through an injected store."""
    set_value("sync_operation_id", operation_id)
    set_value("sync_operation_status", status)
    set_value("sync_operation_phase", phase)
    set_value("sync_operation_progress", str(max(0, min(progress, 100))))
    set_value("sync_operation_message", message)
    if error is not None:
        set_value("last_sync_error", redact(error)[:1000])


def project_sync_status(
    *,
    running: bool,
    get_value: Callable[[str], str | None],
    state_versions: Mapping[str, Any],
    provider_freshness: list[dict[str, Any]],
    maintenance: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the public sync-status DTO from explicitly supplied state."""
    status = get_value("sync_operation_status") or ("running" if running else "idle")
    try:
        progress = max(0, min(int(get_value("sync_operation_progress") or 0), 100))
    except (TypeError, ValueError):
        progress = 0
    return {
        "status": status,
        "phase": get_value("sync_operation_phase") or ("running" if running else "idle"),
        "progress": progress,
        "operation_id": get_value("sync_operation_id"),
        "running": running,
        "message": get_value("sync_operation_message") or None,
        "started_at": get_value("sync_operation_started_at"),
        "finished_at": get_value("sync_operation_finished_at"),
        "last_error": get_value("last_sync_error") or None,
        "state_versions": dict(state_versions),
        "provider_freshness": provider_freshness,
        "maintenance": dict(maintenance),
    }
