"""Trusted nutrient calculation for mixed-origin meal components."""

from __future__ import annotations

import math
from typing import Any

from backend.db.repositories import NutritionProductRepository
from backend.errors import AppError
from backend.nutrition.food_database import NUTRIENTS, FoodDatabaseService

PRODUCT_NOT_FOUND = "Produkt nicht gefunden."


class MealComponentCalculator:
    def __init__(
        self,
        products: NutritionProductRepository,
        food_database: FoodDatabaseService,
    ) -> None:
        self._products = products
        self._food_database = food_database

    def prepare_resolutions(self, components: Any) -> dict[int, dict[str, Any]]:
        if not isinstance(components, list) or not 1 <= len(components) <= 20:
            raise AppError(400, "1 bis 20 Mahlzeitenkomponenten sind erforderlich.")
        resolved: dict[int, dict[str, Any]] = {}
        for index, item in enumerate(components):
            kind, _quantity, _unit = self._validate_component_header(item)
            if kind == "database":
                if set(item) != {"kind", "food_id", "amount", "unit"}:
                    raise AppError(
                        400, "Datenbankkomponente enth\u00e4lt ung\u00fcltige Felder."
                    )
                resolved[index] = self._food_database.resolve(item["food_id"])
        return resolved

    def calculate(
        self,
        db: Any,
        components: Any,
        resolved: dict[int, dict[str, Any]] | None,
    ) -> dict[str, Any]:
        if not isinstance(components, list) or not 1 <= len(components) <= 20:
            raise AppError(400, "1 bis 20 Mahlzeitenkomponenten sind erforderlich.")
        totals: dict[str, float | None] = {key: 0.0 for key in NUTRIENTS}
        snapshots = []
        for index, item in enumerate(components):
            snapshot = self._resolve_component(db, item, (resolved or {}).get(index))
            for key in NUTRIENTS:
                value, current = snapshot[key], totals[key]
                totals[key] = (
                    None if value is None or current is None else current + value
                )
            snapshots.append(snapshot)
        self._validate_totals(totals)
        rounded = {
            key: None
            if value is None
            else round(value)
            if key == "kcal"
            else round(value, 1)
            for key, value in totals.items()
        }
        return {
            **rounded,
            "nutrition_basis": {
                "kind": "composite",
                "version": 1,
                "components": snapshots,
            },
        }

    def _resolve_component(
        self, db: Any, item: Any, resolved_food: dict[str, Any] | None
    ) -> dict[str, Any]:
        kind, quantity, unit = self._validate_component_header(item)
        if kind == "local_product":
            name, nutrients, origin = self._resolve_local_product(
                db, item, quantity, unit
            )
        elif kind == "database":
            name, nutrients, origin = self._resolve_database(
                item, quantity, unit, resolved_food
            )
        else:
            name, nutrients, origin = self._resolve_manual(item, kind)
        return {
            "kind": kind,
            "name": name,
            "amount": quantity,
            "unit": unit,
            **nutrients,
            "nutrition_basis": origin,
        }

    @staticmethod
    def _validated_quantity(amount: Any) -> float:
        if isinstance(amount, bool) or not isinstance(amount, (int, float, str)):
            raise AppError(400, "Ung\u00fcltige Komponentenmenge.")
        try:
            quantity = float(amount)
        except TypeError, ValueError:
            raise AppError(400, "Ung\u00fcltige Komponentenmenge.") from None
        if not math.isfinite(quantity) or not 0 < quantity <= 10000:
            raise AppError(400, "Komponentenmenge muss gr\u00f6\u00dfer als 0 sein.")
        return quantity

    @staticmethod
    def _validate_component_header(item: Any) -> tuple[str, float, str]:
        kinds = {"local_product", "database", "estimate", "packaging_label", "manual"}
        kind = item.get("kind") if isinstance(item, dict) else None
        if not isinstance(kind, str) or kind not in kinds:
            raise AppError(400, "Ung\u00fcltige Mahlzeitenkomponente.")
        if kind in {"local_product", "database"}:
            key = "product_id" if kind == "local_product" else "food_id"
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise AppError(400, "Komponentenreferenz muss eine Zeichenkette sein.")
        quantity = MealComponentCalculator._validated_quantity(item.get("amount"))
        unit = item.get("unit")
        if not isinstance(unit, str) or unit not in {"g", "ml", "portion"}:
            raise AppError(400, "Einheit muss g, ml oder portion sein.")
        return kind, quantity, unit

    def _resolve_local_product(
        self, db: Any, item: dict[str, Any], quantity: float, unit: str
    ) -> tuple[str, dict[str, float | None], dict[str, Any]]:
        if set(item) != {"kind", "product_id", "amount", "unit"}:
            raise AppError(
                400, "Lokale Produktkomponente enth\u00e4lt ung\u00fcltige Felder."
            )
        product = self._products.get(db, item["product_id"])
        if not product:
            raise AppError(404, PRODUCT_NOT_FOUND, reason="nutrition_product_not_found")
        if product.get("status") != "active":
            raise AppError(
                409,
                "Archivierte Produkte k\u00f6nnen nicht erfasst werden.",
                reason="nutrition_product_archived",
            )
        if unit != product["basis_unit"]:
            raise AppError(
                400,
                "Komponenteneinheit stimmt nicht mit dem Produkt \u00fcberein.",
                reason="food_unit_mismatch",
            )
        ratio = quantity / float(product["basis_amount"])
        nutrients = {
            key: None if product.get(key) is None else float(product[key]) * ratio
            for key in NUTRIENTS
        }
        if nutrients["kcal"] is None:
            raise AppError(
                400,
                "F\u00fcr dieses Produkt fehlt der Kalorienwert.",
                reason="food_energy_missing",
            )
        return product["name"], nutrients, {"kind": "local_product", "product": product}

    def _resolve_database(
        self,
        item: dict[str, Any],
        quantity: float,
        unit: str,
        resolved_food: dict[str, Any] | None,
    ) -> tuple[str, dict[str, float | None], dict[str, Any]]:
        if set(item) != {"kind", "food_id", "amount", "unit"}:
            raise AppError(
                400, "Datenbankkomponente enth\u00e4lt ung\u00fcltige Felder."
            )
        food = resolved_food or self._food_database.resolve(item["food_id"])
        if unit != food.get("basis_unit"):
            raise AppError(
                400,
                "Komponenteneinheit stimmt nicht mit der Datenbank \u00fcberein.",
                reason="food_unit_mismatch",
            )
        nutrients = {
            key: None
            if food["per_100"].get(key) is None
            else float(food["per_100"][key]) * quantity / 100
            for key in NUTRIENTS
        }
        if nutrients["kcal"] is None:
            raise AppError(
                400,
                "Kalorienwert fehlt; als Sch\u00e4tzung kennzeichnen.",
                reason="food_energy_missing",
            )
        return food["name"], nutrients, {"kind": "database", "food": food}

    def _resolve_manual(
        self, item: dict[str, Any], kind: str
    ) -> tuple[str, dict[str, float | None], dict[str, str]]:
        required = {
            "kind",
            "name",
            "amount",
            "unit",
            "kcal",
            "carbs_g",
            "protein_g",
            "fat_g",
        }
        if (
            set(item) != required
            or not isinstance(item.get("name"), str)
            or not item["name"].strip()
        ):
            raise AppError(
                400,
                "Manuelle Komponente ben\u00f6tigt Name und alle N\u00e4hrwertfelder.",
            )
        name = item["name"].strip()[:200]
        nutrients = {key: self._validate_nutrient(key, item[key]) for key in NUTRIENTS}
        if nutrients["kcal"] is None:
            raise AppError(
                400, "Kalorienwert ist erforderlich.", reason="food_energy_missing"
            )
        return name, nutrients, {"kind": kind}

    @staticmethod
    def _validate_nutrient(key: str, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise AppError(400, "Ung\u00fcltiger N\u00e4hrwert.")
        try:
            number = float(value)
        except TypeError, ValueError:
            raise AppError(400, "Ung\u00fcltiger N\u00e4hrwert.") from None
        if not math.isfinite(number) or number < 0:
            raise AppError(400, "N\u00e4hrwert muss endlich und nicht negativ sein.")
        if number > (10000 if key == "kcal" else 1000):
            raise AppError(
                400, "N\u00e4hrwert \u00fcberschreitet das zul\u00e4ssige Maximum."
            )
        return number

    @staticmethod
    def _validate_totals(totals: dict[str, float | None]) -> None:
        if totals["kcal"] is not None and totals["kcal"] > 10000:
            raise AppError(400, "Kalorien m\u00fcssen zwischen 0 und 10000 liegen.")
        if any(
            value is not None and value > 1000
            for key, value in totals.items()
            if key != "kcal"
        ):
            raise AppError(
                400, "Makron\u00e4hrwerte \u00fcberschreiten das Maximum von 1000 g."
            )
