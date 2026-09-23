"""Dependency-light Garmin snapshot preparation helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from backend.activities.duplicates import (
    deduplicate_api_records,
    garmin_activity_duplicates_intervals,
)
from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository
from backend.errors import AppError
from backend.observability import Redactor
from backend.performance import garmin_observations
from backend.performance.history import append_garmin_performance_history
from backend.performance.max_hr import garmin_activity_max_hr, merge_garmin_max_hr
from backend.providers.garmin_morning import merge_garmin_records
from backend.sync.daily import DailySyncMarkerService
from backend.sync.refresh import sync_job_error_class
from backend.sync.state import SyncStateRepository

GARMIN_CAPABILITY_FAILURE_LIMIT = 3
GARMIN_CAPABILITY_PAUSE_SECONDS = 24 * 60 * 60

GARMIN_COLLECTION_SOURCES = (
    "sleep",
    "hrv",
    "body_battery",
    "activities",
    "daily_stats",
    "resting_hr",
)
GARMIN_METRIC_SOURCES = (
    "heart_rate_zones",
    "readiness",
    "race_predictions",
    "max_metrics",
    "cycling_ftp",
    "running_threshold",
    "weight",
)


def normalize_fixture_sleep_dates(value: Any, today: date) -> Any:
    """Make the latest static sleep record represent the current local night."""
    fixture_dates = _fixture_sleep_dates(value)
    if not fixture_dates:
        return value
    return _shift_fixture_sleep_dates(value, today - max(fixture_dates))


def _fixture_sleep_dates(value: Any) -> list[date]:
    dates: list[date] = []
    if isinstance(value, list):
        for item in value:
            dates.extend(_fixture_sleep_dates(item))
    elif isinstance(value, dict):
        for key, item in value.items():
            if key in ("calendarDate", "summaryDate") and isinstance(item, str):
                try:
                    dates.append(date.fromisoformat(item[:10]))
                except ValueError:
                    pass
            elif isinstance(item, (dict, list)):
                dates.extend(_fixture_sleep_dates(item))
    return dates


def _shift_fixture_sleep_dates(value: Any, shift: timedelta) -> Any:
    if isinstance(value, list):
        return [_shift_fixture_sleep_dates(item, shift) for item in value]
    if not isinstance(value, dict):
        return value
    normalized = {
        key: _shift_fixture_sleep_dates(item, shift) for key, item in value.items()
    }
    for key in ("calendarDate", "summaryDate"):
        raw = normalized.get(key)
        if isinstance(raw, str):
            try:
                normalized[key] = (date.fromisoformat(raw[:10]) + shift).isoformat()
            except ValueError:
                pass
    return normalized


def merge_sources(payload: dict[str, Any], previous: dict[str, Any]) -> None:
    """Retain source-owned freshness and records across partial reads/backfills."""
    freshness = {
        source: dict(details)
        for source, details in (previous.get("source_freshness") or {}).items()
    }
    failed = {
        error.get("source")
        for error in payload.get("errors") or []
        if isinstance(error, dict)
    }
    pagination = (payload.get("provider_sync") or {}).get("pagination") or {}
    for source in (*GARMIN_COLLECTION_SOURCES, *GARMIN_METRIC_SOURCES):
        _merge_garmin_source(payload, previous, freshness, failed, pagination, source)
    payload["source_freshness"] = freshness
    if isinstance(previous.get("morning_body_battery"), dict):
        payload["morning_body_battery"] = previous["morning_body_battery"]
    if previous.get("start") and payload.get("start"):
        payload["start"] = min(str(previous["start"]), str(payload["start"]))


class GarminPayloadService:
    """Read local Garmin state and prepare collected payloads for persistence."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        sync_state_repository: SyncStateRepository,
        local_today: Callable[[], date],
    ) -> None:
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._sync_state_repository = sync_state_repository
        self._local_today = local_today

    def snapshot(self) -> dict[str, Any]:
        with self._database_manager.unit_of_work() as db:
            serialized = self._key_value_repository.get(db, "garmin_snapshot")
        try:
            value = json.loads(serialized or "{}")
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def prepare_fixture(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._prepare(payload, self.snapshot(), fixture=True)

    def prepare_remote(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._prepare(payload, self.snapshot(), fixture=False)

    def _prepare(
        self,
        payload: dict[str, Any],
        previous: dict[str, Any],
        *,
        fixture: bool,
    ) -> dict[str, Any]:
        merge_sources(payload, previous)
        if not fixture:
            payload["activities"] = deduplicate_api_records(
                payload.get("activities", [])
            )
        payload["sport_max_hr"] = merge_garmin_max_hr(
            garmin_activity_max_hr(payload.get("activities")),
            previous.get("sport_max_hr"),
        )
        payload["activity_matches"] = self._activity_matches(payload)
        if fixture:
            payload.setdefault(
                "provider_sync",
                {
                    "pagination": {
                        "fixture": {
                            "windows": 1,
                            "records": len(payload.get("activities") or []),
                            "complete": True,
                        }
                    }
                },
            )
        append_garmin_performance_history(payload, previous, self._local_today())
        return payload

    def _activity_matches(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        canonical = self._sync_state_repository.latest_snapshot() or {}
        intervals = canonical.get("recent_activities") or []
        return [
            {
                "garmin_activity_id": activity.get("activityId") or activity.get("id"),
                "intervals_activity_id": match.get("id"),
            }
            for activity in payload.get("activities") or []
            if isinstance(activity, dict)
            for match in intervals
            if isinstance(match, dict)
            and garmin_activity_duplicates_intervals(activity, [match])
        ]


def _merge_garmin_source(
    payload: dict[str, Any],
    previous: dict[str, Any],
    freshness: dict[str, Any],
    failed: set[Any],
    pagination: dict[str, Any],
    source: str,
) -> None:
    incoming = payload.get(source)
    complete = source not in failed and pagination.get(source, {}).get("complete", True)
    if incoming:
        freshness[source] = {
            "freshness": "current" if complete else "partial",
            "fetched_at": payload["synced_at"],
            "observed_at": garmin_observations.garmin_source_observed_at(incoming),
        }
    elif source in previous:
        freshness[source] = {**freshness.get(source, {}), "freshness": "stale"}
    if source in GARMIN_COLLECTION_SOURCES and (
        source in previous or source in payload
    ):
        payload[source] = merge_garmin_records(incoming, previous.get(source))
    elif not incoming and source in previous:
        payload[source] = previous[source]


def collection_complete(payload: dict[str, Any]) -> bool:
    pagination = payload.get("provider_sync", {}).get("pagination", {})
    return (
        not payload.get("errors")
        and bool(pagination)
        and all(details.get("complete") is True for details in pagination.values())
    )


class GarminSyncStateService:
    """Persist Garmin sync state without depending on application globals."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        key_value_repository: KeyValueRepository,
        sync_state_repository: SyncStateRepository,
        daily_sync_marker_service: DailySyncMarkerService,
        redactor: Redactor,
        utc_now: Callable[[], str],
        current_time: Callable[[], datetime],
    ) -> None:
        self._database_manager = database_manager
        self._key_value_repository = key_value_repository
        self._sync_state_repository = sync_state_repository
        self._daily_sync_marker_service = daily_sync_marker_service
        self._redactor = redactor
        self._utc_now = utc_now
        self._current_time = current_time

    def _get(self, key: str) -> str | None:
        with self._database_manager.unit_of_work() as db:
            return self._key_value_repository.get(db, key)

    def _set(self, key: str, value: str) -> None:
        with self._database_manager.unit_of_work() as db:
            self._key_value_repository.set(db, key, value)

    def persist_error(self, message: Any, source: str = "sync") -> None:
        safe_message = self._redactor.redact_text(
            str(message or "Garmin synchronization failed.")
        )[:1000]
        self._set(
            "last_garmin_error",
            json.dumps(
                [{"source": source, "message": safe_message}], ensure_ascii=False
            ),
        )

    def capability_state(self, source: str) -> dict[str, Any]:
        try:
            value = json.loads(self._get(f"garmin_capability_{source}") or "{}")
        except (TypeError, ValueError):
            value = {}
        return value if isinstance(value, dict) else {}

    def capability_allowed(self, source: str) -> bool:
        state = self.capability_state(source)
        paused_until = str(state.get("paused_until") or "")
        try:
            return (
                datetime.fromisoformat(paused_until.replace("Z", "+00:00"))
                <= self._current_time()
            )
        except (TypeError, ValueError):
            return True

    def record_capability_failure(self, source: str, error: BaseException) -> None:
        state = self.capability_state(source)
        error_class = sync_job_error_class(error)
        if state.get("error_class") != error_class:
            state = {"error_class": error_class, "count": 0}
        count = int(state.get("count") or 0) + 1
        state["count"] = count
        state["last_failed_at"] = self._utc_now()
        if count >= GARMIN_CAPABILITY_FAILURE_LIMIT:
            state["paused_until"] = (
                self._current_time()
                + timedelta(seconds=GARMIN_CAPABILITY_PAUSE_SECONDS)
            ).isoformat()
        self._set(
            f"garmin_capability_{source}",
            json.dumps(state, ensure_ascii=False, separators=(",", ":")),
        )

    def record_capability_success(self, source: str) -> None:
        if self.capability_state(source):
            self._set(f"garmin_capability_{source}", "")

    def error_entries(self) -> list[dict[str, Any]]:
        try:
            errors = json.loads(self._get("last_garmin_error") or "[]")
        except (TypeError, ValueError):
            errors = []
        return (
            [entry for entry in errors if isinstance(entry, dict)]
            if isinstance(errors, list)
            else []
        )

    def core_error_entries(self) -> list[dict[str, Any]]:
        """Return Garmin errors unrelated to the separate morning recovery read."""
        return [
            entry
            for entry in self.error_entries()
            if entry.get("source") != "body_battery"
        ]

    def set_error_entries(self, errors: list[dict[str, Any]]) -> None:
        self._set(
            "last_garmin_error",
            json.dumps(errors, ensure_ascii=False, separators=(",", ":"))
            if errors
            else "",
        )

    def persist_payload(
        self,
        payload: dict[str, Any],
        end_date: date | None,
        fallback_end: date,
        *,
        source: str | None = None,
        historical_cursor: str | None = None,
    ) -> dict[str, Any]:
        synced_at = payload["synced_at"]
        complete = collection_complete(payload)
        self._set(
            "garmin_snapshot",
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        )
        self._set("last_garmin_sync_at", synced_at)
        if end_date is None:
            self._daily_sync_marker_service.mark("garmin")
        self._set(
            "last_garmin_error",
            ""
            if not payload.get("errors")
            else json.dumps(payload["errors"], ensure_ascii=False),
        )
        if complete:
            self._sync_state_repository.update_cursor(
                "garmin",
                "data",
                str(payload.get("end") or fallback_end.isoformat())[:10],
                synced_at,
            )
            if end_date is not None and historical_cursor is not None:
                self._sync_state_repository.update_cursor(
                    "garmin", "historical", historical_cursor, synced_at
                )
        result = {
            "status": "ok" if complete else "partial",
            "synced_at": synced_at,
            "errors": len(payload.get("errors") or []),
            "activities": len(payload.get("activities") or []),
            "pagination": payload["provider_sync"]["pagination"],
        }
        if source is not None:
            result["source"] = source
        return result


class GarminFixtureLoader:
    """Load an explicit local Garmin fixture without accessing global state."""

    def __init__(
        self,
        config: Config,
        root: Path,
        local_now: Callable[[], datetime],
        utc_now: Callable[[], str],
        earliest_date: date,
        all_sync_days: int,
    ) -> None:
        self._config = config
        self._root = root
        self._local_now = local_now
        self._utc_now = utc_now
        self._earliest_date = earliest_date
        self._all_sync_days = all_sync_days

    def path(self) -> Path | None:
        raw = (self._config.garmin_fixture_path or "").strip()
        if not raw:
            return None
        path = Path(raw)
        return path if path.is_absolute() else self._root / path

    def load(self, days: int) -> dict[str, Any]:
        path = self.path()
        if path is None:
            raise AppError(503, "GARMIN_FIXTURE_PATH ist nicht konfiguriert.")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise AppError(503, f"Garmin-Testdatei nicht gefunden: {path}") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise AppError(
                503, f"Garmin-Testdatei konnte nicht gelesen werden: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise AppError(503, "Die Garmin-Testdatei muss ein JSON-Objekt enthalten.")
        today = self._local_now().date()
        start = (
            self._earliest_date
            if days == self._all_sync_days
            else today - timedelta(days=max(1, min(days, 90)) - 1)
        )
        payload = dict(value)
        payload["sleep"] = normalize_fixture_sleep_dates(payload.get("sleep"), today)
        payload.setdefault("start", start.isoformat())
        payload.setdefault("end", today.isoformat())
        payload["synced_at"] = self._utc_now()
        payload.setdefault("errors", [])
        payload["source"] = "fixture"
        return payload
