from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock

from backend.config import Config
from backend.errors import AppError
from backend.http_api.nutrition import (
    NutritionGetRoutes,
    NutritionPostRoutes,
    NutritionPutRoutes,
)
from backend.nutrition.sync import IntervalsNutritionSyncService


class NutritionHttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = Mock()
        self.auth = Mock()
        self.nutrition_service = Mock()
        self.sync_service = Mock()
        self.local_now = lambda: datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)

        self.get_routes = NutritionGetRoutes(
            session_auth_service=lambda: self.auth,
            nutrition_service=lambda: self.nutrition_service,
            local_now=self.local_now,
        )
        self.post_routes = NutritionPostRoutes(
            nutrition_service=lambda: self.nutrition_service,
            nutrition_sync_service=lambda: self.sync_service,
        )
        self.put_routes = NutritionPutRoutes(
            nutrition_service=lambda: self.nutrition_service,
        )

    def test_get_day_route(self) -> None:
        self.handler.path = "/api/nutrition/day?date=2026-09-24"
        self.nutrition_service.get_day_summary.return_value = {
            "date": "2026-09-24",
            "total_kcal": 2000,
            "entry_count": 3,
        }
        handled = self.get_routes.handle(self.handler, "/api/nutrition/day")
        self.assertTrue(handled)
        self.auth.require_auth.assert_called_once_with(self.handler)
        self.nutrition_service.get_day_summary.assert_called_once_with("2026-09-24")
        self.handler.send_json.assert_called_once_with(
            200,
            {"ok": True, "date": "2026-09-24", "total_kcal": 2000, "entry_count": 3},
        )

    def test_get_range_route(self) -> None:
        self.handler.path = "/api/nutrition/range?start=2026-09-20&end=2026-09-24"
        self.nutrition_service.get_range_summary.return_value = [
            {"date": "2026-09-20", "total_kcal": 1800},
            {"date": "2026-09-24", "total_kcal": 2000},
        ]
        handled = self.get_routes.handle(self.handler, "/api/nutrition/range")
        self.assertTrue(handled)
        self.nutrition_service.get_range_summary.assert_called_once_with("2026-09-20", "2026-09-24")
        self.handler.send_json.assert_called_once_with(
            200,
            {
                "ok": True,
                "summaries": [
                    {"date": "2026-09-20", "total_kcal": 1800},
                    {"date": "2026-09-24", "total_kcal": 2000},
                ],
            },
        )

    def test_post_entry_route(self) -> None:
        self.handler.read_json.return_value = {
            "meal_date": "2026-09-24",
            "description": "Porridge",
            "kcal": 350,
        }
        self.nutrition_service.log_meal.return_value = {
            "id": "entry-123",
            "description": "Porridge",
            "kcal": 350,
        }
        session = {"csrf_hash": "abc"}
        handled = self.post_routes.handle(self.handler, "/api/nutrition/entry")
        self.assertTrue(handled)
        self.nutrition_service.log_meal.assert_called_once()
        self.handler.send_json.assert_called_once_with(
            200,
            {"ok": True, "entry": {"id": "entry-123", "description": "Porridge", "kcal": 350}},
        )

    def test_post_delete_route(self) -> None:
        self.handler.read_json.return_value = {"id": "entry-123"}
        self.nutrition_service.delete_meal.return_value = {"status": "ok", "deleted_id": "entry-123"}
        session = {"csrf_hash": "abc"}
        handled = self.post_routes.handle(self.handler, "/api/nutrition/entry/delete")
        self.assertTrue(handled)
        self.nutrition_service.delete_meal.assert_called_once_with("entry-123")
        self.handler.send_json.assert_called_once_with(
            200, {"ok": True, "status": "ok", "deleted_id": "entry-123"}
        )

    def test_post_sync_route(self) -> None:
        self.handler.headers = {"Content-Length": "15"}
        self.handler.read_json.return_value = {"date": "2026-09-24"}
        self.sync_service.sync_day.return_value = {"ok": True, "date": "2026-09-24"}
        session = {"csrf_hash": "abc"}
        handled = self.post_routes.handle(self.handler, "/api/nutrition/sync")
        self.assertTrue(handled)
        self.sync_service.sync_day.assert_called_once_with("2026-09-24")

    def test_put_entry_route(self) -> None:
        self.handler.read_json.return_value = {
            "id": "entry-123",
            "description": "Updated meal",
            "kcal": 500,
        }
        self.nutrition_service.update_meal.return_value = {
            "id": "entry-123",
            "description": "Updated meal",
            "kcal": 500,
        }
        handled = self.put_routes.handle(self.handler, "/api/nutrition/entry")
        self.assertTrue(handled)
        self.nutrition_service.update_meal.assert_called_once()
        self.handler.send_json.assert_called_once_with(
            200,
            {"ok": True, "entry": {"id": "entry-123", "description": "Updated meal", "kcal": 500}},
        )


class IntervalsNutritionSyncServiceTests(unittest.TestCase):
    def test_sync_day_calls_intervals_api_and_marks_synced(self) -> None:
        mock_config = Mock(spec=Config)
        mock_config.intervals_athlete_id = "i12345"
        mock_api = Mock()
        mock_nutrition = Mock()

        mock_nutrition.get_sync_snapshot.return_value = {
            "date": "2026-09-24",
            "total_kcal": 2200,
            "total_carbs_g": 250.0,
            "total_protein_g": 130.0,
            "total_fat_g": 65.0,
            "entry_count": 3,
            "sync_revision": 4,
        }
        mock_api.put.return_value = {"id": "2026-09-24", "kcalConsumed": 2200}

        sync_service = IntervalsNutritionSyncService(
            config=mock_config,
            api_client=mock_api,
            nutrition_service=mock_nutrition,
        )

        result = sync_service.sync_day("2026-09-24")
        self.assertTrue(result["ok"])
        mock_api.put.assert_called_once_with(
            "/athlete/i12345/wellness/2026-09-24",
            {
                "id": "2026-09-24",
                "kcalConsumed": 2200,
                "carbs": 250.0,
                "protein": 130.0,
                "fat": 65.0,
            },
        )
        mock_nutrition.mark_date_synced.assert_called_once_with("2026-09-24", 4)

    def test_sync_keeps_date_pending_when_meal_changes_during_remote_write(self) -> None:
        config = Mock(spec=Config)
        config.intervals_athlete_id = "i12345"
        api = Mock()
        nutrition = Mock()
        nutrition.get_sync_snapshot.return_value = {
            "date": "2026-09-24", "total_kcal": 500, "total_carbs_g": 0,
            "total_protein_g": 0, "total_fat_g": 0, "entry_count": 1,
            "sync_revision": 7,
        }
        nutrition.mark_date_synced.return_value = False
        result = IntervalsNutritionSyncService(config, api, nutrition).sync_day("2026-09-24")
        self.assertTrue(result["ok"])
        self.assertTrue(result["pending"])
        nutrition.mark_date_synced.assert_called_once_with("2026-09-24", 7)

    def test_sync_pending_processes_all_dates(self) -> None:
        mock_config = Mock(spec=Config)
        mock_config.intervals_athlete_id = "i12345"
        mock_api = Mock()
        mock_nutrition = Mock()

        mock_nutrition.list_unsynced_dates.return_value = ["2026-09-23", "2026-09-24"]
        mock_nutrition.get_sync_snapshot.side_effect = [
            {"date": "2026-09-23", "total_kcal": 1800, "total_carbs_g": 0, "total_protein_g": 0, "total_fat_g": 0, "sync_revision": 1},
            {"date": "2026-09-24", "total_kcal": 2100, "total_carbs_g": 0, "total_protein_g": 0, "total_fat_g": 0, "sync_revision": 2},
        ]

        sync_service = IntervalsNutritionSyncService(
            config=mock_config,
            api_client=mock_api,
            nutrition_service=mock_nutrition,
        )

        res = sync_service.sync_pending()
        self.assertTrue(res["ok"])
        self.assertEqual(res["synced_dates"], ["2026-09-23", "2026-09-24"])
        self.assertEqual(mock_api.put.call_count, 2)


if __name__ == "__main__":
    unittest.main()
