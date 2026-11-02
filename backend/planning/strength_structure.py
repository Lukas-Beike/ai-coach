"""Compact structure of a strength unit: exercises with sets, reps, load and rest.

Stored as ``strength_structure`` in the planned unit or library template
payload. It carries planning content and progression only, never a load number.
The readable description is generated from it; free text stays the fallback
for a unit without a structure. No I/O.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Final

from backend.athlete.measurements import number
from backend.errors import AppError

MAX_EXERCISES: Final = 12
MAX_SETS: Final = 10
MAX_REPS: Final = 100
MAX_KG: Final = 1000
MAX_PCT: Final = 150
MAX_REST_S: Final = 600
LOAD_KEYS: Final = ("kg", "pct_1rm", "rpe", "rir")
EXERCISE_KEYS: Final = ("name", "sets", "reps", *LOAD_KEYS, "rest_s")
# Heavy from 80 % 1RM, RPE 8 or 2 reps in reserve; moderate from 65 %, RPE 6, RIR 4.
HEAVY_PCT: Final = 80
MODERATE_PCT: Final = 65
HEAVY_RPE: Final = 8
MODERATE_RPE: Final = 6
HEAVY_RIR: Final = 2
MODERATE_RIR: Final = 4
_RANK: Final = {"light": 0, "moderate": 1, "heavy": 2}


def _invalid(message: str) -> AppError:
    return AppError(400, message, reason="invalid_strength_structure")


def _bounded(
    value: Any, label: str, low: float, high: float, *, whole: bool
) -> float | int:
    parsed = number(value)
    if parsed is None or not low <= parsed <= high or (whole and parsed % 1):
        raise _invalid(f"Ungültiger Wert für {label} in der Kraftstruktur.")
    return int(parsed) if whole else parsed


def _exercise(item: Any) -> dict[str, Any]:
    if not isinstance(item, Mapping) or set(item) - set(EXERCISE_KEYS):
        raise _invalid("Jede Übung der Kraftstruktur muss ein bekanntes Objekt sein.")
    name = str(item.get("name") or "").strip()[:80]
    if not name:
        raise _invalid("Jede Übung der Kraftstruktur benötigt einen Namen.")
    result: dict[str, Any] = {
        "name": name,
        "sets": _bounded(item.get("sets"), "Sätze", 1, MAX_SETS, whole=True),
        "reps": _bounded(item.get("reps"), "Wiederholungen", 1, MAX_REPS, whole=True),
    }
    limits = {
        "kg": (0, MAX_KG, False),
        "pct_1rm": (1, MAX_PCT, False),
        "rpe": (1, 10, False),
        "rir": (0, 10, True),
        "rest_s": (0, MAX_REST_S, True),
    }
    for key, (low, high, whole) in limits.items():
        if item.get(key) not in (None, ""):
            result[key] = _bounded(item[key], key, low, high, whole=whole)
    if sum(key in result for key in ("pct_1rm", "rpe", "rir")) > 1:
        raise _invalid("Pro Übung nur eine relative Last: %1RM, RPE oder RIR.")
    return result


def normalize_structure(value: Any) -> list[dict[str, Any]] | None:
    """Validated exercises, or ``None`` when no structure is given."""
    if value in (None, "", []):
        return None
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise _invalid("Die Kraftstruktur muss eine Liste von Übungen sein.")
    if len(value) > MAX_EXERCISES:
        raise _invalid(f"Die Kraftstruktur erlaubt höchstens {MAX_EXERCISES} Übungen.")
    return [_exercise(item) for item in value]


def _plain(value: float | int) -> str:
    return str(int(value)) if float(value) == int(value) else f"{value:g}"


def _load_text(item: Mapping[str, Any]) -> str:
    parts = []
    if "kg" in item:
        parts.append(f"{_plain(item['kg'])} kg")
    if "pct_1rm" in item:
        parts.append(f"{_plain(item['pct_1rm'])} % 1RM")
    if "rpe" in item:
        parts.append(f"RPE {_plain(item['rpe'])}")
    if "rir" in item:
        parts.append(f"{item['rir']} RIR")
    return ", ".join(parts)


def render(exercises: Sequence[Mapping[str, Any]]) -> str:
    """One readable line per exercise, e.g. ``Kniebeuge: 4x5 @ 85 % 1RM, 180 s Pause``."""
    lines = []
    for item in exercises:
        line = f"{item['name']}: {item['sets']}x{item['reps']}"
        load = _load_text(item)
        if load:
            line += f" @ {load}"
        if "rest_s" in item:
            line += f", {item['rest_s']} s Pause"
        lines.append(line)
    return "\n".join(lines)


def _grade(item: Mapping[str, Any]) -> str | None:
    if "pct_1rm" in item:
        value, heavy, moderate = item["pct_1rm"], HEAVY_PCT, MODERATE_PCT
    elif "rpe" in item:
        value, heavy, moderate = item["rpe"], HEAVY_RPE, MODERATE_RPE
    elif "rir" in item:
        # Fewer reps in reserve is harder: compare the negated values.
        value, heavy, moderate = -item["rir"], -HEAVY_RIR, -MODERATE_RIR
    else:
        return None
    if value >= heavy:
        return "heavy"
    return "moderate" if value >= moderate else "light"


def derived_intensity(exercises: Sequence[Mapping[str, Any]]) -> str | None:
    """Hardest relative load of the exercises; ``None`` without a relative load."""
    grades = [grade for item in exercises if (grade := _grade(item)) is not None]
    return max(grades, key=_RANK.__getitem__, default=None)


def exercise_names(exercises: Sequence[Mapping[str, Any]]) -> str:
    return " ".join(str(item.get("name") or "") for item in exercises)
