import sqlite3
import threading
import unittest
from datetime import UTC, datetime
from unittest.mock import Mock

from nutrition_service_support import build_nutrition_services
from support import temp_database

from backend.coach.read_tools import CoachReadToolService
from backend.errors import AppError


class CoachReadToolServiceTests(unittest.TestCase):
    def setUp(self):
        self.profile = Mock()
        self.profile.get.return_value = {"name": "Athlete"}
        self.training_state = Mock()
        self.training_state.read.return_value = {
            "planned_units": [],
            "planned_units_page": {"has_more": False},
        }
        self.activity_tools = Mock()
        self.activity_tools.execute.side_effect = lambda name, _arguments: {
            "ok": True,
            "tool": name,
        }
        self.library = Mock()
        self.library.list.return_value = [{"id": "workout-1"}]
        self.planned_units = Mock()
        self.planned_units.list_for_coach.return_value = {"local": []}
        self.history = Mock()
        self.history.list.return_value = [{"id": "change-1"}]
        self.competitions = Mock()
        self.competitions.list.return_value = [{"id": "race-1"}]
        self.training_plans = Mock()
        self.training_plans.list.return_value = [{"id": "plan-1"}]
        self.nutrition_diary = Mock()
        self.nutrition_meal_library = Mock()
        self.nutrition_meal_library.list_templates.return_value = [{"id": "template-1"}]
        self.nutrition_diary.sync_status.get_day_summary.return_value = {
            "date": "2026-03-30",
            "total_kcal": 2100,
        }
        self.nutrition_diary.get_range_summary.return_value = [
            {"date": "2026-03-30", "total_kcal": 2100}
        ]
        self.nutrition_diary_factory = Mock(return_value=self.nutrition_diary)
        self.nutrition_meal_library_factory = Mock(
            return_value=self.nutrition_meal_library
        )
        self.factories = [
            Mock(return_value=service)
            for service in (
                self.profile,
                self.training_state,
                self.activity_tools,
                self.library,
                self.planned_units,
                self.history,
                self.competitions,
                self.training_plans,
            )
        ]
        self.service = CoachReadToolService(
            *self.factories,
            training_change_limit=366,
            nutrition_diary=self.nutrition_diary_factory,
            nutrition_meal_library=self.nutrition_meal_library_factory,
        )

    def test_dispatches_every_read_tool_and_projects_existing_shapes(self):
        self.assertEqual(
            self.service.execute("read_profile", {}),
            {"ok": True, "profile": {"name": "Athlete"}},
        )
        self.assertEqual(
            self.service.execute(
                "read_training_state",
                {"include_inactive": 1, "cursor": "next", "limit": 12},
            ),
            {
                "ok": True,
                "planned_units": [],
                "planned_units_page": {"has_more": False},
            },
        )
        self.training_state.read.assert_called_once_with(
            include_inactive=True, cursor="next", limit=12
        )
        for name in ("list_recent_activities", "get_activity_details"):
            self.assertEqual(
                self.service.execute(name, {"activity_id": "activity-1"}),
                {"ok": True, "tool": name},
            )
        self.activity_tools.execute.assert_any_call(
            "list_recent_activities", {"activity_id": "activity-1"}
        )
        self.activity_tools.execute.assert_any_call(
            "get_activity_details", {"activity_id": "activity-1"}
        )
        self.assertEqual(
            self.service.execute("list_workout_library", {"include_archived": True}),
            {"ok": True, "templates": [{"id": "workout-1"}]},
        )
        self.library.list.assert_called_once_with(100, include_archived=True)
        self.assertEqual(
            self.service.execute("list_planned_workouts", {}),
            {"ok": True, "local": []},
        )
        self.planned_units.list_for_coach.assert_called_once_with(100)
        self.assertEqual(
            self.service.execute("list_change_history", {}),
            {"ok": True, "changes": [{"id": "change-1"}]},
        )
        self.assertEqual(
            self.service.execute("list_competitions", {}),
            {"ok": True, "competitions": [{"id": "race-1"}]},
        )
        self.assertEqual(
            self.service.execute("list_training_plans", {}),
            {"ok": True, "training_plans": [{"id": "plan-1"}]},
        )

    def test_read_nutrition_day_and_range(self):
        day_res = self.service.execute("read_nutrition", {"date": "2026-03-30"})
        self.assertEqual(
            day_res,
            {
                "ok": True,
                "templates": [{"id": "template-1"}],
                "date": "2026-03-30",
                "total_kcal": 2100,
            },
        )
        self.nutrition_diary.sync_status.get_day_summary.assert_called_once_with(
            "2026-03-30"
        )

        range_res = self.service.execute(
            "read_nutrition", {"start": "2026-03-01", "end": "2026-03-31"}
        )
        self.assertEqual(
            range_res,
            {
                "ok": True,
                "templates": [{"id": "template-1"}],
                "summaries": [{"date": "2026-03-30", "total_kcal": 2100}],
            },
        )
        self.nutrition_diary.get_range_summary.assert_called_once_with(
            "2026-03-01", "2026-03-31"
        )

    def test_limit_bounds_saturate_and_optional_filters_are_forwarded(self):
        self.service.execute(
            "list_workout_library", {"limit": 900, "include_archived": False}
        )
        self.library.list.assert_called_once_with(100, include_archived=False)
        self.service.execute("list_planned_workouts", {"limit": 900})
        self.planned_units.list_for_coach.assert_called_once_with(366)
        self.service.execute("list_change_history", {"limit": 0})
        self.history.list.assert_called_once_with(1)

    def test_nutrition_range_is_validated_and_bounded(self):
        for start, end in (("not-a-date", "2026-03-31"), ("2026-01-01", "2026-02-01")):
            with (
                self.subTest(start=start, end=end),
                self.assertRaises(AppError) as caught,
            ):
                self.service.execute("read_nutrition", {"start": start, "end": end})
            self.assertEqual(caught.exception.status, 400)
            self.nutrition_diary.get_range_summary.assert_not_called()

    def test_invalid_limits_keep_bad_request_reason(self):
        for tool_name in (
            "list_workout_library",
            "list_planned_workouts",
            "list_change_history",
        ):
            with self.subTest(tool=tool_name), self.assertRaises(AppError) as caught:
                self.service.execute(tool_name, {"limit": "not-an-integer"})
            self.assertEqual(caught.exception.status, 400)
            self.assertEqual(caught.exception.reason, "invalid_list_request")

    def test_explicit_text_source_bypasses_local_products(self) -> None:
        meal_library = self.nutrition_meal_library
        meal_library.product_catalog.list_products.return_value = []
        meal_library.food_database.lookup.return_value = {
            "ok": True,
            "foods": [{"id": "bls:123"}],
            "source": "bls",
        }
        result = self.service.execute(
            "lookup_food", {"query": "Haferflocken", "source": "bls"}
        )

        assert isinstance(result, dict)
        self.assertEqual(result["source"], "bls")
        meal_library.food_database.lookup.assert_called_once_with(
            {"query": "Haferflocken", "source": "bls"}
        )
        meal_library.product_catalog.lookup_product.assert_not_called()
        self.assertNotIn("local_products", result)

    def test_explicit_text_source_still_returns_matching_saved_products(self) -> None:
        meal_library = self.nutrition_meal_library
        meal_library.food_database.lookup.return_value = {
            "ok": True,
            "foods": [{"id": "bls:123"}],
            "source": "bls",
        }
        saved = [{"id": f"local-oats-{index}"} for index in range(12)]
        meal_library.product_catalog.list_products.return_value = saved
        result = self.service.execute(
            "lookup_food", {"query": "Haferflocken", "source": "bls"}
        )

        assert isinstance(result, dict)
        self.assertEqual(result["source"], "bls")
        # Same saved matches as a lookup without an explicit source.
        self.assertEqual(result["local_products"], saved)
        meal_library.product_catalog.list_products.assert_called_once_with(
            query="Haferflocken"
        )

    def test_explicit_source_outage_still_returns_saved_products(self) -> None:
        meal_library = self.nutrition_meal_library
        meal_library.food_database.lookup.side_effect = AppError(
            429, "Lebensmitteldatenbank ist vorübergehend ausgelastet."
        )
        meal_library.product_catalog.list_products.return_value = [{"id": "local-oats"}]
        result = self.service.execute(
            "lookup_food", {"query": " Skyr ", "source": " Open_Food_Facts "}
        )

        assert isinstance(result, dict)
        self.assertEqual(result["foods"], [])
        self.assertEqual(result["local_products"], [{"id": "local-oats"}])
        meal_library.product_catalog.lookup_product.assert_not_called()
        meal_library.food_database.lookup.assert_called_once_with(
            {"query": "Skyr", "source": "open_food_facts"}
        )
        for status in (400, 404, 502):
            meal_library.food_database.lookup.side_effect = AppError(status, "Fehler.")
            with self.subTest(status=status):
                fallback = self.service.execute(
                    "lookup_food", {"query": "Skyr", "source": "bls"}
                )
                assert isinstance(fallback, dict)
                self.assertEqual(fallback["local_products"], [{"id": "local-oats"}])
                self.assertIn("Fehler.", fallback["notice"])

        meal_library.product_catalog.list_products.return_value = []
        with self.assertRaises(AppError):
            self.service.execute(
                "lookup_food", {"query": "Haferflocken", "source": "bls"}
            )

    def test_batched_queries_return_each_term_and_isolate_failures(self) -> None:
        meal_library = self.nutrition_meal_library

        def lookup(arguments):
            if arguments["query"] == "Pfeffersoße":
                raise AppError(
                    429,
                    "Lebensmitteldatenbank ist vorübergehend ausgelastet.",
                    reason="food_database_rate_limited",
                )
            return {"ok": True, "foods": [{"id": f"local-{arguments['query']}"}]}

        meal_library.product_catalog.lookup_product.side_effect = lookup
        result = self.service.execute(
            "lookup_food",
            {"query": "Reis", "queries": [" Zucchini ", "reis", "Pfeffersoße"]},
        )

        assert isinstance(result, dict)
        self.assertTrue(result["ok"])
        self.assertEqual(
            [item["query"] for item in result["results"]],
            ["Reis", "Zucchini", "Pfeffersoße"],
        )
        self.assertEqual(result["results"][1]["foods"], [{"id": "local-Zucchini"}])
        self.assertEqual(
            result["results"][2],
            {
                "query": "Pfeffersoße",
                "ok": False,
                "error": "Lebensmitteldatenbank ist vorübergehend ausgelastet.",
                "reason": "food_database_rate_limited",
            },
        )
        # Without a source each term keeps the local-first product lookup.
        meal_library.product_catalog.lookup_product.assert_any_call(
            {"query": "Zucchini"}
        )
        meal_library.food_database.lookup.assert_not_called()

        meal_library.product_catalog.lookup_product.side_effect = AppError(
            429, "Ausgelastet."
        )
        with self.assertRaises(AppError):
            self.service.execute("lookup_food", {"queries": ["Reis", "Zucchini"]})
        for arguments in (
            {"queries": "Reis"},
            {"queries": ["Reis"], "barcode": "4001234567890"},
            {"queries": [" "]},
            {"queries": [f"Zutat {index}" for index in range(21)]},
        ):
            with self.subTest(arguments=arguments), self.assertRaises(AppError):
                self.service.execute("lookup_food", arguments)

    def test_barcode_source_keeps_local_first_lookup(self) -> None:
        meal_library = self.nutrition_meal_library
        meal_library.product_catalog.lookup_product.return_value = {
            "ok": True,
            "product": {"id": "local-product"},
            "source": "local",
        }
        result = self.service.execute(
            "lookup_food", {"barcode": "4006381333931", "source": "off"}
        )

        assert isinstance(result, dict)
        self.assertEqual(result["source"], "local")
        meal_library.product_catalog.lookup_product.assert_called_once_with(
            {"barcode": "4006381333931", "source": "off"}
        )
        meal_library.food_database.lookup.assert_not_called()

    def test_omitted_text_source_uses_bls_and_never_queries_open_food_facts(
        self,
    ) -> None:
        manager = temp_database(
            self, "nutrition.db", row_factory=sqlite3.Row, schema=True
        )
        _diary, meal_library = build_nutrition_services(
            manager,
            threading.Lock(),
            lambda: "2026-10-05T12:00:00+00:00",
            lambda: datetime(2026, 10, 5, tzinfo=UTC),
        )
        off_client = Mock()
        off_client.search.return_value = [{"id": "off:1"}]
        off_client.product.return_value = {"id": "off:1"}
        meal_library.food_database._off = off_client
        self.nutrition_meal_library_factory.return_value = meal_library

        result = self.service.execute("lookup_food", {"query": "Haferflocken"})

        assert isinstance(result, dict)
        self.assertFalse(result["local"])
        self.assertTrue(result["foods"])
        self.assertTrue(all(food["id"].startswith("bls:") for food in result["foods"]))
        off_client.search.assert_not_called()
        off_client.product.assert_not_called()

    def test_unknown_name_returns_none_without_constructing_services(self):
        self.assertIsNone(self.service.execute("unknown_read_tool", {}))
        for factory in self.factories:
            factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
