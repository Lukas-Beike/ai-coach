"""Provider-neutral outbound port for explicitly approved workout exports.

A port describes what one export target can do with local planned units. It
never decides when a remote write happens: ``upsert`` and ``delete`` are only
reached from use cases that already require an explicit user or API action,
such as the planned-calendar sync and repair services.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, runtime_checkable

from backend.canonical.planned_workout import PlannedWorkoutExport


@dataclass(frozen=True)
class WorkoutExportCapabilities:
    planned_events: bool = False
    library: bool = False
    competitions: bool = False


@runtime_checkable
class WorkoutExportPort(Protocol):
    @property
    def capabilities(self) -> WorkoutExportCapabilities:
        """Declare which local record families this target can export."""

    def serialize(self, local_id: str, export: PlannedWorkoutExport) -> dict[str, Any]:
        """Render one provider-neutral planned-workout export as the target's payload.

        Pure local work: it must not touch the remote target. The caller builds
        ``export`` from the local planned unit (see planning.workout_export).
        """

    def upsert(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Write explicitly approved event payloads and return saved events."""

    def delete(self, remote_id: str) -> None:
        """Delete one remote event by its target identity."""

    def read_event(self, remote_id: str) -> Any:
        """Read one remote event; a missing event raises an AppError with 404."""

    def list_window(self, *, oldest: str, newest: str) -> list[dict[str, Any]]:
        """List remote planned events within an inclusive local-date window."""

    def verify_readback(self, workout: dict[str, Any], remote: dict[str, Any]) -> None:
        """Raise an AppError unless the saved remote event matches the local unit."""

    def external_id_for(self, local_id: str) -> str:
        """Return the external id that marks one local planned unit as coach-owned."""

    def event_identity(self, event: Any) -> str:
        """Return one remote event's target identity, or "" when it has none."""

    def event_external_id(self, event: Any) -> str:
        """Return one remote event's external identity, or ""."""

    def is_unpaired_future_planned(self, event: Any, *, today: date) -> bool:
        """Return whether a remote event is a planned unit not yet paired and not past."""

    def is_namesake_on_day(self, event: Any, *, day: str, name: Any) -> bool:
        """Return whether a remote planned event on ``day`` shares the local name."""

    def confirms_planned_event(self, event: Any, *, day: str, name: Any) -> bool:
        """Return whether a saved remote event starts on ``day`` with exactly ``name``."""


@runtime_checkable
class WorkoutLibraryExportPort(Protocol):
    """Target-neutral operations of the explicit workout-library synchronization.

    A target offers this family only when ``capabilities.library`` is set. Like
    the planned-event operations, none of these methods decides when a remote
    write happens: callers reach ``library_create``, ``library_update`` and
    ``library_plan`` only from the athlete's explicit library-sync action.
    """

    @property
    def capabilities(self) -> WorkoutExportCapabilities:
        """Declare which local record families this target can export."""

    def serialize_library(self, workout: dict[str, Any]) -> dict[str, Any]:
        """Render one local library entry as the target's payload (pure local work)."""

    def library_list(
        self, *, cancel_event: threading.Event | None = None
    ) -> list[dict[str, Any]]:
        """Read the target's workout library; ``cancel_event`` aborts the read."""

    def library_create(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Create library entries remotely and return the saved remote entries."""

    def library_update(self, remote_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Update one existing remote library entry and return the saved entry."""

    def library_plan(
        self,
        remote_id: str,
        workout: dict[str, Any],
        plan_date: str,
        *,
        today: date | None = None,
    ) -> dict[str, Any]:
        """Schedule one remote library entry on ``plan_date``; return the saved event.

        ``today`` defaults to the target's own local date.
        """

    def verify_library_readback(
        self, workout: dict[str, Any], remote: dict[str, Any]
    ) -> None:
        """Raise an AppError unless the saved remote entry matches the local entry."""
