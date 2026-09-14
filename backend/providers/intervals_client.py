"""Intervals.icu provider client and bounded collection transport."""

from __future__ import annotations

import base64
from collections.abc import Callable
from datetime import date, timedelta
from functools import wraps
import sys
import threading
from typing import Any
from urllib.parse import quote

from backend.config import Config
from backend.providers.intervals import (
    IntervalsReadTransport, IntervalsWriteTransport, fetch_paged_collection,
)


def _app() -> Any:
    # ``python server.py`` registers the entrypoint as ``__main__``. Importing
    # ``server`` here would execute a second application with separate errors,
    # gates and database state. Tests import the entrypoint as ``server`` and
    # use the fallback below.
    active = sys.modules.get("__main__")
    if active is not None and hasattr(active, "initialise_database"):
        return active
    import server
    return server


def provider_operation(function: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(function)
    def wrapped(self: Any, *args: Any, **kwargs: Any) -> Any:
        guarded = _app().intervals_operation(function)
        return guarded(self, *args, **kwargs)
    return wrapped


class IntervalsClient:
    def __init__(self, config: Config, *, request: Callable[..., Any]):
        self.config = config
        request_fn = request
        credentials = base64.b64encode(f"API_KEY:{self.config.intervals_api_key}".encode()).decode()
        self.headers = {"Authorization": f"Basic {credentials}"}
        self.base = "https://intervals.icu/api/v1"
        self._read_transport = IntervalsReadTransport(
            self.base,
            self.headers,
            lambda *args, **kwargs: request_fn(*args, **kwargs),
        )
        self._write_transport = IntervalsWriteTransport(
            self.base,
            self.headers,
            lambda *args, **kwargs: request_fn(*args, **kwargs),
        )
        self.pagination: dict[str, dict[str, Any]] = {}
        self._workout_folder_id: int | None = None

    def get(self, path: str, params: dict[str, Any] | None = None, *, cancel_event: threading.Event | None = None) -> Any:
        return self._read_transport.get(path, params, cancel_event=cancel_event)

    def get_paged_collection(
        self,
        path: str,
        params: dict[str, Any] | None,
        collection: str,
        page_size: int = 500,
        cancel_event: threading.Event | None = None,
    ) -> list[dict[str, Any]]:
        rows, page_metadata = fetch_paged_collection(
            self.get,
            path,
            params,
            collection,
            error=lambda message: _app().AppError(502, message),
            page_size=page_size,
            cancel_event=cancel_event,
        )
        previous = self.pagination.get(collection) or {"pages": 0, "records": 0, "complete": True}
        self.pagination[collection] = {
            "pages": int(previous.get("pages") or 0) + int(page_metadata["pages"]),
            "records": int(previous.get("records") or 0) + int(page_metadata["records"]),
            "complete": bool(previous.get("complete", True)) and bool(page_metadata["complete"]),
        }
        return rows

    @provider_operation
    def post(self, path: str, payload: Any, params: dict[str, Any] | None = None) -> Any:
        return self._write_transport.post(path, payload, params)

    @provider_operation
    def put(self, path: str, payload: Any, params: dict[str, Any] | None = None) -> Any:
        return self._write_transport.put(path, payload, params)

    @provider_operation
    def delete(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._write_transport.delete(path, params)

    def get_workout_library(self, *, cancel_event: threading.Event | None = None) -> list[dict[str, Any]]:
        athlete = quote(self.config.intervals_athlete_id, safe="")
        result = self.get_paged_collection(
            f"/athlete/{athlete}/workouts", {}, "workout_library", cancel_event=cancel_event
        )
        if not isinstance(result, list):
            raise _app().AppError(502, "Intervals.icu hat keine Trainingsbibliothek zurÃ¼ckgegeben.")
        fields = (
            "id", "name", "description", "type", "moving_time", "distance",
            "target", "workout_doc", "icu_training_load", "icu_intensity", "indoor",
            "tags", "folder_id",
        )
        return [_app().selected(item, fields) for item in result if isinstance(item, dict)]

    @staticmethod
    def _folder_id(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            folder_id = int(value)
        except (TypeError, ValueError):
            return None
        return folder_id if folder_id > 0 else None

    def get_or_create_workout_folder(self) -> int:
        """Return the private library folder used for coach-created templates."""
        if self._workout_folder_id is not None:
            return self._workout_folder_id
        athlete = quote(self.config.intervals_athlete_id, safe="")
        folders = self.get(f"/athlete/{athlete}/folders")
        if isinstance(folders, dict):
            folders = folders.get("folders") or folders.get("data") or []
        if not isinstance(folders, list):
            raise _app().AppError(502, "Intervals.icu hat keine gültige Ordnerliste zurückgegeben.")
        matching: list[dict[str, Any]] = []
        pending = [item for item in folders if isinstance(item, dict)]
        while pending:
            folder = pending.pop(0)
            if str(folder.get("name") or "").strip() == _app().APP_NAME:
                matching.append(folder)
            children = folder.get("children")
            if isinstance(children, list):
                pending.extend(item for item in children if isinstance(item, dict))
        for folder in matching:
            folder_id = self._folder_id(folder.get("id"))
            if folder_id is not None:
                self._workout_folder_id = folder_id
                return folder_id
        created = self.post(f"/athlete/{athlete}/folders", {"name": _app().APP_NAME})
        folder_id = self._folder_id(created.get("id") if isinstance(created, dict) else None)
        if folder_id is None:
            raise _app().AppError(502, "Intervals.icu hat keinen gültigen Ordner zurückgegeben.")
        self._workout_folder_id = folder_id
        return folder_id

    def create_library_workouts(self, workouts: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for workout in workouts:
            _app().validate_workout_description(workout)
        athlete = quote(self.config.intervals_athlete_id, safe="")
        folder_id = self.get_or_create_workout_folder()
        created: list[dict[str, Any]] = []
        for workout in workouts:
            payload = {
                "name": str(workout.get("name") or "Coach-Einheit")[:200],
                "description": str(workout.get("description") or "")[:12000],
                "type": _app().intervals_workout_sport(workout.get("type") or workout.get("sport")),
                "folder_id": folder_id,
                "target": workout.get("target") or "AUTO",
            }
            result = self.post(f"/athlete/{athlete}/workouts", payload)
            if not isinstance(result, dict):
                raise _app().AppError(502, "Intervals.icu hat keine Trainingsbibliotheks-Einheit zurÃ¼ckgegeben.")
            created.append(result)
        return created

    def update_library_workout(self, workout_id: str, workout: dict[str, Any]) -> dict[str, Any]:
        _app().validate_workout_description(workout)
        athlete = quote(self.config.intervals_athlete_id, safe="")
        remote_id = quote(str(workout_id), safe="")
        payload = {
            "name": str(workout.get("name") or "Coach-Einheit")[:200],
            "description": str(workout.get("description") or "")[:12000],
            "type": _app().intervals_workout_sport(workout.get("type") or workout.get("sport")),
            "target": workout.get("target") or "AUTO",
        }
        folder_id = self._folder_id(workout.get("folder_id"))
        # Intervals.icu requires folder_id for workout updates as well as
        # creates. Resolve a missing folder through the private Coach folder.
        payload["folder_id"] = folder_id if folder_id is not None else self.get_or_create_workout_folder()
        result = self.put(f"/athlete/{athlete}/workouts/{remote_id}", payload)
        if not isinstance(result, dict):
            raise _app().AppError(502, "Intervals.icu returned no updated library workout.")
        return result

    def plan_library_workout(self, workout_id: str, workout: dict[str, Any], plan_date: str) -> dict[str, Any]:
        athlete = quote(self.config.intervals_athlete_id, safe="")
        payload = _app().workout_event_payload(f"library-{workout_id}-{plan_date}", {
            "date": plan_date,
            "sport": workout.get("type") or workout.get("sport") or "Ride",
            "name": workout.get("name") or "Bibliotheks-Einheit",
            "description": workout.get("description") or "",
            "duration_minutes": workout.get("duration_minutes") or max(5, round(float(workout.get("moving_time") or 3600) / 60)),
            "target": workout.get("target") or "AUTO",
        })
        result = self.post(f"/athlete/{athlete}/events/bulk", [payload], {"upsert": "true"})
        if not isinstance(result, list) or not result:
            raise _app().AppError(502, "Intervals.icu hat keine geplante Einheit zurÃ¼ckgegeben.")
        _app().validate_intervals_workout_result(workout, result[0])
        return result[0]

    def fetch_snapshot(
        self,
        activity_days: int = 42,
        end_date: date | None = None,
        cancel_event: threading.Event | None = None,
    ) -> dict[str, Any]:
        athlete = quote(self.config.intervals_athlete_id, safe="")
        today = end_date or _app().local_now().date()
        calendar_start = today - timedelta(days=_app().PLANNED_CALENDAR_HISTORY_DAYS)
        calendar_end = today + timedelta(days=_app().PLANNED_CALENDAR_FUTURE_DAYS)
        existing = _app().latest_snapshot() or {}
        incremental = bool(existing) and activity_days != _app().ALL_SYNC_DAYS
        request_days = activity_days
        activities: list[Any] = []
        wellness: list[Any] = []
        for window_start, window_end in _app().sync_date_windows(request_days, today):
            _app()._raise_chat_cancelled(cancel_event)
            range_params = {"oldest": window_start.isoformat(), "newest": window_end.isoformat()}
            activities.extend(self.get_paged_collection(f"/athlete/{athlete}/activities", range_params, "activities", cancel_event=cancel_event))
            wellness.extend(self.get_paged_collection(f"/athlete/{athlete}/wellness", range_params, "wellness", cancel_event=cancel_event))
        activities = _app().deduplicate_api_records(activities)
        wellness = _app().deduplicate_api_records(wellness)
        _app()._raise_chat_cancelled(cancel_event)
        events = self.get_paged_collection(
            f"/athlete/{athlete}/events",
            {"oldest": calendar_start.isoformat(), "newest": calendar_end.isoformat()},
            "events",
            cancel_event=cancel_event,
        )
        _app()._raise_chat_cancelled(cancel_event)
        athlete_kwargs = {"cancel_event": cancel_event} if cancel_event is not None else {}
        athlete_data = self.get(f"/athlete/{athlete}", **athlete_kwargs)
        incoming = _app().compact_snapshot(athlete_data, activities, wellness, events, history_days=request_days)
        # Keep the complete provider collections in the durable snapshot. The
        # compact fields above are the read model; Coach projection is the only
        # layer allowed to reduce them for prompt size.
        incoming["raw_provider_data"] = {
            "athlete": athlete_data if isinstance(athlete_data, dict) else {},
            "activities": activities,
            "wellness": wellness,
            "upcoming_calendar": events,
        }
        incoming["provider_sync"] = {
            "pagination": self.pagination,
            "calendar_window": {"start": calendar_start.isoformat(), "end": calendar_end.isoformat()},
        }
        if not incremental:
            return incoming
        merged = dict(incoming)
        merged["recent_activities"] = _app().deduplicate_api_records(incoming["recent_activities"] + existing.get("recent_activities", []))[:500]
        merged["recent_wellness"] = _app().deduplicate_api_records(incoming["recent_wellness"] + existing.get("recent_wellness", []))[-(max(42, activity_days) + 1):]
        previous_raw = existing.get("raw_provider_data") if isinstance(existing.get("raw_provider_data"), dict) else {}
        merged["raw_provider_data"] = {
            "athlete": incoming["raw_provider_data"]["athlete"],
            "activities": _app().deduplicate_api_records(incoming["raw_provider_data"]["activities"] + (previous_raw.get("activities") or [])),
            "wellness": _app().deduplicate_api_records(incoming["raw_provider_data"]["wellness"] + (previous_raw.get("wellness") or [])),
            "upcoming_calendar": incoming["raw_provider_data"]["upcoming_calendar"],
        }
        merged["incremental"] = True
        merged["incremental_window_days"] = request_days
        return merged

    def fetch_competition_events(self) -> list[dict[str, Any]]:
        """Fetch a broad calendar range for target-event synchronization."""
        athlete = quote(self.config.intervals_athlete_id, safe="")
        today = _app().local_now().date()
        result = self.get_paged_collection(
            f"/athlete/{athlete}/events",
            {
                "oldest": (today - timedelta(days=365)).isoformat(),
                "newest": (today + timedelta(days=730)).isoformat(),
            },
            "competition_events",
        )
        if not isinstance(result, list):
            raise _app().AppError(502, "Intervals.icu hat keine Kalenderevents zurückgegeben.")
        return [event for event in result if isinstance(event, dict)]

    def upsert_competition_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not events:
            return []
        athlete = quote(self.config.intervals_athlete_id, safe="")
        result = self.post(f"/athlete/{athlete}/events/bulk", events, {"upsert": "true"})
        if not isinstance(result, list):
            raise _app().AppError(502, "Intervals.icu hat keine Zielwettkämpfe zurückgegeben.")
        return [event for event in result if isinstance(event, dict)]

    def upsert_calendar_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Upsert explicitly approved non-workout calendar events."""
        if not events:
            return []
        athlete = quote(self.config.intervals_athlete_id, safe="")
        result = self.post(f"/athlete/{athlete}/events/bulk", events, {"upsert": "true"})
        if not isinstance(result, list):
            raise _app().AppError(502, "Intervals.icu hat keine Kalendereinträge zurückgegeben.")
        return [event for event in result if isinstance(event, dict)]

    def bulk_delete_events(self, identifiers: list[dict[str, str]]) -> Any:
        athlete = quote(self.config.intervals_athlete_id, safe="")
        return self.put(f"/athlete/{athlete}/events/bulk-delete", identifiers)

    def fetch_performance_snapshot(self, existing_snapshot: dict[str, Any] | None) -> dict[str, Any]:
        """Refresh athlete settings and wellness only; do not request activities or calendar events."""
        athlete = quote(self.config.intervals_athlete_id, safe="")
        today = _app().local_now().date()
        wellness_start = today - timedelta(days=90)
        athlete_data = self.get(f"/athlete/{athlete}")
        wellness = self.get_paged_collection(
            f"/athlete/{athlete}/wellness",
            {"oldest": wellness_start.isoformat(), "newest": today.isoformat()},
            "performance_wellness",
        )
        existing_snapshot = existing_snapshot if isinstance(existing_snapshot, dict) else {}
        snapshot = _app().compact_snapshot(
            athlete_data,
            existing_snapshot.get("recent_activities", []),
            wellness,
            existing_snapshot.get("upcoming_calendar", []),
            history_days=90,
        )
        snapshot["provider_sync"] = {"pagination": self.pagination}
        snapshot["raw_provider_data"] = {"athlete": athlete_data, "wellness": wellness}
        return snapshot

    def delete_event(self, event_id: str) -> Any:
        athlete = quote(self.config.intervals_athlete_id, safe="")
        return self.delete(f"/athlete/{athlete}/events/{quote(event_id, safe='')}")

    def delete_activity(self, activity_id: str) -> Any:
        return self.delete(f"/activity/{quote(activity_id, safe='')}")
