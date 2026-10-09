"""Read and update diary synchronization state."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from typing import Any

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository, NutritionRepository
from backend.errors import AppError
from backend.nutrition.contracts import nutrition_approval_item
from backend.nutrition.models import validate_iso_date
from backend.performance.daily_health import garmin_daily_expenditure


class NutritionSyncStatusService:
    def __init__(
        self,
        database_manager: DatabaseManager,
        db_lock: AbstractContextManager[Any],
        nutrition_repository: NutritionRepository,
        utc_now: Callable[[], str],
        local_now: Callable[[], datetime],
    ) -> None:
        self._database_manager = database_manager
        self._db_lock = db_lock
        self._nutrition_repository = nutrition_repository
        self._key_value_repository = KeyValueRepository(utc_now)
        self._utc_now = utc_now
        self._local_now = local_now

    def get_day_summary(self, meal_date: str) -> dict[str, Any]:
        validated_date = validate_iso_date(meal_date)
        with self._db_lock, self._database_manager.unit_of_work() as db:
            summary = self._nutrition_repository.day_summary(db, validated_date)
            serialized_garmin = self._key_value_repository.get(db, "garmin_snapshot")
        try:
            garmin_snapshot = json.loads(serialized_garmin or "{}")
        except TypeError, ValueError:
            garmin_snapshot = {}
        if not isinstance(garmin_snapshot, dict):
            garmin_snapshot = {}
        summary["energy_expenditure"] = garmin_daily_expenditure(
            garmin_snapshot, validated_date, self._local_now().date()
        )
        return summary

    def get_sync_snapshot(self, meal_date: str) -> dict[str, Any]:
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

    def list_unsynced_dates(self, limit: int = 14) -> list[str]:
        with self._db_lock, self._database_manager.unit_of_work() as db:
            return self._nutrition_repository.list_unsynced_dates(db, limit=limit)

    def mark_date_synced(self, meal_date: str, revision: int) -> bool:
        validated_date = validate_iso_date(meal_date)
        now_str = self._utc_now()
        with self._db_lock, self._database_manager.unit_of_work() as db:
            return self._nutrition_repository.mark_date_synced(
                db, validated_date, revision, now_str
            )
