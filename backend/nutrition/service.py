"""Nutrition domain service orchestrating meal tracking, summaries and sync states."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Any

from backend.db.manager import DatabaseManager
from backend.db.repositories import NutritionRepository
from backend.errors import AppError
from backend.nutrition.models import (
    NutritionDaySummary,
    NutritionEntry,
    normalize_nutrition_entry,
    validate_iso_date,
)

INVALID_ENTRY_ID = "Ungültige Eintrags-ID."
ENTRY_NOT_FOUND = "Ernährungseintrag nicht gefunden."


class NutritionService:
    """Orchestrates nutrition logging, daily aggregations and sync markers."""

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
        self._utc_now = utc_now
        self._local_now = local_now

    def log_meal(self, payload: Any) -> dict[str, Any]:
        """Normalize, validate and store a meal entry."""
        entry = normalize_nutrition_entry(payload, local_now_factory=self._local_now)
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
        entry = normalize_nutrition_entry(payload, local_now_factory=self._local_now)
        entry["id"] = clean_id

        with self._db_lock, self._database_manager.unit_of_work() as db:
            existing = self._nutrition_repository.get(db, clean_id)
            if not existing:
                raise AppError(404, ENTRY_NOT_FOUND)
            updated = self._nutrition_repository.update(db, clean_id, entry)
        if not updated:
            raise AppError(404, ENTRY_NOT_FOUND)
        return updated

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
            entries = self._nutrition_repository.list_by_range(db, valid_start, valid_end)

        by_date: dict[str, list[dict[str, Any]]] = {}
        for entry in entries:
            d = entry["meal_date"]
            by_date.setdefault(d, []).append(entry)

        summaries: list[dict[str, Any]] = []
        for date_key in sorted(by_date.keys()):
            day_entries = by_date[date_key]
            total_kcal = sum(int(e["kcal"]) for e in day_entries)
            total_carbs = round(sum(float(e["carbs_g"]) for e in day_entries if e.get("carbs_g") is not None), 1)
            total_protein = round(sum(float(e["protein_g"]) for e in day_entries if e.get("protein_g") is not None), 1)
            total_fat = round(sum(float(e["fat_g"]) for e in day_entries if e.get("fat_g") is not None), 1)
            summaries.append(
                NutritionDaySummary(
                    date=date_key,
                    total_kcal=total_kcal,
                    total_carbs_g=total_carbs,
                    total_protein_g=total_protein,
                    total_fat_g=total_fat,
                    entry_count=len(day_entries),
                    entries=[NutritionEntry.from_dict(e).to_dict() for e in day_entries],
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
            recent_entries = self._nutrition_repository.list_by_range(db, past_week, today)
        return {
            "today": today_summary,
            "recent_entries_count": len(recent_entries),
            "recent_entries": recent_entries[-10:],
            "scope": "Athlete-entered nutrition logs and calorie totals.",
        }
