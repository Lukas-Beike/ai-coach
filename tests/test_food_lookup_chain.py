"""Lookup priority with Yazio: local, Yazio, Open Food Facts, BLS (synthetic data)."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from backend.db import DatabaseManager, row_factory
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.nutrition.food_database import FoodDatabaseService
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
        "per_100": {"kcal": kcal, "carbs_g": 60.0, "protein_g": 13.0, "fat_g": 7.0},
    }


def off_food(name="Synthetic Haferflocken", barcode=BARCODE):
    return {
        "id": f"off:{barcode}",
        "name": name,
        "brands": "",
        "source": "Open Food Facts",
        "basis_amount": 100,
        "basis_unit": "g",
        "per_100": {"kcal": 365.0, "carbs_g": 58.0, "protein_g": 12.0, "fat_g": 6.0},
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
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = DatabaseManager(
            Path(directory.name) / "chain.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.now = START
        self.mirror = FoodDatabaseMirror(
            lambda: self.manager, threading.RLock(), lambda: self.now.isoformat()
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
        self.assertEqual(raised.exception.reason, "food_database_not_configured")

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

    def test_unknown_yazio_id_is_not_found(self):
        self.yazio.error = AppError(404, "x", reason="food_not_found")
        with self.assertRaises(AppError) as raised:
            self.service.resolve(f"yazio:{YAZIO_ID}")
        self.assertEqual(raised.exception.reason, "food_not_found")
        with self.assertRaises(AppError):
            self.service.resolve("yazio:../../x")


if __name__ == "__main__":
    unittest.main()
