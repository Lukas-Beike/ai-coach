"""Dependency-light orchestration for the read-only synchronization pipeline."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def run_read_sync_pipeline(
    reason: str,
    activity_days: int | None = None,
    operation_id: str | None = None,
    *,
    observe: Callable[..., Any],
    sync_intervals: Callable[..., Any],
    sync_competitions: Callable[..., Any],
    record_failure: Callable[[Mapping[str, Any], str, str, BaseException], None],
) -> None:
    """Run the read-only Intervals and competition steps under one operation."""
    with observe("sync", reason, operation_id) as scope:
        current_operation_id = scope["operation_id"]
        try:
            sync_intervals(reason, activity_days=activity_days, operation_id=current_operation_id)
        except Exception as exc:
            record_failure(scope, "intervals", "sync", exc)
        try:
            sync_competitions(reason, push_local=False, operation_id=current_operation_id)
        except Exception as exc:
            record_failure(scope, "intervals", "competitions", exc)
