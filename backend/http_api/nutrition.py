"""Authenticated HTTP API routes for nutrition and calorie tracking."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.errors import AppError
from backend.http_api.auth import SessionAuthService
from backend.nutrition.service import NutritionService
from backend.nutrition.sync import IntervalsNutritionSyncService

NUTRITION_ENTRY_PATH = "/api/nutrition/entry"
INVALID_BODY = "Ungültiger Anfrageinhalt."


class NutritionGetRoutes:
    """Handle authenticated nutrition query routes."""

    def __init__(
        self,
        session_auth_service: Callable[[], SessionAuthService],
        nutrition_service: Callable[[], NutritionService],
        local_now: Callable[[], datetime],
    ) -> None:
        self._session_auth_service = session_auth_service
        self._nutrition_service = nutrition_service
        self._local_now = local_now

    def handle(self, handler: Any, path: str) -> bool:
        if path not in {"/api/nutrition/day", "/api/nutrition/range"}:
            return False

        self._session_auth_service().require_auth(handler)
        query = parse_qs(urlparse(handler.path).query)
        svc = self._nutrition_service()

        if path == "/api/nutrition/day":
            date_param = query.get("date", [None])[0] or self._local_now().date().isoformat()
            summary = svc.get_day_summary(date_param)
            handler.send_json(200, {"ok": True, **summary})
            return True

        if path == "/api/nutrition/range":
            today = self._local_now().date().isoformat()
            start_param = query.get("start", [today])[0]
            end_param = query.get("end", [today])[0]
            summaries = svc.get_range_summary(start_param, end_param)
            handler.send_json(200, {"ok": True, "summaries": summaries})
            return True

        return False


class NutritionPostRoutes:
    """Handle authenticated nutrition mutations and synchronization."""

    def __init__(
        self,
        nutrition_service: Callable[[], NutritionService],
        nutrition_sync_service: Callable[[], IntervalsNutritionSyncService] | None = None,
    ) -> None:
        self._nutrition_service = nutrition_service
        self._nutrition_sync_service = nutrition_sync_service

    def handle(self, handler: Any, path: str) -> bool:
        routes = {
            NUTRITION_ENTRY_PATH: self._create,
            f"{NUTRITION_ENTRY_PATH}/delete": self._delete,
            "/api/nutrition/sync": self._sync,
        }
        route = routes.get(path)
        if route is None:
            return False
        route(handler)
        return True

    def _create(self, handler: Any) -> None:
        entry = self._nutrition_service().log_meal(handler.read_json())
        handler.send_json(200, {"ok": True, "entry": entry})

    def _delete(self, handler: Any) -> None:
        payload = _read_object(handler)
        entry_id = payload.get("id") or payload.get("entry_id")
        if not entry_id:
            raise AppError(400, "id ist erforderlich zum Löschen.")
        result = self._nutrition_service().delete_meal(str(entry_id))
        handler.send_json(200, {"ok": True, **result})

    def _sync(self, handler: Any) -> None:
        if not self._nutrition_sync_service:
            raise AppError(400, "Intervals.icu Sync ist nicht verfügbar.")
        payload = _read_object(handler) if handler.headers.get("Content-Length") else {}
        sync_service = self._nutrition_sync_service()
        meal_date = payload.get("date") or payload.get("meal_date")
        result = (
            sync_service.sync_day(meal_date)
            if meal_date
            else sync_service.sync_pending(limit=payload.get("limit") or 14)
        )
        handler.send_json(200, {"ok": True, **result})


class NutritionPutRoutes:
    """Handle authenticated nutrition updates."""

    def __init__(
        self,
        nutrition_service: Callable[[], NutritionService],
    ) -> None:
        self._nutrition_service = nutrition_service

    def handle(self, handler: Any, path: str) -> bool:
        if path != NUTRITION_ENTRY_PATH:
            return False

        payload = _read_object(handler)
        entry_id = payload.get("id") or payload.get("entry_id")
        if not entry_id:
            raise AppError(400, "id ist erforderlich zum Aktualisieren.")
        svc = self._nutrition_service()
        updated = svc.update_meal(str(entry_id), payload)
        handler.send_json(200, {"ok": True, "entry": updated})
        return True


def _read_object(handler: Any) -> dict[str, Any]:
    payload = handler.read_json()
    if not isinstance(payload, dict):
        raise AppError(400, INVALID_BODY)
    return payload
