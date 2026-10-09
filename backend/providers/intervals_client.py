"""Intervals.icu client wrapping low-level API client with domain operations."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from contextlib import nullcontext
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

from backend.config import Config
from backend.errors import AppError
from backend.providers.intervals import IntervalsApiClient
from backend.runtime.clock import local_now
from backend.runtime.ports import ProviderOperation

APP_NAME = "Intervals Coach"


class IntervalsClient:
    def __init__(
        self,
        config: Config,
        *,
        request: Callable[..., Any],
        now: Callable[[], datetime] | None = None,
        operation: ProviderOperation | None = None,
    ):
        self.config = config
        self._now = now
        self._operation = operation or (lambda: nullcontext())
        self._api = IntervalsApiClient(
            api_key=self.config.intervals_api_key,
            request=lambda *args, **kwargs: request(*args, **kwargs),
        )
        self._workout_folder_id: int | None = None

    def _get_now(self) -> datetime:
        if self._now is not None:
            return self._now()
        return local_now()

    @property
    def pagination(self) -> dict[str, dict[str, Any]]:
        return {
            collection: dict(metadata)
            for collection, metadata in self._api.pagination.items()
        }

    def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        cancel_event: threading.Event | None = None,
    ) -> Any:
        if cancel_event is None:
            return self._api.get(path, params)
        return self._api.get(path, params, cancel_event=cancel_event)

    def get_paged_collection(
        self,
        path: str,
        params: dict[str, Any] | None,
        collection: str,
        page_size: int = 500,
        cancel_event: threading.Event | None = None,
    ) -> list[dict[str, Any]]:
        return self._api.get_paged_collection(
            path,
            params,
            collection,
            page_size=page_size,
            cancel_event=cancel_event,
        )

    def post(
        self, path: str, payload: Any, params: dict[str, Any] | None = None
    ) -> Any:
        with self._operation():
            return self._api.post(path, payload, params)

    def put(self, path: str, payload: Any, params: dict[str, Any] | None = None) -> Any:
        with self._operation():
            return self._api.put(path, payload, params)

    def delete(self, path: str, params: dict[str, Any] | None = None) -> Any:
        with self._operation():
            return self._api.delete(path, params)

    def get_workout_library(
        self, *, cancel_event: threading.Event | None = None
    ) -> list[dict[str, Any]]:
        athlete = quote(self.config.intervals_athlete_id, safe="")
        result = self.get_paged_collection(
            f"/athlete/{athlete}/workouts",
            {},
            "workout_library",
            cancel_event=cancel_event,
        )
        if not isinstance(result, list):
            raise AppError(
                502, "Intervals.icu hat keine Trainingsbibliothek zurückgegeben."
            )
        fields = (
            "id",
            "name",
            "description",
            "type",
            "moving_time",
            "distance",
            "target",
            "workout_doc",
            "icu_training_load",
            "icu_intensity",
            "indoor",
            "tags",
            "folder_id",
        )
        return [
            {key: item[key] for key in fields if key in item and item[key] is not None}
            for item in result
            if isinstance(item, dict)
        ]

    @staticmethod
    def _folder_id(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            folder_id = int(value)
        except TypeError, ValueError:
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
            raise AppError(
                502, "Intervals.icu hat keine gültige Ordnerliste zurückgegeben."
            )
        matching: list[dict[str, Any]] = []
        pending = [item for item in folders if isinstance(item, dict)]
        while pending:
            folder = pending.pop(0)
            if str(folder.get("name") or "").strip() == APP_NAME:
                matching.append(folder)
            children = folder.get("children")
            if isinstance(children, list):
                pending.extend(item for item in children if isinstance(item, dict))
        for folder in matching:
            folder_id = self._folder_id(folder.get("id"))
            if folder_id is not None:
                self._workout_folder_id = folder_id
                return folder_id
        created = self.post(f"/athlete/{athlete}/folders", {"name": APP_NAME})
        folder_id = self._folder_id(
            created.get("id") if isinstance(created, dict) else None
        )
        if folder_id is None:
            raise AppError(
                502, "Intervals.icu hat keinen gültigen Ordner zurückgegeben."
            )
        self._workout_folder_id = folder_id
        return folder_id

    @staticmethod
    def _library_payload(workout: Mapping[str, Any], folder_id: int) -> dict[str, Any]:
        return {
            "name": str(workout["name"]),
            "description": str(workout["description"]),
            "type": str(workout["type"]),
            "folder_id": folder_id,
            "target": str(workout["target"]),
        }

    def create_library_workouts(
        self, workouts: list[Mapping[str, Any]]
    ) -> list[dict[str, Any]]:
        athlete = quote(self.config.intervals_athlete_id, safe="")
        folder_id = self.get_or_create_workout_folder()
        created: list[dict[str, Any]] = []
        for workout in workouts:
            payload = self._library_payload(workout, folder_id)
            result = self.post(f"/athlete/{athlete}/workouts", payload)
            if not isinstance(result, dict):
                raise AppError(
                    502,
                    "Intervals.icu hat keine Trainingsbibliotheks-Einheit zurückgegeben.",
                )
            created.append(result)
        return created

    def update_library_workout(
        self, workout_id: str, workout: Mapping[str, Any]
    ) -> dict[str, Any]:
        athlete = quote(self.config.intervals_athlete_id, safe="")
        remote_id = quote(str(workout_id), safe="")
        folder_id = self._folder_id(workout.get("folder_id"))
        payload = self._library_payload(
            workout,
            folder_id if folder_id is not None else self.get_or_create_workout_folder(),
        )
        result = self.put(f"/athlete/{athlete}/workouts/{remote_id}", payload)
        if not isinstance(result, dict):
            raise AppError(502, "Intervals.icu returned no updated library workout.")
        return result

    def plan_library_workout(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        athlete = quote(self.config.intervals_athlete_id, safe="")
        result = self.post(
            f"/athlete/{athlete}/events/bulk", [dict(payload)], {"upsert": "true"}
        )
        if not isinstance(result, list) or not result:
            raise AppError(
                502, "Intervals.icu hat keine geplante Einheit zurückgegeben."
            )
        return result[0]

    def local_today(self):
        return self._get_now().date()

    def fetch_competition_events(self) -> list[dict[str, Any]]:
        """Fetch a broad calendar range for target-event synchronization."""
        athlete = quote(self.config.intervals_athlete_id, safe="")
        today = self._get_now().date()
        result = self.get_paged_collection(
            f"/athlete/{athlete}/events",
            {
                "oldest": (today - timedelta(days=365)).isoformat(),
                "newest": (today + timedelta(days=730)).isoformat(),
            },
            "competition_events",
        )
        if not isinstance(result, list):
            raise AppError(502, "Intervals.icu hat keine Kalenderevents zurückgegeben.")
        return [event for event in result if isinstance(event, dict)]

    def upsert_competition_events(
        self, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        if not events:
            return []
        athlete = quote(self.config.intervals_athlete_id, safe="")
        result = self.post(
            f"/athlete/{athlete}/events/bulk", events, {"upsert": "true"}
        )
        if not isinstance(result, list):
            raise AppError(502, "Intervals.icu hat keine Zielwettkämpfe zurückgegeben.")
        return [event for event in result if isinstance(event, dict)]

    def upsert_calendar_events(
        self, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Upsert explicitly approved non-workout calendar events."""
        if not events:
            return []
        athlete = quote(self.config.intervals_athlete_id, safe="")
        result = self.post(
            f"/athlete/{athlete}/events/bulk", events, {"upsert": "true"}
        )
        if not isinstance(result, list):
            raise AppError(
                502, "Intervals.icu hat keine Kalendereinträge zurückgegeben."
            )
        return [event for event in result if isinstance(event, dict)]

    def bulk_delete_events(self, identifiers: list[dict[str, str]]) -> Any:
        athlete = quote(self.config.intervals_athlete_id, safe="")
        return self.put(f"/athlete/{athlete}/events/bulk-delete", identifiers)

    def delete_event(self, event_id: str) -> Any:
        athlete = quote(self.config.intervals_athlete_id, safe="")
        return self.delete(f"/athlete/{athlete}/events/{quote(event_id, safe='')}")

    def delete_activity(self, activity_id: str) -> Any:
        return self.delete(f"/activity/{quote(activity_id, safe='')}")
