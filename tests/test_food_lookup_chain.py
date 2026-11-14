"""Lookup priority with Yazio: local, Yazio, Open Food Facts, BLS (synthetic data)."""

from __future__ import annotations

import time
import unittest
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import patch

from support import temp_database

from backend.db import row_factory
from backend.db.repositories import NutritionProductRepository
from backend.errors import AppError
from backend.nutrition.food_database import (
    FOUND_LIMIT,
    FOUND_TTL_SECONDS,
    FoodDatabaseService,
)
from backend.nutrition.food_mirror import FoodDatabaseMirror

START = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
YAZIO_ID = "11111111-2222-3333-4444-555555555555"
BARCODE = "4006381333931"
OTHER = "66666666-7777-8888-9999-000000000000"


def yazio_food(name="Synthetic Haferflocken", kcal=370.0, food_id=YAZIO_ID):
    return {
        "id": f"yazio:{food_id}",
        "name": name,
        "brands": "Synthetic Mill",
        "source": "Yazio",
        "basis_amount": 100,
        "basis_unit": "g",
        "per_100": {
            "kcal": kcal,
            "carbs_g": 60.0,
            "protein_g": 13.0,
            "fat_g": 7.0,
            "sugar_g": None,
            "fiber_g": None,
            "salt_g": None,
        },
    }


def off_food(name="Synthetic Haferflocken", barcode=BARCODE):
    return {
        "id": f"off:{barcode}",
        "name": name,
        "brands": "",
        "source": "Open Food Facts",
        "basis_amount": 100,
        "basis_unit": "g",
        "per_100": {
            "kcal": 365.0,
            "carbs_g": 58.0,
            "protein_g": 12.0,
            "fat_g": 6.0,
            "sugar_g": None,
            "fiber_g": None,
            "salt_g": None,
        },
    }


class FakeYazio:
    def __init__(self, hits=None):
        self.configured = True
        self.hits = [] if hits is None else hits
        self.error: AppError | None = None
        self.calls: list[tuple[str, str]] = []
        self.barcode_food: dict | None = None

    def _fail(self):
        if self.error:
            raise self.error

    def search(self, query):
        self.calls.append(("search", query))
        self._fail()
        return self.hits

    def product(self, product_id):
        self.calls.append(("product", product_id))
        self._fail()
        return yazio_food(food_id=product_id)

    def barcode(self, barcode):
        self.calls.append(("barcode", barcode))
        self._fail()
        return self.barcode_food


class FakeOff:
    def __init__(self, hits=None):
        self.hits = [] if hits is None else hits
        self.error: AppError | None = None
        self.calls: list[tuple[str, str]] = []

    def search(self, query):
        self.calls.append(("search", query))
        if self.error:
            raise self.error
        return self.hits

    def product(self, barcode):
        self.calls.append(("product", barcode))
        if self.error:
            raise self.error
        return off_food(barcode=barcode)


UNAVAILABLE = AppError(502, "offline", reason="food_database_unavailable")


class LookupChainTests(unittest.TestCase):
    def setUp(self):
        self.manager = temp_database(
            self, "chain.db", row_factory=row_factory, schema=True
        )
        self.now = START
        self.mirror = FoodDatabaseMirror(
            lambda: self.manager, lambda: self.now.isoformat()
        )
        self.yazio = FakeYazio()
        self.off = FakeOff()
        self.service = FoodDatabaseService(
            cast(Any, self.off), self.mirror, cast(Any, self.yazio)
        )

    def ids(self, **arguments):
        return [food["id"] for food in self.service.lookup(arguments)["foods"]]

    def test_yazio_answers_first_with_source_and_origin(self):
        self.yazio.hits = [yazio_food()]
        result = self.service.lookup({"query": "Haferflocken"})
        self.assertEqual([f["id"] for f in result["foods"]], [f"yazio:{YAZIO_ID}"])
        self.assertEqual(result["foods"][0]["source"], "Yazio")
        self.assertEqual(result["foods"][0]["data_origin"], "live")
        self.assertEqual(self.off.calls, [])

    def test_fresh_mirror_hit_prevents_every_external_request(self):
        self.mirror.store([yazio_food()])
        self.assertEqual(self.ids(query="Haferflocken"), [f"yazio:{YAZIO_ID}"])
        self.assertEqual((self.yazio.calls, self.off.calls), ([], []))

    def test_fresh_mirror_entry_of_any_source_answers_before_the_chain(self):
        self.mirror.store([off_food()])
        self.yazio.error = UNAVAILABLE
        self.assertEqual(self.ids(query="Haferflocken"), [f"off:{BARCODE}"])
        self.assertEqual(self.yazio.calls, [])

    def test_empty_or_unsuitable_yazio_falls_through_to_open_food_facts(self):
        self.off.hits = [off_food()]
        for hits in ([], [yazio_food("Kokosmilch")], [yazio_food(kcal=None)]):
            with self.subTest(hits=hits):
                self.yazio.hits = hits
                self.assertEqual(self.ids(query="Haferflocken"), [f"off:{BARCODE}"])

    def test_yazio_hit_without_a_usable_unit_falls_through(self):
        self.yazio.hits = [{**yazio_food(), "basis_unit": None}]
        self.off.hits = [off_food()]
        self.assertEqual(self.ids(query="Haferflocken"), [f"off:{BARCODE}"])

    def test_stale_yazio_barcode_entry_is_used_when_every_source_fails(self):
        self.mirror.store([{**yazio_food(), "barcode": BARCODE}])
        self.now = datetime(2027, 1, 20, tzinfo=UTC)
        self.yazio.error = UNAVAILABLE
        self.off.error = UNAVAILABLE
        result = self.service.lookup({"barcode": BARCODE})
        self.assertEqual(result["foods"][0]["id"], f"yazio:{YAZIO_ID}")
        self.assertEqual(result["foods"][0]["data_origin"], "local_database_stale")
        self.assertIn("Onlinequelle", result["notice"])

    def test_fresh_legacy_yazio_fallback_does_not_retry_each_scan(self):
        legacy = {**yazio_food(), "barcode": BARCODE}
        for key in ("sugar_g", "fiber_g", "salt_g"):
            del legacy["per_100"][key]
        self.mirror.store([legacy])
        self.yazio.configured = False
        self.off.error = UNAVAILABLE
        first = self.service.lookup({"barcode": BARCODE})["foods"][0]
        second = self.service.lookup({"barcode": BARCODE})["foods"][0]
        self.assertEqual(first["id"], f"yazio:{YAZIO_ID}")
        self.assertEqual(second["data_origin"], "local_database")
        self.assertEqual(self.off.calls, [("product", BARCODE)])

    def test_fresh_entry_of_another_source_beats_a_newer_stale_one(self):
        self.mirror.store([off_food()])
        self.now = datetime(2027, 1, 20, tzinfo=UTC)
        self.mirror.store([{**yazio_food(), "barcode": BARCODE}])
        self.now = datetime(2027, 6, 1, tzinfo=UTC)
        self.mirror.store([off_food()])
        self.assertEqual(self.ids(barcode=BARCODE), [f"off:{BARCODE}"])
        self.assertEqual(self.yazio.calls, [])

    def test_unsuitable_stored_hit_does_not_hide_live_yazio_results(self):
        self.mirror.store([yazio_food("Haferflocken", kcal=None)])
        self.yazio.hits = [yazio_food("Haferflocken zart", food_id=OTHER)]
        self.assertEqual(self.ids(query="Haferflocken"), [f"yazio:{OTHER}"])

    def test_text_chain_names_rejected_yazio_credentials(self):
        self.yazio.error = AppError(503, "x", reason="food_database_auth_failed")
        self.off.hits = [off_food()]
        result = self.service.lookup({"query": "Haferflocken"})
        self.assertIn("Zugangsdaten", result["notice"])

    def test_version_block_is_reported_while_fallback_remains_available(self):
        self.yazio.error = AppError(502, "x", reason="food_database_version_blocked")
        self.off.hits = [off_food()]
        result = self.service.lookup({"query": "Haferflocken"})
        self.assertTrue(result["foods"])
        self.assertIn("YAZIO_USER_AGENT", result["notice"])

    def test_version_block_is_reported_in_barcode_fallback(self):
        self.yazio.error = AppError(502, "x", reason="food_database_version_blocked")
        result = self.service.lookup({"barcode": BARCODE})
        self.assertIn("YAZIO_USER_AGENT", result["notice"])

    def test_internal_chain_name_is_not_a_public_source(self):
        with self.assertRaises(AppError) as raised:
            self.service.lookup({"query": "Haferflocken", "source": "chain"})
        self.assertEqual(raised.exception.status, 400)

    def test_failing_providers_end_at_bls(self):
        self.yazio.error = UNAVAILABLE
        self.off.error = UNAVAILABLE
        result = self.service.lookup({"query": "Haferflocken"})
        self.assertTrue(result["foods"])
        self.assertTrue(all(f["id"].startswith("bls:") for f in result["foods"]))
        self.assertIn("Onlinequelle", result["notice"])

    def test_off_hit_without_all_query_words_falls_through_to_bls(self):
        self.off.hits = [off_food("Kokosmilch")]
        result = self.service.lookup({"query": "Haferflocken"})
        self.assertTrue(all(f["id"].startswith("bls:") for f in result["foods"]))

    def test_without_yazio_the_default_stays_bls_only(self):
        self.yazio.configured = False
        result = self.service.lookup({"query": "Haferflocken"})
        self.assertTrue(all(f["id"].startswith("bls:") for f in result["foods"]))
        self.assertEqual((self.yazio.calls, self.off.calls), ([], []))

    def test_explicit_sources_query_only_that_source(self):
        self.yazio.hits = [yazio_food("Kokosmilch")]
        self.off.hits = [off_food()]
        self.assertEqual(
            self.ids(query="Haferflocken", source="yazio"), [f"yazio:{YAZIO_ID}"]
        )
        self.assertEqual(self.off.calls, [])
        self.assertEqual(
            self.ids(query="Haferflocken", source="open_food_facts"), [f"off:{BARCODE}"]
        )

    def test_explicit_yazio_without_configuration_is_a_clear_error(self):
        self.yazio.configured = False
        with self.assertRaises(AppError) as raised:
            self.service.lookup({"query": "Haferflocken", "source": "yazio"})
        self.assertEqual(raised.exception.reason, "not_configured")

    def test_mirror_reads_do_not_mix_sources(self):
        self.mirror.store([yazio_food("Haferflocken Yazio")])
        self.off.hits = [off_food("Haferflocken OFF")]
        self.assertEqual(
            self.ids(query="Haferflocken", source="open_food_facts"), [f"off:{BARCODE}"]
        )

    def test_stale_mirror_entry_is_used_when_yazio_is_unavailable(self):
        self.mirror.store([yazio_food()])
        self.now = datetime(2027, 1, 20, tzinfo=UTC)
        self.yazio.error = UNAVAILABLE
        result = self.service.lookup({"query": "Haferflocken", "source": "yazio"})
        self.assertEqual(result["foods"][0]["data_origin"], "local_database_stale")

    def test_barcode_prefers_mirror_then_yazio_then_open_food_facts(self):
        self.yazio.barcode_food = {**yazio_food(), "barcode": BARCODE}
        self.assertEqual(self.ids(barcode=BARCODE), [f"yazio:{YAZIO_ID}"])
        self.assertEqual(self.yazio.calls, [("barcode", BARCODE)])
        # The stored Yazio record now answers without another request.
        self.assertEqual(self.ids(barcode=BARCODE), [f"yazio:{YAZIO_ID}"])
        self.assertEqual(len(self.yazio.calls), 1)
        other = "4000000000017"
        self.yazio.barcode_food = None
        self.assertEqual(self.ids(barcode=other), [f"off:{other}"])

    def test_scanned_barcode_is_stored_and_found_again(self):
        self.yazio.barcode_food = {**yazio_food(), "barcode": "4000000000017"}
        self.ids(barcode=BARCODE)
        self.assertEqual(self.mirror.by_barcode(BARCODE)[0]["id"], f"yazio:{YAZIO_ID}")
        self.assertEqual(self.ids(barcode=BARCODE), [f"yazio:{YAZIO_ID}"])
        self.assertEqual(len(self.yazio.calls), 1)

    def test_unusable_stored_barcode_entry_does_not_shadow_open_food_facts(self):
        self.mirror.store([{**yazio_food(kcal=None), "barcode": BARCODE}])
        self.yazio.error = UNAVAILABLE
        self.assertEqual(self.ids(barcode=BARCODE), [f"off:{BARCODE}"])

    def test_rejected_yazio_login_is_named_in_the_barcode_notice(self):
        self.yazio.error = AppError(503, "x", reason="food_database_auth_failed")
        result = self.service.lookup({"barcode": BARCODE})
        self.assertIn("Zugangsdaten", result["notice"])

    def test_search_hit_keeps_the_barcode_of_a_stored_detail(self):
        self.mirror.store([{**yazio_food(), "barcode": BARCODE}])
        self.mirror.store([yazio_food(name="Synthetic Haferflocken neu")])
        self.assertEqual(
            self.mirror.by_barcode(BARCODE)[0]["name"], "Synthetic Haferflocken neu"
        )

    def test_unusable_stored_entry_is_not_a_stale_barcode_answer(self):
        self.mirror.store([{**yazio_food(kcal=None), "barcode": BARCODE}])
        self.now = datetime(2027, 6, 1, tzinfo=UTC)
        self.yazio.error = UNAVAILABLE
        self.off.error = UNAVAILABLE
        with self.assertRaises(AppError):
            self.service.lookup({"barcode": BARCODE})

    def test_unusable_live_yazio_barcode_hit_falls_through_to_open_food_facts(self):
        self.yazio.barcode_food = {**yazio_food(kcal=None), "barcode": BARCODE}
        self.assertEqual(self.ids(barcode=BARCODE), [f"off:{BARCODE}"])

    def test_yazio_failure_does_not_block_barcode_lookup(self):
        self.yazio.error = UNAVAILABLE
        self.assertEqual(self.ids(barcode=BARCODE), [f"off:{BARCODE}"])

    def test_yazio_food_resolves_for_calculation_and_survives_an_outage(self):
        self.yazio.hits = [yazio_food()]
        self.service.lookup({"query": "Haferflocken"})
        self.yazio.error = UNAVAILABLE
        result = self.service.calculate(
            [{"food_id": f"yazio:{YAZIO_ID}", "amount": 50, "unit": "g"}]
        )
        self.assertEqual(result["kcal"], 185)
        self.assertEqual(result["nutrition_basis"]["ingredients"][0]["source"], "Yazio")

    def test_a_re_check_fills_remaining_gaps_from_yazio_by_ean(self):
        self.mirror.store([off_food()])
        with_salt = yazio_food()
        with_salt["per_100"] |= {"salt_g": 0.01, "fat_g": 99.0}
        self.yazio.barcode_food = with_salt
        self.now += timedelta(days=1)

        refreshed = self.service.refresh_stored(f"off:{BARCODE}")

        self.assertEqual(
            (refreshed["per_100"]["salt_g"], refreshed["per_100"]["fat_g"]), (0.01, 6.0)
        )
        self.assertEqual(
            refreshed["filled_fields"],
            {"salt_g": {"origin": "yazio", "fetched_at": self.now.isoformat()}},
        )
        self.assertEqual(refreshed["missing_fields"], ["sugar_g", "fiber_g"])
        # An own product filling from this entry keeps the Yazio origin.
        with self.manager.unit_of_work() as db:
            db.execute(
                "INSERT INTO nutrition_products(id, barcode, name, basis_amount, "
                "basis_unit, source, created_at, updated_at) VALUES "
                "('own', ?, 'Eigen', 100, 'g', 'manual', 'now', 'now')",
                (BARCODE,),
            )
            NutritionProductRepository.fill_from_database_entries(db, "own", BARCODE)
            filled = NutritionProductRepository().get(db, "own")["filled_fields"]
        self.assertEqual(filled["salt_g"]["origin"], "yazio")
        self.assertEqual(filled["kcal"]["origin"], "open_food_facts")
        # A later Open Food Facts value wins and drops the Yazio origin.
        later = off_food()
        later["per_100"]["salt_g"] = 0.02
        self.off.product = lambda barcode: later
        self.yazio.barcode_food = None
        self.now += timedelta(days=1)
        refreshed = self.service.refresh_stored(f"off:{BARCODE}")
        self.assertEqual(
            (refreshed["per_100"]["salt_g"], refreshed["filled_fields"]), (0.02, {})
        )

    def test_a_basis_change_ends_a_yazio_fill(self):
        self.mirror.store([off_food()])
        with_salt = yazio_food()
        with_salt["per_100"]["salt_g"] = 0.01
        self.yazio.barcode_food = with_salt
        self.now += timedelta(days=1)
        self.service.refresh_stored(f"off:{BARCODE}")
        in_ml = off_food()
        in_ml["basis_unit"] = "ml"
        self.off.product = lambda barcode: in_ml
        self.now += timedelta(days=1)

        refreshed = self.service.refresh_stored(f"off:{BARCODE}")

        self.assertIsNone(refreshed["per_100"]["salt_g"])
        self.assertEqual(refreshed["filled_fields"], {})

    def test_lookups_and_calculations_ask_yazio_at_most_once(self):
        self.mirror.store([off_food()])
        self.now += timedelta(days=100)

        self.service.lookup({"barcode": BARCODE})
        self.service.resolve(f"off:{BARCODE}")

        self.assertEqual(self.yazio.calls, [("barcode", BARCODE)])

    def test_yazio_fills_nothing_without_a_match_on_the_same_basis(self):
        portion = yazio_food()
        portion["basis_unit"] = "ml"
        portion["per_100"]["salt_g"] = 0.01
        for case, setup in (
            ("not configured", lambda: setattr(self.yazio, "configured", False)),
            ("failure", lambda: setattr(self.yazio, "error", UNAVAILABLE)),
            ("no product", lambda: setattr(self.yazio, "barcode_food", None)),
            ("other basis", lambda: setattr(self.yazio, "barcode_food", portion)),
        ):
            with self.subTest(case=case):
                self.setUp()
                self.mirror.store([off_food()])
                setup()
                self.now += timedelta(days=1)
                refreshed = self.service.refresh_stored(f"off:{BARCODE}")
                self.assertIsNone(refreshed["per_100"]["salt_g"])
                self.assertNotIn("filled_fields", refreshed)
                self.assertEqual("notice" in refreshed, case == "failure")

    def test_a_complete_re_check_does_not_ask_yazio(self):
        complete = off_food()
        complete["per_100"] |= {"sugar_g": 1.0, "fiber_g": 10.0, "salt_g": 0.01}
        self.off.product = lambda barcode: complete
        self.mirror.store([complete])
        self.now += timedelta(days=1)

        self.service.refresh_stored(f"off:{BARCODE}")

        self.assertEqual(self.yazio.calls, [])

    def test_a_filled_value_backs_only_the_origin_it_came_from(self):
        # An off: entry whose salt came from Yazio and whose sugar the athlete
        # entered: salt backs yazio, sugar backs nothing, fat backs off.
        food = {
            **off_food(),
            "per_100": {"fat_g": 6.0, "salt_g": 0.3, "sugar_g": 1.0},
            "filled_fields": {
                "salt_g": {"origin": "yazio"},
                "sugar_g": {"origin": "manual"},
            },
        }
        self.service._remember_foods([food])
        for args, expected in (
            (("open_food_facts", "fat_g", 6.0, 100, "g"), True),
            (("open_food_facts", "salt_g", 0.3, 100, "g"), False),
            (("yazio", "salt_g", 0.3, 100, "g"), True),
            (("open_food_facts", "sugar_g", 1.0, 100, "g"), False),
            (("manual", "sugar_g", 1.0, 100, "g"), False),
        ):
            with self.subTest(args=args):
                self.assertIs(self.service.found_value(*args), expected)

    def test_returned_values_back_a_gap_fill_origin_for_an_hour(self):
        bls = {**off_food(), "id": "bls:C1", "per_100": {"fat_g": 2.0, "kcal": None}}
        self.yazio.hits = [yazio_food()]
        self.service.lookup({"query": "Haferflocken"})
        with patch("backend.nutrition.food_database._bls_search") as search:
            search.return_value = ([bls], False)
            self.service.lookup({"query": "Haferflocken", "source": "bls"})
        self.mirror.store([off_food()])
        self.now += timedelta(days=1)
        self.service.refresh_stored(f"off:{BARCODE}")

        for label, args, expected in (
            ("returned value", ("yazio", "kcal", 370, 100, "g"), True),
            ("scaled to the basis", ("yazio", "kcal", 185, 50, "g"), True),
            ("within one percent", ("yazio", "kcal", 372, 100, "g"), True),
            ("another value", ("yazio", "kcal", 380, 100, "g"), False),
            ("another origin", ("open_food_facts", "kcal", 370, 100, "g"), False),
            ("another unit", ("yazio", "kcal", 370, 100, "ml"), False),
            ("no basis", ("yazio", "kcal", 370, 0, "g"), False),
            ("empty field never returned", ("bls", "kcal", 0, 100, "g"), False),
            ("bls value", ("bls", "fat_g", 2, 100, "g"), True),
            ("re-checked value", ("open_food_facts", "kcal", 365, 100, "g"), True),
        ):
            with self.subTest(label):
                self.assertIs(self.service.found_value(*args), expected)
        # A value expires after the hour.
        later = time.monotonic() + FOUND_TTL_SECONDS + 1
        with patch("backend.nutrition.food_database.time.monotonic") as clock:
            clock.return_value = later
            self.assertFalse(self.service.found_value("yazio", "kcal", 370, 100, "g"))
        # Only the newest values are kept.
        self.service.remember_found(
            "yazio", [("kcal", 1.5, 100, "g", None)] * FOUND_LIMIT
        )
        self.assertFalse(self.service.found_value("yazio", "kcal", 370, 100, "g"))
        self.assertTrue(self.service.found_value("yazio", "kcal", 1.5, 100, "g"))

    def test_unknown_yazio_id_is_not_found(self):
        self.yazio.error = AppError(404, "x", reason="food_not_found")
        with self.assertRaises(AppError) as raised:
            self.service.resolve(f"yazio:{YAZIO_ID}")
        self.assertEqual(raised.exception.reason, "food_not_found")
        with self.assertRaises(AppError):
            self.service.resolve("yazio:../../x")


if __name__ == "__main__":
    unittest.main()
