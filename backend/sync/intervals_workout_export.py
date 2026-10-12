"""Intervals.icu implementation of the planned-event export port.

REST transport lives in ``backend.providers.intervals_client``. This adapter maps
local planned units onto the Intervals event payload and checks saved readback.
The client is resolved per remote call, so local serialization and readback
never open the transport.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Any

from backend.athlete.local_date import iso_date_prefix
from backend.canonical.planned_workout import PlannedWorkoutExport
from backend.planning import workouts as planning_workouts
from backend.providers.intervals_client import IntervalsClient
from backend.providers.intervals_workouts import (
    INTERVALS_EVENT_CATEGORY,
    intervals_event_confirms_schedule,
    intervals_event_external_id,
    intervals_event_identity,
    intervals_event_is_namesake,
    intervals_event_is_paired,
    intervals_event_is_planned,
    intervals_event_payload,
    intervals_event_start_date,
    intervals_external_id,
)
from backend.sync.workout_export import WorkoutExportCapabilities

PLANNED_WINDOW_COLLECTION = "repair_workouts"


class IntervalsWorkoutExport:
    capabilities = WorkoutExportCapabilities(planned_events=True)

    def __init__(self, client_factory: Callable[[], IntervalsClient]) -> None:
        self._client_factory = client_factory

    def serialize(self, local_id: str, export: PlannedWorkoutExport) -> dict[str, Any]:
        return intervals_event_payload(local_id, export)

    def upsert(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self._client_factory().upsert_calendar_events(payloads)

    def delete(self, remote_id: str) -> None:
        self._client_factory().delete_event(remote_id)

    def read_event(self, remote_id: str) -> Any:
        return self._client_factory().get_event(remote_id)

    def list_window(self, *, oldest: str, newest: str) -> list[dict[str, Any]]:
        return self._client_factory().list_events_window(
            oldest=oldest,
            newest=newest,
            category=INTERVALS_EVENT_CATEGORY,
            collection=PLANNED_WINDOW_COLLECTION,
        )

    def verify_readback(self, workout: dict[str, Any], remote: dict[str, Any]) -> None:
        planning_workouts.validate_intervals_workout_result(workout, remote)

    def external_id_for(self, local_id: str) -> str:
        return intervals_external_id(local_id)

    def event_identity(self, event: Any) -> str:
        return intervals_event_identity(event)

    def event_external_id(self, event: Any) -> str:
        return intervals_event_external_id(event)

    def is_unpaired_future_planned(self, event: Any, *, today: date) -> bool:
        return (
            intervals_event_is_planned(event)
            and not intervals_event_is_paired(event)
            and iso_date_prefix(intervals_event_start_date(event)) >= today.isoformat()
        )

    def is_namesake_on_day(self, event: Any, *, day: str, name: Any) -> bool:
        return intervals_event_is_namesake(event, day=day, name=name)

    def confirms_planned_event(self, event: Any, *, day: str, name: Any) -> bool:
        return intervals_event_confirms_schedule(event, day=day, name=name)
