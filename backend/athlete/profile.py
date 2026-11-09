"""Athlete profile normalization and persistence use cases."""

import json
import math
import os
from collections.abc import Callable
from datetime import date
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend import change_history
from backend.athlete import weekly_plan
from backend.canonical.first_threshold import (
    FIRST_THRESHOLD_BOUNDS,
    FIRST_THRESHOLD_DATE_FIELD,
    FIRST_THRESHOLD_ENTRY_FIELD,
    FIRST_THRESHOLD_FIELD,
    FIRST_THRESHOLD_PERCENT_BOUNDS,
    first_threshold_bpm,
    first_threshold_percent,
    percent_of_lthr,
)
from backend.canonical.vocabulary import ProviderId
from backend.errors import AppError

DEFAULT_TIMEZONE = "Europe/Berlin"
# Intensity distribution the Coach plans with; pyramidal unless the athlete chooses.
TRAINING_MODELS = ("pyramidal", "polarized", "threshold", "sweet_spot")
# The athlete's preferred source per metric group (#1668); empty keeps the
# default order. ``source_policy.PREFERENCE_PROFILE_FIELDS`` reads these fields.
PREFERRED_SOURCE_FIELDS = (
    "preferred_source_thresholds",
    "preferred_source_body",
    "preferred_source_hrv",
    "preferred_source_resting_hr",
    "preferred_source_sleep",
)
PREFERRED_SOURCES = ("", ProviderId.GARMIN.value)
# The athlete's sex for sex-specific methods (M6 TRIMP constants, #1774); empty
# means not set.
SEXES = ("", "male", "female")
# The athlete's measured first threshold heart rate (bpm, for example from a lab
# test); empty means not set. Only the athlete sets it, through the profile form
# or the API: the Coach can read it but never write it.
COACH_READ_ONLY_FIELDS = frozenset({FIRST_THRESHOLD_FIELD})

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
    "training_preferences_running": "",
    "training_preferences_cycling": "",
    "training_preferences_swimming": "",
    "training_preferences_strength": "",
    "training_preferences_mobility": "",
    "training_model": TRAINING_MODELS[0],
    "weekly_plan": "",
    "performance_notes": "",
    "weight_kg": "",
    "body_fat_pct": "",
    "height_cm": "",
    "sex": "",
    "coaching_style": "Supportive, direct, and evidence-aware",
    "timezone": os.environ.get("TZ", DEFAULT_TIMEZONE),
    "weather_location": "",
    "sleep_target_hours": "",
    "fueling_tolerance": "",
    FIRST_THRESHOLD_FIELD: "",
    **dict.fromkeys(PREFERRED_SOURCE_FIELDS, ""),
}


def timezone_name(value: Any, *, strict: bool = False) -> str:
    """Return a valid IANA timezone name, falling back when allowed."""
    candidate = str(value or DEFAULT_TIMEZONE).strip()[:120] or DEFAULT_TIMEZONE
    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError, ValueError:
        if strict:
            raise AppError(400, "Die Zeitzone muss eine gültige IANA-Zeitzone sein.")
        return DEFAULT_TIMEZONE
    return candidate


def _normalize_preferred_sources(result: dict[str, str], *, strict: bool) -> None:
    """Reject (strict) or clear an unknown preferred source."""
    for field_name in PREFERRED_SOURCE_FIELDS:
        if result[field_name] in PREFERRED_SOURCES:
            continue
        if strict:
            raise AppError(
                400,
                "Unbekannte bevorzugte Quelle; erlaubt: "
                + ", ".join(PREFERRED_SOURCES[1:])
                + " oder leer.",
            )
        result[field_name] = ""


def _normalize_sex(result: dict[str, str], *, strict: bool) -> None:
    """Reject (strict) or clear an unknown sex."""
    if result["sex"] in SEXES:
        return
    if strict:
        raise AppError(400, "Unbekanntes Geschlecht; erlaubt: male, female oder leer.")
    result["sex"] = ""


def _normalize_first_threshold(result: dict[str, str], *, strict: bool) -> None:
    """Keep a plausible stored first threshold (percent of LTHR); reject or clear another.

    The entry fields (bpm and measurement date) are consumed by the profile
    service when it saves and are no profile fields: a stored profile never has them.
    """
    text = result[FIRST_THRESHOLD_FIELD]
    if not text:
        return
    number = first_threshold_percent(text)
    if number is not None:
        result[FIRST_THRESHOLD_FIELD] = f"{number:g}"
        return
    if strict:
        low, high = FIRST_THRESHOLD_PERCENT_BOUNDS
        raise AppError(
            400,
            f"Die gemessene erste Schwelle muss zwischen {low:g} und {high:g} % LSHF liegen.",
        )
    result[FIRST_THRESHOLD_FIELD] = ""


def normalize_profile(
    value: dict[str, Any], *, validate_timezone: bool = False
) -> dict[str, str]:
    """Copy and normalize known profile fields without mutating the input."""
    result = dict(DEFAULT_PROFILE)
    for key in result:
        if key in value and key != "weekly_plan":
            result[key] = str(value[key]).strip()[:4000]
    result["weekly_plan"] = weekly_plan.normalize(
        value.get("weekly_plan", ""), strict=validate_timezone
    )
    result["timezone"] = timezone_name(result.get("timezone"), strict=validate_timezone)
    if result["training_model"] not in TRAINING_MODELS:
        if validate_timezone and result["training_model"]:
            raise AppError(
                400,
                "Unbekanntes Trainingsmodell; erlaubt: " + ", ".join(TRAINING_MODELS),
            )
        result["training_model"] = TRAINING_MODELS[0]
    _normalize_preferred_sources(result, strict=validate_timezone)
    _normalize_sex(result, strict=validate_timezone)
    _normalize_first_threshold(result, strict=validate_timezone)
    if result["sleep_target_hours"]:
        try:
            target = float(result["sleep_target_hours"])
        except ValueError as exc:
            raise AppError(
                400, "Das Schlafziel muss zwischen 4 und 12 Stunden liegen."
            ) from exc
        if not math.isfinite(target) or not 4 <= target <= 12:
            raise AppError(400, "Das Schlafziel muss zwischen 4 und 12 Stunden liegen.")
    return result


class ProfileService:
    """Own profile reads, writes, audit history, and cache invalidation."""

    def __init__(
        self,
        manager: Any,
        profile_repository: Any,
        key_value_repository: Any,
        *,
        on_location_changed: Callable[..., Any],
        mutation_coordinator: Any,
        run_lthr_on: Callable[[date | None], float | None] = lambda _day: None,
    ):
        self.mutation_coordinator = mutation_coordinator
        self._manager = manager
        self._profile_repository = profile_repository
        self._key_value_repository = key_value_repository
        self._on_location_changed = on_location_changed
        self._run_lthr_on = run_lthr_on

    def get_from_db(self, db: Any) -> dict[str, str]:
        payload = self._profile_repository.get(db)
        try:
            return normalize_profile(json.loads(payload or "{}"))
        except TypeError, json.JSONDecodeError:
            return dict(DEFAULT_PROFILE)

    def get(self) -> dict[str, str]:
        with self._manager.reader() as db:
            return self.get_from_db(db)

    def revision(self) -> str | None:
        """Identify the latest committed profile history entry for export ordering."""
        with self._manager.reader() as db:
            row = db.execute(
                "SELECT id FROM change_history WHERE entity_type=? AND entity_id=? ORDER BY rowid DESC LIMIT 1",
                ("profile", "profile"),
            ).fetchone()
            return str(row["id"]) if row else None

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
            else normalize_profile(
                self._with_first_threshold(profile), validate_timezone=True
            )
        )
        previous = self.get_from_db(db)
        self._profile_repository.set(db, json.dumps(normalized, ensure_ascii=False))
        self._on_location_changed(
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
        previous = self.get_from_db(db)
        self._profile_repository.set(db, json.dumps(normalized, ensure_ascii=False))
        self._on_location_changed(
            previous,
            normalized,
            repository=self._key_value_repository,
            db=db,
        )
        return normalized

    def _with_first_threshold(self, profile: dict[str, Any]) -> dict[str, Any]:
        """Turn an entered first threshold (bpm) into percent of the LTHR on its date.

        The entry is the athlete's own explicit input; the stored value is the
        percent of the run threshold HR in effect on the measurement date (today
        when none is given), so the threshold's later changes never move it.
        """
        entry = str(profile.get(FIRST_THRESHOLD_ENTRY_FIELD) or "").strip()
        if not entry:
            return profile
        bpm = first_threshold_bpm(entry)
        low, high = FIRST_THRESHOLD_BOUNDS
        if bpm is None:
            raise AppError(
                400,
                f"Die gemessene erste Schwelle muss zwischen {low} und {high} bpm liegen.",
            )
        text = str(profile.get(FIRST_THRESHOLD_DATE_FIELD) or "").strip()
        try:
            measured_on = date.fromisoformat(text) if text else None
        except ValueError as exc:
            raise AppError(
                400, "Das Messdatum muss das Format JJJJ-MM-TT haben."
            ) from exc
        lthr = self._run_lthr_on(measured_on)
        percent = None if lthr is None else percent_of_lthr(bpm, lthr)
        if percent is None:
            raise AppError(
                400,
                "Zu diesem Datum ist keine Laktatschwelle (LSHF) bekannt, mit der die "
                "erste Schwelle in Prozent gespeichert werden kann.",
            )
        return {**profile, FIRST_THRESHOLD_FIELD: f"{percent:g}"}

    def save(self, profile: dict[str, Any]) -> dict[str, str]:
        """Replace the whole profile; callers must send every field they keep."""
        normalized = normalize_profile(
            self._with_first_threshold(profile), validate_timezone=True
        )
        with self.mutation_coordinator, self._manager.unit_of_work() as db:
            return self.save_in_transaction(normalized, db, already_normalized=True)

    def patch(self, changes: dict[str, Any]) -> dict[str, str]:
        """Apply only the submitted fields onto the profile stored in this transaction."""
        if not isinstance(changes, dict):
            raise AppError(400, "Die Profiländerung muss ein Objekt sein.")
        with self.mutation_coordinator, self._manager.unit_of_work() as db:
            current = self.get_from_db(db)
            return self.save_in_transaction({**current, **changes}, db)
