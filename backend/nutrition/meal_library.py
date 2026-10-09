"""Saved meals, food products, and component calculations."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any

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
from backend.nutrition.photo import NutritionPhotoExtractionService
from backend.nutrition.photo_service import PhotoExtractionService

SAVED_MEAL_NOT_FOUND = "Gespeicherte Mahlzeit nicht gefunden."


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
        db_lock: AbstractContextManager[Any],
        utc_now: Callable[[], str],
        local_now: Callable[[], datetime],
        food_database: FoodDatabaseService,
        photo_extractor: NutritionPhotoExtractionService | None = None,
        product_repository: NutritionProductRepository | None = None,
        template_repository: NutritionTemplateRepository | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._db_lock = db_lock
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
            db_lock,
            self._products,
            utc_now,
            self.food_database,
            self._component_calculator,
        )
        self._photo_service = PhotoExtractionService(photo_extractor)

    def list_products(
        self,
        *,
        query: str | None = None,
        barcode: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        return self._product_catalog.list_products(
            query=query, barcode=barcode, include_archived=include_archived
        )

    def get_product(self, product_id: str) -> dict[str, Any]:
        return self._product_catalog.get_product(product_id)

    def save_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._product_catalog.save_product(payload)

    def update_product(
        self, product_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self._product_catalog.update_product(product_id, payload)

    def archive_product(self, product_id: str) -> dict[str, Any]:
        return self._product_catalog.archive_product(product_id)

    def lookup_product(
        self, arguments: dict[str, Any], *, online_fallback: bool = True
    ) -> dict[str, Any]:
        return self._product_catalog.lookup_product(
            arguments, online_fallback=online_fallback
        )

    def extract_packaging_photo(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._photo_service.extract_packaging_photo(payload)

    def calculate_product(
        self, product_id: str, amount: Any, unit: str
    ) -> dict[str, Any]:
        return self._product_catalog.calculate_product(product_id, amount, unit)

    def calculate_components(self, components: Any) -> dict[str, Any]:
        """Resolve a meal recipe into immutable, trusted nutrient snapshots."""
        return self._product_catalog.calculate_components(components)

    def prepare_component_resolutions(
        self, components: Any
    ) -> dict[int, dict[str, Any]]:
        return self._component_calculator.prepare_resolutions(components)

    def calculate_components_in_transaction(
        self,
        db: Any,
        components: Any,
        resolutions: dict[int, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return self._component_calculator.calculate(db, components, resolutions)

    def prepare_values(self, payload: dict[str, Any]) -> dict[str, Any]:
        packaging_label = payload.get("packaging_label") is True
        payload = {
            key: value
            for key, value in payload.items()
            if key not in {"nutrition_basis", "packaging_label"}
        }
        if "food_ingredients" in payload:
            return {
                **payload,
                **self.food_database.calculate(payload["food_ingredients"]),
            }
        kind = (
            "packaging_label"
            if packaging_label
            else "estimate"
            if payload.get("source") in {"coach", "photo", "voice"}
            else "manual"
        )
        return {**payload, "nutrition_basis": {"kind": kind}}

    def list_templates(self) -> list[dict[str, Any]]:
        with self._db_lock, self._database_manager.unit_of_work() as db:
            return self._templates.list(db)

    def get_template(self, template_id: str) -> dict[str, Any]:
        with self._db_lock, self._database_manager.unit_of_work() as db:
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
            self.prepare_component_resolutions(payload["components"])
            if "components" in payload
            else None
        )
        with self._db_lock, self._database_manager.unit_of_work() as db:
            if "components" in payload:
                validate_component_payload(payload)
                prepared = {
                    **payload,
                    **self.calculate_components_in_transaction(
                        db, payload["components"], resolved_database
                    ),
                }
                prepared.pop("components", None)
            elif "food_ingredients" in payload:
                prepared = self.prepare_values(payload)
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
        with self._db_lock, self._database_manager.unit_of_work() as db:
            if not self._templates.delete(db, template_id):
                raise AppError(404, SAVED_MEAL_NOT_FOUND)
        return {"deleted_id": template_id}
