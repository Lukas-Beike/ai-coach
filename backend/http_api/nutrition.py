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

    def handle(self, handler: Any, path: str, session: dict[str, Any]) -> bool:
        if path not in {
            "/api/nutrition/entry",
            "/api/nutrition/entry/delete",
            "/api/nutrition/sync",
        }:
            return False

        svc = self._nutrition_service()

        if path == "/api/nutrition/entry":
            payload = handler.read_json()
            entry = svc.log_meal(payload)
            handler.send_json(200, {"ok": True, "entry": entry})
            return True

        if path == "/api/nutrition/entry/delete":
            payload = handler.read_json()
            if not isinstance(payload, dict):
                raise AppError(400, "Ungültiger Anfrageinhalt.")
            entry_id = payload.get("id") or payload.get("entry_id")
            if not entry_id:
                raise AppError(400, "id ist erforderlich zum Löschen.")
            result = svc.delete_meal(str(entry_id))
            handler.send_json(200, {"ok": True, **result})
            return True

        if path == "/api/nutrition/sync":
            if not self._nutrition_sync_service:
                raise AppError(400, "Intervals.icu Sync ist nicht verfügbar.")
            payload = handler.read_json() if handler.headers.get("Content-Length") else {}
            if not isinstance(payload, dict):
                raise AppError(400, "Ungültiger Anfrageinhalt.")
            sync_svc = self._nutrition_sync_service()
            meal_date = payload.get("date") or payload.get("meal_date")
            if meal_date:
                result = sync_svc.sync_day(meal_date)
            else:
                limit = payload.get("limit") or 14
                result = sync_svc.sync_pending(limit=limit)
            handler.send_json(200, {"ok": True, **result})
            return True

        return False


class NutritionPutRoutes:
    """Handle authenticated nutrition updates."""

    def __init__(
        self,
        nutrition_service: Callable[[], NutritionService],
    ) -> None:
        self._nutrition_service = nutrition_service

    def handle(self, handler: Any, path: str) -> bool:
        if path != "/api/nutrition/entry":
            return False

        payload = handler.read_json()
        if not isinstance(payload, dict):
            raise AppError(400, "Ungültiger Anfrageinhalt.")
        entry_id = payload.get("id") or payload.get("entry_id")
        if not entry_id:
            raise AppError(400, "id ist erforderlich zum Aktualisieren.")
        svc = self._nutrition_service()
        updated = svc.update_meal(str(entry_id), payload)
        handler.send_json(200, {"ok": True, "entry": updated})
        return True
