"""Authenticated HTTP API routes for nutrition and calorie tracking."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, datetime, timedelta
from typing import Any

from backend import change_history
from backend.errors import AppError
from backend.http_api.route_table import Access, Route, RouteRequest
from backend.nutrition.diary import NutritionDiaryService
from backend.nutrition.macro_ranges import macro_ranges
from backend.nutrition.meal_library import NutritionMealLibraryService
from backend.nutrition.models import validate_iso_date
from backend.nutrition.photo import PHOTO_REQUEST_MAX_BYTES

NUTRITION_ENTRY_PATH = "/api/nutrition/entry"
NUTRITION_PRODUCTS_PATH = "/api/nutrition/products"
PRODUCT_ENTITY = "nutrition_product"
INVALID_BODY = "Ungültiger Anfrageinhalt."


class NutritionGetRoutes:
    """Handle authenticated nutrition query routes."""

    def __init__(
        self,
        diary_service: Callable[[], NutritionDiaryService],
        meal_library_service: Callable[[], NutritionMealLibraryService],
        local_now: Callable[[], datetime],
        macro_context: Callable[[str], tuple[Any, Any]] | None = None,
    ) -> None:
        self._diary_service = diary_service
        self._meal_library_service = meal_library_service
        self._local_now = local_now
        self._macro_context = macro_context

    def _day_summary(self, date_param: str) -> dict[str, Any]:
        summary = self._diary_service().sync_status.get_day_summary(date_param)
        if self._macro_context is None:
            return summary
        try:
            weight, calendar = self._macro_context(date_param)
        except AppError, OSError, RuntimeError, ValueError:
            logging.getLogger("intervals_coach").warning(
                "Nutrition reference data unavailable"
            )
            weight, calendar = None, None
        summary["macro_ranges"] = macro_ranges(
            weight, calendar, date_param, summary.get("total_kcal")
        )
        return summary

    def _products(self, query: dict[str, list[str]]) -> dict[str, Any]:
        meal_library = self._meal_library_service()
        barcode = query.get("barcode", [None])[0]
        term = query.get("q", [None])[0]
        if query.get("source", [None])[0] == "database":
            return {"ok": True, "foods": meal_library.list_database_foods(term)}
        if barcode:
            return meal_library.product_catalog.lookup_product({"barcode": barcode})
        return {
            "ok": True,
            "products": meal_library.product_catalog.list_products(
                query=term, favorites_first=True
            ),
        }

    def routes(self) -> list[Route]:
        return [
            Route("GET", "/api/nutrition/yazio/status", Access.SESSION, self._yazio),
            Route("GET", "/api/nutrition/day", Access.SESSION, self._day),
            Route("GET", "/api/nutrition/week", Access.SESSION, self._week),
            Route("GET", NUTRITION_PRODUCTS_PATH, Access.SESSION, self._product_list),
        ]

    def _yazio(self, handler: Any, _request: RouteRequest) -> None:
        """Last local Yazio authentication check, without contacting Yazio."""
        handler.send_json(
            200, self._meal_library_service().food_database.yazio_connection_status()
        )

    def _week(self, handler: Any, request: RouteRequest) -> None:
        """Nutrition week summary."""
        try:
            days = int(request.query.get("days", ["7"])[0])
        except ValueError:
            raise AppError(400, "Ungültiger Zeitraum.") from None
        handler.send_json(
            200,
            {"ok": True, **self._diary_service().sync_status.get_week_summary(days)},
        )

    def _product_list(self, handler: Any, request: RouteRequest) -> None:
        """Product search, barcode lookup or food database entries."""
        handler.send_json(200, self._products(request.query))

    def _day(self, handler: Any, request: RouteRequest) -> None:
        """Nutrition day summary with macro ranges."""
        date_param = (
            request.query.get("date", [None])[0] or self._local_now().date().isoformat()
        )
        handler.send_json(200, {"ok": True, **self._day_summary(date_param)})


class NutritionPostRoutes:
    """Handle authenticated nutrition mutations and synchronization."""

    def __init__(
        self,
        diary_service: Callable[[], NutritionDiaryService],
        meal_library_service: Callable[[], NutritionMealLibraryService],
        nutrition_refresh_service: Callable[[], Any] | None = None,
        local_now: Callable[[], datetime] | None = None,
    ) -> None:
        self._diary_service = diary_service
        self._meal_library_service = meal_library_service
        self._nutrition_refresh_service = nutrition_refresh_service
        self._local_now = local_now or datetime.now

    def routes(self) -> list[Route]:
        return [
            Route("POST", path, Access.SESSION_CSRF, handle)
            for path, handle in (
                ("/api/nutrition/yazio/check", self._check_yazio),
                (NUTRITION_ENTRY_PATH, self._create),
                (f"{NUTRITION_ENTRY_PATH}/delete", self._delete),
                (f"{NUTRITION_ENTRY_PATH}/add-product", self._add_product),
                ("/api/nutrition/refresh", self._refresh),
                (NUTRITION_PRODUCTS_PATH, self._save_product),
                (f"{NUTRITION_PRODUCTS_PATH}/lookup", self._lookup_product),
                (f"{NUTRITION_PRODUCTS_PATH}/extract", self._extract_product),
                (f"{NUTRITION_PRODUCTS_PATH}/archive", self._archive_product),
                (f"{NUTRITION_PRODUCTS_PATH}/favorite", self._favorite_product),
                (
                    f"{NUTRITION_PRODUCTS_PATH}/database/delete",
                    self._forget_database_food,
                ),
            )
        ]

    def _check_yazio(self, handler: Any, _request: RouteRequest) -> None:
        """Explicitly check Yazio authentication; the result is kept in memory."""
        handler.read_json()
        handler.send_json(
            200, self._meal_library_service().food_database.check_yazio_connection()
        )

    def _create(self, handler: Any, _request: RouteRequest) -> None:
        """Log a meal; returns a `change` undo reference."""
        with change_history.collect_changes() as changes:
            entry = self._diary_service().log_meal(handler.read_json())
        handler.send_json(200, {"ok": True, "entry": entry, **_change(changes)})

    def _add_product(self, handler: Any, _request: RouteRequest) -> None:
        """Add a saved product to a logged meal."""
        payload = _read_object(handler)
        with change_history.collect_changes() as changes:
            entry = self._diary_service().add_product_to_meal(
                str(payload.get("id") or ""),
                str(payload.get("product_id") or ""),
                payload.get("amount"),
                str(payload.get("unit") or ""),
            )
        handler.send_json(200, {"ok": True, "entry": entry, **_change(changes)})

    def _delete(self, handler: Any, _request: RouteRequest) -> None:
        """Delete a logged meal."""
        payload = _read_object(handler)
        entry_id = payload.get("id") or payload.get("entry_id")
        if not entry_id:
            raise AppError(400, "id ist erforderlich zum Löschen.")
        with change_history.collect_changes() as changes:
            result = self._diary_service().delete_meal(str(entry_id))
        handler.send_json(200, {"ok": True, **result, **_change(changes)})

    def _refresh(self, handler: Any, _request: RouteRequest) -> None:
        """Run a targeted nutrition refresh."""
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
            summary = self._diary_service().sync_status.get_day_summary(meal_date)
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
            products = self._meal_library_service().product_catalog.list_products()
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

    def _save_product(self, handler: Any, _request: RouteRequest) -> None:
        """Save a product."""
        payload = _read_object(handler)
        confirmed = payload.pop("confirmed", None)
        product = payload.pop("product", payload)
        if confirmed is not True:
            raise AppError(
                400,
                "Das Produkt muss ausdrücklich bestätigt werden.",
                reason="confirmation_required",
            )
        with change_history.collect_changes() as changes:
            saved = self._meal_library_service().product_catalog.save_product(product)
        handler.send_json(
            200, {"ok": True, "product": saved, **_change(changes, PRODUCT_ENTITY)}
        )

    def _lookup_product(self, handler: Any, _request: RouteRequest) -> None:
        """Look a product up by barcode."""
        payload = _read_object(handler)
        handler.send_json(
            200, self._meal_library_service().product_catalog.lookup_product(payload)
        )

    def _extract_product(self, handler: Any, _request: RouteRequest) -> None:
        """Extract a product from a label photo."""
        payload = _read_object(handler, PHOTO_REQUEST_MAX_BYTES)
        handler.send_json(
            200, self._meal_library_service().extract_packaging_photo(payload)
        )

    def _forget_database_food(self, handler: Any, _request: RouteRequest) -> None:
        """Forget a food database entry."""
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

    def _favorite_product(self, handler: Any, _request: RouteRequest) -> None:
        """Mark or unmark a product as favorite."""
        payload = _read_object(handler)
        product = self._meal_library_service().product_catalog.set_favorite(
            str(payload.get("id") or ""), payload.get("favorite")
        )
        handler.send_json(200, {"ok": True, "product": product})

    def _archive_product(self, handler: Any, _request: RouteRequest) -> None:
        """Archive a product."""
        payload = _read_object(handler)
        if payload.get("confirmed") is not True:
            raise AppError(
                400,
                "Das Archivieren muss ausdrücklich bestätigt werden.",
                reason="confirmation_required",
            )
        with change_history.collect_changes() as changes:
            archived = self._meal_library_service().product_catalog.archive_product(
                str(payload.get("id") or "")
            )
        handler.send_json(
            200, {"ok": True, "product": archived, **_change(changes, PRODUCT_ENTITY)}
        )


class NutritionPutRoutes:
    """Handle authenticated product updates.

    Diary entries change only through the Coach correction, which enforces the
    field whitelist, the ``manual_correction`` basis and the undo reference; the
    old ``PUT /api/nutrition/entry`` skipped all three (#2137, F-018).
    """

    def __init__(
        self, meal_library_service: Callable[[], NutritionMealLibraryService]
    ) -> None:
        self._meal_library_service = meal_library_service

    def routes(self) -> list[Route]:
        return [
            Route(
                "PUT",
                NUTRITION_PRODUCTS_PATH,
                Access.SESSION_CSRF,
                self._update_product,
            )
        ]

    def _update_product(self, handler: Any, _request: RouteRequest) -> None:
        """Update a confirmed saved product."""
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
        with change_history.collect_changes() as changes:
            updated = self._meal_library_service().product_catalog.update_product(
                product_id, payload
            )
        handler.send_json(
            200,
            {"ok": True, "product": updated, **_change(changes, PRODUCT_ENTITY)},
        )


def _change(
    changes: list[dict[str, str]], entity_type: str = "nutrition_entry"
) -> dict[str, Any]:
    """The undo reference of the last change of one entity type, as ``{"change": ...}``."""
    matching = [item for item in changes if item["entity_type"] == entity_type]
    return {"change": matching[-1]} if matching else {}


def _read_object(handler: Any, max_bytes: int | None = None) -> dict[str, Any]:
    payload = handler.read_json(max_bytes)
    if not isinstance(payload, dict):
        raise AppError(400, INVALID_BODY)
    return payload
