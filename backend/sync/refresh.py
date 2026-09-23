"""Database operations for durable provider-refresh history."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any


def sync_job_error_class(error: BaseException) -> str:
    """Map provider exceptions to bounded, retry-safe job classes."""
    reason = str(getattr(error, "reason", "") or "").strip().casefold()
    if reason in {"unsupported_job", "invalid_job_request", "invalid_job_resolution"}:
        return reason
    code = ProviderRefreshTracker.error_code(error)
    return {
        "provider_network_error": "network_error",
        "provider_http_error": "temporary_error",
        "provider_client_error": "client_error",
        "provider_error": "temporary_error",
    }.get(code, code)


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
    db: Any,
    *,
    refresh_id: str,
    provider: str,
    area: str,
    operation_id: str,
    trigger: str,
    started_at: str,
) -> None:
    db.execute(
        "INSERT INTO provider_refresh_history(id, provider, area, operation_id, trigger, started_at, phase, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'queued', 'running')",
        (refresh_id, provider, area, operation_id, trigger, started_at),
    )


def finish_refresh_record(
    db: Any,
    *,
    refresh_id: str,
    finished_at: str,
    phase: str,
    status: str,
    error_code: str | None,
    now: datetime,
    base_seconds: int,
    max_seconds: int,
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
    next_retry = (
        retry_at(
            rows,
            current_error_code=error_code,
            now=now,
            base_seconds=base_seconds,
            max_seconds=max_seconds,
        )
        if status == "error"
        else None
    )
    db.execute(
        "UPDATE provider_refresh_history SET finished_at=?, phase=?, status=?, error_code=?, next_retry_at=? WHERE id=?",
        (finished_at, phase, status, error_code, next_retry, refresh_id),
    )
    return str(row["provider"]), str(row["area"])


class ProviderRefreshTracker:
    """Own provider-refresh history transactions and state-event publication."""

    def __init__(
        self,
        database_manager: Any,
        event_buffer: Any,
        now: Callable[[], datetime],
        uuid_factory: Callable[[], Any],
        *,
        retention_days: int = 30,
        max_rows: int = 200,
        retry_base_seconds: int = 900,
        retry_max_seconds: int = 21600,
    ):
        self._database_manager = database_manager
        self._event_buffer = event_buffer
        self._now = now
        self._uuid_factory = uuid_factory
        self._retention_days = retention_days
        self._max_rows = max_rows
        self._retry_base_seconds = retry_base_seconds
        self._retry_max_seconds = retry_max_seconds

    def start(self, provider: str, area: str, operation_id: str, trigger: str) -> str:
        current_time = self._now()
        refresh_id = str(self._uuid_factory())
        with self._database_manager.unit_of_work() as db:
            create_refresh_record(
                db,
                refresh_id=refresh_id,
                provider=provider,
                area=area,
                operation_id=operation_id,
                trigger=trigger,
                started_at=current_time.isoformat(),
            )
            cleanup_refresh_history(
                db,
                cutoff=(
                    current_time - timedelta(days=self._retention_days)
                ).isoformat(),
                max_rows=self._max_rows,
            )
        self._event_buffer.publish(
            "provider",
            {
                "provider": provider,
                "area": area,
                "status": "loading",
                "refresh_id": refresh_id,
            },
        )
        return refresh_id

    def finish(
        self,
        refresh_id: str,
        status: str,
        phase: str,
        *,
        error_code: str | None = None,
    ) -> None:
        current_time = self._now()
        with self._database_manager.unit_of_work() as db:
            provider_area = finish_refresh_record(
                db,
                refresh_id=refresh_id,
                finished_at=current_time.isoformat(),
                phase=phase,
                status=status,
                error_code=error_code,
                now=current_time,
                base_seconds=self._retry_base_seconds,
                max_seconds=self._retry_max_seconds,
            )
            cleanup_refresh_history(
                db,
                cutoff=(
                    current_time - timedelta(days=self._retention_days)
                ).isoformat(),
                max_rows=self._max_rows,
            )
        if provider_area is None:
            return
        provider, area = provider_area
        public_status = {"success": "ready", "partial": "degraded"}.get(status, "error")
        self._event_buffer.publish(
            "provider", {"provider": provider, "area": area, "status": public_status}
        )

    @staticmethod
    def error_code(error: BaseException) -> str:
        reason = str(getattr(error, "reason", "") or "").casefold()
        status = getattr(error, "status", None)
        message = str(getattr(error, "message", "") or "").casefold()
        if status == 429 or "rate" in reason or "rate limit" in message:
            return "rate_limited"
        if (
            status in {401, 403}
            or any(token in reason for token in ("auth", "unauthorized", "forbidden"))
            or any(code in message for code in ("http 401", "http 403"))
        ):
            return "auth_required"
        if status == 400 or "configur" in message or "not_configured" in reason:
            return "invalid_configuration"
        if "network" in reason or isinstance(error, TimeoutError):
            return "network_error"
        return "provider_error"
