"""Authenticated local athlete PUT routes."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import nullcontext
from time import monotonic
from typing import Any

from backend.athlete.profile import ProfileService
from backend.errors import NOT_FOUND_ERROR, AppError
from backend.http_api.route_table import Access, Route, RouteRequest


class AthletePutRoutes:
    """Dispatch athlete writes through their existing domain services."""

    def __init__(
        self,
        profile_service: Callable[[], ProfileService],
        database_lock: Any | None = None,
        zone_service: Callable[[], Any] | None = None,
        body_export: Callable[[dict[str, str], str | None, float], str] | None = None,
    ) -> None:
        self._profile_service = profile_service
        self._database_lock = database_lock
        self._zone_service = zone_service
        self._body_export = body_export

    def routes(self) -> list[Route]:
        routes = [
            Route("PUT", "/api/profile", Access.SESSION_CSRF, self._handle_profile)
        ]
        if self._zone_service is not None:
            routes += [
                Route("PUT", path, Access.SESSION_CSRF, self._handle_zones)
                for path in ("/api/zones", "/api/zones/remove")
            ]
        return routes

    def _handle_profile(self, handler: Any, _request: RouteRequest) -> None:
        deadline = monotonic() + 10.0
        payload = handler.read_json()
        profile = self._profile_service()
        opted_in = (
            isinstance(payload, dict) and payload.get("sync_body_to_garmin") is True
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
        with profile.mutation_coordinator, self._database_lock or nullcontext():
            before = profile.get() if opted_in and self._body_export else None
            result = profile.patch(changes)
            revision = profile.revision() if before is not None else None

        result = self._export_body_if_needed(
            result, before, retry_export, revision, deadline
        )
        handler.send_json(200, result)

    def _export_body_if_needed(
        self,
        result: dict[str, Any],
        before: dict[str, str] | None,
        retry_export: bool,
        revision: str | None,
        deadline: float,
    ) -> dict[str, Any]:
        if before is None:
            return result
        if not self._body_export:
            return {**result, "garmin_body_export": "unchanged"}
        body_changed = any(
            before.get(k) != result.get(k) for k in ("weight_kg", "body_fat_pct")
        )
        if not (retry_export or body_changed):
            return {**result, "garmin_body_export": "unchanged"}
        try:
            status = self._body_export(result, revision, deadline)
        except Exception:  # noqa: BLE001 - local profile was already committed
            status = "uncertain"
        return {**result, "garmin_body_export": status}

    def _handle_zones(self, handler: Any, request: RouteRequest) -> None:
        """Save one local zone configuration or remove one after confirmation."""
        if self._zone_service is None:
            raise AppError(404, NOT_FOUND_ERROR)
        payload = handler.read_json()
        with self._database_lock or nullcontext():
            service = self._zone_service()
            result = (
                service.save(payload)
                if request.path == "/api/zones"
                else service.remove(payload)
            )
        handler.send_json(200, result)
