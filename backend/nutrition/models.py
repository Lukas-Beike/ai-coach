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
VALID_SYNC_STATES = ("local", "synced", "pending", "failed")

MAX_KCAL = 10000
MAX_MACRO_G = 1000.0
MAX_DESCRIPTION_LEN = 500


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
        if not default_date:
            default_date = now_dt.date().isoformat()
        if not default_time:
            default_time = now_dt.isoformat()

    # 1. Date
    raw_date = raw.get("meal_date") or raw.get("date") or default_date
    if not raw_date:
        raise AppError(400, "meal_date ist erforderlich.")
    meal_date = validate_iso_date(raw_date)

    # 2. Logged at timestamp
    raw_logged_at = raw.get("logged_at") or default_time
    if not raw_logged_at and raw.get("meal_time"):
        raw_logged_at = f"{meal_date}T{str(raw['meal_time']).strip()}"
    if raw_logged_at:
        try:
            # Check ISO format
            datetime.fromisoformat(str(raw_logged_at).replace("Z", "+00:00"))
            logged_at = str(raw_logged_at)
        except (ValueError, TypeError):
            logged_at = f"{meal_date}T12:00:00"
    else:
        logged_at = f"{meal_date}T12:00:00"

    # 3. Meal type
    raw_meal_type = str(raw.get("meal_type") or "").strip().lower()
    if not raw_meal_type:
        try:
            dt = datetime.fromisoformat(logged_at.replace("Z", "+00:00"))
            raw_meal_type = meal_type_from_hour(dt.hour)
        except Exception:
            raw_meal_type = "snack"
    if raw_meal_type not in VALID_MEAL_TYPES:
        raise AppError(
            400,
            f"Ungültiger Mahlzeittyp '{raw_meal_type}'. Erlaubt sind: {', '.join(VALID_MEAL_TYPES)}.",
        )
    meal_type = raw_meal_type

    # 4. Description
    raw_desc = str(raw.get("description") or "").strip()
    if not raw_desc:
        raise AppError(400, "Beschreibung der Mahlzeit ist erforderlich.")
    description = raw_desc[:MAX_DESCRIPTION_LEN]

    # 5. Calories (kcal)
    raw_kcal = raw.get("kcal")
    if raw_kcal is None:
        raw_kcal = raw.get("calories")
    if raw_kcal is None:
        raise AppError(400, "Kalorienangabe (kcal) ist erforderlich.")
    try:
        kcal_num = float(str(raw_kcal).replace(",", "."))
    except (TypeError, ValueError):
        raise AppError(400, f"Ungültige Kalorienangabe: {raw_kcal}")
    if not math.isfinite(kcal_num):
        raise AppError(400, "Kalorien dürfen nicht unendlich oder NaN sein.")

    if clamp_out_of_bounds:
        kcal_num = max(0.0, min(kcal_num, float(MAX_KCAL)))
    else:
        if kcal_num < 0:
            raise AppError(400, "Kalorien dürfen nicht negativ sein.")
        if kcal_num > MAX_KCAL:
            raise AppError(400, f"Kalorien übersteigen das Maximum von {MAX_KCAL} kcal.")
    kcal = int(round(kcal_num))

    # 6. Macros (optional)
    carbs_value = next((raw[key] for key in ("carbs_g", "carbs", "carbohydrates") if raw.get(key) is not None), None)
    protein_value = next((raw[key] for key in ("protein_g", "protein") if raw.get(key) is not None), None)
    fat_value = next((raw[key] for key in ("fat_g", "fat") if raw.get(key) is not None), None)
    carbs_g = _as_nonnegative_number(
        carbs_value,
        "Kohlenhydrate",
        MAX_MACRO_G,
        clamp=clamp_out_of_bounds,
    )
    protein_g = _as_nonnegative_number(
        protein_value,
        "Protein",
        MAX_MACRO_G,
        clamp=clamp_out_of_bounds,
    )
    fat_g = _as_nonnegative_number(
        fat_value,
        "Fett",
        MAX_MACRO_G,
        clamp=clamp_out_of_bounds,
    )

    # 7. Source & Sync state
    source = str(raw.get("source") or "manual").strip().lower()
    if source not in VALID_SOURCES:
        source = "manual"

    # Sync state is owned by the server; client payloads cannot suppress a push.
    sync_state = "local"

    entry_dict: dict[str, Any] = {
        "meal_date": meal_date,
        "logged_at": logged_at,
        "meal_type": meal_type,
        "description": description,
        "kcal": kcal,
        "carbs_g": carbs_g,
        "protein_g": protein_g,
        "fat_g": fat_g,
        "source": source,
        "sync_state": sync_state,
    }
    if raw.get("id"):
        entry_dict["id"] = str(raw["id"])
    return entry_dict
