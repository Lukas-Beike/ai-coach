"""Build the local nutrition services and the explicit Intervals.icu nutrition sync."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from backend.app.context import AppContext
from backend.db.repositories import (
    NutritionProductRepository,
    NutritionRepository,
    NutritionTemplateRepository,
)
from backend.nutrition.catalog import ProductCatalogService
from backend.nutrition.diary import NutritionDiaryService
from backend.nutrition.food_database import FoodDatabaseService
from backend.nutrition.food_mirror import FoodDatabaseMirror
from backend.nutrition.meal_library import NutritionMealLibraryService
from backend.nutrition.photo import NutritionPhotoExtractionService
from backend.nutrition.sync import IntervalsNutritionSyncService
from backend.nutrition.web_search import NutritionWebSearchService
from backend.providers.intervals import IntervalsApiClient
from backend.providers.model_seam import ModelRequest, ModelTurn
from backend.providers.open_food_facts import OpenFoodFactsClient
from backend.providers.yazio import YazioClient
from backend.runtime import clock as runtime_clock


@dataclass(frozen=True)
class NutritionServices:
    secret_values: Callable[[], tuple[str, ...]]
    food_database: Callable[[], FoodDatabaseService]
    food_mirror: Callable[[], FoodDatabaseMirror]
    meal_library_service: Callable[[], NutritionMealLibraryService]
    product_catalog_service: Callable[[], ProductCatalogService]
    diary_service: Callable[[], NutritionDiaryService]
    intervals_sync_service: Callable[[], IntervalsNutritionSyncService]


def build_nutrition(ctx: AppContext) -> NutritionServices:
    """One food database and mirror for the process; the rest fresh per call."""
    utc_now = runtime_clock.utc_now
    mirror = FoodDatabaseMirror(ctx.database, ctx.database_lock, utc_now)
    food_database = FoodDatabaseService(
        off=OpenFoodFactsClient(opener=ctx.observed_opener("open_food_facts")),
        mirror=mirror,
        yazio=YazioClient(
            ctx.config,
            # The profile sex Yazio searches send; empty sends none (#1774).
            athlete_sex=lambda: ctx.athlete_profile.get().get("sex", ""),
            opener=ctx.observed_opener("yazio"),
        ),
    )
    products = NutritionProductRepository()
    templates = NutritionTemplateRepository()

    def complete(request: ModelRequest) -> ModelTurn:
        return ctx.model_transport.complete(request)

    def meal_library_service() -> NutritionMealLibraryService:
        return NutritionMealLibraryService(
            database_manager=ctx.database(),
            db_lock=ctx.database_lock,
            utc_now=utc_now,
            local_now=ctx.clock.now,
            food_database=food_database,
            photo_extractor=NutritionPhotoExtractionService(
                selected_model=ctx.settings.selected_model, complete=complete
            ),
            product_repository=products,
            template_repository=templates,
            web_search=NutritionWebSearchService(
                selected_model=ctx.settings.selected_model, complete=complete
            ),
        )

    def diary_service() -> NutritionDiaryService:
        return NutritionDiaryService(
            database_manager=ctx.database(),
            db_lock=ctx.database_lock,
            nutrition_repository=NutritionRepository(utc_now),
            utc_now=utc_now,
            local_now=ctx.clock.now,
            meal_library=meal_library_service(),
            observation_reader=lambda: ctx.canonical_read,
        )

    def intervals_sync_service() -> IntervalsNutritionSyncService:
        config = ctx.config()
        return IntervalsNutritionSyncService(
            config=config,
            api_client=IntervalsApiClient(
                api_key=config.intervals_api_key,
                request=ctx.provider_transport.json_http_client().request,
            ),
            diary_service=diary_service(),
        )

    return NutritionServices(
        # Runtime-only provider tokens for the log redactor.
        secret_values=food_database.yazio_secret_values,
        food_database=lambda: food_database,
        food_mirror=lambda: mirror,
        meal_library_service=meal_library_service,
        product_catalog_service=lambda: meal_library_service().product_catalog,
        diary_service=diary_service,
        intervals_sync_service=intervals_sync_service,
    )
