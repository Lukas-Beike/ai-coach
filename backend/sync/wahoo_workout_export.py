"""Wahoo implementation of the workout-library export port.

A local library workout becomes one Wahoo plan. REST transport lives in
``backend.providers.wahoo_client`` and the plan document in
``backend.providers.wahoo_plan_mapping``; this adapter parses the stored workout
text, resolves its sport, and hands both to them. Only the library family is
offered: Wahoo has no calendar events this app writes, so ``library_plan`` is
refused. The client is resolved per remote call, so local serialization never
opens the transport.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date, datetime
from typing import Any

from backend.activities.workout_text import WorkoutTextError, structured_steps
from backend.errors import AppError
from backend.planning.sport import planned_sport_environment
from backend.providers.wahoo_client import WahooClient
from backend.providers.wahoo_plan_mapping import (
    WahooPlanMappingError,
    WahooPlanReferences,
    wahoo_plan,
)
from backend.sync.workout_export import WorkoutExportCapabilities

WAHOO_EXTERNAL_ID_PREFIX = "coach-library-"
_FILENAME_SUFFIX = ".json"


def wahoo_external_id(local_id: str) -> str:
    """Return the id that marks one local library workout as coach-owned at Wahoo."""
    return f"{WAHOO_EXTERNAL_ID_PREFIX}{local_id}"


class WahooWorkoutExport:
    """Export local library workouts as Wahoo plans."""

    capabilities = WorkoutExportCapabilities(library=True)

    def __init__(
        self,
        client_factory: Callable[[], WahooClient],
        *,
        now: Callable[[], datetime],
        references: Callable[[], WahooPlanReferences | None] | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._now = now
        self._references = references

    def serialize_library(self, workout: dict[str, Any]) -> dict[str, Any]:
        """Return ``{external_id, filename, plan}`` or raise a mapping error."""
        local_id = str(workout.get("local_id") or workout.get("id") or "").strip()
        if not local_id:
            raise WahooPlanMappingError("Die Einheit hat keine lokale ID.")
        sport, environment = planned_sport_environment(
            workout.get("type") or workout.get("sport")
        )
        description = str(workout.get("description") or "")
        try:
            steps = structured_steps(description, str(workout.get("target") or "AUTO"))
        except WorkoutTextError as exc:
            raise WahooPlanMappingError(
                "Die Einheit enthält keine gültigen Trainingsschritte für Wahoo."
            ) from exc
        references = self._references() if self._references else None
        plan = wahoo_plan(
            name=str(workout.get("name") or "Coach-Einheit"),
            description=description,
            sport=sport,
            environment=environment,
            steps=steps,
            references=references,
        )
        return {
            "external_id": wahoo_external_id(local_id),
            "filename": f"{wahoo_external_id(local_id)}{_FILENAME_SUFFIX}",
            "plan": plan,
        }

    def library_list(
        self, *, cancel_event: threading.Event | None = None
    ) -> list[dict[str, Any]]:
        del cancel_event
        return [dict(plan) for plan in self._client_factory().list_plans()]

    def library_create(self, payloads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        client = self._client_factory()
        saved: list[dict[str, Any]] = []
        for payload in payloads:
            plan = client.create_plan(
                payload["plan"],
                filename=payload["filename"],
                external_id=payload["external_id"],
                provider_updated_at=self._now(),
            )
            saved.append(_saved_entry(plan))
        return saved

    def library_update(self, remote_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        plan = self._client_factory().update_plan(
            _plan_id(remote_id),
            payload["plan"],
            filename=payload["filename"],
            provider_updated_at=self._now(),
        )
        return {**_saved_entry(plan), "id": str(remote_id)}

    def delete_library(self, remote_id: str) -> None:
        """Delete one plan; a plan that is already gone counts as deleted."""
        try:
            self._client_factory().delete_plan(_plan_id(remote_id))
        except AppError as exc:
            if exc.upstream_status != 404:
                raise

    def library_plan(
        self,
        remote_id: str,
        workout: dict[str, Any],
        plan_date: str,
        *,
        today: date | None = None,
    ) -> dict[str, Any]:
        raise AppError(
            409,
            "Wahoo-Pläne werden nicht im Kalender terminiert.",
            reason="unsupported_export",
        )

    def verify_library_readback(
        self, workout: dict[str, Any], remote: dict[str, Any]
    ) -> None:
        if not str(remote.get("id") or "").strip():
            raise AppError(
                502, "Wahoo hat keine Plan-ID zurückgegeben.", reason="invalid_response"
            )


def _plan_id(remote_id: str) -> int:
    try:
        return int(str(remote_id).strip())
    except ValueError:
        raise AppError(
            400, "Ungültige Wahoo-Plan-ID.", reason="invalid_remote_id"
        ) from None


def _saved_entry(plan: Any) -> dict[str, Any]:
    entry = dict(plan) if isinstance(plan, dict) else {}
    identifier = entry.get("id")
    if isinstance(identifier, bool) or not isinstance(identifier, int | str):
        raise AppError(
            502, "Wahoo hat keine Plan-ID zurückgegeben.", reason="invalid_response"
        )
    entry["id"] = str(identifier)
    return entry
