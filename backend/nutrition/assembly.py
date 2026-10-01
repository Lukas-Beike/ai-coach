"""Composition for local nutrition records and Intervals synchronization."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from backend.config import Config
from backend.db.repositories import NutritionRepository
from backend.nutrition.food_database import FoodDatabaseService
from backend.nutrition.service import NutritionService
from backend.nutrition.sync import IntervalsNutritionSyncService
from backend.providers.intervals import IntervalsApiClient


@dataclass(frozen=True)
class NutritionPersistence:
    database_manager: Callable[[], Any]
    database_lock: Any


@dataclass(frozen=True)
class NutritionRuntime:
    config: Callable[[], Config]
    utc_now: Callable[[], Any]
    local_now: Callable[[], Any]
    intervals_request: Callable[[], Callable[..., Any]]


class NutritionAssembly:
    """Create local nutrition and explicitly requested provider-sync services."""

    @dataclass(frozen=True)
    class Inputs:
        persistence: NutritionPersistence
        runtime: NutritionRuntime

    def __init__(
        self,
        *,
        dependencies: NutritionAssembly.Inputs,
    ) -> None:
        self._config = dependencies.runtime.config
        self._database_manager = dependencies.persistence.database_manager
        self._database_lock = dependencies.persistence.database_lock
        self._utc_now = dependencies.runtime.utc_now
        self._local_now = dependencies.runtime.local_now
        self._intervals_request = dependencies.runtime.intervals_request
        self._food_database = FoodDatabaseService()

    def food_database(self) -> FoodDatabaseService:
        return self._food_database

    def service(self) -> NutritionService:
        return NutritionService(
            database_manager=self._database_manager(),
            db_lock=self._database_lock,
            nutrition_repository=NutritionRepository(self._utc_now),
            utc_now=self._utc_now,
            local_now=self._local_now,
            food_database=self._food_database,
        )

    def intervals_sync_service(self) -> IntervalsNutritionSyncService:
        config = self._config()
        api_client = IntervalsApiClient(
            api_key=config.intervals_api_key,
            request=self._intervals_request(),
        )
        return IntervalsNutritionSyncService(
            config=config,
            api_client=api_client,
            nutrition_service=self.service(),
        )
