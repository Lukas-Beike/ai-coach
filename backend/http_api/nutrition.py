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
from backend.nutrition.food_mirror import FOOD_ENTITY_TYPE
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
        if query.get("scope", [None])[0] == "all":
            return {
                "ok": True,
                "products": meal_library.product_catalog.list_all_products(term),
            }
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
        """Last local Yazio authentication check, without contacting Yazio.

        Request: no body.

        Response: 200 `{"status", "checked_at"}`. `status` is `not_configured`
        (`checked_at` `null`), `unchecked` before the first check, else the result of
        the last check (`success`, `auth_failed`, `rate_limited`, `unavailable`) with
        its `checked_at`.

        Errors: none beyond the common ones.
        """
        handler.send_json(
            200, self._meal_library_service().food_database.yazio_connection_status()
        )

    def _week(self, handler: Any, request: RouteRequest) -> None:
        """Nutrition week summary of the closed days before today.

        Request: query `days` (integer, default `7`; `7`, `14` or `84`).

        Response: 200 `{"ok": true, "start_date", "end_date", "days", "averages",
        "balance_kcal", "balance_days"}`. Each item of `days` has `date`, `intake_kcal`,
        `expenditure_kcal`, `balance_kcal`, `energy_expenditure`, the macro totals and
        the intake fields; unknown values are `null`. `averages` gives `{"value",
        "days"}` per field.

        Errors: 400 "Ungültiger Zeitraum." for a non-integer `days`; 400 "Zeitraum muss
        7, 14 oder 84 Tage umfassen." for another number.
        """
        try:
            days = int(request.query.get("days", ["7"])[0])
        except ValueError:
            raise AppError(400, "Ungültiger Zeitraum.") from None
        handler.send_json(
            200,
            {"ok": True, **self._diary_service().sync_status.get_week_summary(days)},
        )

    def _product_list(self, handler: Any, request: RouteRequest) -> None:
        """Product search, barcode lookup or food database entries.

        Request: query `q` (search text, optional), `source`, `scope` and `barcode`,
        checked in this order. `source=database` lists the stored food database entries
        (at most 50, newest first without `q`). `scope=all` lists own products and
        stored database foods matching `q`. A `barcode` looks the product up, local
        first, then the food databases. Otherwise the active own products matching `q`,
        favorites first, at most 50.

        Response: 200. `source=database`: `{"ok": true, "foods"}`, each food with
        `missing_fields`. `scope=all` and the plain list: `{"ok": true, "products"}`.
        Barcode: `{"ok": true, "foods", "product", "local", "source"}` with `source`
        `local`, `yazio` or `open_food_facts`, plus a `notice` for a database hit.

        Errors: none beyond the common ones.
        """
        handler.send_json(200, self._products(request.query))

    def _day(self, handler: Any, request: RouteRequest) -> None:
        """Nutrition day summary with macro ranges.

        Request: query `date` (`YYYY-MM-DD`, default today).

        Response: 200 `{"ok": true, ...}` with the day of `get_day_summary`: `date`,
        `total_kcal`, `total_carbs_g`, `total_protein_g`, `total_fat_g`,
        `total_sugar_g`, `total_salt_g`, `known_macro_totals`, `known_intake_totals`,
        `entries_without_macros`, `entry_count`, `entries` and `energy_expenditure`; a
        macro total is `null` unless every entry reports it. `macro_ranges` maps
        `protein_g`, `carbs_g` and `fat_g` to `[low, high]` where weight and training
        calendar allow it.

        Errors: 400 "Ungültiges Datumsformat '{value}'. Erwartet wird YYYY-MM-DD." for
        an invalid `date`.
        """
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
                (
                    f"{NUTRITION_PRODUCTS_PATH}/database/refresh",
                    self._refresh_database_food,
                ),
            )
        ]

    def _check_yazio(self, handler: Any, _request: RouteRequest) -> None:
        """Explicitly check Yazio authentication; the result is kept in memory.

        Request: JSON object; its content is ignored.

        Response: 200 `{"status", "checked_at"}`: `not_configured` (`checked_at` `null`)
        without Yazio credentials, else `success`, `auth_failed`, `rate_limited` or
        `unavailable` with the check time.

        Errors: none beyond the common ones.
        """
        handler.read_json()
        handler.send_json(
            200, self._meal_library_service().food_database.check_yazio_connection()
        )

    def _create(self, handler: Any, _request: RouteRequest) -> None:
        """Log a meal; returns a `change` undo reference.

        Request: JSON body, either `components` alone or one meal. Meal fields:
        `description` (cut to 500 characters; required unless `product_id` supplies it),
        `kcal` (0 to 10000, or `calories`; required unless `product_id`,
        `food_ingredients` or `components` supply it), optional `carbs_g`, `protein_g`,
        `fat_g` (0 to 1000, or `carbs`, `carbohydrates`, `protein`, `fat`), `meal_date`
        (or `date`, default today), `meal_time` (or `logged_at`; a time or an ISO
        timestamp), `logged_time_known` (boolean; `false` needs `meal_type`),
        `meal_type` (`breakfast`, `lunch`, `dinner`, `snack`; default derived from the
        time), `source` (`manual`, `voice`, `photo`, `coach`; anything else is
        `manual`), `packaging_label` (`true` marks label values), `food_ingredients`
        (list of `{food_id, amount, unit}`) or `product_id` with `amount` and `unit`
        (nutrients calculated from the saved product). `components` is a list of 1 to 20
        items `{kind, amount, unit}` plus `product_id` (`local_product`), `food_id`
        (`database`) or `name`, `kcal`, `carbs_g`, `protein_g`, `fat_g` (`manual`,
        `estimate`, `packaging_label`); `unit` is `g`, `ml` or `portion`. It excludes
        `product_id`, `food_ingredients`, `nutrition_basis` and every nutrient field.

        Response: 200 `{"ok": true, "entry", "change"}`; `entry` is the stored entry
        (`id`, `meal_date`, `logged_at`, `meal_type`, `description`, `kcal`, the macros,
        `source`, `nutrition_basis`, `sync_state`, `logged_time_known`), `change` the
        undo reference.

        Errors: 400 "Beschreibung der Mahlzeit ist erforderlich."; 400 "Kalorienangabe
        (kcal) ist erforderlich."; 400 "Kalorien müssen zwischen 0 und 10000 liegen.";
        400 "Ungültiges Datumsformat '{value}'. Erwartet wird YYYY-MM-DD."; 400
        "Ungültige Uhrzeit '{value}'."; 400 "Bei unbekannter Uhrzeit ist der Mahlzeittyp
        erforderlich."; 400 "Ungültiger Mahlzeittyp '{value}'. Erlaubt sind: breakfast,
        lunch, dinner, snack."; 400 "Komponenten dürfen nicht mit Einzelzutaten,
        Summenwerten oder clientseitiger Herkunft kombiniert werden."; 400 "1 bis 20
        Mahlzeitenkomponenten sind erforderlich."; 400 "Ungültige Mahlzeitenkomponente."
        and 400 "Einheit muss g, ml oder portion sein." for a malformed component; 404
        `nutrition_product_not_found` "Produkt nicht gefunden." and 409
        `nutrition_product_archived` "Archivierte Produkte können nicht erfasst werden."
        for an unknown or archived product; 400 `food_unit_mismatch` when `unit` differs
        from the basis unit of the product; 400 `food_energy_missing` for a component
        without calorie value.
        """
        with change_history.collect_changes() as changes:
            entry = self._diary_service().log_meal(handler.read_json())
        handler.send_json(200, {"ok": True, "entry": entry, **_change(changes)})

    def _add_product(self, handler: Any, _request: RouteRequest) -> None:
        """Add a saved product to a logged meal as one more component.

        Request: JSON body `{"id": string, "product_id": string, "amount": number,
        "unit": string}`; `id` is the entry id, `amount` is above 0 up to 10000, `unit`
        must be the basis unit of the product (`g`, `ml` or `portion`). The entry
        becomes a composite of at most 20 components and its description gains " +
        {product name}".

        Response: 200 `{"ok": true, "entry", "change"}` with the updated entry and the
        undo reference.

        Errors: 400 "Ungültige Eintrags-ID." for a missing `id`; 404 "Ernährungseintrag
        nicht gefunden."; 404 `nutrition_product_not_found` "Produkt nicht gefunden.";
        409 `nutrition_product_archived` "Archivierte Produkte können nicht erfasst
        werden."; 400 "Komponentenreferenz muss eine Zeichenkette sein." for a missing
        `product_id`; 400 "Ungültige Komponentenmenge." or 400 "Komponentenmenge muss
        größer als 0 sein."; 400 "Einheit muss g, ml oder portion sein."; 400
        `food_unit_mismatch` "Komponenteneinheit stimmt nicht mit dem Produkt überein.";
        400 `food_energy_missing` "Für dieses Produkt fehlt der Kalorienwert."; 400
        "Eine Mahlzeit kann höchstens 20 Komponenten enthalten."
        """
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
        """Delete a logged meal.

        Request: JSON body `{"id": string}` (or `entry_id`), the entry id.

        Response: 200 `{"ok": true, "status": "ok", "deleted_id", "change"}`; `change`
        is the undo reference.

        Errors: 400 "id ist erforderlich zum Löschen." for a missing id; 404
        "Ernährungseintrag nicht gefunden."
        """
        payload = _read_object(handler)
        entry_id = payload.get("id") or payload.get("entry_id")
        if not entry_id:
            raise AppError(400, "id ist erforderlich zum Löschen.")
        with change_history.collect_changes() as changes:
            result = self._diary_service().delete_meal(str(entry_id))
        handler.send_json(200, {"ok": True, **result, **_change(changes)})

    def _refresh(self, handler: Any, _request: RouteRequest) -> None:
        """Run a targeted nutrition refresh.

        Request: JSON body `{"area": string, "date": "YYYY-MM-DD", "days": integer}` and
        no other key. `area` is `diary`, `week`, `body` or `products`. `date` is
        optional: today for `diary` and `body`, yesterday for `week`; for `week` and
        `body` it must not lie in the future. `days` is `14` or `84` (default `14` for
        `week`, `84` for `body`) and ends at `date`. `diary` refreshes the Garmin energy
        expenditure of that day, `week` the Garmin daily totals, `body` the Garmin
        weight; `products` only reads the local products and ignores `date` and `days`.

        Response: 200 `{"ok": true, "area", ...}`. `diary`: `status`, `meal_status`
        (`local`), `summary` (the day as in `GET /api/nutrition/day`) and
        `expenditure_refresh`. `products`: `status` `local` and `products` (active own
        products). `week` and `body`: the Garmin result, `status` (`ok` or `partial`),
        `source`, `data_source`, `start`, `end`, `records`, `synced_at`, or `status`
        `partial` with `reason` (`not_configured`, `not_supported`,
        `library_unavailable`, `provider_unavailable`) when Garmin cannot be read.

        Errors: 400 "Ungültiger Ernährungsbereich." for another `area`; 400 "Ungültiger
        Anfrageinhalt." for another key; 400 "Ungültiges Datumsformat '{value}'.
        Erwartet wird YYYY-MM-DD." for an invalid `date`; 400 "Der Zeitraum muss 14 oder
        84 Tage umfassen."; 400 "Das Datum darf nicht in der Zukunft liegen."; 503
        `provider_busy` "Garmin wird bereits aktualisiert."
        """
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
            return self._nutrition_refresh_service().refresh_nutrition(
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
        """Save a confirmed product.

        Request: JSON body `{"confirmed": true, "product": {...}}`, or the product
        fields next to `confirmed`. Product fields: `name` (required, at most 200
        characters), `brand` (cut to 120), `barcode` (8, 12, 13 or 14 digits, else
        dropped), `basis_amount` (above 0 up to 10000) and `basis_unit` (`g`, `ml`,
        `portion`), both required, `kcal`, `carbs_g`, `protein_g`, `fat_g`, `sugar_g`,
        `fiber_g`, `salt_g` (0 to 10000, empty is unknown), `confidence` (clamped to 0
        to 1), `source` (`packaging_label` default, `manual`, `open_food_facts`,
        `yazio`, `bls`, `fddb_export`), `source_url` (cut to 500), `external_id` (cut to
        200), `id` (saves over that product) and `status` (`active` or `archived`).
        Saving a new product with a barcode fills its empty fields from the stored
        database foods of that barcode.

        Response: 200 `{"ok": true, "product", "change"}` with the stored product and
        the undo reference.

        Errors: 400 `confirmation_required` "Das Produkt muss ausdrücklich bestätigt
        werden."; 400 `invalid_food_extraction` "Ein Produktname ist erforderlich.",
        "Ungültiger Wert für {field}.", "Ungültige Bezugsmenge.", "Bezugsmenge muss
        zwischen 0 und 10000 liegen." or "Bezugsmenge und Einheit sind erforderlich.";
        400 "Ungültige Produktquelle."; 409 `nutrition_product_barcode_conflict` "Diese
        EAN ist bereits einem lokalen Produkt zugeordnet."
        """
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
        """Look a product up by barcode or name, local products first.

        Request: JSON body `{"barcode": string}` or `{"query": string}` (alias `q`, at
        least 2 characters), with the optional `source` `open_food_facts`, `yazio` or
        `bls` for a name search. Without a local hit the food databases are asked.

        Response: 200 `{"ok": true, "foods", "product", "local", "source", "notice"}`;
        `product` is the first hit or `null`; a local hit has `local: true` and `source:
        "local"`; `notice` comes with a database hit.

        Errors: 400 "Suchbegriff muss mindestens 2 Zeichen enthalten." without a barcode
        and a query of fewer than 2 characters; 400 "Suchbegriff muss 2 bis 120 Zeichen
        enthalten." for a longer query; 400 "Ungültige Lebensmitteldatenbank." for
        another `source`.
        """
        payload = _read_object(handler)
        handler.send_json(
            200, self._meal_library_service().product_catalog.lookup_product(payload)
        )

    def _extract_product(self, handler: Any, _request: RouteRequest) -> None:
        """Extract a product from a label photo; the image is not stored.

        Request: JSON body `{"image_data_url": string}`, a `data:image/jpeg`,
        `image/png` or `image/webp` base64 URL of at most 5 MiB decoded. Without
        `image_data_url` the body is validated as an extraction (`name`, `brand`,
        `barcode`, `basis_amount`, `basis_unit`, `kcal`, `carbs_g`, `protein_g`,
        `fat_g`, `sugar_g`, `fiber_g`, `salt_g`, `confidence`; `name` required). The
        body limit is 7 056 044 bytes.

        Response: 200 `{"ok": true, "candidate", "extraction", "provenance":
        "packaging_label", "requires_confirmation": true}`; `extraction` repeats
        `candidate`. Nothing is saved.

        Errors: 413 `food_image_too_large` "Das Verpackungsfoto ist zu groß."; 415
        `food_image_type` "Nur JPEG-, PNG- oder WebP-Fotos werden unterstützt." or
        "Dateityp und Bildinhalt stimmen nicht überein."; 400 `invalid_food_image` "Das
        Verpackungsfoto ist ungültig."; 503 `provider_unavailable` "Fotoerkennung ist
        nicht verfügbar." or "Der OpenAI-Dienst ist nicht verfügbar."; 502
        `invalid_provider_response` "Die Nährwerttabelle konnte nicht gelesen werden.";
        400 `invalid_food_extraction` for an invalid candidate (as for the product
        save).
        """
        payload = _read_object(handler, PHOTO_REQUEST_MAX_BYTES)
        handler.send_json(
            200, self._meal_library_service().extract_packaging_photo(payload)
        )

    def _refresh_database_food(self, handler: Any, _request: RouteRequest) -> None:
        """Re-check one food database entry or own product online now; gaps fill.

        Request: JSON body `{"id": string}`, an own product id or a stored database food
        id (`off:...` or `yazio:...`). Only empty fields are filled; known values stay.

        Response: 200 for an own product: `{"ok": true, "product", "notice", "change"}`
        (`change` only when fields were filled); for a database food: `{"ok": true,
        "food"}` with `missing_fields` and a `notice` when a source was skipped.

        Errors: 409 `nutrition_product_archived` "Archivierte Produkte werden nicht
        aktualisiert."; 400 `nutrition_product_barcode_missing` "Zum Aktualisieren
        braucht das Produkt eine EAN. Trage sie beim Bearbeiten ein."; 404
        `food_not_found` "Datenbankeintrag nicht gefunden."; 409 `not_configured` "Yazio
        ist nicht konfiguriert." for a Yazio food without credentials; 502
        `food_database_unavailable` "Der Datenbankeintrag konnte nicht aktualisiert
        werden."
        """
        payload = _read_object(handler)
        with change_history.collect_changes() as changes:
            result = self._meal_library_service().refresh_database_food(
                str(payload.get("id") or "")
            )
        handler.send_json(200, {**result, **_change(changes, PRODUCT_ENTITY)})

    def _forget_database_food(self, handler: Any, _request: RouteRequest) -> None:
        """Forget a food database entry.

        Request: JSON body `{"id": string, "confirmed": true}`.

        Response: 200 `{"ok": true, "id", "status": "removed"}`.

        Errors: 400 `confirmation_required` "Das Entfernen muss ausdrücklich bestätigt
        werden."; 404 `food_not_found` "Datenbankeintrag nicht gefunden."
        """
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
        """Mark or unmark a product as favorite.

        Request: JSON body `{"id": string, "favorite": boolean}`.

        Response: 200 `{"ok": true, "product"}` with the updated product.

        Errors: 400 "favorite muss true oder false sein."; 404
        `nutrition_product_not_found` "Produkt nicht gefunden."
        """
        payload = _read_object(handler)
        product = self._meal_library_service().product_catalog.set_favorite(
            str(payload.get("id") or ""), payload.get("favorite")
        )
        handler.send_json(200, {"ok": True, "product": product})

    def _archive_product(self, handler: Any, _request: RouteRequest) -> None:
        """Archive a product.

        Request: JSON body `{"id": string, "confirmed": true}`.

        Response: 200 `{"ok": true, "product", "change"}` with the archived product and
        the undo reference.

        Errors: 400 `confirmation_required` "Das Archivieren muss ausdrücklich bestätigt
        werden."; 404 `nutrition_product_not_found` "Produkt nicht gefunden."
        """
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
        """Update a confirmed saved product.

        Request: JSON body `{"id": string, "confirmed": true, ...}` with the fields to
        change, as for the product save; they are merged into the stored product. For a
        stored database food only the nutrient values (`kcal`, `carbs_g`, `protein_g`,
        `fat_g`, `sugar_g`, `fiber_g`, `salt_g`) can change.

        Response: 200 `{"ok": true, "product", "change"}` with the updated product and
        the undo reference.

        Errors: 400 `confirmation_required` "Das Produkt muss ausdrücklich bestätigt
        werden."; 400 "id ist erforderlich zum Aktualisieren."; 404
        `nutrition_product_not_found` "Produkt nicht gefunden."; 404 `food_not_found`
        "Datenbankeintrag nicht gefunden."; 400 `food_database_field_fixed` "Bei einem
        Datenbankeintrag sind nur die Nährwerte änderbar."; the validation errors of the
        product save.
        """
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
            {
                "ok": True,
                "product": updated,
                **(
                    _change(changes, PRODUCT_ENTITY)
                    or _change(changes, FOOD_ENTITY_TYPE)
                ),
            },
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
