"""Stateful orchestration for Garmin's morning Body Battery reading."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Hashable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
)
from backend.db import canonical_store, garmin_store
from backend.performance import morning_battery
from backend.providers.garmin_morning import latest_garmin_record, morning_sleep_element
from backend.runtime.ports import ObservationReader, SleepPeriodReader
from backend.weather import history as weather_history

MORNING_RETRY_SECONDS = 15 * 60
MORNING_MAX_ATTEMPTS = 3
MORNING_LOCK_POLL_SECONDS = 1

MORNING_BATTERY_HISTORY_KEY = "morning_body_battery_history"
MORNING_SOURCES = frozenset({"body_battery", "sleep"})
_GARMIN_ERROR_KEY = "last_garmin_error"
# The morning record's values are stored as local derived observations
# (#1686); the Garmin state view keeps only the refresh bookkeeping.
METHOD_ID = "morning_body_battery"
METHOD_VERSION = 1
_DERIVED_LABEL = "Garmin Connect (abgeleitet)"
_VALUE_KINDS = {
    "before_sleep": MetricKind.BODY_BATTERY_BEFORE_SLEEP,
    "morning": MetricKind.MORNING_BODY_BATTERY,
}
_SLEEP_KEYS = ("sleep_start_at", "sleep_end_at")
_VALUE_KEYS = (*_VALUE_KINDS, *_SLEEP_KEYS)


class GarminSnapshotSink(Protocol):
    """Stores refreshed Garmin sections and state on the given connection."""

    def write_refresh(
        self,
        db: Any,
        *,
        fetched_at: str,
        sections: Mapping[str, Any],
        view: Mapping[str, Any],
        windows: Mapping[str, tuple[date, date]],
        allowed: frozenset[str],
    ) -> object: ...


class MorningCanonicalReader(SleepPeriodReader, ObservationReader, Protocol):
    """Reads the canonical sleep periods and Body Battery levels just stored."""


class MorningBatteryStore:
    """Own the morning Garmin reading, morning history, and Body Battery error state.

    With a ``canonical`` reader the refresh stores the night's sleep record next to
    the Body Battery samples and derives the morning record from the canonical
    NIGHT period and BODY_BATTERY levels inside the same unit of work; without one
    the record computed from the fetched payloads is stored.
    """

    def __init__(
        self,
        manager: Any,
        key_values: Any,
        garmin_snapshots: GarminSnapshotSink,
        canonical: MorningCanonicalReader | None = None,
    ) -> None:
        self._manager = manager
        self._key_values = key_values
        self._garmin_snapshots = garmin_snapshots
        self._canonical = canonical

    def current(self) -> dict[str, Any] | None:
        with self._manager.reader() as db:
            return self.current_in(db)

    @staticmethod
    def current_in(db: Any) -> dict[str, Any] | None:
        """The morning record: the view's bookkeeping with the derived values.

        A record stored before the values became observations keeps its inline
        values until the next refresh of its night.
        """
        view = garmin_store.read_state(db).get("morning_body_battery")
        if not isinstance(view, dict):
            return None
        night = str(view.get("sleep_date") or "")
        rows = canonical_store.derived_observation_rows(
            db, METHOD_ID, owners=[_night_owner(night)]
        )
        if not rows:
            # A night without values; a record stored before #1686 keeps its own.
            return {**dict.fromkeys(_VALUE_KINDS), **view}
        record = {key: value for key, value in view.items() if key not in _VALUE_KEYS}
        for name, kind in _VALUE_KINDS.items():
            row = next((item for item in rows if item["metric"] == kind.value), None)
            record[name] = (
                None
                if row is None
                else {"observed_at": row["observed_at"], "value": round(row["value"])}
            )
            if row is not None:
                for key in _SLEEP_KEYS:
                    if row["derivation"].get(key):
                        record[key] = row["derivation"][key]
        return record

    def persist(
        self,
        checkin_date: date,
        existing: dict[str, Any] | None,
        record: dict[str, Any],
        records: Any,
        sleep_payload: Any = None,
    ) -> dict[str, Any]:
        record["attempts"] = _attempts(existing, checkin_date)
        sections: dict[str, Any] = (
            {"body_battery": records} if isinstance(records, list) else {}
        )
        night = morning_sleep_element(checkin_date, sleep_payload)
        if self._canonical is not None and night is not None:
            sections["sleep"] = [night]
        with self._manager.unit_of_work() as db:
            fetched_at = datetime.now(UTC).isoformat()
            if self._canonical is not None and not record.get("error"):
                # Store the night and the levels first, then read them back.
                self._garmin_snapshots.write_refresh(
                    db,
                    fetched_at=fetched_at,
                    sections=sections,
                    view={},
                    windows={},
                    allowed=MORNING_SOURCES,
                )
                sections = {}
                attempts, attempted_at = record["attempts"], record["attempted_at"]
                record.clear()
                record.update(
                    self._canonical_record(
                        self._canonical, db, checkin_date, attempted_at=attempted_at
                    ),
                    attempts=attempts,
                )
            view = record
            if self._canonical is not None and not record.get("error"):
                _store_values(db, checkin_date, record, now=fetched_at)
                view = {k: v for k, v in record.items() if k not in _VALUE_KEYS}
            self._garmin_snapshots.write_refresh(
                db,
                fetched_at=fetched_at,
                sections=sections,
                view={"morning_body_battery": view},
                windows={},
                allowed=MORNING_SOURCES,
            )
            history = weather_history.decode_history(
                self._key_values.get(db, MORNING_BATTERY_HISTORY_KEY)
            )
            for saved in (existing, record):
                _remember_ready(history, saved)
            self._key_values.set(db, MORNING_BATTERY_HISTORY_KEY, json.dumps(history))

        self.clear_body_battery_errors()
        return {
            "status": record["status"],
            "sleep_date": record["sleep_date"],
            "records": len(records) if isinstance(records, list) else 0,
        }

    @staticmethod
    def _canonical_record(
        reader: MorningCanonicalReader,
        db: Any,
        checkin_date: date,
        *,
        attempted_at: str,
    ) -> dict[str, Any]:
        return morning_battery.canonical_morning_record(
            checkin_date,
            reader.sleep_periods(
                db,
                start=checkin_date - timedelta(days=1),
                end=checkin_date + timedelta(days=1),
            ),
            reader.observations(
                db,
                MetricKind.BODY_BATTERY,
                start=checkin_date - timedelta(days=2),
                end=checkin_date + timedelta(days=1),
            ),
            attempted_at=attempted_at,
        )

    def clear_body_battery_errors(self) -> None:
        with self._manager.unit_of_work() as db:
            try:
                errors = json.loads(self._key_values.get(db, _GARMIN_ERROR_KEY) or "[]")
            except TypeError, ValueError:
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


def _night_owner(sleep_date: str) -> str:
    return f"night:{sleep_date}"


def _store_values(
    db: Any, checkin_date: date, record: Mapping[str, Any], *, now: str
) -> None:
    """Store the night's before-sleep and morning levels as derived observations.

    Each observation is dated on the night (``sleep_date``) at its sample time and
    owned by the night, so a refresh that picks another sample, or none, retires
    the night's earlier rows.
    """
    owner = _night_owner(checkin_date.isoformat())
    derivation = {key: record[key] for key in _SLEEP_KEYS if record.get(key)}
    fingerprint = hashlib.sha256(
        json.dumps(
            {key: record.get(key) for key in _VALUE_KEYS}, sort_keys=True
        ).encode("utf-8")
    ).hexdigest()
    keep: set[str] = set()
    for name, kind in _VALUE_KINDS.items():
        sample = record.get(name)
        if not isinstance(sample, Mapping):
            continue
        observation = Observation(
            kind=kind,
            value=MetricValue(float(sample["value"]), kind.unit),
            observed_on=checkin_date,
            observed_at=datetime.fromisoformat(str(sample["observed_at"])),
            provenance=Provenance(
                provider=None,
                source_kind=SourceKind.DERIVED,
                source_record_id=owner,
                recorded_by=RecordingOrigin.GARMIN,
                retrieved_at=None,
                label=_DERIVED_LABEL,
            ),
            method=METHOD_ID,
            method_version=METHOD_VERSION,
            input_fingerprint=fingerprint,
        )
        keep.add(canonical_store.observation_natural_key(observation))
        canonical_store.upsert_observation(
            db,
            observation,
            mapper_version=METHOD_VERSION,
            now=now,
            owner=owner,
            derivation=derivation,
        )
    canonical_store.retire_owner_derived_observations(
        db, METHOD_ID, owner, keep=keep, now=now
    )


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
                {"dailySleepDTO": latest_garmin_record(payload.get("sleep"))},
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
    def shared_lock(
        self, cancel_event: threading.Event | None = None
    ) -> Iterator[bool]:
        """Wait for the shared lock; a set ``cancel_event`` stops the wait."""
        if cancel_event is None:
            acquired = self._lock.acquire(timeout=self._wait_seconds)
        else:
            acquired = False
            remaining = float(self._wait_seconds)
            while not acquired and remaining > 0 and not cancel_event.is_set():
                step = min(MORNING_LOCK_POLL_SECONDS, remaining)
                acquired = self._lock.acquire(timeout=step)
                remaining -= step
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
            return now.replace(tzinfo=UTC)
        return now.astimezone(UTC)


@dataclass(frozen=True)
class MorningBatteryRetryPolicy:
    max_attempts: int = MORNING_MAX_ATTEMPTS
    retry_seconds: int = MORNING_RETRY_SECONDS


class MorningBatteryEvents:
    """Own sanitized provider state events and refresh warning logs."""

    def __init__(
        self, publish_event: Callable[[str, dict[str, Any]], None], logger: Any
    ):
        self._publish_event = publish_event
        self._logger = logger

    def provider_updated(self, record: dict[str, Any]) -> None:
        self._publish_event(
            "provider",
            {
                "provider": ProviderId.GARMIN,
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

    def sync(
        self, checkin_date: date, cancel_event: threading.Event | None = None
    ) -> dict[str, Any]:
        """Return a cached result or fetch and persist this sleep window.

        A set ``cancel_event`` stops the wait for the shared lock and skips the
        provider request; the result is then ``cancelled``.
        """
        with self._execution_gate.operation():
            existing = self.current()
            cached = self._cached_result(existing, checkin_date)
            if cached:
                return cached
            with self._execution_gate.shared_lock(cancel_event) as acquired:
                if cancel_event is not None and cancel_event.is_set():
                    return {
                        "status": "cancelled",
                        "sleep_date": checkin_date.isoformat(),
                    }
                if not acquired:
                    return {
                        "status": "already_running",
                        "sleep_date": checkin_date.isoformat(),
                    }
                return self._sync_locked(checkin_date)

    def refresh(
        self,
        checkin_date: date | None = None,
        cancel_event: threading.Event | None = None,
    ) -> bool:
        """Refresh optional recovery after 05:00, swallowing refresh failures.

        Returns ``False`` when a due refresh failed, found the reading busy, or
        was cancelled; a refresh that is not due or not configured returns
        ``True``.
        """
        now = self._clock.local_now()
        if checkin_date is None and now.hour < 5:
            return True
        if not (self.source.fixture_available() or self.source.configured()):
            return True
        try:
            result = self.sync(checkin_date or now.date(), cancel_event)
        except Exception as exc:  # noqa: BLE001 - optional refresh failures are logged and swallowed
            self._events.refresh_failed(self.source.safe_provider_error(exc))
            return False
        return not (
            result.get("failed")
            or result.get("status") in {"already_running", "cancelled"}
        )

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
                sleep_payload, records = {}, []

        result = self.store.persist(
            checkin_date, existing, record, records, sleep_payload
        )
        self._events.provider_updated(record)
        if record.get("error"):
            result["failed"] = True
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

    def current(self) -> dict[str, Any] | None:
        """Return the persisted morning record (bookkeeping and derived values)."""
        return self.store.current()

    def current_in(self, db: Any) -> dict[str, Any] | None:
        """The persisted morning record, read inside the caller's transaction."""
        return self.store.current_in(db)


class MorningBodyBatteryServiceCache:
    """Keep morning recovery bound to the active database and config."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._manager: Any = None
        self._config_id: Hashable | None = None
        self._service: MorningBodyBatteryService | None = None

    def get(
        self,
        manager: Any,
        config_id: Hashable,
        store: MorningBatteryStore,
        source: MorningBatterySource,
        execution_gate: MorningBatteryExecutionGate,
        clock: MorningBatteryClock,
        events: MorningBatteryEvents,
        retry_policy: MorningBatteryRetryPolicy,
    ) -> MorningBodyBatteryService:
        with self._lock:
            if (
                self._service is None
                or self._manager is not manager
                or self._config_id != config_id
            ):
                self._service = MorningBodyBatteryService(
                    store, source, execution_gate, clock, events, retry_policy
                )
                self._manager = manager
                self._config_id = config_id
            return self._service


MORNING_BODY_BATTERY_SERVICE_CACHE = MorningBodyBatteryServiceCache()


def _attempts(existing: dict[str, Any] | None, checkin_date: date) -> int:
    """Count this attempt on top of the earlier ones for the same night."""
    if existing is None or existing.get("sleep_date") != checkin_date.isoformat():
        return 1
    return 1 + int(existing.get("attempts") or 1)


def _remember_ready(history: dict[str, Any], saved: Any) -> None:
    if (
        isinstance(saved, dict)
        and saved.get("status") == "ready"
        and saved.get("sleep_date")
    ):
        morning = saved.get("morning")
        history[saved["sleep_date"]] = (
            morning.get("value") if isinstance(morning, dict) else None
        )
