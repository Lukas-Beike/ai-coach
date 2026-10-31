from typing import Any

from backend.db.repositories import (
    NutritionProductRepository,
    NutritionRepository,
    NutritionTemplateRepository,
)
from backend.nutrition.diary import NutritionDiaryService
from backend.nutrition.food_database import FoodDatabaseService
from backend.nutrition.meal_library import NutritionMealLibraryService
from backend.sync.canonical_table_reader import CanonicalTableReader


def build_nutrition_services(
    database_manager: Any,
    db_lock: Any,
    utc_now: Any,
    local_now: Any,
    *,
    food_database: Any = None,
    photo_extractor: Any = None,
    observation_reader: Any = None,
) -> tuple[NutritionDiaryService, NutritionMealLibraryService]:
    food_database = food_database or FoodDatabaseService()
    product_repository = NutritionProductRepository()
    template_repository = NutritionTemplateRepository()
    meal_library = NutritionMealLibraryService(
        database_manager=database_manager,
        db_lock=db_lock,
        utc_now=utc_now,
        local_now=local_now,
        food_database=food_database,
        photo_extractor=photo_extractor,
        product_repository=product_repository,
        template_repository=template_repository,
    )
    diary = NutritionDiaryService(
        database_manager=database_manager,
        db_lock=db_lock,
        nutrition_repository=NutritionRepository(now=utc_now),
        utc_now=utc_now,
        local_now=local_now,
        meal_library=meal_library,
        # The energy views read canonical observations only (#1415); the table
        # reader serves what the Garmin snapshot writer stored.
        observation_reader=observation_reader or CanonicalTableReader,
    )
    return diary, meal_library
