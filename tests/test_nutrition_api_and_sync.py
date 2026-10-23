from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock

from nutrition_service_support import build_nutrition_services

from backend.config import Config
from backend.db.manager import DatabaseManager
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.http_api.handler import RequestHandler
from backend.http_api.nutrition import (
    NUTRITION_ENTRY_PATH,
    NUTRITION_PRODUCTS_PATH,
    NutritionGetRoutes,
    NutritionPostRoutes,
    NutritionPutRoutes,
)
from backend.nutrition.contracts import nutrition_approval_item
from backend.nutrition.sync import IntervalsNutritionSyncService

# server.py MAX_BODY_BYTES: the cap of every JSON route without its own.
GLOBAL_BODY_BYTES = 1_000_000


def json_route_handler(payload: Any, *, padding: int = 0) -> Any:
    """Return a bare handler whose read_json is the production body reader."""
    body = json.dumps(payload).encode() + b" " * padding
    handler: Any = RequestHandler.__new__(RequestHandler)
    handler.headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
    }
    handler._read_input = io.BytesIO(body).read
    handler.dependencies = SimpleNamespace(max_body_bytes=GLOBAL_BODY_BYTES)
    handler.send_json = Mock()
    return handler


class NutritionHttpApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.handler = Mock()
        self.auth = Mock()
        self.diary_service = Mock()
        self.meal_library_service = Mock()
        self.sync_service = Mock()
        self.sync_job_queue = Mock()
        self.sync_job_queue.enqueue.return_value = {"id": "nutrition-job-1"}
        self.nutrition_refresh_service = Mock()
        self.local_now = lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC)

        self.get_routes = NutritionGetRoutes(
            session_auth_service=lambda: self.auth,
            diary_service=lambda: self.diary_service,
            meal_library_service=lambda: self.meal_library_service,
            local_now=self.local_now,
        )
        self.post_routes = NutritionPostRoutes(
            diary_service=lambda: self.diary_service,
            meal_library_service=lambda: self.meal_library_service,
            sync_job_queue=lambda: self.sync_job_queue,
            nutrition_refresh_service=lambda: self.nutrition_refresh_service,
            local_now=self.local_now,
        )
        self.put_routes = NutritionPutRoutes(
            diary_service=lambda: self.diary_service,
            meal_library_service=lambda: self.meal_library_service,
        )

    def test_history_period_is_forwarded_after_authentication(self) -> None:
        self.diary_service.get_week_summary.return_value = {"days": []}
        for count in (7, 14, 84):
            self.handler.path = f"/api/nutrition/week?days={count}"
            self.assertTrue(self.get_routes.handle(self.handler, "/api/nutrition/week"))
            self.auth.require_auth.assert_called_with(self.handler)
            self.diary_service.get_week_summary.assert_called_with(count)
        self.handler.path = "/api/nutrition/week?days=invalid"
        with self.assertRaises(AppError):
            self.get_routes.handle(self.handler, "/api/nutrition/week")

    def test_templates_route_requires_authentication(self) -> None:
        self.handler.path = "/api/nutrition/templates"
        self.meal_library_service.list_templates.return_value = [{"id": "template-1"}]
        self.assertTrue(
            self.get_routes.handle(self.handler, "/api/nutrition/templates")
        )
        self.auth.require_auth.assert_called_once_with(self.handler)
        self.handler.send_json.assert_called_once_with(
            200, {"ok": True, "templates": [{"id": "template-1"}]}
        )

    def test_get_day_route(self) -> None:
        self.handler.path = "/api/nutrition/day?date=2026-09-24"
        self.diary_service.get_day_summary.return_value = {
            "date": "2026-09-24",
            "total_kcal": 2000,
            "entry_count": 3,
        }
        handled = self.get_routes.handle(self.handler, "/api/nutrition/day")
        self.assertTrue(handled)
        self.auth.require_auth.assert_called_once_with(self.handler)
        self.diary_service.get_day_summary.assert_called_once_with("2026-09-24")
        self.handler.send_json.assert_called_once_with(
            200,
            {"ok": True, "date": "2026-09-24", "total_kcal": 2000, "entry_count": 3},
        )

    def test_week_route_requires_authentication(self) -> None:
        self.handler.path = "/api/nutrition/week"
        self.diary_service.get_week_summary.return_value = {"balance_days": 7}
        self.assertTrue(self.get_routes.handle(self.handler, "/api/nutrition/week"))
        self.auth.require_auth.assert_called_once_with(self.handler)
        self.handler.send_json.assert_called_once_with(
            200, {"ok": True, "balance_days": 7}
        )

    def test_removed_fueling_route_is_not_handled(self) -> None:
        self.handler.path = "/api/nutrition/fueling"
        self.assertFalse(self.get_routes.handle(self.handler, "/api/nutrition/fueling"))

    def test_week_route_rejects_unauthenticated_read_before_service_access(
        self,
    ) -> None:
        self.handler.path = "/api/nutrition/week"
        self.auth.require_auth.side_effect = AppError(401, "Authentication required")
        with self.assertRaises(AppError):
            self.get_routes.handle(self.handler, "/api/nutrition/week")
        self.diary_service.get_week_summary.assert_not_called()

    def test_get_range_route(self) -> None:
        self.handler.path = "/api/nutrition/range?start=2026-09-20&end=2026-09-24"
        self.diary_service.get_range_summary.return_value = [
            {"date": "2026-09-20", "total_kcal": 1800},
            {"date": "2026-09-24", "total_kcal": 2000},
        ]
        handled = self.get_routes.handle(self.handler, "/api/nutrition/range")
        self.assertTrue(handled)
        self.diary_service.get_range_summary.assert_called_once_with(
            "2026-09-20", "2026-09-24"
        )
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
        self.diary_service.log_meal.return_value = {
            "id": "entry-123",
            "description": "Porridge",
            "kcal": 350,
        }
        handled = self.post_routes.handle(self.handler, "/api/nutrition/entry")
        self.assertTrue(handled)
        self.diary_service.log_meal.assert_called_once()
        self.handler.send_json.assert_called_once_with(
            200,
            {
                "ok": True,
                "entry": {"id": "entry-123", "description": "Porridge", "kcal": 350},
            },
        )

    def test_post_delete_route(self) -> None:
        self.handler.read_json.return_value = {"id": "entry-123"}
        self.diary_service.delete_meal.return_value = {
            "status": "ok",
            "deleted_id": "entry-123",
        }
        handled = self.post_routes.handle(self.handler, "/api/nutrition/entry/delete")
        self.assertTrue(handled)
        self.diary_service.delete_meal.assert_called_once_with("entry-123")
        self.handler.send_json.assert_called_once_with(
            200, {"ok": True, "status": "ok", "deleted_id": "entry-123"}
        )

    def test_post_sync_route(self) -> None:
        self.handler.headers = {"Content-Length": "15"}
        self.handler.read_json.return_value = {"date": "2026-09-24"}
        self.sync_service.sync_day.return_value = {"ok": True, "date": "2026-09-24"}
        handled = self.post_routes.handle(self.handler, "/api/nutrition/sync")
        self.assertTrue(handled)
        self.sync_job_queue.enqueue.assert_called_once_with(
            "intervals",
            "nutrition_sync",
            {"date": "2026-09-24"},
            requested_by="http_api",
        )
        self.handler.send_json.assert_called_once_with(
            202,
            {
                "ok": True,
                "status": "queued",
                "sync_job_id": "nutrition-job-1",
            },
        )

    def test_post_sync_pending_route_queues_bounded_provider_job(self) -> None:
        self.handler.headers = {"Content-Length": "11"}
        self.handler.read_json.return_value = {"limit": 3}
        self.post_routes.handle(self.handler, "/api/nutrition/sync")
        self.sync_job_queue.enqueue.assert_called_once_with(
            "intervals", "nutrition_sync", {"pending_limit": 3}, requested_by="http_api"
        )

    def test_nutrition_refresh_diary_reads_local_meals_and_only_daily_energy(self) -> None:
        self.handler.read_json.return_value = {"area": "diary", "date": "2026-09-23"}
        self.diary_service.get_day_summary.return_value = {"date": "2026-09-23", "entries": []}
        self.nutrition_refresh_service.refresh.return_value = {
            "status": "ok", "source": "Garmin Connect", "records": 1
        }

        handled = self.post_routes.handle(self.handler, "/api/nutrition/refresh")

        self.assertTrue(handled)
        self.diary_service.get_day_summary.assert_called_once_with("2026-09-23")
        self.nutrition_refresh_service.refresh.assert_called_once_with(
            "daily_stats", date(2026, 9, 23), date(2026, 9, 23)
        )
        self.sync_job_queue.enqueue.assert_not_called()
        self.handler.send_json.assert_called_once_with(
            200,
            {
                "ok": True,
                "area": "diary",
                "status": "ok",
                "meal_status": "local",
                "summary": {"date": "2026-09-23", "entries": []},
                "expenditure_refresh": {
                    "status": "ok", "source": "Garmin Connect", "records": 1
                },
            },
        )

    def test_nutrition_refresh_diary_exposes_partial_provider_status(self) -> None:
        self.handler.read_json.return_value = {"area": "diary", "date": "2026-09-23"}
        self.diary_service.get_day_summary.return_value = {
            "date": "2026-09-23",
            "entries": [],
            "energy_expenditure": {"freshness": "stale"},
        }
        self.nutrition_refresh_service.refresh.return_value = {
            "status": "partial", "reason": "provider_unavailable"
        }

        self.post_routes.handle(self.handler, "/api/nutrition/refresh")

        response = self.handler.send_json.call_args.args[1]
        self.assertEqual(response["status"], "partial")
        self.assertEqual(response["meal_status"], "local")
        self.assertEqual(
            response["summary"]["energy_expenditure"]["freshness"], "partial"
        )

    def test_nutrition_refresh_week_uses_requested_range(self) -> None:
        self.handler.read_json.return_value = {
            "area": "week", "days": 84, "date": "2026-09-23"
        }
        self.nutrition_refresh_service.refresh.return_value = {"status": "partial"}

        self.post_routes.handle(self.handler, "/api/nutrition/refresh")

        self.nutrition_refresh_service.refresh.assert_called_once_with(
            "daily_stats", date(2026, 7, 2), date(2026, 9, 23)
        )
        self.handler.send_json.assert_called_once_with(
            200, {"ok": True, "area": "week", "status": "partial"}
        )

    def test_nutrition_refresh_body_uses_bounded_weight_range(self) -> None:
        self.handler.read_json.return_value = {"area": "body"}
        self.nutrition_refresh_service.refresh.return_value = {"status": "ok"}

        self.post_routes.handle(self.handler, "/api/nutrition/refresh")

        self.nutrition_refresh_service.refresh.assert_called_once_with(
            "weight", date(2026, 7, 3), date(2026, 9, 24)
        )

    def test_nutrition_refresh_local_products_never_calls_provider(self) -> None:
        self.handler.read_json.return_value = {"area": "products"}
        self.meal_library_service.list_products.return_value = [{"id": "food-1"}]

        self.post_routes.handle(self.handler, "/api/nutrition/refresh")

        self.nutrition_refresh_service.refresh.assert_not_called()
        self.handler.send_json.assert_called_once_with(
            200,
            {"ok": True, "area": "products", "status": "local", "products": [{"id": "food-1"}]},
        )

    def test_nutrition_refresh_rejects_invalid_range(self) -> None:
        self.handler.read_json.return_value = {"area": "week", "days": 15}

        with self.assertRaises(AppError):
            self.post_routes.handle(self.handler, "/api/nutrition/refresh")
        self.nutrition_refresh_service.refresh.assert_not_called()

    def test_put_entry_route(self) -> None:
        self.handler.read_json.return_value = {
            "id": "entry-123",
            "description": "Updated meal",
            "kcal": 500,
        }
        self.diary_service.update_meal.return_value = {
            "id": "entry-123",
            "description": "Updated meal",
            "kcal": 500,
        }
        handled = self.put_routes.handle(self.handler, "/api/nutrition/entry")
        self.assertTrue(handled)
        self.diary_service.update_meal.assert_called_once()
        self.handler.send_json.assert_called_once_with(
            200,
            {
                "ok": True,
                "entry": {
                    "id": "entry-123",
                    "description": "Updated meal",
                    "kcal": 500,
                },
            },
        )


class NutritionRouteBodyTests(unittest.TestCase):
    """Routes read real JSON bodies into the real diary on temporary storage."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        manager = DatabaseManager(
            Path(directory.name) / "nutrition.db", sqlite3, row_factory=sqlite3.Row
        )
        self.addCleanup(manager.close)
        with manager.unit_of_work() as db:
            initialize_schema(db)
        self.diary, self.library = build_nutrition_services(
            manager,
            threading.Lock(),
            lambda: "2026-09-24T12:00:00+00:00",
            lambda: datetime(2026, 9, 24, 12, 0, tzinfo=UTC),
        )
        self.post_routes = NutritionPostRoutes(
            lambda: self.diary, lambda: self.library, sync_job_queue=Mock
        )
        self.put_routes = NutritionPutRoutes(lambda: self.diary, lambda: self.library)

    def test_put_entry_applies_the_calorie_alias_to_the_stored_entry(self) -> None:
        saved = self.diary.log_meal(
            {"meal_date": "2026-09-24", "description": "Lunch", "kcal": 500}
        )
        handler = json_route_handler({"id": saved["id"], "calories": 600})

        self.assertTrue(self.put_routes.handle(handler, NUTRITION_ENTRY_PATH))

        status, body = handler.send_json.call_args.args
        self.assertEqual((status, body["entry"]["kcal"]), (200, 600))
        self.assertEqual(self.diary.get_meal(saved["id"])["kcal"], 600)

    def test_non_photo_json_routes_keep_the_global_body_cap(self) -> None:
        for method, handle, path in (
            ("POST", self.post_routes.handle, NUTRITION_ENTRY_PATH),
            ("POST", self.post_routes.handle, f"{NUTRITION_PRODUCTS_PATH}/lookup"),
            ("PUT", self.put_routes.handle, NUTRITION_ENTRY_PATH),
        ):
            handler = json_route_handler(
                {"description": "Pasta", "kcal": 500}, padding=GLOBAL_BODY_BYTES
            )
            with (
                self.subTest(method=method, path=path),
                self.assertRaises(AppError) as raised,
            ):
                handle(handler, path)
            self.assertEqual(raised.exception.status, 413)
        self.assertEqual(self.diary.get_day_summary("2026-09-24")["entry_count"], 0)


class IntervalsNutritionSyncServiceTests(unittest.TestCase):
    def test_approved_sync_rejects_changed_manifest_before_provider_write(self) -> None:
        config = Mock(spec=Config)
        config.intervals_athlete_id = "i12345"
        api = Mock()
        nutrition = Mock()
        nutrition.approval_manifest.return_value = [
            {
                "date": "2026-09-24",
                "revision": 5,
                "total_kcal": 2200,
                "total_carbs_g": 250.0,
                "total_protein_g": 130.0,
                "total_fat_g": 65.0,
                "entry_count": 3,
                "sha256": "a" * 64,
            }
        ]
        approval = [{**nutrition.approval_manifest.return_value[0]}]
        approval[0]["revision"] = 4

        with self.assertRaises(AppError):
            IntervalsNutritionSyncService(config, api, nutrition).sync_approved(
                approval
            )
        api.put.assert_not_called()
        nutrition.get_sync_snapshot.assert_not_called()

    def test_approved_sync_dispatches_only_frozen_dates(self) -> None:
        config = Mock(spec=Config)
        config.intervals_athlete_id = "i12345"
        api = Mock()
        nutrition = Mock()
        snapshot = {
            "date": "2026-09-24",
            "total_kcal": 2200,
            "total_carbs_g": 250.0,
            "total_protein_g": 130.0,
            "total_fat_g": 65.0,
            "entry_count": 3,
            "sync_revision": 4,
        }
        manifest = [nutrition_approval_item(snapshot)]
        nutrition.approval_manifest.return_value = manifest
        nutrition.get_sync_snapshot.return_value = snapshot
        nutrition.mark_date_synced.return_value = True
        result = IntervalsNutritionSyncService(config, api, nutrition).sync_approved(
            manifest
        )
        self.assertEqual(result["synced_dates"], ["2026-09-24"])
        nutrition.approval_manifest.assert_called_once_with(dates=["2026-09-24"])
        self.assertEqual(api.put.call_count, 1)

    def test_approved_sync_preserves_prior_results_when_a_later_day_fails(self) -> None:
        config = Mock(spec=Config)
        config.intervals_athlete_id = "i12345"
        api = Mock()
        nutrition = Mock()
        first = {
            "date": "2026-09-24",
            "total_kcal": 2200,
            "total_carbs_g": 250.0,
            "total_protein_g": 130.0,
            "total_fat_g": 65.0,
            "entry_count": 3,
            "sync_revision": 4,
        }
        second = {**first, "date": "2026-09-25", "sync_revision": 5}
        manifest = [
            nutrition_approval_item({**first}),
            nutrition_approval_item({**second}),
        ]
        nutrition.approval_manifest.return_value = manifest
        nutrition.get_sync_snapshot.side_effect = [first, AppError(409, "changed")]
        nutrition.mark_date_synced.return_value = True

        result = IntervalsNutritionSyncService(config, api, nutrition).sync_approved(
            manifest
        )

        self.assertEqual(result["synced_dates"], ["2026-09-24"])
        self.assertEqual(result["failed_dates"], {"2026-09-25": "changed"})
        self.assertFalse(result["ok"])
        self.assertEqual(api.put.call_count, 1)

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
            diary_service=mock_nutrition,
        )

        result = sync_service.sync_day("2026-09-24")
        self.assertTrue(result["ok"])
        mock_api.put.assert_called_once_with(
            "/athlete/i12345/wellness/2026-09-24",
            {
                "id": "2026-09-24",
                "kcalConsumed": 2200,
                "carbohydrates": 250.0,
                "protein": 130.0,
                "fatTotal": 65.0,
            },
        )
        sent_payload = mock_api.put.call_args.args[1]
        self.assertNotIn("carbs", sent_payload)
        self.assertNotIn("fat", sent_payload)
        self.assertEqual(result["synced_summary"]["carbs"], 250.0)
        self.assertEqual(result["synced_summary"]["fat"], 65.0)
        mock_nutrition.mark_date_synced.assert_called_once_with("2026-09-24", 4)

    def test_sync_keeps_date_pending_when_meal_changes_during_remote_write(
        self,
    ) -> None:
        config = Mock(spec=Config)
        config.intervals_athlete_id = "i12345"
        api = Mock()
        nutrition = Mock()
        nutrition.get_sync_snapshot.return_value = {
            "date": "2026-09-24",
            "total_kcal": 500,
            "total_carbs_g": 0,
            "total_protein_g": 0,
            "total_fat_g": 0,
            "entry_count": 1,
            "sync_revision": 7,
        }
        nutrition.mark_date_synced.return_value = False
        result = IntervalsNutritionSyncService(config, api, nutrition).sync_day(
            "2026-09-24"
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["pending"])
        self.assertEqual(
            api.put.call_args.args[1],
            {
                "id": "2026-09-24",
                "kcalConsumed": 500,
                "carbohydrates": 0,
                "protein": 0,
                "fatTotal": 0,
            },
        )
        nutrition.mark_date_synced.assert_called_once_with("2026-09-24", 7)

    def test_sync_clears_unknown_macros_remotely_and_marks_date_synced(self) -> None:
        config = Mock(spec=Config)
        config.intervals_athlete_id = "i12345"
        api = Mock()
        nutrition = Mock()
        nutrition.get_sync_snapshot.return_value = {
            "date": "2026-09-24",
            "total_kcal": 500,
            "total_carbs_g": None,
            "total_protein_g": 20,
            "total_fat_g": 10,
            "entry_count": 1,
            "sync_revision": 7,
        }
        nutrition.mark_date_synced.return_value = True

        result = IntervalsNutritionSyncService(config, api, nutrition).sync_day(
            "2026-09-24"
        )

        self.assertTrue(result["ok"])
        self.assertFalse(result["pending"])
        self.assertEqual(
            api.put.call_args.args[1],
            {
                "id": "2026-09-24",
                "kcalConsumed": 500,
                "carbohydrates": -1,
                "protein": 20,
                "fatTotal": 10,
            },
        )
        self.assertIsNone(result["synced_summary"]["carbs"])
        self.assertEqual(result["synced_summary"]["protein"], 20)
        nutrition.mark_date_synced.assert_called_once_with("2026-09-24", 7)

    def test_sync_pending_processes_all_dates(self) -> None:
        mock_config = Mock(spec=Config)
        mock_config.intervals_athlete_id = "i12345"
        mock_api = Mock()
        mock_nutrition = Mock()

        mock_nutrition.list_unsynced_dates.return_value = ["2026-09-23", "2026-09-24"]
        mock_nutrition.get_sync_snapshot.side_effect = [
            {
                "date": "2026-09-23",
                "total_kcal": 1800,
                "total_carbs_g": 0,
                "total_protein_g": 0,
                "total_fat_g": 0,
                "sync_revision": 1,
            },
            {
                "date": "2026-09-24",
                "total_kcal": 2100,
                "total_carbs_g": 0,
                "total_protein_g": 0,
                "total_fat_g": 0,
                "sync_revision": 2,
            },
        ]
        mock_nutrition.mark_date_synced.return_value = True

        sync_service = IntervalsNutritionSyncService(
            config=mock_config,
            api_client=mock_api,
            diary_service=mock_nutrition,
        )

        res = sync_service.sync_pending()
        self.assertTrue(res["ok"])
        self.assertEqual(res["synced_dates"], ["2026-09-23", "2026-09-24"])
        self.assertEqual(mock_api.put.call_count, 2)

    def test_sync_pending_keeps_revision_races_out_of_synced_dates(self) -> None:
        config = Mock(spec=Config)
        config.intervals_athlete_id = "i12345"
        nutrition = Mock()
        nutrition.list_unsynced_dates.return_value = ["2026-09-24"]
        nutrition.get_sync_snapshot.return_value = {
            "date": "2026-09-24",
            "total_kcal": 0,
            "total_carbs_g": 0,
            "total_protein_g": 0,
            "total_fat_g": 0,
            "entry_count": 0,
            "sync_revision": 8,
        }
        nutrition.mark_date_synced.return_value = False

        result = IntervalsNutritionSyncService(config, Mock(), nutrition).sync_pending()

        self.assertFalse(result["ok"])
        self.assertEqual(result["synced_dates"], [])
        self.assertEqual(result["pending_dates"], ["2026-09-24"])


if __name__ == "__main__":
    unittest.main()
