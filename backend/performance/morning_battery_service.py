"""Stateful orchestration for Garmin's morning Body Battery reading."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Protocol

from backend.performance import garmin_projection, morning_battery
from backend.providers.garmin_morning import merge_garmin_records
from backend.weather import history as weather_history

MORNING_RETRY_SECONDS = 15 * 60
MORNING_MAX_ATTEMPTS = 3

MORNING_BATTERY_HISTORY_KEY = "morning_body_battery_history"
_GARMIN_SNAPSHOT_KEY = "garmin_snapshot"
_GARMIN_ERROR_KEY = "last_garmin_error"


class MorningBatteryStore:
    """Own Garmin snapshot, morning history, and Body Battery error state."""

    def __init__(self, manager: Any, key_values: Any) -> None:
        self._manager = manager
        self._key_values = key_values

    def current(self) -> dict[str, Any] | None:
        value = self._read_snapshot().get("morning_body_battery")
        return value if isinstance(value, dict) else None

    def persist(
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

        self.clear_body_battery_errors()
        return {
            "status": record["status"],
            "sleep_date": record["sleep_date"],
            "records": len(records) if isinstance(records, list) else 0,
        }

    def clear_body_battery_errors(self) -> None:
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

    def _read_snapshot(self, db: Any | None = None) -> dict[str, Any]:
        if db is None:
            with self._manager.unit_of_work() as owned:
                return self._read_snapshot(owned)
        try:
            value = json.loads(self._key_values.get(db, _GARMIN_SNAPSHOT_KEY) or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}


class MorningBatteryRemoteSource(Protocol):
    """Expose configured Garmin reads to the morning recovery workflow."""

    def configured(self) -> bool: ...

    def fetch(self, checkin_date: date) -> tuple[Any, Any]: ...


class MorningBatterySource:
    """Own fixture and Garmin reads, including safe provider error rendering."""

    def __init__(
        self,
        fixture_loader: Any,
        remote_reader: MorningBatteryRemoteSource,
        safe_error: Callable[[Exception], Any],
    ) -> None:
        self._fixture_loader = fixture_loader
        self._remote_reader = remote_reader
        self._safe_error = safe_error

    def fixture_available(self) -> bool:
        return self._fixture_loader.path() is not None

    def configured(self) -> bool:
        return self._remote_reader.configured()

    def fetch(self, checkin_date: date) -> tuple[Any, Any]:
        if self.fixture_available():
            payload = self._fixture_loader.load(2)
            payload = payload if isinstance(payload, dict) else {}
            return (
                {
                    "dailySleepDTO": garmin_projection.latest_garmin_record(
                        payload.get("sleep")
                    )
                },
                payload.get("body_battery"),
            )
        return self.fetch_remote(checkin_date)

    def fetch_remote(self, checkin_date: date) -> tuple[Any, Any]:
        return self._remote_reader.fetch(checkin_date)

    def safe_provider_error(self, error: Exception) -> Any:
        return self._safe_error(error)


class MorningBatteryExecutionGate:
    """Keep maintenance, provider, then shared-lock execution ordering together."""

    def __init__(
        self, lock: Any, maintenance_gate: Any, provider_gate: Any, wait_seconds: int
    ) -> None:
        self._lock = lock
        self._maintenance_gate = maintenance_gate
        self._provider_gate = provider_gate
        self._wait_seconds = wait_seconds

    @contextmanager
    def operation(self) -> Iterator[None]:
        with self._maintenance_gate.operation(), self._provider_gate.operation():
            yield

    @contextmanager
    def shared_lock(self) -> Iterator[bool]:
        acquired = self._lock.acquire(timeout=self._wait_seconds)
        try:
            yield acquired
        finally:
            if acquired:
                self._lock.release()


@dataclass(frozen=True)
class MorningBatteryClock:
    utc_now: Callable[[], datetime]
    local_now: Callable[[], datetime]

    def normalized_utc_now(self) -> datetime:
        now = self.utc_now()
        if now.tzinfo is None:
            return now.replace(tzinfo=timezone.utc)
        return now.astimezone(timezone.utc)


@dataclass(frozen=True)
class MorningBatteryRetryPolicy:
    max_attempts: int = MORNING_MAX_ATTEMPTS
    retry_seconds: int = MORNING_RETRY_SECONDS


class MorningBatteryEvents:
    """Own sanitized provider state events and refresh warning logs."""

    def __init__(self, publish_event: Callable[[str, dict[str, Any]], None], logger: Any):
        self._publish_event = publish_event
        self._logger = logger

    def provider_updated(self, record: dict[str, Any]) -> None:
        self._publish_event(
            "provider",
            {
                "provider": "garmin",
                "area": "performance",
                "status": "ready" if record["status"] == "ready" else "degraded",
            },
        )

    def refresh_failed(self, safe_error: Any) -> None:
        self._logger.warning(
            "Morning Body Battery refresh failed",
            extra={
                "event": "morning_body_battery_sync_failed",
                "context": safe_error,
            },
            exc_info=True,  # noqa: LOG014 - called from the refresh exception handler
        )


class MorningBodyBatteryService:
    """Coordinate one morning reading while leaving state ownership injected."""

    def __init__(
        self,
        store: MorningBatteryStore,
        source: MorningBatterySource,
        execution_gate: MorningBatteryExecutionGate,
        clock: MorningBatteryClock,
        events: MorningBatteryEvents,
        retry_policy: MorningBatteryRetryPolicy,
    ) -> None:
        self.store = store
        self.source = source
        self._execution_gate = execution_gate
        self._clock = clock
        self._events = events
        self._retry_policy = retry_policy

    def sync(self, checkin_date: date) -> dict[str, Any]:
        """Return a cached result or fetch and persist this sleep window."""
        with self._execution_gate.operation():
            existing = self.current()
            cached = self._cached_result(existing, checkin_date)
            if cached:
                return cached
            with self._execution_gate.shared_lock() as acquired:
                if not acquired:
                    return {"status": "already_running", "sleep_date": checkin_date.isoformat()}
                return self._sync_locked(checkin_date)

    def refresh(self, checkin_date: date | None = None) -> None:
        """Refresh optional recovery after 05:00, swallowing refresh failures."""
        now = self._clock.local_now()
        if checkin_date is None and now.hour < 5:
            return
        if not (self.source.fixture_available() or self.source.configured()):
            return
        try:
            self.sync(checkin_date or now.date())
        except Exception as exc:  # noqa: BLE001 - optional refresh failures are logged and swallowed
            self._events.refresh_failed(self.source.safe_provider_error(exc))

    def _sync_locked(self, checkin_date: date) -> dict[str, Any]:
        existing = self.current()
        cached = self._cached_result(existing, checkin_date)
        if cached:
            return cached

        attempted_at = self._clock.normalized_utc_now().isoformat()
        if self.source.fixture_available():
            sleep_payload, records = self.source.fetch(checkin_date)
            record = morning_battery.morning_body_battery_record(
                checkin_date,
                sleep_payload,
                records,
                attempted_at=attempted_at,
            )
        elif not self.source.configured():
            return {"status": "not_configured", "sleep_date": checkin_date.isoformat()}
        else:
            try:
                sleep_payload, records = self.source.fetch(checkin_date)
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
                record["error"] = self.source.safe_provider_error(exc)
                records = []

        result = self.store.persist(checkin_date, existing, record, records)
        self._events.provider_updated(record)
        return result

    def _cached_result(
        self, existing: dict[str, Any] | None, checkin_date: date
    ) -> dict[str, Any] | None:
        return morning_battery.cached_result(
            existing,
            checkin_date,
            now=self._clock.normalized_utc_now(),
            max_attempts=self._retry_policy.max_attempts,
            retry_seconds=self._retry_policy.retry_seconds,
        )

    def current(self, snapshot: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Return the persisted morning record from an explicit or current snapshot."""
        if snapshot is None:
            return self.store.current()
        value = snapshot.get("morning_body_battery")
        return value if isinstance(value, dict) else None
