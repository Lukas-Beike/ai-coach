"""Athlete profile normalization and persistence use cases."""

import json
import os
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend import change_history
from backend.errors import AppError
from backend.weather import cache as weather_cache

DEFAULT_TIMEZONE = "Europe/Berlin"

DEFAULT_PROFILE = {
    "name": "",
    "goals": "",
    "sports": "Cycling",
    "training_background": "",
    "typical_weekly_volume": "",
    "availability": "",
    "constraints": "",
    "equipment": "",
    "training_preferences": "",
    "performance_notes": "",
    "weight_kg": "",
    "body_fat_pct": "",
    "height_cm": "",
    "coaching_style": "Supportive, direct, and evidence-aware",
    "timezone": os.environ.get("TZ", DEFAULT_TIMEZONE),
    "weather_location": "",
}


def timezone_name(value: Any, *, strict: bool = False) -> str:
    """Return a valid IANA timezone name, falling back when allowed."""
    candidate = str(value or DEFAULT_TIMEZONE).strip()[:120] or DEFAULT_TIMEZONE
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError):
        if strict:
            raise AppError(400, "Die Zeitzone muss eine gültige IANA-Zeitzone sein.")
        return DEFAULT_TIMEZONE
    return candidate


def normalize_profile(
    value: dict[str, Any], *, validate_timezone: bool = False
) -> dict[str, str]:
    """Copy and normalize known profile fields without mutating the input."""
    result = dict(DEFAULT_PROFILE)
    for key in result:
        if key in value:
            result[key] = str(value[key]).strip()[:4000]
    result["timezone"] = timezone_name(result.get("timezone"), strict=validate_timezone)
    return result


class ProfileService:
    """Own profile reads, writes, audit history, and cache invalidation."""

    def __init__(
        self, manager: Any, profile_repository: Any, key_value_repository: Any
    ):
        self._manager = manager
        self._profile_repository = profile_repository
        self._key_value_repository = key_value_repository

    def get_from_db(self, db: Any) -> dict[str, str]:
        payload = self._profile_repository.get(db)
        try:
            return normalize_profile(json.loads(payload or "{}"))
        except (TypeError, json.JSONDecodeError):
            return dict(DEFAULT_PROFILE)

    def get(self) -> dict[str, str]:
        with self._manager.unit_of_work() as db:
            return self.get_from_db(db)

    def save_in_transaction(
        self,
        profile: dict[str, Any],
        db: Any,
        *,
        already_normalized: bool = False,
    ) -> dict[str, str]:
        normalized = (
            dict(profile)
            if already_normalized
            else normalize_profile(profile, validate_timezone=True)
        )
        previous = self.get_from_db(db)
        self._profile_repository.set(db, json.dumps(normalized, ensure_ascii=False))
        weather_cache.invalidate_for_location_change(
            previous,
            normalized,
            repository=self._key_value_repository,
            db=db,
        )
        change_history.record_change(
            db, "profile", "profile", "update", previous, normalized
        )
        return normalized

    def restore_in_transaction(
        self,
        db: Any,
        current: dict[str, Any] | None,
        target: dict[str, Any] | None,
    ) -> dict[str, str]:
        restored = dict(current or DEFAULT_PROFILE)
        restored.update(target or DEFAULT_PROFILE)
        normalized = normalize_profile(restored)
        self._profile_repository.set(db, json.dumps(normalized, ensure_ascii=False))
        return normalized

    def save(self, profile: dict[str, Any]) -> dict[str, str]:
        normalized = normalize_profile(profile, validate_timezone=True)
        with self._manager.unit_of_work() as db:
            return self.save_in_transaction(normalized, db, already_normalized=True)
