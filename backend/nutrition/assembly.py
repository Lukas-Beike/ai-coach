"""Composition for local nutrition records and Intervals synchronization."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from backend.config import Config
from backend.db.repositories import NutritionRepository
from backend.nutrition.service import NutritionService
from backend.nutrition.sync import IntervalsNutritionSyncService
from backend.providers.intervals import IntervalsApiClient


class NutritionAssembly:
    """Create local nutrition and explicitly requested provider-sync services."""

    def __init__(
        self,
        *,
        config: Callable[[], Config],
        database_manager: Callable[[], Any],
        database_lock: Any,
        utc_now: Callable[[], Any],
        local_now: Callable[[], Any],
        intervals_request: Callable[[], Callable[..., Any]],
    ) -> None:
        self._config = config
        self._database_manager = database_manager
        self._database_lock = database_lock
        self._utc_now = utc_now
        self._local_now = local_now
        self._intervals_request = intervals_request

    def service(self) -> NutritionService:
        return NutritionService(
            database_manager=self._database_manager(),
            db_lock=self._database_lock,
            nutrition_repository=NutritionRepository(self._utc_now),
            utc_now=self._utc_now,
            local_now=self._local_now,
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
