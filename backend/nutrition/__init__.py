"""Nutrition package for meal logging, macronutrient tracking, and platform syncing."""

from backend.nutrition.diary import NutritionDiaryService
from backend.nutrition.meal_library import NutritionMealLibraryService
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

__all__ = [
    "MAX_KCAL",
    "MAX_MACRO_G",
    "VALID_MEAL_TYPES",
    "NutritionDaySummary",
    "NutritionDiaryService",
    "NutritionEntry",
    "NutritionMealLibraryService",
    "meal_type_from_hour",
    "normalize_nutrition_entry",
    "validate_iso_date",
]
