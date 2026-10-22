"""Per-element Garmin rows: identity, delta writes, windowed pruning and the read view.

Temporary SQLite only. No Garmin account or token is used.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from backend.canonical.garmin_payload import ITEM_SECTIONS, SECTIONS
from backend.canonical.section_items import (
    assemble_section,
    merge_records,
    record_id,
    split_section,
)
from backend.db import garmin_store
from backend.db.schema import initialize_schema

NOW = "2026-10-10T08:00:00+00:00"
FETCHED = "2026-10-10T07:00:00+00:00"


def days(*values: str) -> list[dict[str, Any]]:
    return [
        {"calendarDate": value, "score": index} for index, value in enumerate(values)
    ]


class SectionItemTests(unittest.TestCase):
    def test_identity_prefers_the_provider_id_and_falls_back_to_a_digest(self) -> None:
        keys = [
            item.key
            for item in split_section(
                [{"id": 7}, {"gearUUID": "g-1"}, {"calendarDate": "2026-10-01"}]
            )
        ]
        self.assertEqual(keys, ["7", "g-1", "2026-10-01"])
        digest = split_section([{"note": "x"}])[0].key
        self.assertTrue(digest.startswith("~"))
        self.assertEqual(digest, split_section([{"note": "x"}])[0].key)

    def test_duplicate_keys_stay_separate_elements(self) -> None:
        items = split_section([{"id": 1, "a": 1}, {"id": 1, "a": 2}])
        self.assertEqual(len({item.key for item in items}), 2)
        self.assertEqual(
            assemble_section(items), [{"id": 1, "a": 1}, {"id": 1, "a": 2}]
        )

    def test_merge_keeps_the_incoming_element_over_the_stored_one(self) -> None:
        merged = merge_records(
            [{"calendarDate": "2026-10-01", "v": 2}],
            [{"calendarDate": "2026-10-01", "v": 1}, {"calendarDate": "2026-09-30"}],
        )
        self.assertEqual(merged[0]["v"], 2)
        self.assertEqual(len(merged), 2)


class GarminStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.db = sqlite3.connect(Path(self.temporary.name) / "store.db")
        self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        initialize_schema(self.db)

    def put(self, section: str, value: Any, *, replace: bool = False):
        return garmin_store.put_section(
            self.db,
            section,
            split_section(value),
            fetched_at=FETCHED,
            now=NOW,
            mapper_version=1,
            replace=replace,
        )

    def test_a_repeated_write_changes_no_row_and_a_delta_writes_only_itself(
        self,
    ) -> None:
        first = self.put("sleep", days("2026-10-01", "2026-10-02"))
        self.assertEqual((first.written, first.changed), (2, 2))
        again = self.put("sleep", days("2026-10-01", "2026-10-02"))
        self.assertEqual((again.unchanged, again.changed), (2, 0))
        delta = self.put("sleep", days("2026-10-01", "2026-10-02", "2026-10-03")[2:])
        self.assertEqual(delta.changed, 1)
        self.assertEqual(
            len(garmin_store.read_sections(self.db, {"sleep"})["sleep"]), 3
        )

    def test_a_replacing_write_drops_missing_elements_but_an_empty_one_clears_nothing(
        self,
    ) -> None:
        self.put("sleep", days("2026-10-01", "2026-10-02"))
        self.assertEqual(self.put("sleep", [], replace=True).removed, 0)
        removed = self.put("sleep", days("2026-10-02"), replace=True).removed
        self.assertEqual(removed, 1)

    def test_windowed_pruning_keeps_elements_outside_the_window(self) -> None:
        self.put("sleep", days("2026-09-01", "2026-10-01", "2026-10-05"))
        keep = {record_id("sleep", "2026-10-05")}
        removed = garmin_store.prune_section(
            self.db, "sleep", keep, start="2026-10-01", end="2026-10-07"
        )
        self.assertEqual(removed, 1)
        view = garmin_store.read_sections(self.db, {"sleep"})["sleep"]
        self.assertEqual(
            sorted(item["calendarDate"] for item in view), ["2026-09-01", "2026-10-05"]
        )

    def test_the_view_loads_only_the_requested_window_and_state_is_separate(
        self,
    ) -> None:
        self.put("sleep", days("2026-09-01", "2026-10-05"))
        garmin_store.write_state(
            self.db, {"synced_at": FETCHED, "note": "kept"}, now=NOW
        )
        view = garmin_store.read_view(
            self.db, {"sleep"}, start="2026-10-01", end="2026-10-10"
        )
        self.assertEqual(
            [item["calendarDate"] for item in view["sleep"]], ["2026-10-05"]
        )
        self.assertEqual(view["note"], "kept")
        self.assertEqual(garmin_store.read_state(self.db)["note"], "kept")

    def test_every_item_section_is_a_known_section(self) -> None:
        self.assertLessEqual(ITEM_SECTIONS, SECTIONS)


if __name__ == "__main__":
    unittest.main()
