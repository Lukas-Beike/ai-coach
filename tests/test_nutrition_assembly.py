from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from backend.nutrition.assembly import NutritionAssembly


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
            config=self.config_factory,
            database_manager=self.manager_factory,
            database_lock=self.lock,
            utc_now=self.utc_now,
            local_now=self.local_now,
            intervals_request=self.request_factory,
        )

    def test_local_service_uses_active_manager_lock_repository_clock_and_local_time(self):
        assembly = self.make_assembly()
        with patch("backend.nutrition.assembly.NutritionRepository") as repository, patch(
            "backend.nutrition.assembly.NutritionService", return_value="service"
        ) as service:
            self.assertEqual(assembly.service(), "service")

        repository.assert_called_once_with(self.utc_now)
        service.assert_called_once_with(
            database_manager=self.manager,
            db_lock=self.lock,
            nutrition_repository=repository.return_value,
            utc_now=self.utc_now,
            local_now=self.local_now,
        )

    def test_intervals_sync_lazily_uses_current_config_and_shared_local_service_factory(self):
        assembly = self.make_assembly()
        with patch("backend.nutrition.assembly.IntervalsApiClient") as client, patch(
            "backend.nutrition.assembly.IntervalsNutritionSyncService",
            return_value="sync",
        ) as sync_service, patch.object(assembly, "service", return_value="nutrition"):
            self.assertEqual(assembly.intervals_sync_service(), "sync")

        self.config_factory.assert_called_once_with()
        self.request_factory.assert_called_once_with()
        client.assert_called_once_with(api_key="synthetic-key", request=self.request)
        sync_service.assert_called_once_with(
            config=self.config,
            api_client=client.return_value,
            nutrition_service="nutrition",
        )


if __name__ == "__main__":
    unittest.main()
