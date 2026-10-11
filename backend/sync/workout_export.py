"""Provider-neutral outbound port for explicitly approved workout exports.

A port describes what one export target can do with local planned units. It
never decides when a remote write happens: ``upsert`` and ``delete`` are only
reached from use cases that already require an explicit user or API action,
such as the planned-calendar sync and repair services.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, runtime_checkable


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

    def serialize(
        self, local_id: str, workout: dict[str, Any], *, today: date
    ) -> dict[str, Any]:
        """Render one local planned unit as the target's event payload.

        Pure local work: it must not touch the remote target.
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
