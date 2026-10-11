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

from backend.planning import workouts as planning_workouts
from backend.providers.intervals_client import IntervalsClient
from backend.sync.workout_export import WorkoutExportCapabilities

INTERVALS_EVENT_CATEGORY = "WORKOUT"
PLANNED_WINDOW_COLLECTION = "repair_workouts"


class IntervalsWorkoutExport:
    capabilities = WorkoutExportCapabilities(planned_events=True)

    def __init__(self, client_factory: Callable[[], IntervalsClient]) -> None:
        self._client_factory = client_factory

    def serialize(
        self, local_id: str, workout: dict[str, Any], *, today: date
    ) -> dict[str, Any]:
        return planning_workouts.workout_event_payload(local_id, workout, today=today)

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
