"""The nutrition builder reads the live configuration and database (#2099)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.nutrition import wiring as nutrition_wiring
from backend.providers.model_seam import ModelRequest


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

    def test_label_photo_uses_the_nutrition_model_and_thinking(self) -> None:
        self.make_services()
        settings = self.ctx.settings
        settings.selected_model.side_effect = lambda task="conversation": f"m-{task}"
        settings.selected_thinking_level.side_effect = lambda task="conversation": (
            f"t-{task}"
        )
        with patch.object(nutrition_wiring, "NutritionPhotoExtractionService") as photo:
            nutrition_wiring.build_nutrition(self.ctx).meal_library_service()
        options = photo.call_args.kwargs
        self.assertEqual(options["selected_model"](), "m-nutrition")
        complete = self.ctx.model_transport.complete
        options["complete"](ModelRequest(model="m"))
        self.assertEqual(complete.call_args.args[0].reasoning_effort, "t-nutrition")
        # A fixed effort, such as the web search's, is kept.
        options["complete"](ModelRequest(model="m", reasoning_effort="low"))
        self.assertEqual(complete.call_args.args[0].reasoning_effort, "low")

    def test_each_owner_reaches_its_parameter(self) -> None:
        ctx = Mock()
        ctx.athlete_profile.get.return_value = {"sex": "female"}
        with (
            patch.object(nutrition_wiring, "OpenFoodFactsClient") as off,
            patch.object(nutrition_wiring, "YazioClient") as yazio,
            patch.object(nutrition_wiring, "NutritionMealLibraryService") as library,
            patch.object(nutrition_wiring, "NutritionDiaryService") as diary,
            patch.object(nutrition_wiring, "NutritionWebSearchService") as search,
        ):
            nutrition_wiring.build_nutrition(ctx).diary_service()

        off.assert_called_once_with(opener=ctx.observed_opener.return_value)
        self.assertEqual(
            ["open_food_facts", "yazio"],
            [call.args[0] for call in ctx.observed_opener.call_args_list],
        )
        self.assertIs(ctx.config, yazio.call_args.args[0])
        self.assertEqual("female", yazio.call_args.kwargs["athlete_sex"]())
        self.assertIs(ctx.database_lock, library.call_args.kwargs["db_lock"])
        self.assertIs(ctx.database_lock, diary.call_args.kwargs["db_lock"])
        self.assertIs(library.return_value, diary.call_args.kwargs["meal_library"])
        # The product web search reads the Nutrition model choice.
        ctx.settings.selected_model.return_value = "nutrition-model"
        self.assertEqual("nutrition-model", search.call_args.kwargs["selected_model"]())
        ctx.settings.selected_model.assert_called_with("nutrition")
        reader = diary.call_args.kwargs["observation_reader"]
        ctx.canonical_read = "live reader"
        self.assertEqual("live reader", reader())


if __name__ == "__main__":
    unittest.main()
