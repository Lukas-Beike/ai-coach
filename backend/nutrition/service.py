"""Nutrition domain service orchestrating meal tracking, summaries and sync states."""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Any

from backend.db.manager import DatabaseManager
from backend.db.repositories import (
    NutritionProductRepository,
    NutritionRepository,
    NutritionTemplateRepository,
)
from backend.errors import AppError
from backend.nutrition.food_database import NUTRIENTS, FoodDatabaseService
from backend.nutrition.models import (
    NutritionDaySummary,
    NutritionEntry,
    normalize_nutrition_entry,
    validate_iso_date,
)
from backend.nutrition.photo import (
    NutritionPhotoExtractionService,
    validate_packaging_extraction,
)

PRODUCT_NOT_FOUND = "Produkt nicht gefunden."

SAVED_MEAL_NOT_FOUND = "Gespeicherte Mahlzeit nicht gefunden."
INVALID_ENTRY_ID = "Ungültige Eintrags-ID."
ENTRY_NOT_FOUND = "Ernährungseintrag nicht gefunden."


NUTRITION_APPROVAL_FIELDS = (
    "date",
    "revision",
    "total_kcal",
    "total_carbs_g",
    "total_protein_g",
    "total_fat_g",
    "entry_count",
)
NUTRIENT_INPUT_ALIASES = {"calories", "carbs", "carbohydrates", "protein", "fat"}


def _known_daily_total(entries: list[dict[str, Any]], field: str) -> float | None:
    if any(entry.get(field) is None for entry in entries):
        return None
    return round(sum(float(entry[field]) for entry in entries), 1)


def _validate_component_payload(payload: dict[str, Any]) -> None:
    forbidden = (
        {"product_id", "food_ingredients", "nutrition_basis"}
        | set(NUTRIENTS)
        | NUTRIENT_INPUT_ALIASES
    )
    if forbidden & payload.keys():
        raise AppError(
            400,
            "Komponenten dürfen nicht mit Einzelzutaten, Summenwerten oder clientseitiger Herkunft kombiniert werden.",
        )


def nutrition_approval_item(snapshot: dict[str, Any]) -> dict[str, Any]:
    item = {
        "date": str(snapshot["date"]),
        "revision": int(snapshot.get("sync_revision") or 0),
        "total_kcal": int(snapshot.get("total_kcal") or 0),
        "total_carbs_g": snapshot.get("total_carbs_g"),
        "total_protein_g": snapshot.get("total_protein_g"),
        "total_fat_g": snapshot.get("total_fat_g"),
        "entry_count": int(snapshot.get("entry_count") or 0),
    }
    digest_values = {
        key: item[key] for key in NUTRITION_APPROVAL_FIELDS if key != "revision"
    }
    serialized = json.dumps(
        digest_values, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return {**item, "sha256": hashlib.sha256(serialized).hexdigest()}


def nutrition_approval_item_matches(
    expected: dict[str, Any], actual: dict[str, Any]
) -> bool:
    if expected == actual:
        return True
    return (
        expected.get("revision") == 0
        and actual.get("revision") == 1
        and expected.get("entry_count") == actual.get("entry_count") == 0
        and expected.get("sha256") == actual.get("sha256")
    )


class NutritionService:
    """Orchestrates nutrition logging, daily aggregations and sync markers."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        db_lock: AbstractContextManager[Any],
        nutrition_repository: NutritionRepository,
        utc_now: Callable[[], str],
        local_now: Callable[[], datetime],
        food_database: FoodDatabaseService | None = None,
        fueling_service: Callable[[], Any] | None = None,
        photo_extractor: NutritionPhotoExtractionService | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._db_lock = db_lock
        self._nutrition_repository = nutrition_repository
        self._utc_now = utc_now
        self._local_now = local_now
        self._templates = NutritionTemplateRepository()
        self._products = NutritionProductRepository()
        self._photo_extractor = photo_extractor
        self.food_database = food_database or FoodDatabaseService()
        self._fueling_service = fueling_service

    def list_products(
        self,
        *,
        query: str | None = None,
        barcode: str | None = None,
        include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        with self._db_lock, self._database_manager.unit_of_work() as db:
            return self._products.list(
                db, query=query, barcode=barcode, include_archived=include_archived
            )

    def get_product(self, product_id: str) -> dict[str, Any]:
        with self._db_lock, self._database_manager.unit_of_work() as db:
            product = self._products.get(db, str(product_id or "").strip())
        if not product:
            raise AppError(
                404, PRODUCT_NOT_FOUND, reason="nutrition_product_not_found"
            )
        return product

    def save_product(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_product(payload)
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
            return self._products.save(db, normalized)

    def update_product(
        self, product_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        current = self.get_product(product_id)
        merged = {**current, **(payload if isinstance(payload, dict) else {})}
        merged["id"] = str(product_id)
        return self.save_product(merged)

    def archive_product(self, product_id: str) -> dict[str, Any]:
        product_id = str(product_id or "").strip()
        with self._db_lock, self._database_manager.unit_of_work() as db:
            if not self._products.archive(db, product_id, self._utc_now()):
                raise AppError(
                    404, PRODUCT_NOT_FOUND, reason="nutrition_product_not_found"
                )
            return self._products.get(db, product_id) or {
                "id": product_id,
                "status": "archived",
            }

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
                "source": "open_food_facts",
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

    def calculate_product(
        self, product_id: str, amount: Any, unit: str
    ) -> dict[str, Any]:
        product = self.get_product(product_id)
        if product.get("status") != "active":
            raise AppError(
                409,
                "Archivierte Produkte können nicht erfasst werden.",
                reason="nutrition_product_archived",
            )
        try:
            quantity = float(amount)
        except (TypeError, ValueError) as exc:
            raise AppError(400, "Ungültige Produktmenge.") from exc
        if not math.isfinite(quantity) or not 0 < quantity <= 10000:
            raise AppError(400, "Produktmenge muss zwischen 0 und 10000 liegen.")
        if unit != product["basis_unit"]:
            raise AppError(
                400,
                "Gramm und Milliliter dürfen ohne bekannte Dichte nicht umgerechnet werden.",
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
        """Resolve a flat meal recipe into immutable, trusted nutrient snapshots."""
        if not isinstance(components, list) or not 1 <= len(components) <= 20:
            raise AppError(400, "1 bis 20 Mahlzeitenkomponenten sind erforderlich.")
        with self._db_lock, self._database_manager.unit_of_work() as db:
            return self._calculate_components(db, components)

    def _calculate_components(self, db: Any, components: list[Any]) -> dict[str, Any]:
        if not isinstance(components, list) or not 1 <= len(components) <= 20:
            raise AppError(400, "1 bis 20 Mahlzeitenkomponenten sind erforderlich.")
        totals, snapshots = self._resolve_component_totals(db, components)
        self._validate_component_totals(totals)
        rounded = self._round_component_totals(totals)
        return {
            **rounded,
            "nutrition_basis": {
                "kind": "composite",
                "version": 1,
                "components": snapshots,
            },
        }

    def _resolve_component_totals(self, db: Any, components: list[Any]) -> tuple[dict[str, float | None], list[dict[str, Any]]]:
        totals: dict[str, float | None] = {key: 0.0 for key in NUTRIENTS}
        snapshots = []
        for item in components:
            snapshot = self._resolve_component(db, item)
            for key in NUTRIENTS:
                value, current = snapshot[key], totals[key]
                totals[key] = None if value is None or current is None else current + value
            snapshots.append(snapshot)
        return totals, snapshots

    @staticmethod
    def _validate_component_totals(totals: dict[str, float | None]) -> None:
        if totals["kcal"] is not None and totals["kcal"] > 10000:
            raise AppError(400, "Kalorien müssen zwischen 0 und 10000 liegen.")
        if any(value is not None and value > 1000 for key, value in totals.items() if key != "kcal"):
            raise AppError(400, "Makronährwerte überschreiten das Maximum von 1000 g.")

    @staticmethod
    def _round_component_totals(totals: dict[str, float | None]) -> dict[str, float | None]:
        return {key: None if value is None else round(value) if key == "kcal" else round(value, 1) for key, value in totals.items()}

    def _resolve_component(self, db: Any, item: Any) -> dict[str, Any]:
        kind, quantity, unit = self._validate_component_header(item)

        if kind == "local_product":
            name, nutrients, origin = self._resolve_local_product_component(
                db, item, quantity, unit
            )
        elif kind == "database":
            name, nutrients, origin = self._resolve_database_component(
                item, quantity, unit
            )
        else:
            name, nutrients, origin = self._resolve_manual_component(item, kind)
        return {
            "kind": kind,
            "name": name,
            "amount": quantity,
            "unit": unit,
            **nutrients,
            "nutrition_basis": origin,
        }

    @staticmethod
    def _validate_component_header(item: Any) -> tuple[str, float, str]:
        kinds = {"local_product", "database", "estimate", "packaging_label", "manual"}
        kind = item.get("kind") if isinstance(item, dict) else None
        if not isinstance(kind, str) or kind not in kinds:
            raise AppError(400, "Ungültige Mahlzeitenkomponente.")
        NutritionService._validate_component_reference(item, kind)
        amount = item.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, (int, float, str)):
            raise AppError(400, "Ungültige Komponentenmenge.")
        try:
            quantity = float(amount)
        except (TypeError, ValueError):
            raise AppError(400, "Ungültige Komponentenmenge.") from None
        if not math.isfinite(quantity) or not 0 < quantity <= 10000:
            raise AppError(400, "Komponentenmenge muss größer als 0 sein.")
        unit = item.get("unit")
        if not isinstance(unit, str) or unit not in {"g", "ml", "portion"}:
            raise AppError(400, "Einheit muss g, ml oder portion sein.")
        return kind, quantity, unit

    @staticmethod
    def _validate_component_reference(item: dict[str, Any], kind: str) -> None:
        if kind not in {"local_product", "database"}:
            return
        key = "product_id" if kind == "local_product" else "food_id"
        if not isinstance(item.get(key), str) or not item[key].strip():
            raise AppError(400, "Komponentenreferenz muss eine Zeichenkette sein.")

    def _resolve_local_product_component(
        self, db: Any, item: dict[str, Any], quantity: float, unit: str
    ) -> tuple[str, dict[str, float | None], dict[str, Any]]:
        if set(item) != {"kind", "product_id", "amount", "unit"}:
            raise AppError(400, "Lokale Produktkomponente enthält ungültige Felder.")
        product = self._products.get(db, item["product_id"])
        if not product:
            raise AppError(
                404, PRODUCT_NOT_FOUND, reason="nutrition_product_not_found"
            )
        if product.get("status") != "active":
            raise AppError(
                409,
                "Archivierte Produkte können nicht erfasst werden.",
                reason="nutrition_product_archived",
            )
        if unit != product["basis_unit"]:
            raise AppError(
                400,
                "Komponenteneinheit stimmt nicht mit dem Produkt überein.",
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
                "Für dieses Produkt fehlt der Kalorienwert.",
                reason="food_energy_missing",
            )
        return product["name"], nutrients, {"kind": "local_product", "product": product}

    def _resolve_database_component(
        self, item: dict[str, Any], quantity: float, unit: str
    ) -> tuple[str, dict[str, float | None], dict[str, Any]]:
        if set(item) != {"kind", "food_id", "amount", "unit"}:
            raise AppError(400, "Datenbankkomponente enthält ungültige Felder.")
        food = self.food_database.resolve(item["food_id"])
        if unit != food.get("basis_unit"):
            raise AppError(
                400,
                "Komponenteneinheit stimmt nicht mit der Datenbank überein.",
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
                "Kalorienwert fehlt; als Schätzung kennzeichnen.",
                reason="food_energy_missing",
            )
        return food["name"], nutrients, {"kind": "database", "food": food}

    def _resolve_manual_component(
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
                400, "Manuelle Komponente benötigt Name und alle Nährwertfelder."
            )
        name = item["name"].strip()[:200]
        nutrients = {key: self._validate_component_nutrient(key, item[key]) for key in NUTRIENTS}
        if nutrients["kcal"] is None:
            raise AppError(
                400, "Kalorienwert ist erforderlich.", reason="food_energy_missing"
            )
        return name, nutrients, {"kind": kind}

    @staticmethod
    def _validate_component_nutrient(key: str, value: Any) -> float | None:
        if value is None:
            return None
        if isinstance(value, bool):
            raise AppError(400, "Ungültiger Nährwert.")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise AppError(400, "Ungültiger Nährwert.") from None
        if not math.isfinite(number) or number < 0:
            raise AppError(400, "Nährwert muss endlich und nicht negativ sein.")
        if number > (10000 if key == "kcal" else 1000):
            raise AppError(400, "Nährwert überschreitet das zulässige Maximum.")
        return number

    def log_product(
        self,
        product_id: str,
        amount: Any,
        unit: str,
        *,
        meal_date: str | None = None,
        meal_time: str | None = None,
    ) -> dict[str, Any]:
        calculation = self.calculate_product(product_id, amount, unit)
        if calculation.get("kcal") is None:
            raise AppError(
                400,
                "Für dieses Produkt fehlt der Kalorienwert.",
                reason="food_energy_missing",
            )
        entry = self.log_meal(
            {
                "product_id": product_id,
                "amount": amount,
                "unit": unit,
                "meal_date": meal_date,
                "meal_time": meal_time,
                "description": f"{calculation['product']['name']} · {calculation['amount']:g} {unit}",
                "kcal": calculation["kcal"],
                "carbs_g": calculation["carbs_g"],
                "protein_g": calculation["protein_g"],
                "fat_g": calculation["fat_g"],
                "nutrition_basis": calculation["nutrition_basis"],
                "source": "manual",
            }
        )
        return entry

    def _normalize_product(self, payload: dict[str, Any]) -> dict[str, Any]:
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
            "bls",
            "fddb_export",
        }:
            raise AppError(400, "Ungültige Produktquelle.")
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

    def fueling(self) -> Any:
        if not self._fueling_service:
            raise AppError(503, "Trainingsverpflegung ist nicht verfügbar.")
        return self._fueling_service()

    def _prepare_values(self, payload: dict[str, Any]) -> dict[str, Any]:
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
            else self._nutrition_basis_kind(payload)
        )
        return {**payload, "nutrition_basis": {"kind": kind}}

    @staticmethod
    def _nutrition_basis_kind(payload: dict[str, Any]) -> str:
        return (
            "estimate"
            if payload.get("source") in {"coach", "photo", "voice"}
            else "manual"
        )

    def list_templates(self) -> list[dict[str, Any]]:
        with self._db_lock, self._database_manager.unit_of_work() as db:
            return self._templates.list(db)

    def save_template(
        self, payload: Any, *, expected_calculation: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Save a confirmed recipe for one portion without recording consumption."""
        if not isinstance(payload, dict):
            raise AppError(400, "Mahlzeit muss ein Objekt sein.")
        prepared = payload
        template_id = str(payload.get("id") or "").strip()
        with self._db_lock, self._database_manager.unit_of_work() as db:
            if "components" in payload:
                _validate_component_payload(payload)
                prepared = {
                    **payload,
                    **self._calculate_components(db, payload["components"]),
                }
                prepared.pop("components", None)
            elif "food_ingredients" in payload:
                prepared = self._prepare_values(payload)
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

    def _prepare_template_values(
        self, payload: dict[str, Any], expected: dict[str, Any] | None
    ) -> dict[str, Any]:
        prepared = (
            self._prepare_values(payload) if "food_ingredients" in payload else payload
        )
        if expected is not None and any(
            prepared.get(key) != value for key, value in expected.items()
        ):
            raise AppError(
                409,
                "Datenbankwerte haben sich seit der Vorschau ge�ndert. Bitte neue Vorschau best�tigen.",
                reason="food_calculation_changed",
            )
        return prepared

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
            else self._prepare_values(values)
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

    def log_template(
        self,
        template_id: str,
        portions: Any = 1,
        *,
        meal_date: str | None = None,
        meal_time: str | None = None,
    ) -> dict[str, Any]:
        """Copy current per-portion values; later recipe edits never affect the log."""
        try:
            amount = float(portions)
        except (TypeError, ValueError) as exc:
            raise AppError(400, "Ungültige Portionsanzahl.") from exc
        if not math.isfinite(amount) or not 0 < amount <= 20:
            raise AppError(
                400, "Portionsanzahl muss größer als 0 und höchstens 20 sein."
            )
        with self._db_lock, self._database_manager.unit_of_work() as db:
            template = self._templates.get(db, template_id)
            if not template:
                raise AppError(404, SAVED_MEAL_NOT_FOUND)
            payload = {
                **template,
                "description": f"{template['name']} · {amount:g} Portion(en): {template['description']}",
                "meal_date": meal_date,
                "meal_time": meal_time or "12:00",
            }
            payload.pop("id")
            payload.pop("meal_type", None)
            if template.get("meal_type_explicit"):
                payload["meal_type"] = template["meal_type"]
            payload["source"] = (
                "coach" if template.get("source") == "coach" else template["source"]
            )
            for key in ("kcal", "carbs_g", "protein_g", "fat_g"):
                payload[key] = None if template[key] is None else template[key] * amount
            basis = template.get("nutrition_basis", {})
            if basis.get("kind") == "database":
                payload["nutrition_basis"] = {"kind": "database", "ingredients": [{**item, "amount": item["amount"] * amount} for item in basis["ingredients"]]}
            elif basis.get("kind") == "composite":
                payload["nutrition_basis"] = self._scale_composite_basis(basis, amount)
                self._set_composite_totals(payload)
            elif basis.get("kind") == "local_product":
                payload["nutrition_basis"] = {**basis, "amount": basis["amount"] * amount}
            entry = normalize_nutrition_entry(
                payload, local_now_factory=self._local_now
            )
            entry["id"] = uuid.uuid4().hex
            return self._nutrition_repository.create(db, entry)

    @staticmethod
    def _scale_composite_basis(basis: dict[str, Any], amount: float) -> dict[str, Any]:
        return {**basis, "components": [{**item, "amount": item["amount"] * amount, **{key: None if item.get(key) is None else item[key] * amount for key in NUTRIENTS}} for item in basis.get("components", [])]}

    @staticmethod
    def _set_composite_totals(payload: dict[str, Any]) -> None:
        components = payload["nutrition_basis"]["components"]
        for key in NUTRIENTS:
            values = [item.get(key) for item in components]
            if any(value is None for value in values):
                payload[key] = None
            else:
                precision = 0 if key == "kcal" else 1
                payload[key] = round(sum(values), precision)

    def log_meal(self, payload: Any) -> dict[str, Any]:
        """Normalize, validate and store a meal entry."""
        if not isinstance(payload, dict):
            raise AppError(400, "Ernährungseintrag muss ein Objekt sein.")
        if "components" in payload:
            _validate_component_payload(payload)
            with self._db_lock, self._database_manager.unit_of_work() as db:
                calculation = self._calculate_components(db, payload["components"])
                values = {
                    **payload,
                    **{key: calculation[key] for key in NUTRIENTS},
                    "nutrition_basis": calculation["nutrition_basis"],
                }
                entry = normalize_nutrition_entry(
                    values, local_now_factory=self._local_now
                )
                entry["id"] = str(entry.get("id") or uuid.uuid4().hex)
                return self._nutrition_repository.create(db, entry)
        values = self._prepare_values(payload)
        if payload.get("product_id"):
            calculation = self.calculate_product(
                str(payload["product_id"]),
                payload.get("amount"),
                str(payload.get("unit") or ""),
            )
            values.update(
                {key: calculation[key] for key in NUTRIENTS},
                nutrition_basis=calculation["nutrition_basis"],
                description=payload.get("description")
                or f"{calculation['product']['name']} · {calculation['amount']:g} {calculation['unit']}",
            )
        entry = normalize_nutrition_entry(values, local_now_factory=self._local_now)
        if not entry.get("id"):
            entry["id"] = uuid.uuid4().hex

        with self._db_lock, self._database_manager.unit_of_work() as db:
            saved = self._nutrition_repository.create(db, entry)
        return saved

    def get_meal(self, entry_id: str) -> dict[str, Any]:
        """Get a single meal entry by ID or raise AppError(404)."""
        clean_id = str(entry_id or "").strip()
        if not clean_id:
            raise AppError(400, INVALID_ENTRY_ID)
        with self._db_lock, self._database_manager.unit_of_work() as db:
            entry = self._nutrition_repository.get(db, clean_id)
        if not entry:
            raise AppError(404, ENTRY_NOT_FOUND)
        return entry

    def update_meal(self, entry_id: str, payload: Any) -> dict[str, Any]:
        """Normalize and update an existing meal entry."""
        clean_id = str(entry_id or "").strip()
        if not clean_id:
            raise AppError(400, INVALID_ENTRY_ID)
        if not isinstance(payload, dict):
            raise AppError(400, "Ernährungseintrag muss ein Objekt sein.")
        with self._db_lock, self._database_manager.unit_of_work() as db:
            existing = self._nutrition_repository.get(db, clean_id)
            if not existing:
                raise AppError(404, ENTRY_NOT_FOUND)
            merged_payload = {**existing, **payload}
            if "components" in payload:
                _validate_component_payload(payload)
                prepared = {
                    **merged_payload,
                    **self._calculate_components(db, payload["components"]),
                }
                prepared.pop("components", None)
            else:
                prepared = self._prepare_values(merged_payload)
            entry = normalize_nutrition_entry(
                prepared, local_now_factory=self._local_now
            )
            if (
                "food_ingredients" not in payload
                and "components" not in payload
                and not any(entry.get(key) != existing.get(key) for key in NUTRIENTS)
            ):
                entry["nutrition_basis"] = existing.get(
                    "nutrition_basis", {"kind": "manual"}
                )
            entry["id"] = clean_id
            updated = self._nutrition_repository.update(db, clean_id, entry)
        if not updated:
            raise AppError(404, ENTRY_NOT_FOUND)
        return updated

    def correct_meal(self, entry_id: str, changes: Any) -> dict[str, Any]:
        """Apply a partial correction while preserving every omitted meal field."""
        clean_id = str(entry_id or "").strip()
        if not clean_id:
            raise AppError(400, INVALID_ENTRY_ID)
        if not self._is_valid_meal_correction(changes):
            raise AppError(
                400, "Korrektur muss mindestens ein gültiges Ernährungsfeld enthalten."
            )
        calculation = self.food_database.calculate(changes["food_ingredients"]) if "food_ingredients" in changes else None
        with self._db_lock, self._database_manager.unit_of_work() as db:
            existing = self._nutrition_repository.get(db, clean_id)
            if not existing:
                raise AppError(404, ENTRY_NOT_FOUND)
            entry = self._apply_meal_correction(db, existing, changes, calculation)
            updated = self._nutrition_repository.update(db, clean_id, entry)
        if not updated:
            raise AppError(404, ENTRY_NOT_FOUND)
        return updated

    @staticmethod
    def _is_valid_meal_correction(changes: Any) -> bool:
        editable = {
            "meal_date",
            "date",
            "logged_at",
            "meal_time",
            "meal_type",
            "description",
            "kcal",
            "calories",
            "carbs_g",
            "carbs",
            "carbohydrates",
            "protein_g",
            "protein",
            "fat_g",
            "fat",
            "food_ingredients",
            "components",
            "packaging_label",
        }
        return isinstance(changes, dict) and bool(changes) and not (set(changes) - editable)

    def _apply_meal_correction(self, db: Any, existing: dict[str, Any], changes: dict[str, Any], calculation: dict[str, Any] | None) -> dict[str, Any]:
        aliases = {"date": "meal_date", "meal_time": "logged_at", "calories": "kcal", "carbs": "carbs_g", "carbohydrates": "carbs_g", "protein": "protein_g", "fat": "fat_g"}
        canonical = {str(aliases.get(key, key)): value for key, value in changes.items()}
        merged = {**existing, **canonical}
        if "components" in changes:
            _validate_component_payload(changes)
            merged.update(self._calculate_components(db, changes["components"]))
            merged.pop("components", None)
        elif set(canonical) & {*NUTRIENTS, "food_ingredients", "packaging_label"}:
            merged.update(calculation if calculation is not None else self._prepare_values(merged))
            if "food_ingredients" not in canonical and canonical.get("packaging_label") is not True:
                merged["nutrition_basis"] = {"kind": "manual_correction"}
        entry = normalize_nutrition_entry(merged, local_now_factory=self._local_now)
        entry.update(id=existing["id"], source=existing["source"])
        return entry

    def delete_meal(self, entry_id: str) -> dict[str, Any]:
        """Delete an existing meal entry by ID."""
        clean_id = str(entry_id or "").strip()
        if not clean_id:
            raise AppError(400, INVALID_ENTRY_ID)
        with self._db_lock, self._database_manager.unit_of_work() as db:
            deleted = self._nutrition_repository.delete(db, clean_id)
        if not deleted:
            raise AppError(404, ENTRY_NOT_FOUND)
        return {"status": "ok", "deleted_id": clean_id}

    def get_day_summary(self, meal_date: str) -> dict[str, Any]:
        """Return all meal entries and totals for a single ISO-8601 date."""
        validated_date = validate_iso_date(meal_date)
        with self._db_lock, self._database_manager.unit_of_work() as db:
            return self._nutrition_repository.day_summary(db, validated_date)

    def get_sync_snapshot(self, meal_date: str) -> dict[str, Any]:
        """Capture totals and a revision for race-safe provider synchronization."""
        validated_date = validate_iso_date(meal_date)
        with self._db_lock, self._database_manager.unit_of_work() as db:
            return self._nutrition_repository.day_sync_snapshot(db, validated_date)

    def approval_manifest(
        self,
        *,
        meal_date: str | None = None,
        pending_limit: int | None = None,
        dates: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Read exact nutrition revisions and totals without changing sync state."""
        selectors = sum(
            value is not None for value in (meal_date, pending_limit, dates)
        )
        if selectors != 1:
            raise AppError(400, "Choose one date or an approved date range.")
        with self._db_lock, self._database_manager.unit_of_work() as db:
            if meal_date is not None:
                selected_dates = [validate_iso_date(meal_date)]
            elif pending_limit is not None:
                if type(pending_limit) is not int or not 1 <= pending_limit <= 31:
                    raise AppError(
                        400,
                        "Die Anzahl ausstehender Tage muss zwischen 1 und 31 liegen.",
                    )
                selected_dates = self._nutrition_repository.list_unsynced_dates(
                    db, limit=pending_limit
                )
            else:
                if (
                    not isinstance(dates, list)
                    or len(dates) > 31
                    or any(not isinstance(value, str) for value in dates)
                ):
                    raise AppError(400, "Invalid nutrition approval manifest.")
                selected_dates = [validate_iso_date(value) for value in dates]
                if len(selected_dates) != len(set(selected_dates)):
                    raise AppError(
                        400, "Nutrition approval manifest contains duplicate dates."
                    )
            return [
                nutrition_approval_item(
                    self._nutrition_repository.day_sync_snapshot(
                        db, day, create_if_missing=False
                    )
                )
                for day in selected_dates
            ]

    def get_today_summary(self) -> dict[str, Any]:
        """Return today's local nutrition totals."""
        return self.get_day_summary(self._local_now().date().isoformat())

    def get_range_summary(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        """Return daily summaries for each date in a range."""
        valid_start = validate_iso_date(start_date)
        valid_end = validate_iso_date(end_date)
        if valid_start > valid_end:
            raise AppError(400, "Startdatum muss vor oder am Enddatum liegen.")

        with self._db_lock, self._database_manager.unit_of_work() as db:
            entries = self._nutrition_repository.list_by_range(
                db, valid_start, valid_end
            )

        by_date: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            d = entry["meal_date"]
            by_date.setdefault(d, []).append(entry)

        summaries: list[dict[str, Any]] = []
        for date_key in sorted(by_date.keys()):
            day_entries = by_date[date_key]
            total_kcal = sum(int(e["kcal"]) for e in day_entries)
            total_carbs = _known_daily_total(day_entries, "carbs_g")
            total_protein = _known_daily_total(day_entries, "protein_g")
            total_fat = _known_daily_total(day_entries, "fat_g")
            summaries.append(
                NutritionDaySummary(
                    date=date_key,
                    total_kcal=total_kcal,
                    total_carbs_g=total_carbs,
                    total_protein_g=total_protein,
                    total_fat_g=total_fat,
                    entry_count=len(day_entries),
                    entries=[
                        NutritionEntry.from_dict(e).to_dict() for e in day_entries
                    ],
                ).to_dict()
            )
        return summaries

    def list_unsynced_dates(self, limit: int = 14) -> list[str]:
        """Return distinct dates with un-synced nutrition entries."""
        with self._db_lock, self._database_manager.unit_of_work() as db:
            return self._nutrition_repository.list_unsynced_dates(db, limit=limit)

    def mark_date_synced(self, meal_date: str, revision: int) -> bool:
        """Mark a date synced only if its records did not change during remote I/O."""
        validated_date = validate_iso_date(meal_date)
        now_str = self._utc_now()
        with self._db_lock, self._database_manager.unit_of_work() as db:
            return self._nutrition_repository.mark_date_synced(
                db, validated_date, revision, now_str
            )

    def context(self) -> dict[str, Any]:
        """Provide concise recent nutrition summary for coach prompts."""
        today = self._local_now().date().isoformat()
        past_week = (self._local_now().date() - timedelta(days=6)).isoformat()
        with self._db_lock, self._database_manager.unit_of_work() as db:
            today_summary = self._nutrition_repository.day_summary(db, today)
            recent_entries = self._nutrition_repository.list_by_range(
                db, past_week, today
            )
        return {
            "today": today_summary,
            "recent_entries_count": len(recent_entries),
            "recent_entries": recent_entries[-10:],
            "scope": "Athlete-entered nutrition logs and calorie totals.",
        }
