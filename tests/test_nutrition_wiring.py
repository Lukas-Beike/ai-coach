"""The nutrition builder reads the live configuration and database (#2099)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.nutrition import wiring as nutrition_wiring


class NutritionBuilderTests(unittest.TestCase):
    def make_services(self) -> nutrition_wiring.NutritionServices:
        self.ctx = Mock()
        self.config = SimpleNamespace(intervals_api_key="synthetic-key")
        self.ctx.config.return_value = self.config
        self.request = self.ctx.provider_transport.json_http_client.return_value
        return nutrition_wiring.build_nutrition(self.ctx)

    def test_building_resolves_no_database_or_configuration(self) -> None:
        self.make_services()

        self.ctx.database.assert_not_called()
        self.ctx.config.assert_not_called()
        self.ctx.model_transport.complete.assert_not_called()

    def test_local_services_use_the_active_manager_and_lock(self) -> None:
        services = self.make_services()

        library = services.meal_library_service()
        diary = services.diary_service()

        self.assertIsNotNone(library)
        self.assertIsNotNone(diary)
        self.ctx.database.assert_called_with()
        self.assertIs(services.food_mirror(), services.food_mirror())

    def test_intervals_sync_uses_the_current_config_and_a_fresh_diary(self) -> None:
        services = self.make_services()
        with (
            patch.object(nutrition_wiring, "IntervalsApiClient") as client,
            patch.object(
                nutrition_wiring, "IntervalsNutritionSyncService", return_value="sync"
            ) as sync_service,
            patch.object(
                nutrition_wiring, "NutritionDiaryService", return_value="diary"
            ),
        ):
            self.assertEqual("sync", services.intervals_sync_service())

        client.assert_called_once_with(
            api_key="synthetic-key", request=self.request.request
        )
        sync_service.assert_called_once_with(
            config=self.config, api_client=client.return_value, diary_service="diary"
        )


if __name__ == "__main__":
    unittest.main()
