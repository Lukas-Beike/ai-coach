"""Authenticated local athlete PUT routes."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from time import monotonic
from typing import Any

from backend.athlete.context import AthleteContextService
from backend.athlete.profile import ProfileService


class AthletePutRoutes:
    """Dispatch athlete writes through their existing domain services."""

    def __init__(
        self,
        athlete_context_service: Callable[[], AthleteContextService],
        profile_service: Callable[[], ProfileService],
        database_lock: Any | None = None,
        zone_service: Callable[[], Any] | None = None,
        body_export: Callable[[dict[str, str], str | None, float], str] | None = None,
    ) -> None:
        self._athlete_context_service = athlete_context_service
        self._profile_service = profile_service
        self._database_lock = database_lock
        self._zone_service = zone_service
        self._body_export = body_export

    def handle(self, handler: Any, path: str) -> bool:
        if path in {"/api/zones", "/api/zones/remove"}:
            return self._handle_zones(handler, path)
        if path not in {"/api/athlete-context", "/api/profile"}:
            return False

        deadline = monotonic() + 10.0
        payload = handler.read_json()
        context = (
            self._athlete_context_service() if path == "/api/athlete-context" else None
        )
        profile = (
            context.profile_service if context is not None else self._profile_service()
        )
        before = None
        retry_export = False
        revision = None
        with profile.mutation_coordinator, self._database_lock or nullcontext():
            if context is not None:
                result = context.save(
                    payload.get("profile"), payload.get("competitions")
                )
            else:
                opted_in = (
                    isinstance(payload, dict)
                    and payload.get("sync_body_to_garmin") is True
                )
                retry_export = opted_in and payload.get("retry_body_to_garmin") is True
                changes = (
                    {
                        k: v
                        for k, v in payload.items()
                        if k not in {"sync_body_to_garmin", "retry_body_to_garmin"}
                    }
                    if isinstance(payload, dict)
                    else payload
                )
                before = profile.get() if opted_in and self._body_export else None
                result = profile.patch(changes)
                if before is not None:
                    revision = profile.revision()

        if (
            self._body_export is not None
            and before is not None
            and (
                retry_export
                or any(
                    before.get(k) != result.get(k)
                    for k in ("weight_kg", "body_fat_pct")
                )
            )
        ):
            try:
                status = self._body_export(result, revision, deadline)
            except Exception:  # noqa: BLE001 - local profile was already committed
                status = "uncertain"
            result = {**result, "garmin_body_export": status}
        elif before is not None:
            result = {**result, "garmin_body_export": "unchanged"}
        handler.send_json(200, result)
        return True

    def _handle_zones(self, handler: Any, path: str) -> bool:
        """Save one local zone configuration or remove one after confirmation."""
        if self._zone_service is None:
            return False
        payload = handler.read_json()
        with self._database_lock or nullcontext():
            service = self._zone_service()
            result = (
                service.save(payload)
                if path == "/api/zones"
                else service.remove(payload)
            )
        handler.send_json(200, result)
        return True
