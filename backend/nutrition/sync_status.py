"""Read and update diary synchronization state."""

from __future__ import annotations

import json
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import date, datetime, timedelta
from typing import Any

from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository, NutritionRepository
from backend.errors import AppError
from backend.nutrition.contracts import nutrition_approval_item
from backend.nutrition.models import validate_iso_date
from backend.performance.canonical_inputs import resolve_reader
from backend.performance.daily_health import (
    daily_energy_expenditure,
    read_daily_health_by_date,
)
from backend.runtime.ports import ObservationReader


class NutritionSyncStatusService:
    def __init__(
        self,
        database_manager: DatabaseManager,
        db_lock: AbstractContextManager[Any],
        nutrition_repository: NutritionRepository,
        utc_now: Callable[[], str],
        local_now: Callable[[], datetime],
        observation_reader: Callable[[], ObservationReader] | None = None,
    ) -> None:
        self._observation_reader = observation_reader
        self._database_manager = database_manager
        self._db_lock = db_lock
        self._nutrition_repository = nutrition_repository
        self._key_value_repository = KeyValueRepository(utc_now)
        self._utc_now = utc_now
        self._local_now = local_now

    def get_day_summary(self, meal_date: str) -> dict[str, Any]:
        validated_date = validate_iso_date(meal_date)
        with self._database_manager.read_snapshot() as db:
            summary = self._nutrition_repository.day_summary(db, validated_date)
            # The snapshot only carries the resting calories (no metric kind) and
            # the daily-stats sync status.
            serialized_garmin = self._key_value_repository.get(db, "garmin_snapshot")
            measured = self._measured_energy(db, validated_date, validated_date)
        try:
            garmin_snapshot = json.loads(serialized_garmin or "{}")
        except TypeError, ValueError:
            garmin_snapshot = {}
        if not isinstance(garmin_snapshot, dict):
            garmin_snapshot = {}
        if measured is not None:
            measured = _filter_targeted_missing_energy(
                measured, garmin_snapshot, [validated_date]
            )
        summary["energy_expenditure"] = daily_energy_expenditure(
            garmin_snapshot,
            validated_date,
            self._local_now().date(),
            measured=None if measured is None else measured.get(validated_date, {}),
        )
        return summary

    def _measured_energy(
        self, db: Any, start: str, end: str
    ) -> dict[str, dict[str, Any]] | None:
        """Read the canonical daily energy, or None without an observation reader."""
        if self._observation_reader is None:
            return None
        return read_daily_health_by_date(
            resolve_reader(self._observation_reader(), db),
            db,
            start=date.fromisoformat(start),
            end=date.fromisoformat(end),
        )

    def get_sync_snapshot(self, meal_date: str) -> dict[str, Any]:
        validated_date = validate_iso_date(meal_date)
        with self._db_lock, self._database_manager.unit_of_work() as db:
            return self._nutrition_repository.day_sync_snapshot(db, validated_date)

    def get_week_summary(self, day_count: int = 7) -> dict[str, Any]:
        """Compare logged intake with measured expenditure for closed days."""
        if type(day_count) is not int or day_count not in (7, 14, 84):
            raise AppError(400, "Zeitraum muss 7, 14 oder 84 Tage umfassen.")
        today = self._local_now().date()
        dates = [
            (today - timedelta(days=offset)).isoformat()
            for offset in range(day_count, 0, -1)
        ]
        with self._database_manager.read_snapshot() as db:
            summaries = [
                self._nutrition_repository.day_summary(db, day) for day in dates
            ]
            serialized = self._key_value_repository.get(db, "garmin_snapshot")
            measured = self._measured_energy(db, dates[0], dates[-1])
        try:
            snapshot = json.loads(serialized or "{}")
        except TypeError, ValueError:
            snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {}
        if measured is not None:
            measured = _filter_targeted_missing_energy(measured, snapshot, dates)
        days = []
        for summary in summaries:
            expenditure = daily_energy_expenditure(
                snapshot,
                summary["date"],
                today,
                measured=None
                if measured is None
                else measured.get(summary["date"], {}),
            )
            days.append(_week_day(summary, expenditure))
        averages = {}
        for key in ("intake_kcal", "expenditure_kcal", "carbs_g", "protein_g", "fat_g"):
            values = [day[key] for day in days if day[key] is not None]
            averages[key] = {
                "value": round(sum(values) / len(values), 1) if values else None,
                "days": len(values),
            }
        balances = [
            day["balance_kcal"] for day in days if day["balance_kcal"] is not None
        ]
        return {
            "start_date": dates[0],
            "end_date": dates[-1],
            "days": days,
            "averages": averages,
            "balance_kcal": sum(balances) if balances else None,
            "balance_days": len(balances),
        }

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


def _week_day(summary: dict[str, Any], expenditure: dict[str, Any]) -> dict[str, Any]:
    """One closed day of the week summary: logged intake against expenditure."""
    logged = bool(summary["entry_count"])
    intake = summary["total_kcal"] if logged else None
    consumed = expenditure["total_kcal"]
    return {
        "date": summary["date"],
        "intake_kcal": intake,
        "expenditure_kcal": consumed,
        "balance_kcal": intake - consumed
        if intake is not None and consumed is not None
        else None,
        "energy_expenditure": expenditure,
        **{
            key: summary[f"total_{key}"] if logged else None
            for key in ("carbs_g", "protein_g", "fat_g")
        },
    }


def _filter_targeted_missing_energy(
    measured: dict[str, dict[str, Any]], snapshot: dict[str, Any], dates: list[str]
) -> dict[str, dict[str, Any]]:
    """Do not reuse older canonical observations after a complete empty day read."""
    nutrition_refresh = snapshot.get("nutrition_refresh")
    targeted = (
        nutrition_refresh.get("daily_stats", {})
        if isinstance(nutrition_refresh, dict)
        else {}
    )
    if not isinstance(targeted, dict):
        return measured
    records = snapshot.get("daily_stats")
    observed_dates = {
        str(record.get(key))[:10]
        for record in records
        if isinstance(record, dict)
        for key in ("calendarDate", "summaryDate", "date")
        if record.get(key)
    } if isinstance(records, list) else set()
    result = dict(measured)
    for day in dates:
        refresh = targeted.get(day)
        if (
            isinstance(refresh, dict)
            and refresh.get("freshness") == "current"
            and day not in observed_dates
        ):
            result[day] = {}
    return result
