"""Nutrition package for meal logging, macronutrient tracking, and platform syncing."""

from backend.nutrition.models import (
    MAX_KCAL,
    MAX_MACRO_G,
    VALID_MEAL_TYPES,
    NutritionDaySummary,
    NutritionEntry,
    meal_type_from_hour,
    normalize_nutrition_entry,
    validate_iso_date,
)
from backend.nutrition.service import NutritionService

__all__ = [
    "MAX_KCAL",
    "MAX_MACRO_G",
    "VALID_MEAL_TYPES",
    "NutritionDaySummary",
    "NutritionEntry",
    "NutritionService",
    "meal_type_from_hour",
    "normalize_nutrition_entry",
    "validate_iso_date",
]
