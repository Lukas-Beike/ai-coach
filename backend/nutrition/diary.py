"""Daily nutrition entries, totals, and synchronization state."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, datetime, timedelta
from typing import Any

from backend import change_history
from backend.db.manager import DatabaseManager
from backend.db.repositories import NutritionRepository, nutrition_macro_totals
from backend.errors import AppError
from backend.nutrition.food_database import NUTRIENTS
from backend.nutrition.meal_library import (
    SAVED_MEAL_NOT_FOUND,
    NutritionMealLibraryService,
    validate_component_payload,
)
from backend.nutrition.models import (
    MAX_DESCRIPTION_LEN,
    NutritionDaySummary,
    NutritionEntry,
    normalize_nutrition_entry,
    nutrition_number,
    validate_iso_date,
)
from backend.nutrition.sync_status import NutritionSyncStatusService
from backend.runtime.ports import ObservationReader

INVALID_ENTRY_ID = "Ungültige Eintrags-ID."
ENTRY_NOT_FOUND = "Ernährungseintrag nicht gefunden."
ENTITY_TYPE = "nutrition_entry"
# Alternative names the Coach and API clients use for stored entry fields.
MEAL_FIELD_ALIASES = {
    "date": "meal_date",
    "meal_time": "logged_at",
    "calories": "kcal",
    "carbs": "carbs_g",
    "carbohydrates": "carbs_g",
    "protein": "protein_g",
    "fat": "fat_g",
}


def _canonical_meal_changes(changes: dict[str, Any]) -> dict[str, Any]:
    """Rename alias keys to stored field names; reject conflicting values."""
    canonical: dict[str, Any] = {}
    for key, value in changes.items():
        name = str(MEAL_FIELD_ALIASES.get(key, key))
        if name in canonical and canonical[name] != value:
            raise AppError(400, f"Widersprüchliche Werte für {name}.")
        canonical[name] = value
    return canonical


def _names_time_without_flag(changes: dict[str, Any]) -> bool:
    """A newly named meal time is known even when the stored entry had none."""
    return bool({"logged_at", "meal_time"} & set(changes)) and (
        "logged_time_known" not in changes
    )


# The longest inclusive span one range read returns (#2137, F-017).
MAX_RANGE_DAYS = 366


class NutritionDiaryService:
    """Manage consumption entries, daily aggregates, and sync markers."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        db_lock: AbstractContextManager[Any],
        nutrition_repository: NutritionRepository,
        utc_now: Callable[[], str],
        local_now: Callable[[], datetime],
        meal_library: NutritionMealLibraryService,
        observation_reader: Callable[[], ObservationReader],
    ) -> None:
        self._database_manager = database_manager
        self._db_lock = db_lock
        self._nutrition_repository = nutrition_repository
        self._utc_now = utc_now
        self._local_now = local_now
        self._meal_library = meal_library
        self._sync_status = NutritionSyncStatusService(
            database_manager,
            db_lock,
            nutrition_repository,
            utc_now,
            local_now,
            observation_reader,
        )

    @property
    def sync_status(self) -> NutritionSyncStatusService:
        return self._sync_status

    def log_product(
        self,
        product_id: str,
        amount: Any,
        unit: str,
        *,
        meal_date: str | None = None,
        meal_time: str | None = None,
    ) -> dict[str, Any]:
        calculation = self._meal_library.product_catalog.calculate_product(
            product_id, amount, unit
        )
        if calculation.get("kcal") is None:
            raise AppError(
                400,
                "Für dieses Produkt fehlt der Kalorienwert.",
                reason="food_energy_missing",
            )
        return self.log_meal(
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

    def log_template(
        self,
        template_id: str,
        portions: Any = 1,
        *,
        meal_date: str | None = None,
        meal_time: str | None = None,
    ) -> dict[str, Any]:
        try:
            amount = nutrition_number(portions)
        except (TypeError, ValueError) as exc:
            raise AppError(400, "Ungültige Portionsanzahl.") from exc
        if not math.isfinite(amount) or not 0 < amount <= 20:
            raise AppError(
                400, "Portionsanzahl muss größer als 0 und höchstens 20 sein."
            )
        with self._db_lock, self._database_manager.unit_of_work() as db:
            template = self._meal_library.get_template_in_transaction(db, template_id)
            if not template:
                raise AppError(404, SAVED_MEAL_NOT_FOUND)
            payload = {
                **template,
                "description": f"{template['name']} · {amount:g} Portion(en): {template['description']}",
                "meal_date": meal_date,
                "meal_time": meal_time,
                # Without a time from the athlete, the diary must not show an invented one.
                "logged_time_known": bool(meal_time),
            }
            payload.pop("id")
            payload.pop("meal_type", None)
            # An unknown time keeps the template's own meal type instead of inferring one.
            if template.get("meal_type_explicit") or not meal_time:
                payload["meal_type"] = template["meal_type"]
            payload["source"] = (
                "coach" if template.get("source") == "coach" else template["source"]
            )
            for key in NUTRIENTS:
                payload[key] = None if template[key] is None else template[key] * amount
            basis = template.get("nutrition_basis", {})
            if basis.get("kind") == "database":
                payload["nutrition_basis"] = {
                    "kind": "database",
                    "ingredients": [
                        {**item, "amount": item["amount"] * amount}
                        for item in basis["ingredients"]
                    ],
                }
            elif basis.get("kind") == "composite":
                payload["nutrition_basis"] = self._scale_composite_basis(basis, amount)
                self._set_composite_totals(payload)
            elif basis.get("kind") == "local_product":
                payload["nutrition_basis"] = {
                    **basis,
                    "amount": basis["amount"] * amount,
                }
            entry = normalize_nutrition_entry(
                payload, local_now_factory=self._local_now
            )
            entry["id"] = uuid.uuid4().hex
            return self._create(db, entry)

    @staticmethod
    def _scale_composite_basis(basis: dict[str, Any], amount: float) -> dict[str, Any]:
        return {
            **basis,
            "components": [
                {
                    **item,
                    "amount": item["amount"] * amount,
                    **{
                        key: None if item.get(key) is None else item[key] * amount
                        for key in NUTRIENTS
                    },
                }
                for item in basis.get("components", [])
            ],
        }

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
        if not isinstance(payload, dict):
            raise AppError(400, "Ernährungseintrag muss ein Objekt sein.")
        if "components" in payload:
            validate_component_payload(payload)
            resolved_database = (
                self._meal_library.component_calculator.prepare_resolutions(
                    payload["components"]
                )
            )
            with self._db_lock, self._database_manager.unit_of_work() as db:
                calculation = self._meal_library.component_calculator.calculate(
                    db, payload["components"], resolved_database
                )
                values = {
                    **payload,
                    **{key: calculation[key] for key in NUTRIENTS},
                    "nutrition_basis": calculation["nutrition_basis"],
                }
                entry = normalize_nutrition_entry(
                    values, local_now_factory=self._local_now
                )
                entry["id"] = str(entry.get("id") or uuid.uuid4().hex)
                return self._create(db, entry)
        values = self._meal_library.prepare_values(payload)
        if payload.get("product_id"):
            calculation = self._meal_library.product_catalog.calculate_product(
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
            return self._create(db, entry)

    def get_meal(self, entry_id: str) -> dict[str, Any]:
        clean_id = str(entry_id or "").strip()
        if not clean_id:
            raise AppError(400, INVALID_ENTRY_ID)
        with self._db_lock, self._database_manager.unit_of_work() as db:
            entry = self._nutrition_repository.get(db, clean_id)
        if not entry:
            raise AppError(404, ENTRY_NOT_FOUND)
        return entry

    def update_meal(self, entry_id: str, payload: Any) -> dict[str, Any]:
        clean_id = str(entry_id or "").strip()
        if not clean_id:
            raise AppError(400, INVALID_ENTRY_ID)
        if not isinstance(payload, dict):
            raise AppError(400, "Ernährungseintrag muss ein Objekt sein.")
        payload = _canonical_meal_changes(payload)
        resolved_database = (
            self._meal_library.component_calculator.prepare_resolutions(
                payload["components"]
            )
            if "components" in payload
            else None
        )
        calculation = (
            self._meal_library.food_database.calculate(payload["food_ingredients"])
            if "food_ingredients" in payload and "components" not in payload
            else None
        )
        with self._db_lock, self._database_manager.unit_of_work() as db:
            existing = self._nutrition_repository.get(db, clean_id)
            if not existing:
                raise AppError(404, ENTRY_NOT_FOUND)
            merged_payload = {**existing, **payload}
            if _names_time_without_flag(payload):
                merged_payload["logged_time_known"] = True
            if "components" in payload:
                validate_component_payload(payload)
                prepared = {
                    **merged_payload,
                    **self._meal_library.component_calculator.calculate(
                        db, payload["components"], resolved_database
                    ),
                }
                prepared.pop("components", None)
            else:
                prepared = self._meal_library.prepare_values(
                    merged_payload, calculation
                )
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
            updated = self._update(db, existing, entry)
        if not updated:
            raise AppError(404, ENTRY_NOT_FOUND)
        return updated

    def add_product_to_meal(
        self, entry_id: str, product_id: str, amount: Any, unit: str
    ) -> dict[str, Any]:
        """Add a saved product to a logged meal as one more component.

        A meal that is not yet a composite becomes one whose first component is
        its previous values, so no earlier nutrient or origin is lost.
        """
        clean_id = str(entry_id or "").strip()
        if not clean_id:
            raise AppError(400, INVALID_ENTRY_ID)
        component = {
            "kind": "local_product",
            "product_id": str(product_id or "").strip(),
            "amount": amount,
            "unit": unit,
        }
        with self._db_lock, self._database_manager.unit_of_work() as db:
            existing = self._nutrition_repository.get(db, clean_id)
            if not existing:
                raise AppError(404, ENTRY_NOT_FOUND)
            added = self._meal_library.component_calculator.calculate(
                db, [component], None
            )["nutrition_basis"]["components"][0]
            basis = existing.get("nutrition_basis") or {}
            earlier = (
                list(basis["components"])
                if basis.get("kind") == "composite" and basis.get("components")
                else [self._meal_component(existing)]
            )
            if len(earlier) >= 20:
                raise AppError(
                    400, "Eine Mahlzeit kann höchstens 20 Komponenten enthalten."
                )
            entry = {
                **existing,
                "description": self._extended_description(
                    existing["description"], added["name"]
                ),
                "nutrition_basis": {
                    "kind": "composite",
                    "version": 1,
                    "components": [*earlier, added],
                },
            }
            self._set_composite_totals(entry)
            updated = self._update(
                db,
                existing,
                normalize_nutrition_entry(entry, local_now_factory=self._local_now)
                | {"id": clean_id},
            )
        if not updated:
            raise AppError(404, ENTRY_NOT_FOUND)
        return updated

    @staticmethod
    def _extended_description(description: str, name: str) -> str:
        # The newest product always stays visible; earlier text gives way.
        suffix = f" + {name}"[:MAX_DESCRIPTION_LEN]
        return str(description)[: MAX_DESCRIPTION_LEN - len(suffix)] + suffix

    @staticmethod
    def _meal_component(entry: dict[str, Any]) -> dict[str, Any]:
        basis = entry.get("nutrition_basis") or {"kind": "manual"}
        # The intake totals scale a product or database basis by its component
        # amount, so the wrapped component keeps the amount of that basis.
        amount = basis.get("amount")
        unit = basis.get("unit")
        estimated = basis.get("kind") == "estimate" or entry.get("source") in {
            "coach",
            "photo",
            "voice",
        }
        return {
            "kind": "estimate" if estimated else "manual",
            "name": str(entry.get("description") or "Mahlzeit")[:200],
            "amount": amount
            if isinstance(amount, (int, float))
            and not isinstance(amount, bool)
            and amount > 0
            else 1,
            "unit": unit if unit in {"g", "ml", "portion"} else "portion",
            **{key: entry.get(key) for key in NUTRIENTS},
            "nutrition_basis": basis,
        }

    def correct_meal(self, entry_id: str, changes: Any) -> dict[str, Any]:
        clean_id = str(entry_id or "").strip()
        if not clean_id:
            raise AppError(400, INVALID_ENTRY_ID)
        if not self._is_valid_meal_correction(changes):
            raise AppError(
                400, "Korrektur muss mindestens ein gültiges Ernährungsfeld enthalten."
            )
        changes = _canonical_meal_changes(changes)
        resolved_database = (
            self._meal_library.component_calculator.prepare_resolutions(
                changes["components"]
            )
            if "components" in changes
            else None
        )
        calculation = (
            self._meal_library.food_database.calculate(changes["food_ingredients"])
            if "food_ingredients" in changes
            else None
        )
        with self._db_lock, self._database_manager.unit_of_work() as db:
            existing = self._nutrition_repository.get(db, clean_id)
            if not existing:
                raise AppError(404, ENTRY_NOT_FOUND)
            entry = self._apply_meal_correction(
                db, existing, changes, calculation, resolved_database
            )
            updated = self._update(db, existing, entry)
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
            "logged_time_known",
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
        return (
            isinstance(changes, dict)
            and bool(changes)
            and not (set(changes) - editable)
        )

    def _apply_meal_correction(
        self,
        db: Any,
        existing: dict[str, Any],
        changes: dict[str, Any],
        calculation: dict[str, Any] | None,
        resolved_database: dict[int, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        merged = {**existing, **changes}
        if _names_time_without_flag(changes):
            merged["logged_time_known"] = True
        if "components" in changes:
            validate_component_payload(changes)
            merged.update(
                self._meal_library.component_calculator.calculate(
                    db, changes["components"], resolved_database
                )
            )
            merged.pop("components", None)
        elif set(changes) & {*NUTRIENTS, "food_ingredients", "packaging_label"}:
            merged.update(
                calculation
                if calculation is not None
                else self._meal_library.prepare_values(merged)
            )
            if (
                "food_ingredients" not in changes
                and changes.get("packaging_label") is not True
            ):
                merged["nutrition_basis"] = {"kind": "manual_correction"}
        entry = normalize_nutrition_entry(merged, local_now_factory=self._local_now)
        entry.update(id=existing["id"], source=existing["source"])
        return entry

    def delete_meal(self, entry_id: str) -> dict[str, Any]:
        clean_id = str(entry_id or "").strip()
        if not clean_id:
            raise AppError(400, INVALID_ENTRY_ID)
        with self._db_lock, self._database_manager.unit_of_work() as db:
            existing = self._nutrition_repository.get(db, clean_id)
            deleted = bool(existing) and self._nutrition_repository.delete(db, clean_id)
            if deleted:
                change_history.record_change(
                    db, ENTITY_TYPE, clean_id, "delete", existing, None
                )
        if not deleted:
            raise AppError(404, ENTRY_NOT_FOUND)
        return {"status": "ok", "deleted_id": clean_id}

    def _create(self, db: Any, entry: dict[str, Any]) -> dict[str, Any]:
        created = self._nutrition_repository.create(db, entry)
        change_history.record_change(
            db, ENTITY_TYPE, str(created["id"]), "create", None, created
        )
        return created

    def _update(
        self, db: Any, existing: dict[str, Any], entry: dict[str, Any]
    ) -> dict[str, Any] | None:
        updated = self._nutrition_repository.update(db, str(existing["id"]), entry)
        if updated:
            change_history.record_change(
                db, ENTITY_TYPE, str(existing["id"]), "update", existing, updated
            )
        return updated

    def current(
        self, db: Any, entity_id: str
    ) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
        """The stored entry of one recorded change, for change history."""
        value = self._nutrition_repository.get(db, entity_id)
        return value, change_history.audit_projection(ENTITY_TYPE, value)

    def restore_in_transaction(
        self,
        db: Any,
        entity_id: str,
        current: dict[str, Any] | None,
        target: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        """Put one entry back as recorded; the day is marked for sync again."""
        if target is None:
            self._nutrition_repository.delete(db, entity_id)
            return None
        entry = {**(current or {}), **target, "id": entity_id, "sync_state": "local"}
        if current:
            return self._nutrition_repository.update(db, entity_id, entry)
        return self._nutrition_repository.create(db, entry)

    def get_today_summary(self) -> dict[str, Any]:
        return self._sync_status.get_day_summary(self._local_now().date().isoformat())

    def get_range_summary(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        valid_start = validate_iso_date(start_date)
        valid_end = validate_iso_date(end_date)
        if valid_start > valid_end:
            raise AppError(400, "Startdatum muss vor oder am Enddatum liegen.")
        span = date.fromisoformat(valid_end) - date.fromisoformat(valid_start)
        if span.days >= MAX_RANGE_DAYS:
            raise AppError(
                400,
                f"Der Zeitraum darf höchstens {MAX_RANGE_DAYS} Tage umfassen.",
                reason="range_too_large",
            )
        with self._database_manager.reader() as db:
            entries = self._nutrition_repository.list_by_range(
                db, valid_start, valid_end
            )
        by_date: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            by_date.setdefault(entry["meal_date"], []).append(entry)
        summaries: list[dict[str, Any]] = []
        for date_key in sorted(by_date):
            day_entries = by_date[date_key]
            summaries.append(
                NutritionDaySummary(
                    date=date_key,
                    total_kcal=sum(int(e["kcal"]) for e in day_entries),
                    **nutrition_macro_totals(day_entries),
                    entry_count=len(day_entries),
                    entries=[
                        NutritionEntry.from_dict(e).to_dict() for e in day_entries
                    ],
                ).to_dict()
            )
        return summaries

    def context(self) -> dict[str, Any]:
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
