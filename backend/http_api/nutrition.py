"""Authenticated HTTP API routes for nutrition and calorie tracking."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any
from urllib.parse import parse_qs, urlparse

from backend.canonical.vocabulary import ProviderId
from backend.errors import AppError
from backend.http_api.auth import SessionAuthService
from backend.nutrition.diary import NutritionDiaryService
from backend.nutrition.meal_library import NutritionMealLibraryService
from backend.nutrition.models import validate_iso_date
from backend.nutrition.photo import PHOTO_REQUEST_MAX_BYTES

NUTRITION_ENTRY_PATH = "/api/nutrition/entry"
NUTRITION_PRODUCTS_PATH = "/api/nutrition/products"
INVALID_BODY = "Ungültiger Anfrageinhalt."


class NutritionGetRoutes:
    """Handle authenticated nutrition query routes."""

    def __init__(
        self,
        session_auth_service: Callable[[], SessionAuthService],
        diary_service: Callable[[], NutritionDiaryService],
        meal_library_service: Callable[[], NutritionMealLibraryService],
        local_now: Callable[[], datetime],
    ) -> None:
        self._session_auth_service = session_auth_service
        self._diary_service = diary_service
        self._meal_library_service = meal_library_service
        self._local_now = local_now

    def handle(self, handler: Any, path: str) -> bool:
        if path not in {
            "/api/nutrition/yazio/status",
            "/api/nutrition/day",
            "/api/nutrition/range",
            "/api/nutrition/week",
            "/api/nutrition/templates",
            NUTRITION_PRODUCTS_PATH,
        }:
            return False

        self._session_auth_service().require_auth(handler)
        if path == "/api/nutrition/yazio/status":
            handler.send_json(
                200,
                self._meal_library_service().food_database.yazio_connection_status(),
            )
            return True
        query = parse_qs(urlparse(handler.path).query)
        if path == "/api/nutrition/week":
            try:
                days = int(query.get("days", ["7"])[0])
            except ValueError:
                raise AppError(400, "Ungültiger Zeitraum.") from None
            handler.send_json(
                200, {"ok": True, **self._diary_service().get_week_summary(days)}
            )
            return True
        if path == NUTRITION_PRODUCTS_PATH:
            meal_library = self._meal_library_service()
            barcode = query.get("barcode", [None])[0]
            term = query.get("q", [None])[0]
            if query.get("source", [None])[0] == "database":
                handler.send_json(
                    200,
                    {"ok": True, "foods": meal_library.list_database_foods(term)},
                )
            elif barcode:
                handler.send_json(
                    200, meal_library.lookup_product({"barcode": barcode})
                )
            else:
                products = meal_library.list_products(query=term)
                handler.send_json(200, {"ok": True, "products": products})
            return True
        if path == "/api/nutrition/templates":
            meal_library = self._meal_library_service()
            handler.send_json(
                200, {"ok": True, "templates": meal_library.list_templates()}
            )
            return True

        if path == "/api/nutrition/day":
            diary = self._diary_service()
            date_param = (
                query.get("date", [None])[0] or self._local_now().date().isoformat()
            )
            summary = diary.get_day_summary(date_param)
            handler.send_json(200, {"ok": True, **summary})
            return True

        if path == "/api/nutrition/range":
            diary = self._diary_service()
            today = self._local_now().date().isoformat()
            start_param = query.get("start", [today])[0]
            end_param = query.get("end", [today])[0]
            summaries = diary.get_range_summary(start_param, end_param)
            handler.send_json(200, {"ok": True, "summaries": summaries})
            return True

        return False


class NutritionPostRoutes:
    """Handle authenticated nutrition mutations and synchronization."""

    def __init__(
        self,
        diary_service: Callable[[], NutritionDiaryService],
        meal_library_service: Callable[[], NutritionMealLibraryService],
        sync_job_queue: Callable[[], Any],
        nutrition_refresh_service: Callable[[], Any] | None = None,
        local_now: Callable[[], datetime] | None = None,
    ) -> None:
        self._diary_service = diary_service
        self._meal_library_service = meal_library_service
        self._sync_job_queue = sync_job_queue
        self._nutrition_refresh_service = nutrition_refresh_service
        self._local_now = local_now or datetime.now

    def handle(self, handler: Any, path: str) -> bool:
        routes = {
            "/api/nutrition/yazio/check": self._check_yazio,
            NUTRITION_ENTRY_PATH: self._create,
            f"{NUTRITION_ENTRY_PATH}/delete": self._delete,
            "/api/nutrition/sync": self._sync,
            "/api/nutrition/refresh": self._refresh,
            NUTRITION_PRODUCTS_PATH: self._save_product,
            f"{NUTRITION_PRODUCTS_PATH}/lookup": self._lookup_product,
            f"{NUTRITION_PRODUCTS_PATH}/extract": self._extract_product,
            f"{NUTRITION_PRODUCTS_PATH}/archive": self._archive_product,
            f"{NUTRITION_PRODUCTS_PATH}/database/delete": self._forget_database_food,
        }
        route = routes.get(path)
        if route is None:
            return False
        route(handler)
        return True

    def _check_yazio(self, handler: Any) -> None:
        handler.read_json()
        handler.send_json(
            200, self._meal_library_service().food_database.check_yazio_connection()
        )

    def _create(self, handler: Any) -> None:
        entry = self._diary_service().log_meal(handler.read_json())
        handler.send_json(200, {"ok": True, "entry": entry})

    def _delete(self, handler: Any) -> None:
        payload = _read_object(handler)
        entry_id = payload.get("id") or payload.get("entry_id")
        if not entry_id:
            raise AppError(400, "id ist erforderlich zum Löschen.")
        result = self._diary_service().delete_meal(str(entry_id))
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
            ProviderId.INTERVALS.value,
            "nutrition_sync",
            job_payload,
            requested_by="http_api",
        )
        handler.send_json(
            202,
            {"ok": True, "status": "queued", "sync_job_id": job["id"]},
        )

    def _refresh(self, handler: Any) -> None:
        payload = _read_object(handler)
        area = payload.get("area")
        if area not in {"diary", "week", "body", "products"}:
            raise AppError(400, "Ungültiger Ernährungsbereich.")
        if set(payload) - {"area", "date", "days"}:
            raise AppError(400, INVALID_BODY)

        if area == "diary":
            meal_date = validate_iso_date(
                payload.get("date") or self._local_now().date().isoformat()
            )
            expenditure = self._refresh_provider("daily_stats", meal_date, meal_date)
            summary = self._diary_service().get_day_summary(meal_date)
            if expenditure.get("status") != "ok":
                summary["energy_expenditure"]["freshness"] = "partial"
            handler.send_json(
                200,
                {
                    "ok": True,
                    "area": area,
                    "status": expenditure.get("status", "partial"),
                    "meal_status": "local",
                    "summary": summary,
                    "expenditure_refresh": expenditure,
                },
            )
            return
        if area == "products":
            products = self._meal_library_service().list_products()
            handler.send_json(
                200,
                {"ok": True, "area": area, "status": "local", "products": products},
            )
            return

        days = payload.get("days", 14 if area == "week" else 84)
        if type(days) is not int or days not in {14, 84}:
            raise AppError(400, "Der Zeitraum muss 14 oder 84 Tage umfassen.")
        default_end = self._local_now().date()
        if area == "week" and "date" not in payload:
            default_end -= timedelta(days=1)
        end = validate_iso_date(payload.get("date") or default_end.isoformat())
        end_date = date.fromisoformat(end)
        today = self._local_now().date()
        if end_date > today:
            raise AppError(400, "Das Datum darf nicht in der Zukunft liegen.")
        start = end_date - timedelta(days=days - 1)
        source = "daily_stats" if area == "week" else "weight"
        result = self._refresh_provider(source, start.isoformat(), end)
        handler.send_json(200, {"ok": True, "area": area, **result})

    def _refresh_provider(self, source: str, start: str, end: str) -> dict[str, Any]:
        if self._nutrition_refresh_service is None:
            return {"status": "partial", "reason": "not_configured"}
        try:
            return self._nutrition_refresh_service().refresh(
                source,
                date.fromisoformat(start),
                date.fromisoformat(end),
            )
        except AppError as exc:
            if exc.reason not in {
                "not_configured",
                "not_supported",
                "library_unavailable",
            }:
                raise
            return {"status": "partial", "reason": exc.reason}

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
            {"ok": True, "product": self._meal_library_service().save_product(product)},
        )

    def _lookup_product(self, handler: Any) -> None:
        payload = _read_object(handler)
        handler.send_json(200, self._meal_library_service().lookup_product(payload))

    def _extract_product(self, handler: Any) -> None:
        payload = _read_object(handler, PHOTO_REQUEST_MAX_BYTES)
        handler.send_json(
            200, self._meal_library_service().extract_packaging_photo(payload)
        )

    def _forget_database_food(self, handler: Any) -> None:
        payload = _read_object(handler)
        if payload.get("confirmed") is not True:
            raise AppError(
                400,
                "Das Entfernen muss ausdrücklich bestätigt werden.",
                reason="confirmation_required",
            )
        handler.send_json(
            200,
            self._meal_library_service().forget_database_food(
                str(payload.get("id") or "")
            ),
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
                "product": self._meal_library_service().archive_product(
                    str(payload.get("id") or "")
                ),
            },
        )


class NutritionPutRoutes:
    """Handle authenticated nutrition updates."""

    def __init__(
        self,
        diary_service: Callable[[], NutritionDiaryService],
        meal_library_service: Callable[[], NutritionMealLibraryService],
    ) -> None:
        self._diary_service = diary_service
        self._meal_library_service = meal_library_service

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
                    "product": self._meal_library_service().update_product(
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
        svc = self._diary_service()
        updated = svc.update_meal(str(entry_id), payload)
        handler.send_json(200, {"ok": True, "entry": updated})
        return True


def _read_object(handler: Any, max_bytes: int | None = None) -> dict[str, Any]:
    payload = handler.read_json(max_bytes)
    if not isinstance(payload, dict):
        raise AppError(400, INVALID_BODY)
    return payload
