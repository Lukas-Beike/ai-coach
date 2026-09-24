"""Domain models and validation for nutrition tracking."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

from backend.errors import AppError

VALID_MEAL_TYPES = ("breakfast", "lunch", "dinner", "snack")
VALID_SOURCES = ("manual", "voice", "photo", "coach")

MAX_KCAL = 10000
MAX_MACRO_G = 1000.0
MAX_DESCRIPTION_LEN = 500
MEAL_DATE_REQUIRED = "meal_date ist erforderlich."


def validate_iso_date(value: Any) -> str:
    """Validate ISO-8601 YYYY-MM-DD date string."""
    text = str(value or "").strip()
    try:
        parsed = date.fromisoformat(text)
        return parsed.isoformat()
    except (ValueError, TypeError) as exc:
        raise AppError(400, f"Ungültiges Datumsformat '{value}'. Erwartet wird YYYY-MM-DD.") from exc


def meal_type_from_hour(hour: int) -> str:
    """Infer default meal type based on local hour of day."""
    if 5 <= hour < 11:
        return "breakfast"
    elif 11 <= hour < 15:
        return "lunch"
    elif 15 <= hour < 18:
        return "snack"
    elif 18 <= hour < 23:
        return "dinner"
    return "snack"


def _as_nonnegative_number(
    value: Any, name: str, max_value: float, *, clamp: bool = False
) -> float | None:
    if value is None or value == "":
        return None
    try:
        num = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        raise AppError(400, f"Ungültiger Wert für {name}: {value}")
    if not math.isfinite(num):
        raise AppError(400, f"{name} darf nicht unendlich oder NaN sein.")
    if clamp:
        num = max(0.0, min(num, max_value))
    else:
        if num < 0:
            raise AppError(400, f"{name} darf nicht negativ sein.")
        if num > max_value:
            raise AppError(400, f"{name} übersteigt das Maximum von {max_value}.")
    return round(num, 1)


@dataclass(frozen=True)
class NutritionEntry:
    id: str
    meal_date: str
    logged_at: str
    meal_type: str
    description: str
    kcal: int
    carbs_g: float | None = None
    protein_g: float | None = None
    fat_g: float | None = None
    source: str = "manual"
    sync_state: str = "local"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> NutritionEntry:
        return cls(
            id=str(data.get("id") or ""),
            meal_date=str(data.get("meal_date") or ""),
            logged_at=str(data.get("logged_at") or ""),
            meal_type=str(data.get("meal_type") or "snack"),
            description=str(data.get("description") or ""),
            kcal=int(data.get("kcal") or 0),
            carbs_g=float(data["carbs_g"]) if data.get("carbs_g") is not None else None,
            protein_g=float(data["protein_g"]) if data.get("protein_g") is not None else None,
            fat_g=float(data["fat_g"]) if data.get("fat_g") is not None else None,
            source=str(data.get("source") or "manual"),
            sync_state=str(data.get("sync_state") or "local"),
            created_at=str(data.get("created_at") or ""),
            updated_at=str(data.get("updated_at") or ""),
        )


@dataclass(frozen=True)
class NutritionDaySummary:
    date: str
    total_kcal: int
    total_carbs_g: float
    total_protein_g: float
    total_fat_g: float
    entry_count: int
    entries: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_nutrition_entry(
    raw: dict[str, Any],
    *,
    default_date: str | None = None,
    default_time: str | None = None,
    local_now_factory: Callable[[], datetime] | None = None,
    clamp_out_of_bounds: bool = False,
) -> dict[str, Any]:
    """Validate and normalize one raw nutrition payload."""
    if not isinstance(raw, dict):
        raise AppError(400, "Ernährungseintrag muss ein JSON-Objekt sein.")
    if local_now_factory is not None:
        now_dt = local_now_factory()
        default_date = default_date or now_dt.date().isoformat()
        default_time = default_time or now_dt.isoformat()
    raw_date = raw.get("meal_date") or raw.get("date") or default_date
    if not raw_date:
        raise AppError(400, MEAL_DATE_REQUIRED)
    meal_date = validate_iso_date(raw_date)
    logged_at = _normalize_logged_at(
        meal_date, raw.get("logged_at") or raw.get("meal_time") or default_time
    )
    meal_type = _normalize_meal_type(raw.get("meal_type"), logged_at)
    raw_desc = str(raw.get("description") or "").strip()
    if not raw_desc:
        raise AppError(400, "Beschreibung der Mahlzeit ist erforderlich.")
    description = raw_desc[:MAX_DESCRIPTION_LEN]
    carbs_g, protein_g, fat_g = _normalize_macros(raw, clamp_out_of_bounds)
    return {
        "meal_date": meal_date,
        "logged_at": logged_at,
        "meal_type": meal_type,
        "description": description,
        "kcal": _normalize_calories(raw, clamp_out_of_bounds),
        "carbs_g": carbs_g,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "source": _normalize_source(raw.get("source")),
        "sync_state": "local",
        **({"id": str(raw["id"])} if raw.get("id") else {}),
    }


def _normalize_logged_at(meal_date: str, value: Any) -> str:
    if not value:
        return f"{meal_date}T12:00:00"
    try:
        timestamp = str(value)
        if "T" not in timestamp:
            timestamp = f"{meal_date}T{timestamp}"
        datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        return timestamp
    except (ValueError, TypeError):
        return f"{meal_date}T12:00:00"


def _normalize_meal_type(value: Any, logged_at: str) -> str:
    meal_type = str(value or "").strip().lower()
    if not meal_type:
        meal_type = meal_type_from_hour(datetime.fromisoformat(logged_at.replace("Z", "+00:00")).hour)
    if meal_type not in VALID_MEAL_TYPES:
        raise AppError(
            400,
            f"Ungültiger Mahlzeittyp '{meal_type}'. Erlaubt sind: {', '.join(VALID_MEAL_TYPES)}.",
        )
    return meal_type


def _normalize_calories(raw: dict[str, Any], clamp: bool) -> int:
    value = raw.get("kcal") if raw.get("kcal") is not None else raw.get("calories")
    if value is None:
        raise AppError(400, "Kalorienangabe (kcal) ist erforderlich.")
    try:
        calories = float(str(value).replace(",", "."))
    except (TypeError, ValueError) as exc:
        raise AppError(400, f"Ungültige Kalorienangabe: {value}") from exc
    if not math.isfinite(calories):
        raise AppError(400, "Kalorien dürfen nicht unendlich oder NaN sein.")
    if clamp:
        calories = max(0.0, min(calories, float(MAX_KCAL)))
    elif calories < 0 or calories > MAX_KCAL:
        raise AppError(400, f"Kalorien müssen zwischen 0 und {MAX_KCAL} liegen.")
    return int(round(calories))


def _normalize_macros(raw: dict[str, Any], clamp: bool) -> tuple[float | None, float | None, float | None]:
    values = []
    for aliases, label in (
        (("carbs_g", "carbs", "carbohydrates"), "Kohlenhydrate"),
        (("protein_g", "protein"), "Protein"),
        (("fat_g", "fat"), "Fett"),
    ):
        value = next((raw[key] for key in aliases if raw.get(key) is not None), None)
        values.append(_as_nonnegative_number(value, label, MAX_MACRO_G, clamp=clamp))
    return tuple(values)


def _normalize_source(value: Any) -> str:
    source = str(value or "manual").strip().lower()
    return source if source in VALID_SOURCES else "manual"
