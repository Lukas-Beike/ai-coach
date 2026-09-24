"""Platform synchronization service for nutrition and calorie data."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from urllib.parse import quote

from backend.config import Config
from backend.errors import AppError
from backend.nutrition.service import NutritionService
from backend.providers.intervals import IntervalsApiClient

logger = logging.getLogger("ai_coach.nutrition.sync")


class IntervalsNutritionSyncService:
    """Synchronize aggregated daily calories and macronutrients to Intervals.icu wellness."""

    def __init__(
        self,
        config: Config,
        api_client: IntervalsApiClient,
        nutrition_service: NutritionService,
    ) -> None:
        self._config = config
        self._api_client = api_client
        self._nutrition_service = nutrition_service

    @property
    def _athlete_id(self) -> str:
        raw_id = self._config.intervals_athlete_id or "0"
        return quote(str(raw_id).strip(), safe="")

    def sync_day(self, meal_date: str) -> dict[str, Any]:
        """Push daily calorie and macro aggregates for a specific date to Intervals.icu."""
        summary = self._nutrition_service.get_day_summary(meal_date)
        athlete = self._athlete_id
        if not athlete:
            raise AppError(400, "Intervals Athlete-ID ist nicht konfiguriert.")

        payload: dict[str, Any] = {
            "id": meal_date,
            "kcalConsumed": summary["total_kcal"],
        }
        if summary.get("total_carbs_g") is not None and summary["total_carbs_g"] > 0:
            payload["carbs"] = summary["total_carbs_g"]
        if summary.get("total_protein_g") is not None and summary["total_protein_g"] > 0:
            payload["protein"] = summary["total_protein_g"]
        if summary.get("total_fat_g") is not None and summary["total_fat_g"] > 0:
            payload["fat"] = summary["total_fat_g"]

        endpoint = f"/athlete/{athlete}/wellness/{meal_date}"
        try:
            remote_record = self._api_client.put(endpoint, payload)
            self._nutrition_service.mark_date_synced(meal_date)
            return {
                "ok": True,
                "date": meal_date,
                "remote_endpoint": endpoint,
                "synced_summary": {
                    "kcalConsumed": summary["total_kcal"],
                    "carbs": summary.get("total_carbs_g"),
                    "protein": summary.get("total_protein_g"),
                    "fat": summary.get("total_fat_g"),
                },
                "remote_response": remote_record,
            }
        except Exception as exc:
            logger.warning(
                "Nutrition sync failed for %s (%s)", meal_date, type(exc).__name__
            )
            raise

    def sync_pending(self, limit: int = 14) -> dict[str, Any]:
        """Push all unsynced dates within the limit to Intervals.icu."""
        try:
            limit = int(limit)
        except (TypeError, ValueError) as exc:
            raise AppError(400, "Ungültiges Sync-Limit.") from exc
        if not 1 <= limit <= 31:
            raise AppError(400, "Das Sync-Limit muss zwischen 1 und 31 Tagen liegen.")
        unsynced_dates = self._nutrition_service.list_unsynced_dates(limit=limit)
        synced: list[str] = []
        errors: dict[str, str] = {}

        for d in unsynced_dates:
            try:
                self.sync_day(d)
                synced.append(d)
            except Exception as exc:
                errors[d] = str(exc)

        return {
            "ok": len(errors) == 0,
            "synced_dates": synced,
            "failed_dates": errors,
            "total_pending": len(unsynced_dates),
        }
