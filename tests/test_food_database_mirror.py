"""The local food mirror stores external foods and is read before the network.

Each test uses a temporary SQLite file through the real DatabaseManager and the
current schema. The Open Food Facts client is a small fake; nothing touches the
network, a real data directory or an encryption key.
"""

from __future__ import annotations

import sqlite3
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from backend.db import DatabaseManager, row_factory
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.nutrition.food_database import FoodDatabaseService
from backend.nutrition.food_mirror import MAX_AGE, FoodDatabaseMirror

START = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
BARCODE = "4006381333931"


def food(barcode: str = BARCODE, name: str = "Haselnuss Riegel") -> dict:
    return {
        "id": f"off:{barcode}",
        "name": name,
        "brands": "Knoppers",
        "source": "Open Food Facts",
        "basis_amount": 100,
        "basis_unit": "g",
        "per_100": {"kcal": 540, "carbs_g": 50, "protein_g": 8, "fat_g": 33},
    }


class FakeOff:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []
        self.offline = False

    def product(self, barcode: str) -> dict:
        self.calls.append(("product", barcode))
        if self.offline:
            raise AppError(502, "offline", reason="food_database_unavailable")
        return food(barcode)

    def search(self, query: str) -> list[dict]:
        self.calls.append(("search", query))
        if self.offline:
            raise AppError(502, "offline", reason="food_database_unavailable")
        return [food()]


class MirrorFixture(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = DatabaseManager(
            Path(directory.name) / "mirror.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(self.manager.close)
        with self.manager.unit_of_work() as db:
            initialize_schema(db)
        self.now = START
        self.mirror = FoodDatabaseMirror(
            lambda: self.manager, threading.RLock(), lambda: self.now.isoformat()
        )
        self.off = FakeOff()
        self.service = FoodDatabaseService(cast(Any, self.off), self.mirror)


class FoodMirrorTests(MirrorFixture):
    def test_stored_food_is_found_by_id_and_by_name_or_brand_words(self):
        self.mirror.store(
            [
                food(),
                {**food("4000000000017", "Vanille Pudding"), "brands": "Milsani"},
            ]
        )

        self.assertEqual(self.mirror.get(f"off:{BARCODE}")["name"], "Haselnuss Riegel")
        self.assertEqual(len(self.mirror.search("knoppers")), 1)
        self.assertEqual(len(self.mirror.search("pudding vanille")), 1)
        self.assertEqual(len(self.mirror.search("")), 2)
        self.assertEqual(self.mirror.search("x"), [])
        self.assertEqual(self.mirror.search("schokolade"), [])

    def test_storing_again_refreshes_the_entry_instead_of_duplicating_it(self):
        self.mirror.store([food()])
        self.now += timedelta(days=100)
        self.mirror.store([food(name="Haselnuss Riegel neu")])

        self.assertEqual(len(self.mirror.search("")), 1)
        entry = self.mirror.get(f"off:{BARCODE}")
        self.assertEqual(entry["name"], "Haselnuss Riegel neu")
        self.assertTrue(self.mirror.is_fresh(entry))

    def test_entries_expire_after_ninety_days(self):
        self.mirror.store([food()])
        entry = self.mirror.get(f"off:{BARCODE}")

        self.now = START + MAX_AGE - timedelta(seconds=1)
        self.assertTrue(self.mirror.is_fresh(entry))
        self.now = START + MAX_AGE
        self.assertFalse(self.mirror.is_fresh(entry))

    def test_a_failing_write_never_breaks_the_lookup(self):
        self.mirror.store([{"id": "off:1", "name": None}])
        self.mirror.store([{"name": "ohne id"}])

        self.assertEqual(self.mirror.search(""), [])

    def test_delete_removes_the_entry_and_unknown_ids_are_not_found(self):
        self.mirror.store([food()])
        self.mirror.delete(f"off:{BARCODE}")

        self.assertIsNone(self.mirror.get(f"off:{BARCODE}"))
        with self.assertRaises(AppError) as raised:
            self.mirror.delete(f"off:{BARCODE}")
        self.assertEqual(raised.exception.reason, "food_not_found")


class FoodDatabaseServiceMirrorTests(MirrorFixture):
    def test_barcode_lookup_stores_the_live_hit_and_then_reads_locally(self):
        first = self.service.lookup({"barcode": BARCODE})["foods"][0]
        second = self.service.lookup({"barcode": BARCODE})["foods"][0]

        self.assertEqual(first["data_origin"], "live")
        self.assertEqual(second["data_origin"], "local_database")
        self.assertEqual(second["stored_at"], START.isoformat())
        self.assertNotIn("fetched_at", second)
        self.assertEqual(self.off.calls, [("product", BARCODE)])

    def test_offline_lookup_falls_back_to_the_stale_entry_with_a_notice(self):
        self.service.lookup({"barcode": BARCODE})
        self.now += MAX_AGE + timedelta(days=1)
        self.off.offline = True

        result = self.service.lookup({"barcode": BARCODE})

        self.assertEqual(result["foods"][0]["data_origin"], "local_database_stale")
        self.assertIn("stored_at", result["foods"][0])
        self.assertIn("gespeicherte Stand", result["notice"])

    def test_expired_entry_is_refreshed_online_when_available(self):
        self.service.lookup({"barcode": BARCODE})
        self.now += MAX_AGE + timedelta(days=1)

        result = self.service.lookup({"barcode": BARCODE})

        self.assertEqual(result["foods"][0]["data_origin"], "live")
        self.assertEqual(len(self.off.calls), 2)
        self.assertTrue(self.mirror.is_fresh(self.mirror.get(f"off:{BARCODE}")))

    def test_unknown_food_offline_still_raises_the_provider_error(self):
        self.off.offline = True

        with self.assertRaises(AppError) as raised:
            self.service.lookup({"barcode": BARCODE})
        self.assertEqual(raised.exception.reason, "food_database_unavailable")

    def test_search_stores_hits_and_is_answered_locally_afterwards(self):
        live = self.service.lookup({"query": "knoppers", "source": "open_food_facts"})
        local = self.service.lookup({"query": "knoppers", "source": "open_food_facts"})

        self.assertEqual(live["foods"][0]["data_origin"], "live")
        self.assertEqual(local["foods"][0]["data_origin"], "local_database")
        self.assertEqual(self.off.calls, [("search", "knoppers")])

    def test_resolve_uses_the_mirror_without_calling_online(self):
        self.mirror.store([food()])

        resolved = self.service.resolve(f"off:{BARCODE}")

        self.assertEqual(resolved["name"], "Haselnuss Riegel")
        self.assertNotIn("fetched_at", resolved)
        self.assertEqual(self.off.calls, [])

    def test_reference_database_is_unaffected_by_the_mirror(self):
        result = self.service.lookup({"query": "Haferflocken"})

        self.assertTrue(result["foods"])
        self.assertNotIn("data_origin", result["foods"][0])
        self.assertEqual(self.off.calls, [])

    def test_stored_foods_and_forget_back_the_database_section(self):
        self.mirror.store([food()])

        listed = self.service.stored_foods()
        self.assertEqual([item["id"] for item in listed], [f"off:{BARCODE}"])
        self.assertEqual(listed[0]["data_origin"], "local_database")

        self.service.forget(f"off:{BARCODE}")
        self.assertEqual(self.service.stored_foods(), [])

    def test_service_without_a_mirror_keeps_working_online_only(self):
        service = FoodDatabaseService(cast(Any, self.off))

        result = service.lookup({"barcode": BARCODE})

        self.assertEqual(result["foods"][0]["data_origin"], "live")
        self.assertEqual(service.stored_foods(), [])
        with self.assertRaises(AppError):
            service.forget(f"off:{BARCODE}")


if __name__ == "__main__":
    unittest.main()
