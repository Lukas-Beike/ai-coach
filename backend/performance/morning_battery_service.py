"""Stateful orchestration for Garmin's morning Body Battery reading."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, timezone
from typing import Any

from backend.performance import garmin_projection, morning_battery
from backend.providers.garmin_morning import merge_garmin_records
from backend.weather import history as weather_history

MORNING_BATTERY_HISTORY_KEY = "morning_body_battery_history"
_GARMIN_SNAPSHOT_KEY = "garmin_snapshot"
_GARMIN_ERROR_KEY = "last_garmin_error"


class MorningBodyBatteryService:
    """Coordinate one morning reading while leaving state ownership injected."""

    def __init__(
        self,
        *,
        manager: Any,
        key_values: Any,
        fixture_loader: Any,
        remote_configured: Callable[[], bool],
        fetch_remote: Callable[[date], tuple[Any, Any]],
        lock: Any,
        maintenance_gate: Any,
        provider_gate: Any,
        now: Callable[[], datetime],
        local_now: Callable[[], datetime],
        publish_event: Callable[[str, dict[str, Any]], None],
        safe_error: Callable[[Exception], Any],
        logger: Any,
        lock_wait_seconds: int = 120,
        max_attempts: int = 3,
        retry_seconds: int = 900,
    ) -> None:
        self._manager = manager
        self._key_values = key_values
        self._fixture_loader = fixture_loader
        self._remote_configured = remote_configured
        self._fetch_remote = fetch_remote
        self._lock = lock
        self._maintenance_gate = maintenance_gate
        self._provider_gate = provider_gate
        self._now = now
        self._local_now = local_now
        self._publish_event = publish_event
        self._safe_error = safe_error
        self._logger = logger
        self._lock_wait_seconds = lock_wait_seconds
        self._max_attempts = max_attempts
        self._retry_seconds = retry_seconds

    def sync(self, checkin_date: date) -> dict[str, Any]:
        """Return a cached result or fetch and persist this sleep window."""
        with self._maintenance_gate.operation(), self._provider_gate.operation():
            return self._sync_guarded(checkin_date)

    def _sync_guarded(self, checkin_date: date) -> dict[str, Any]:
        existing = self.current()
        cached = self._cached_result(existing, checkin_date)
        if cached:
            return cached
        if not self._lock.acquire(timeout=self._lock_wait_seconds):
            return {"status": "already_running", "sleep_date": checkin_date.isoformat()}
        try:
            return self._sync_locked(checkin_date)
        finally:
            self._lock.release()

    def refresh(self, checkin_date: date | None = None) -> None:
        """Refresh optional recovery after 05:00, swallowing refresh failures."""
        now = self._local_now()
        if checkin_date is None and now.hour < 5:
            return
        if not (self._fixture_loader.path() is not None or self._remote_configured()):
            return
        try:
            self.sync(checkin_date or now.date())
        except Exception as exc:
            self._logger.warning(
                "Morning Body Battery refresh failed",
                extra={
                    "event": "morning_body_battery_sync_failed",
                    "context": self._safe_error(exc),
                },
                exc_info=True,
            )

    def _sync_locked(self, checkin_date: date) -> dict[str, Any]:
        existing = self.current()
        cached = self._cached_result(existing, checkin_date)
        if cached:
            return cached

        attempted_at = self._utc_now().isoformat()
        if self._fixture_loader.path() is not None:
            fixture = self._fixture_loader.load(2)
            payload = fixture if isinstance(fixture, dict) else {}
            sleep_payload = {
                "dailySleepDTO": garmin_projection.latest_garmin_record(
                    payload.get("sleep")
                )
            }
            record = morning_battery.morning_body_battery_record(
                checkin_date,
                sleep_payload,
                payload.get("body_battery"),
                attempted_at=attempted_at,
            )
            return self._persist(
                checkin_date, existing, record, payload.get("body_battery")
            )

        if not self._remote_configured():
            return {"status": "not_configured", "sleep_date": checkin_date.isoformat()}

        try:
            sleep_payload, records = self._fetch_remote(checkin_date)
            record = morning_battery.morning_body_battery_record(
                checkin_date,
                sleep_payload,
                records,
                attempted_at=attempted_at,
            )
        except Exception as exc:  # noqa: BLE001 - remote failures become saved unavailable results
            record = morning_battery.morning_body_battery_record(
                checkin_date, {}, [], attempted_at=attempted_at
            )
            record["error"] = self._safe_error(exc)
            records = []
        return self._persist(checkin_date, existing, record, records)

    def _persist(
        self,
        checkin_date: date,
        existing: dict[str, Any] | None,
        record: dict[str, Any],
        records: Any,
    ) -> dict[str, Any]:
        same_date = bool(
            existing and existing.get("sleep_date") == checkin_date.isoformat()
        )
        record["attempts"] = 1 + (
            int(existing.get("attempts") or 1) if same_date else 0
        )
        with self._manager.unit_of_work() as db:
            current = self._read_snapshot(db)
            if not isinstance(current, dict):
                current = {}
            if isinstance(records, list):
                current["body_battery"] = merge_garmin_records(
                    records, current.get("body_battery")
                )
            current["morning_body_battery"] = record
            self._key_values.set(
                db,
                _GARMIN_SNAPSHOT_KEY,
                json.dumps(current, ensure_ascii=False, separators=(",", ":")),
            )
            history = weather_history.decode_history(
                self._key_values.get(db, MORNING_BATTERY_HISTORY_KEY)
            )
            for saved in (existing, record):
                if (
                    isinstance(saved, dict)
                    and saved.get("status") == "ready"
                    and saved.get("sleep_date")
                ):
                    morning = saved.get("morning")
                    history[saved["sleep_date"]] = (
                        morning.get("value") if isinstance(morning, dict) else None
                    )
            self._key_values.set(db, MORNING_BATTERY_HISTORY_KEY, json.dumps(history))

        self._clear_body_battery_errors()
        self._publish_event(
            "provider",
            {
                "provider": "garmin",
                "area": "performance",
                "status": "ready" if record["status"] == "ready" else "degraded",
            },
        )
        return {
            "status": record["status"],
            "sleep_date": record["sleep_date"],
            "records": len(records) if isinstance(records, list) else 0,
        }

    def _clear_body_battery_errors(self) -> None:
        with self._manager.unit_of_work() as db:
            try:
                errors = json.loads(self._key_values.get(db, _GARMIN_ERROR_KEY) or "[]")
            except (TypeError, ValueError):
                errors = []
            retained = (
                [
                    entry
                    for entry in errors
                    if isinstance(entry, dict) and entry.get("source") != "body_battery"
                ]
                if isinstance(errors, list)
                else []
            )
            value = (
                json.dumps(retained, ensure_ascii=False, separators=(",", ":"))
                if retained
                else ""
            )
            self._key_values.set(db, _GARMIN_ERROR_KEY, value)

    def _cached_result(
        self, existing: dict[str, Any] | None, checkin_date: date
    ) -> dict[str, Any] | None:
        return morning_battery.cached_result(
            existing,
            checkin_date,
            now=self._utc_now(),
            max_attempts=self._max_attempts,
            retry_seconds=self._retry_seconds,
        )

    def _existing_record(self, snapshot: Any) -> dict[str, Any] | None:
        value = (
            snapshot.get("morning_body_battery") if isinstance(snapshot, dict) else None
        )
        return value if isinstance(value, dict) else None

    def current(self, snapshot: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Return the persisted morning record from an explicit or current snapshot."""
        return self._existing_record(
            self._read_snapshot(None) if snapshot is None else snapshot
        )

    def _read_snapshot(self, db: Any | None) -> dict[str, Any]:
        if db is None:
            with self._manager.unit_of_work() as owned:
                return self._read_snapshot(owned)
        try:
            value = json.loads(self._key_values.get(db, _GARMIN_SNAPSHOT_KEY) or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def _utc_now(self) -> datetime:
        now = self._now()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)
