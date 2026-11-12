"""Nutrition product catalog and provenance workflows."""

from __future__ import annotations

import math
import uuid
from contextlib import AbstractContextManager
from typing import Any

from backend import change_history
from backend.db.manager import DatabaseManager
from backend.db.repositories import (
    FoodDatabaseEntryRepository,
    NutritionProductRepository,
)
from backend.errors import AppError
from backend.nutrition.components import MealComponentCalculator
from backend.nutrition.food_database import FoodDatabaseService, matches_all_terms
from backend.nutrition.models import nutrition_number
from backend.nutrition.photo import validate_packaging_extraction

PRODUCT_NOT_FOUND = "Produkt nicht gefunden."
PRODUCT_ENTITY_TYPE = "nutrition_product"


class ProductCatalogService:
    def __init__(
        self,
        database_manager: DatabaseManager,
        db_lock: AbstractContextManager[Any],
        products: NutritionProductRepository,
        utc_now: Any,
        food_database: FoodDatabaseService,
        component_calculator: MealComponentCalculator,
    ) -> None:
        self._database_manager = database_manager
        self._db_lock = db_lock
        self._products = products
        self._utc_now = utc_now
        self.food_database = food_database
        self._component_calculator = component_calculator

    def list_products(
        self,
        *,
        query: str | None = None,
        barcode: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        favorites_first: bool = False,
    ) -> list[dict[str, Any]]:
        with self._database_manager.reader() as db:
            found = self._products.list(
                db,
                query=query,
                barcode=barcode,
                include_archived=include_archived,
                limit=limit,
                favorites_first=favorites_first,
            )
            if found or not (query and query.strip()) or barcode:
                return found
            # Plurals, umlauts and one typo ("Champignons", "Hüttenkase") still
            # find a saved product before any database is asked; every word
            # must fit, so a loose match never hides a better database food.
            recent = self._products.list(
                db,
                include_archived=include_archived,
                limit=100,
                favorites_first=favorites_first,
            )
        return [
            product
            for product in recent
            if matches_all_terms(
                query, f"{product.get('name') or ''} {product.get('brand') or ''}"
            )
        ][: max(1, min(int(limit), 100))]

    def get_product(self, product_id: str) -> dict[str, Any]:
        with self._db_lock, self._database_manager.unit_of_work() as db:
            product = self._products.get(db, str(product_id or "").strip())
        if not product:
            raise AppError(404, PRODUCT_NOT_FOUND, reason="nutrition_product_not_found")
        return product

    def save_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self.normalize_product(payload)
        with self._db_lock, self._database_manager.unit_of_work() as db:
            existing = (
                self._products.list(
                    db, barcode=normalized["barcode"], include_archived=True
                )
                if normalized.get("barcode")
                else []
            )
            if existing and existing[0]["id"] != normalized["id"]:
                raise AppError(
                    409,
                    "Diese EAN ist bereits einem lokalen Produkt zugeordnet.",
                    reason="nutrition_product_barcode_conflict",
                )
            previous = self._products.get(db, normalized["id"])
            if previous is None and FoodDatabaseEntryRepository().get(
                db, normalized["id"]
            ):
                # A new product never takes over a stored database food's id.
                normalized["id"] = uuid.uuid4().hex
            saved = self._products.save(db, normalized)
            # A new own product wins for its EAN: its empty fields come from the
            # stored foods of that EAN and are part of this change.
            if (
                previous is None
                and saved.get("barcode")
                and self._products.fill_from_database_entries(
                    db, saved["id"], saved["barcode"]
                )
            ):
                saved = self._products.get(db, saved["id"]) or saved
            change_history.record_change(
                db,
                PRODUCT_ENTITY_TYPE,
                saved["id"],
                "update" if previous else "create",
                previous,
                saved,
            )
            return saved

    def update_product(
        self, product_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        current = self.get_product(product_id)
        merged = {**current, **(payload if isinstance(payload, dict) else {})}
        if merged.get("confidence") is None:
            # The stored value is the product's own; an edit without one keeps it.
            merged["confidence"] = current.get("extraction_confidence")
        merged["id"] = str(product_id)
        return self.save_product(merged)

    def set_favorite(self, product_id: str, favorite: Any) -> dict[str, Any]:
        if not isinstance(favorite, bool):
            raise AppError(400, "favorite muss true oder false sein.")
        product_id = str(product_id or "").strip()
        with self._db_lock, self._database_manager.unit_of_work() as db:
            if not self._products.set_favorite(db, product_id, favorite):
                raise AppError(
                    404, PRODUCT_NOT_FOUND, reason="nutrition_product_not_found"
                )
            product = self._products.get(db, product_id)
        return product or {"id": product_id, "favorite": int(favorite)}

    def archive_product(self, product_id: str) -> dict[str, Any]:
        product_id = str(product_id or "").strip()
        with self._db_lock, self._database_manager.unit_of_work() as db:
            previous = self._products.get(db, product_id)
            if not self._products.archive(db, product_id, self._utc_now()):
                raise AppError(
                    404, PRODUCT_NOT_FOUND, reason="nutrition_product_not_found"
                )
            archived = self._products.get(db, product_id)
            change_history.record_change(
                db, PRODUCT_ENTITY_TYPE, product_id, "update", previous, archived
            )
            return archived or {"id": product_id, "status": "archived"}

    def lookup_product(
        self, arguments: dict[str, Any], *, online_fallback: bool = True
    ) -> dict[str, Any]:
        barcode = str(arguments.get("barcode") or "").strip()
        query = str(arguments.get("query") or arguments.get("q") or "").strip()
        if barcode:
            local = self.list_products(barcode=barcode)
            if local:
                return {
                    "ok": True,
                    "foods": local,
                    "product": local[0],
                    "local": True,
                    "source": "local",
                }
            result = self.food_database.lookup({"barcode": barcode})
            remote = (result.get("foods") or [None])[0]
            return {
                **result,
                "product": remote,
                "local": False,
                "source": "yazio"
                if str((remote or {}).get("id", "")).startswith("yazio:")
                else "open_food_facts",
            }
        if len(query) < 2:
            raise AppError(400, "Suchbegriff muss mindestens 2 Zeichen enthalten.")
        local = self.list_products(query=query)
        if local:
            return {
                "ok": True,
                "foods": local,
                "product": local[0],
                "local": True,
                "source": "local",
            }
        if online_fallback:
            result = self.food_database.lookup({**arguments, "query": query})
            return {
                **result,
                "product": (result.get("foods") or [None])[0],
                "local": False,
            }
        return {
            "ok": True,
            "foods": [],
            "product": None,
            "local": True,
            "source": "local",
        }

    def calculate_product(
        self, product_id: str, amount: Any, unit: str
    ) -> dict[str, Any]:
        product = self.get_product(product_id)
        if product.get("status") != "active":
            raise AppError(
                409,
                "Archivierte Produkte k\u00f6nnen nicht erfasst werden.",
                reason="nutrition_product_archived",
            )
        try:
            quantity = nutrition_number(amount)
        except (TypeError, ValueError) as exc:
            raise AppError(400, "Ung\u00fcltige Produktmenge.") from exc
        if not math.isfinite(quantity) or not 0 < quantity <= 10000:
            raise AppError(400, "Produktmenge muss zwischen 0 und 10000 liegen.")
        if unit != product["basis_unit"]:
            raise AppError(
                400,
                "Gramm und Milliliter d\u00fcrfen ohne bekannte Dichte nicht umgerechnet werden.",
                reason="food_unit_mismatch",
            )
        ratio = quantity / float(product["basis_amount"])
        nutrients = {
            key: None
            if product.get(key) is None
            else round(float(product[key]) * ratio, 1)
            for key in ("kcal", "carbs_g", "protein_g", "fat_g")
        }
        return {
            "ok": True,
            "product": product,
            "amount": quantity,
            "unit": unit,
            **nutrients,
            "nutrition_basis": {
                "kind": "local_product",
                "product": product,
                "amount": quantity,
                "unit": unit,
            },
        }

    def calculate_components(self, components: Any) -> dict[str, Any]:
        resolved = self._component_calculator.prepare_resolutions(components)
        with self._db_lock, self._database_manager.unit_of_work() as db:
            return self._component_calculator.calculate(db, components, resolved)

    def normalize_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise AppError(400, "Produkt muss ein Objekt sein.")
        extracted = validate_packaging_extraction(
            {**payload, "source": payload.get("source", "packaging_label")}
        )
        candidate = extracted["candidate"]
        if not candidate.get("basis_amount") or not candidate.get("basis_unit"):
            raise AppError(
                400,
                "Bezugsmenge und Einheit sind erforderlich.",
                reason="invalid_food_extraction",
            )
        source = str(payload.get("source") or "packaging_label").strip().lower()
        if source not in {
            "packaging_label",
            "manual",
            "open_food_facts",
            "yazio",
            "bls",
            "fddb_export",
        }:
            raise AppError(400, "Ung\u00fcltige Produktquelle.")
        now = self._utc_now()
        source_url = str(payload.get("source_url") or "")[:500]
        external_id = str(payload.get("external_id") or "")[:200]
        extraction_confidence = candidate.get("confidence")
        return {
            **candidate,
            "id": str(payload.get("id") or uuid.uuid4().hex),
            "source": source,
            "provenance": {
                "kind": source,
                "source_url": source_url or None,
                "external_id": external_id or None,
                "extraction_confidence": extraction_confidence,
            },
            "extraction_confidence": extraction_confidence,
            "source_url": source_url,
            "external_id": external_id,
            "status": str(payload.get("status") or "active")
            if payload.get("status") in {"active", "archived"}
            else "active",
            "created_at": str(payload.get("created_at") or now),
            "updated_at": now,
        }

    def current(
        self, db: Any, entity_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """The stored product of one recorded change, for change history."""
        value = self._products.get(db, entity_id)
        return value, change_history.audit_projection(PRODUCT_ENTITY_TYPE, value)

    def restore_in_transaction(
        self,
        db: Any,
        entity_id: str,
        current: dict[str, Any] | None,
        target: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Put one product back as recorded, validated like a new save.

        Diary entries and saved meals keep their own nutrient snapshots, so they
        are left as they are; a barcode taken since is refused.
        """
        if target is None:
            # Undo of a created product.
            self._products.delete(db, entity_id)
            return None
        # The target holds only changed fields, so a stored None would be missing.
        merged = {
            **dict.fromkeys(change_history.NUTRITION_PRODUCT_FIELDS),
            **(current or {}),
            **target,
            "id": entity_id,
        }
        merged["confidence"] = merged.get("extraction_confidence")
        restored = self.normalize_product(merged)
        if restored.get("barcode"):
            taken = self._products.list(
                db, barcode=restored["barcode"], include_archived=True
            )
            if taken and taken[0]["id"] != entity_id:
                raise AppError(
                    409,
                    "Diese EAN ist bereits einem lokalen Produkt zugeordnet.",
                    reason="nutrition_product_barcode_conflict",
                )
        return self._products.save(db, restored)
