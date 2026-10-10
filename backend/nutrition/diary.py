"""Daily nutrition entries, totals, and synchronization state."""

from __future__ import annotations

import math
import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Any

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
    NutritionDaySummary,
    NutritionEntry,
    normalize_nutrition_entry,
    validate_iso_date,
)
from backend.nutrition.sync_status import NutritionSyncStatusService

INVALID_ENTRY_ID = "Ungültige Eintrags-ID."
ENTRY_NOT_FOUND = "Ernährungseintrag nicht gefunden."


def _names_time_without_flag(changes: dict[str, Any]) -> bool:
    """A newly named meal time is known even when the stored entry had none."""
    return bool({"logged_at", "meal_time"} & set(changes)) and (
        "logged_time_known" not in changes
    )


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
        fueling_service: Callable[[], Any] | None = None,
    ) -> None:
        self._database_manager = database_manager
        self._db_lock = db_lock
        self._nutrition_repository = nutrition_repository
        self._utc_now = utc_now
        self._local_now = local_now
        self._meal_library = meal_library
        self._sync_status = NutritionSyncStatusService(
            database_manager, db_lock, nutrition_repository, utc_now, local_now
        )
        self._fueling_service = fueling_service

    def log_product(
        self,
        product_id: str,
        amount: Any,
        unit: str,
        *,
        meal_date: str | None = None,
        meal_time: str | None = None,
    ) -> dict[str, Any]:
        calculation = self._meal_library.calculate_product(product_id, amount, unit)
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

    def fueling(self) -> Any:
        if not self._fueling_service:
            raise AppError(503, "Trainingsverpflegung ist nicht verfügbar.")
        return self._fueling_service()

    def log_template(
        self,
        template_id: str,
        portions: Any = 1,
        *,
        meal_date: str | None = None,
        meal_time: str | None = None,
    ) -> dict[str, Any]:
        try:
            amount = float(portions)
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
                "meal_time": meal_time or "12:00",
            }
            payload.pop("id")
            payload.pop("meal_type", None)
            if template.get("meal_type_explicit"):
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
            return self._nutrition_repository.create(db, entry)

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
            resolved_database = self._meal_library.prepare_component_resolutions(
                payload["components"]
            )
            with self._db_lock, self._database_manager.unit_of_work() as db:
                calculation = self._meal_library.calculate_components_in_transaction(
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
                return self._nutrition_repository.create(db, entry)
        values = self._meal_library.prepare_values(payload)
        if payload.get("product_id"):
            calculation = self._meal_library.calculate_product(
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
            return self._nutrition_repository.create(db, entry)

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
        resolved_database = (
            self._meal_library.prepare_component_resolutions(payload["components"])
            if "components" in payload
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
                    **self._meal_library.calculate_components_in_transaction(
                        db, payload["components"], resolved_database
                    ),
                }
                prepared.pop("components", None)
            else:
                prepared = self._meal_library.prepare_values(merged_payload)
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
        clean_id = str(entry_id or "").strip()
        if not clean_id:
            raise AppError(400, INVALID_ENTRY_ID)
        if not self._is_valid_meal_correction(changes):
            raise AppError(
                400, "Korrektur muss mindestens ein gültiges Ernährungsfeld enthalten."
            )
        resolved_database = (
            self._meal_library.prepare_component_resolutions(changes["components"])
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
        aliases = {
            "date": "meal_date",
            "meal_time": "logged_at",
            "calories": "kcal",
            "carbs": "carbs_g",
            "carbohydrates": "carbs_g",
            "protein": "protein_g",
            "fat": "fat_g",
        }
        canonical = {
            str(aliases.get(key, key)): value for key, value in changes.items()
        }
        merged = {**existing, **canonical}
        if _names_time_without_flag(canonical):
            merged["logged_time_known"] = True
        if "components" in changes:
            validate_component_payload(changes)
            merged.update(
                self._meal_library.calculate_components_in_transaction(
                    db, changes["components"], resolved_database
                )
            )
            merged.pop("components", None)
        elif set(canonical) & {*NUTRIENTS, "food_ingredients", "packaging_label"}:
            merged.update(
                calculation
                if calculation is not None
                else self._meal_library.prepare_values(merged)
            )
            if (
                "food_ingredients" not in canonical
                and canonical.get("packaging_label") is not True
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
            deleted = self._nutrition_repository.delete(db, clean_id)
        if not deleted:
            raise AppError(404, ENTRY_NOT_FOUND)
        return {"status": "ok", "deleted_id": clean_id}

    def get_day_summary(self, meal_date: str) -> dict[str, Any]:
        return self._sync_status.get_day_summary(meal_date)

    def get_sync_snapshot(self, meal_date: str) -> dict[str, Any]:
        return self._sync_status.get_sync_snapshot(meal_date)

    def approval_manifest(
        self,
        *,
        meal_date: str | None = None,
        pending_limit: int | None = None,
        dates: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        return self._sync_status.approval_manifest(
            meal_date=meal_date, pending_limit=pending_limit, dates=dates
        )

    def get_today_summary(self) -> dict[str, Any]:
        return self.get_day_summary(self._local_now().date().isoformat())

    def get_range_summary(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
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

    def list_unsynced_dates(self, limit: int = 14) -> list[str]:
        return self._sync_status.list_unsynced_dates(limit=limit)

    def mark_date_synced(self, meal_date: str, revision: int) -> bool:
        return self._sync_status.mark_date_synced(meal_date, revision)

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
