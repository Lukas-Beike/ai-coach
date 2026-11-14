"""Carbohydrate rules for races and long sessions (athlete decision, #2803).

The single owner of the fuelling rules; the race plan and #2804 read them here.
Steps by duration follow Thomas, Erdman and Burke (2016), the joint position
statement of the American College of Sports Medicine, the Academy of Nutrition
and Dietetics and Dietitians of Canada (Med Sci Sports Exerc 48(3):543-568).
Above 2.5 h the athlete chose up to 120 g/h (Hearris et al. 2022; Podlogar et
al. 2022); the step is flagged because a benefit above 90 g/h is not yet shown
(Wallis and Podlogar 2022). Pure: no I/O.
"""

from __future__ import annotations

from typing import Any, Final

METHOD_ID: Final = "carbohydrate-fuelling"
POSITION_STAND: Final = "Thomas, Erdman und Burke 2016"
# Above this rate the athlete's chosen ceiling exceeds the position stand.
ESTABLISHED_MAX_G_PER_H: Final = 90
_MINUTES: Final = 60.0


def carbohydrate_per_hour(duration_s: Any) -> dict[str, Any] | None:
    """Grams per hour during an effort of ``duration_s``, or None if unknown."""
    if isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)):
        return None
    if duration_s <= 0:
        return None
    minutes = duration_s / _MINUTES
    if minutes < 45:
        return {"step": "none", "low_g": 0, "high_g": 0}
    if minutes <= 75:
        # Small amounts including a mouth rinse; the stand gives no gram rate.
        return {"step": "mouth_rinse", "low_g": None, "high_g": None}
    if minutes <= 150:
        return {"step": "moderate", "low_g": 30, "high_g": 60}
    return {
        "step": "high",
        "low_g": 60,
        "high_g": 120,
        "established_max_g": ESTABLISHED_MAX_G_PER_H,
        "glucose_fructose": True,
    }


def _grams(weight_kg: float | None, per_kg: tuple[int, int]) -> list[int] | None:
    if weight_kg is None:
        return None
    return [round(weight_kg * per_kg[0]), round(weight_kg * per_kg[1])]


def pre_race_carbohydrates(
    duration_s: Any, weight_kg: float | None
) -> list[dict[str, Any]]:
    """Carbohydrates before a race: daily intake on the days before, then the meal.

    Over 90 min: 10-12 g/kg per day for the 36-48 h before (loading); up to
    90 min: 7-12 g/kg in the 24 h before; over 60 min also a meal of 1-4 g/kg
    in the 1-4 h before the start. Grams need the weight; g/kg always stays.
    """
    if isinstance(duration_s, bool) or not isinstance(duration_s, (int, float)):
        return []
    if duration_s <= 0:
        return []
    minutes = duration_s / _MINUTES
    kind, days, per_kg = ("loading", 2, (10, 12)) if minutes > 90 else ("daily", 1, (7, 12))
    result: list[dict[str, Any]] = [
        {
            "kind": kind,
            "days_before": days,
            "g_per_kg": list(per_kg),
            "grams": _grams(weight_kg, per_kg),
        }
    ]
    if minutes > 60:
        result.append(
            {
                "kind": "meal",
                "hours_before": [4, 1],
                "g_per_kg": [1, 4],
                "grams": _grams(weight_kg, (1, 4)),
            }
        )
    return result
