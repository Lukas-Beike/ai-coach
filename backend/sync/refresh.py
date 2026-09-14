"""Database operations for durable provider-refresh history."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def cleanup_refresh_history(db: Any, *, cutoff: str, max_rows: int) -> None:
    db.execute("DELETE FROM provider_refresh_history WHERE started_at < ?", (cutoff,))
    db.execute(
        "DELETE FROM provider_refresh_history WHERE id NOT IN "
        "(SELECT id FROM provider_refresh_history ORDER BY started_at DESC LIMIT ?)",
        (max_rows,),
    )


def retry_at(
    rows: list[Any],
    *,
    current_error_code: str | None,
    now: datetime,
    base_seconds: int,
    max_seconds: int,
) -> str | None:
    if current_error_code in {"auth_required", "invalid_configuration"}:
        return None
    failures = 1 if current_error_code else 0
    for row in rows:
        if row["status"] in {"success", "partial", "skipped"}:
            break
        if row["status"] != "error":
            continue
        if row["error_code"] in {"auth_required", "invalid_configuration"}:
            return None
        failures += 1
    if not failures:
        return None
    delay = min(base_seconds * (2 ** min(failures - 1, 5)), max_seconds)
    return (now + timedelta(seconds=delay)).isoformat()


def create_refresh_record(
    db: Any, *, refresh_id: str, provider: str, area: str,
    operation_id: str, trigger: str, started_at: str,
) -> None:
    db.execute(
        "INSERT INTO provider_refresh_history(id, provider, area, operation_id, trigger, started_at, phase, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'queued', 'running')",
        (refresh_id, provider, area, operation_id, trigger, started_at),
    )


def finish_refresh_record(
    db: Any, *, refresh_id: str, finished_at: str, phase: str,
    status: str, error_code: str | None, now: datetime,
    base_seconds: int, max_seconds: int,
) -> tuple[str, str] | None:
    row = db.execute(
        "SELECT provider, area FROM provider_refresh_history WHERE id=?", (refresh_id,)
    ).fetchone()
    if not row:
        return None
    rows = db.execute(
        "SELECT status, error_code FROM provider_refresh_history "
        "WHERE provider=? AND area=? ORDER BY started_at DESC LIMIT 20",
        (row["provider"], row["area"]),
    ).fetchall()
    next_retry = retry_at(
        rows,
        current_error_code=error_code if status == "error" else None,
        now=now,
        base_seconds=base_seconds,
        max_seconds=max_seconds,
    )
    db.execute(
        "UPDATE provider_refresh_history SET finished_at=?, phase=?, status=?, error_code=?, next_retry_at=? WHERE id=?",
        (finished_at, phase, status, error_code, next_retry, refresh_id),
    )
    return str(row["provider"]), str(row["area"])
