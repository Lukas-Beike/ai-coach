"""Platform synchronization service for nutrition and calorie data."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import quote

from backend.config import Config
from backend.errors import AppError
from backend.nutrition.service import (
    NutritionService,
    nutrition_approval_item,
    nutrition_approval_item_matches,
)
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

    def sync_day(
        self, meal_date: str, *, approval: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Push daily calorie and macro aggregates for a specific date to Intervals.icu."""
        summary = self._nutrition_service.get_sync_snapshot(meal_date)
        if approval is not None and not nutrition_approval_item_matches(
            approval, nutrition_approval_item(summary)
        ):
            raise AppError(
                409, "Nutrition data changed after approval; no update was sent."
            )
        revision = summary.pop("sync_revision")
        athlete = self._athlete_id
        if not athlete:
            raise AppError(400, "Intervals Athlete-ID ist nicht konfiguriert.")

        payload: dict[str, Any] = {
            "id": meal_date,
            "kcalConsumed": summary["total_kcal"],
        }
        if summary.get("total_carbs_g") is not None:
            payload["carbs"] = summary["total_carbs_g"]
        if summary.get("total_protein_g") is not None:
            payload["protein"] = summary["total_protein_g"]
        if summary.get("total_fat_g") is not None:
            payload["fat"] = summary["total_fat_g"]

        endpoint = f"/athlete/{athlete}/wellness/{meal_date}"
        try:
            remote_record = self._api_client.put(endpoint, payload)
            current = self._nutrition_service.mark_date_synced(meal_date, revision)
            return {
                "ok": True,
                "date": meal_date,
                "pending": not current,
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

    def sync_approved(self, manifest: list[dict[str, Any]]) -> dict[str, Any]:
        """Validate the complete approval, then sync only its frozen dates."""
        if not isinstance(manifest, list) or len(manifest) > 31:
            raise AppError(409, "The approved nutrition manifest is invalid.")
        dates = [entry.get("date") for entry in manifest if isinstance(entry, dict)]
        if len(dates) != len(manifest) or len(set(dates)) != len(dates):
            raise AppError(409, "The approved nutrition manifest is invalid.")
        current = self._nutrition_service.approval_manifest(dates=dates)
        if len(current) != len(manifest) or any(
            not nutrition_approval_item_matches(expected, actual)
            for expected, actual in zip(manifest, current)
        ):
            raise AppError(
                409, "Nutrition data changed after approval; no updates were sent."
            )
        synced: list[str] = []
        pending: list[str] = []
        errors: dict[str, str] = {}
        for approved in manifest:
            meal_date = str(approved["date"])
            try:
                result = self.sync_day(meal_date, approval=approved)
                (pending if result["pending"] else synced).append(meal_date)
            except AppError as exc:
                errors[meal_date] = str(exc)
            except Exception as exc:
                errors[meal_date] = str(exc)
        return {
            "ok": not pending and not errors,
            "synced_dates": synced,
            "pending_dates": pending,
            "failed_dates": errors,
            "total_pending": len(manifest),
        }

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
        pending: list[str] = []
        errors: dict[str, str] = {}

        for d in unsynced_dates:
            try:
                result = self.sync_day(d)
                (pending if result["pending"] else synced).append(d)
            except Exception as exc:
                errors[d] = str(exc)

        return {
            "ok": len(errors) == 0 and len(pending) == 0,
            "synced_dates": synced,
            "pending_dates": pending,
            "failed_dates": errors,
            "total_pending": len(unsynced_dates),
        }
