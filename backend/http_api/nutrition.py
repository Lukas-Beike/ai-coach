"""Authenticated HTTP API routes for nutrition and calorie tracking."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.errors import AppError
from backend.http_api.auth import SessionAuthService
from backend.nutrition.service import NutritionService

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
        if path not in {
            "/api/nutrition/day",
            "/api/nutrition/range",
            "/api/nutrition/templates",
            "/api/nutrition/fueling",
            "/api/nutrition/products",
        }:
            return False

        self._session_auth_service().require_auth(handler)
        query = parse_qs(urlparse(handler.path).query)
        svc = self._nutrition_service()
        if path == "/api/nutrition/products":
            barcode = query.get("barcode", [None])[0]
            term = query.get("q", [None])[0]
            if barcode:
                handler.send_json(200, svc.lookup_product({"barcode": barcode}))
            else:
                products = svc.list_products(query=term)
                handler.send_json(200, {"ok": True, "products": products})
            return True
        if path == "/api/nutrition/fueling":
            unit_id = query.get("planned_unit_id", [None])[0]
            handler.send_json(
                200, svc.fueling().read(unit_id) if unit_id else svc.fueling().choices()
            )
            return True

        if path == "/api/nutrition/templates":
            handler.send_json(200, {"ok": True, "templates": svc.list_templates()})
            return True

        if path == "/api/nutrition/day":
            date_param = (
                query.get("date", [None])[0] or self._local_now().date().isoformat()
            )
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
        sync_job_queue: Callable[[], Any],
    ) -> None:
        self._nutrition_service = nutrition_service
        self._sync_job_queue = sync_job_queue

    def handle(self, handler: Any, path: str) -> bool:
        routes = {
            NUTRITION_ENTRY_PATH: self._create,
            f"{NUTRITION_ENTRY_PATH}/delete": self._delete,
            "/api/nutrition/sync": self._sync,
            "/api/nutrition/products": self._save_product,
            "/api/nutrition/products/lookup": self._lookup_product,
            "/api/nutrition/products/extract": self._extract_product,
            "/api/nutrition/products/archive": self._archive_product,
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
        payload = _read_object(handler) if handler.headers.get("Content-Length") else {}
        meal_date = payload.get("date") or payload.get("meal_date")
        job_payload = (
            {"date": meal_date}
            if meal_date
            else {"pending_limit": payload.get("limit") or 14}
        )
        job = self._sync_job_queue().enqueue(
            "intervals", "nutrition_sync", job_payload, requested_by="http_api"
        )
        handler.send_json(
            202,
            {
                "ok": True,
                "status": "queued",
                "sync_job_id": job["id"],
            },
        )

    def _save_product(self, handler: Any) -> None:
        payload = _read_object(handler)
        confirmed = payload.pop("confirmed", None)
        product = payload.pop("product", payload)
        if confirmed is not True:
            raise AppError(
                400,
                "Das Produkt muss ausdrücklich bestätigt werden.",
                reason="confirmation_required",
            )
        handler.send_json(
            200,
            {"ok": True, "product": self._nutrition_service().save_product(product)},
        )

    def _lookup_product(self, handler: Any) -> None:
        payload = _read_object(handler)
        handler.send_json(200, self._nutrition_service().lookup_product(payload))

    def _extract_product(self, handler: Any) -> None:
        payload = _read_object(handler)
        handler.send_json(
            200, self._nutrition_service().extract_packaging_photo(payload)
        )

    def _archive_product(self, handler: Any) -> None:
        payload = _read_object(handler)
        if payload.get("confirmed") is not True:
            raise AppError(
                400,
                "Das Archivieren muss ausdrücklich bestätigt werden.",
                reason="confirmation_required",
            )
        handler.send_json(
            200,
            {
                "ok": True,
                "product": self._nutrition_service().archive_product(
                    str(payload.get("id") or "")
                ),
            },
        )


class NutritionPutRoutes:
    """Handle authenticated nutrition updates."""

    def __init__(
        self,
        nutrition_service: Callable[[], NutritionService],
    ) -> None:
        self._nutrition_service = nutrition_service

    def handle(self, handler: Any, path: str) -> bool:
        if path == "/api/nutrition/products":
            payload = _read_object(handler)
            if payload.pop("confirmed", None) is not True:
                raise AppError(
                    400,
                    "Das Produkt muss ausdrücklich bestätigt werden.",
                    reason="confirmation_required",
                )
            product_id = str(payload.get("id") or "").strip()
            if not product_id:
                raise AppError(400, "id ist erforderlich zum Aktualisieren.")
            handler.send_json(
                200,
                {
                    "ok": True,
                    "product": self._nutrition_service().update_product(
                        product_id, payload
                    ),
                },
            )
            return True
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
