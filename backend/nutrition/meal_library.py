"""Saved meals, food products, and component calculations."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Any

from backend import change_history
from backend.db.manager import DatabaseManager
from backend.db.repositories import (
    NutritionProductRepository,
    NutritionTemplateRepository,
)
from backend.errors import AppError
from backend.nutrition.catalog import ProductCatalogService
from backend.nutrition.components import MealComponentCalculator
from backend.nutrition.food_database import NUTRIENTS, FoodDatabaseService
from backend.nutrition.models import normalize_nutrition_entry
from backend.nutrition.photo import (
    NutritionPhotoExtractionService,
    validate_packaging_extraction,
)
from backend.nutrition.web_search import NutritionWebSearchService

SAVED_MEAL_NOT_FOUND = "Gespeicherte Mahlzeit nicht gefunden."
TEMPLATE_ENTITY_TYPE = "nutrition_template"


def validate_component_payload(payload: dict[str, Any]) -> None:
    forbidden = (
        {"product_id", "food_ingredients", "nutrition_basis"}
        | set(NUTRIENTS)
        | {"calories", "carbs", "carbohydrates", "protein", "fat"}
    )
    if forbidden & payload.keys():
        raise AppError(
            400,
            "Komponenten dürfen nicht mit Einzelzutaten, Summenwerten oder clientseitiger Herkunft kombiniert werden.",
        )


class NutritionMealLibraryService:
    """Manage reusable meals and the trusted food catalog."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        utc_now: Callable[[], str],
        local_now: Callable[[], datetime],
        food_database: FoodDatabaseService,
        photo_extractor: NutritionPhotoExtractionService | None = None,
        product_repository: NutritionProductRepository | None = None,
        template_repository: NutritionTemplateRepository | None = None,
        web_search: NutritionWebSearchService | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._utc_now = utc_now
        self._local_now = local_now
        self.food_database = food_database
        self._products = product_repository or NutritionProductRepository()
        self._templates = template_repository or NutritionTemplateRepository()
        self._component_calculator = MealComponentCalculator(
            self._products, self.food_database
        )
        self._product_catalog = ProductCatalogService(
            database_manager,
            self._products,
            utc_now,
            self.food_database,
            self._component_calculator,
            web_search.search if web_search else None,
        )
        self._photo_extractor = photo_extractor

    @property
    def product_catalog(self) -> ProductCatalogService:
        return self._product_catalog

    @property
    def component_calculator(self) -> MealComponentCalculator:
        return self._component_calculator

    def list_database_foods(self, query: str | None = None) -> list[dict[str, Any]]:
        return self.food_database.stored_foods(query)

    def refresh_database_food(self, product_id: str) -> dict[str, Any]:
        """Re-check a stored food, or an own product by its EAN."""
        with self._database_manager.reader() as db:
            own = self._products.get(db, product_id)
        if own and own.get("status") != "active":
            raise AppError(
                409,
                "Archivierte Produkte werden nicht aktualisiert.",
                reason="nutrition_product_archived",
            )
        if own:
            return self._product_catalog.refresh_product(own)
        return {"ok": True, "food": self.food_database.refresh_stored(product_id)}

    def forget_database_food(self, food_id: str) -> dict[str, Any]:
        self.food_database.forget(food_id)
        return {"ok": True, "id": food_id, "status": "removed"}

    def extract_packaging_photo(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise AppError(400, "Ungültiger Fotoinhalt.")
        if payload.get("image_data_url"):
            if not self._photo_extractor:
                raise AppError(
                    503,
                    "Fotoerkennung ist nicht verfügbar.",
                    reason="provider_unavailable",
                )
            result = self._photo_extractor.extract(payload["image_data_url"])
        else:
            result = validate_packaging_extraction(payload)
        return {**result, "extraction": result["candidate"]}

    def prepare_values(
        self,
        payload: dict[str, Any],
        calculation: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Normalize nutrient values; pass a precomputed food calculation to
        keep network lookups outside the caller's unit of work."""
        packaging_label = payload.get("packaging_label") is True
        payload = {
            key: value
            for key, value in payload.items()
            if key not in {"nutrition_basis", "packaging_label"}
        }
        if "food_ingredients" in payload:
            if calculation is None:
                calculation = self.food_database.calculate(payload["food_ingredients"])
            return {**payload, **calculation}
        if packaging_label:
            kind = "packaging_label"
        elif payload.get("source") in {"coach", "photo", "voice"}:
            kind = "estimate"
        else:
            kind = "manual"
        return {**payload, "nutrition_basis": {"kind": kind}}

    def list_templates(self) -> list[dict[str, Any]]:
        with self._database_manager.reader() as db:
            return self._templates.list(db)

    def get_template(self, template_id: str) -> dict[str, Any]:
        with self._database_manager.unit_of_work() as db:
            template = self.get_template_in_transaction(db, template_id)
        if not template:
            raise AppError(404, SAVED_MEAL_NOT_FOUND)
        return template

    def get_template_in_transaction(
        self, db: Any, template_id: str
    ) -> dict[str, Any] | None:
        return self._templates.get(db, template_id)

    def save_template(
        self, payload: Any, *, expected_calculation: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Save a confirmed recipe for one portion without recording consumption."""
        if not isinstance(payload, dict):
            raise AppError(400, "Mahlzeit muss ein Objekt sein.")
        prepared = payload
        template_id = str(payload.get("id") or "").strip()
        resolved_database = (
            self._component_calculator.prepare_resolutions(payload["components"])
            if "components" in payload
            else None
        )
        calculation = (
            self.food_database.calculate(payload["food_ingredients"])
            if "food_ingredients" in payload and "components" not in payload
            else None
        )
        with self._database_manager.unit_of_work() as db:
            if "components" in payload:
                validate_component_payload(payload)
                prepared = {
                    **payload,
                    **self._component_calculator.calculate(
                        db, payload["components"], resolved_database
                    ),
                }
                prepared.pop("components", None)
            elif "food_ingredients" in payload:
                prepared = self.prepare_values(payload, calculation)
            if expected_calculation is not None and any(
                prepared.get(key) != value
                for key, value in expected_calculation.items()
            ):
                raise AppError(
                    409,
                    "Berechnung hat sich seit der Vorschau geändert.",
                    reason="food_calculation_changed",
                )
            existing = self._templates.get(db, template_id) if template_id else None
            if template_id and not existing:
                raise AppError(404, SAVED_MEAL_NOT_FOUND)
            name = str(
                payload.get("name") or (existing or {}).get("name") or ""
            ).strip()
            self._validate_template_name(db, name, template_id, existing)
            template = self._build_template(
                payload, prepared, existing, name, template_id
            )
            self._templates.save(db, template)
            change_history.record_change(
                db,
                TEMPLATE_ENTITY_TYPE,
                template["id"],
                "update" if existing else "create",
                existing,
                template,
            )
            return template

    def _build_template(
        self,
        payload: dict[str, Any],
        prepared: dict[str, Any],
        existing: dict[str, Any] | None,
        name: str,
        template_id: str,
    ) -> dict[str, Any]:
        values = {**(existing or {}), **payload}
        values = (
            {**values, **prepared}
            if "food_ingredients" in payload or "components" in payload
            else self.prepare_values(values)
        )
        values.pop("components", None)
        normalized = normalize_nutrition_entry(
            values, local_now_factory=self._local_now
        )
        nutrients_unchanged = not any(
            key in payload and payload[key] != (existing or {}).get(key)
            for key in NUTRIENTS
        )
        if (
            existing
            and "food_ingredients" not in payload
            and "components" not in payload
            and nutrients_unchanged
            and payload.get("packaging_label") is not True
        ):
            normalized["nutrition_basis"] = existing.get(
                "nutrition_basis", {"kind": "manual"}
            )
        fields = (
            "description",
            "meal_type",
            "kcal",
            "carbs_g",
            "protein_g",
            "fat_g",
            "source",
            "nutrition_basis",
        )
        template = {key: normalized[key] for key in fields}
        template["meal_type_explicit"] = "meal_type" in payload or bool(
            existing and existing.get("meal_type_explicit")
        )
        template.update(
            id=template_id or uuid.uuid4().hex, name=name, updated_at=self._utc_now()
        )
        return template

    def _validate_template_name(
        self,
        db: Any,
        name: str,
        template_id: str,
        existing: dict[str, Any] | None,
    ) -> None:
        if not name or len(name) > 120:
            raise AppError(400, "Mahlzeitname muss 1 bis 120 Zeichen enthalten.")
        templates = self._templates.list(db)
        if any(
            item["name"].casefold() == name.casefold() and item["id"] != template_id
            for item in templates
        ):
            raise AppError(
                409,
                "Dieser Mahlzeitname ist bereits vergeben. Lies die Vorlage und ändere sie gezielt.",
            )
        if not existing and len(templates) >= 200:
            raise AppError(400, "Maximal 200 gespeicherte Mahlzeiten sind möglich.")

    def delete_template(self, template_id: str) -> dict[str, Any]:
        with self._database_manager.unit_of_work() as db:
            existing = self._templates.get(db, template_id)
            if not existing or not self._templates.delete(db, template_id):
                raise AppError(404, SAVED_MEAL_NOT_FOUND)
            record = change_history.record_change(
                db, TEMPLATE_ENTITY_TYPE, template_id, "delete", existing, None
            )
        result: dict[str, Any] = {"deleted_id": template_id}
        if record:
            result["change"] = {
                field: record[field] for field in change_history.UNDO_REFERENCE_FIELDS
            }
        return result

    def current(
        self, db: Any, entity_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """The stored saved meal of one recorded change, for change history."""
        value = self._templates.get(db, entity_id)
        return value, change_history.audit_projection(TEMPLATE_ENTITY_TYPE, value)

    def restore_in_transaction(
        self,
        db: Any,
        entity_id: str,
        current: dict[str, Any] | None,
        target: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Put one saved meal back as recorded; a taken name is refused."""
        if target is None:
            # Undo of a created meal.
            self._templates.delete(db, entity_id)
            return None
        template = {
            # A field recorded as None before a delete is absent from the diff.
            **dict.fromkeys(change_history.NUTRITION_TEMPLATE_FIELDS),
            **(current or {}),
            **target,
            "id": entity_id,
            "updated_at": self._utc_now(),
        }
        self._validate_template_name(db, template["name"], entity_id, current)
        self._templates.save(db, template)
        return template
