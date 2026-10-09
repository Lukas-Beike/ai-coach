from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.nutrition.assembly import (
    NutritionAssembly,
    NutritionPersistence,
    NutritionRuntime,
)


class NutritionAssemblyTests(unittest.TestCase):
    def make_assembly(self) -> NutritionAssembly:
        self.config = SimpleNamespace(intervals_api_key="synthetic-key")
        self.manager = object()
        self.lock = object()
        self.utc_now = Mock(return_value="2026-09-26T00:00:00Z")
        self.local_now = Mock()
        self.request = Mock()
        self.config_factory = Mock(return_value=self.config)
        self.manager_factory = Mock(return_value=self.manager)
        self.request_factory = Mock(return_value=self.request)
        return NutritionAssembly(
            dependencies=NutritionAssembly.Inputs(
                persistence=NutritionPersistence(self.manager_factory, self.lock),
                runtime=NutritionRuntime(
                    self.config_factory,
                    self.utc_now,
                    self.local_now,
                    self.request_factory,
                ),
            )
        )

    def test_local_services_use_active_manager_lock_repository_clock_and_local_time(
        self,
    ):
        assembly = self.make_assembly()
        self.assertIsNotNone(assembly.diary_service())
        self.assertIsNotNone(assembly.meal_library_service())

    def test_intervals_sync_lazily_uses_current_config_and_shared_local_service_factory(
        self,
    ):
        assembly = self.make_assembly()
        with (
            patch("backend.nutrition.assembly.IntervalsApiClient") as client,
            patch(
                "backend.nutrition.assembly.IntervalsNutritionSyncService",
                return_value="sync",
            ) as sync_service,
            patch.object(assembly, "diary_service", return_value="nutrition"),
        ):
            self.assertEqual(assembly.intervals_sync_service(), "sync")

        self.config_factory.assert_called_once_with()
        self.request_factory.assert_called_once_with()
        client.assert_called_once_with(api_key="synthetic-key", request=self.request)
        sync_service.assert_called_once_with(
            config=self.config,
            api_client=client.return_value,
            diary_service="nutrition",
        )


if __name__ == "__main__":
    unittest.main()
