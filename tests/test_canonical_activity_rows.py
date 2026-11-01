"""Raw activity rows: the table source, the selector route and the dedup helper."""

from __future__ import annotations

import copy
from datetime import date
from typing import Any
from unittest.mock import patch

from canonical_read_support import CanonicalReadFixture, make_selector, populate


def _by_id(rows: tuple[dict[str, Any], ...]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda row: str(row["id"]))


class ActivitySummarySourceTests(CanonicalReadFixture):
    def test_tables_return_the_raw_snapshot_rows(self) -> None:
        populate(self)
        table = self.read(self.table.activity_rows)

        self.assertTrue(table)
        self.assertEqual(
            _by_id(table),
            _by_id(tuple(self.intervals["raw_provider_data"]["activities"])),
        )

    def test_tables_serve_newest_first(self) -> None:
        populate(self)
        table_rows = self.read(self.table.activity_rows)
        self.assertEqual(
            [row["id"] for row in table_rows],
            ["i-act-005", "i-act-004", "i-act-001", "i-act-003", "i-act-002"],
        )
        starts = [
            self.rows(
                "SELECT started_at FROM activity_records WHERE provider_activity_id = ?",
                (row["id"],),
            )[0]["started_at"]
            for row in table_rows
        ]
        self.assertEqual(starts, sorted(starts, reverse=True))

    def test_date_bounds_filter_the_athlete_local_day(self) -> None:
        populate(self)
        for start, end, expected in (
            (date(2026, 10, 8), date(2026, 10, 8), ["i-act-001"]),
            (date(2026, 10, 1), None, ["i-act-001", "i-act-004", "i-act-005"]),
            (None, date(2026, 3, 30), ["i-act-002", "i-act-003"]),
            (date(2999, 1, 1), None, []),
        ):
            with self.subTest(start=start, end=end):
                table = self.read(self.table.activity_rows, start=start, end=end)
                self.assertEqual(sorted(row["id"] for row in table), expected)

    def test_deleted_and_invalid_records_are_not_served(self) -> None:
        populate(self)
        before = len(self.read(self.table.activity_rows))
        self.execute(
            "UPDATE activity_records SET state = 'deleted' "
            "WHERE provider_activity_id = 'i-act-001'"
        )
        after = self.read(self.table.activity_rows)
        self.assertEqual(len(after), before - 1)
        self.assertNotIn("i-act-001", [row["id"] for row in after])

        self.execute(
            "UPDATE provider_records SET state = 'deleted' "
            "WHERE source_record_id = 'i-act-002'"
        )
        self.assertNotIn(
            "i-act-002", [r["id"] for r in self.read(self.table.activity_rows)]
        )

        self.execute(
            "UPDATE activity_sessions SET state = 'deleted', merged_into = NULL"
        )
        self.assertEqual(self.read(self.table.activity_rows), ())

    def test_unparsable_and_non_object_payloads_are_skipped(self) -> None:
        texts = ["not json", "[1]", '{"id": "x"}', "null"]
        with patch(
            "backend.sync.canonical_table_reader.canonical_store."
            "active_activity_payload_texts",
            return_value=texts,
        ):
            rows = self.read(self.table.activity_rows)
        self.assertEqual(rows, ({"id": "x"},))


class ActivityRowSelectorTests(CanonicalReadFixture):
    def test_pending_backfill_serves_no_rows(self) -> None:
        selector = make_selector(self)
        self.assertEqual(self.read(selector.activity_rows), ())

    def test_complete_backfill_serves_table_rows(self) -> None:
        populate(self)
        selector = make_selector(self)
        # Change the stored snapshot so it differs from the tables.
        self.intervals = copy.deepcopy(self.intervals)
        self.intervals["raw_provider_data"]["activities"].pop()
        rows = self.read(selector.activity_rows)
        self.assertEqual(list(rows), list(self.read(self.table.activity_rows)))
        self.assertEqual(
            len(rows), len(self.intervals["raw_provider_data"]["activities"]) + 1
        )

    def test_complete_backfill_serves_table_rows_for_a_compact_only_snapshot(
        self,
    ) -> None:
        populate(self)
        selector = make_selector(self)
        self.intervals = copy.deepcopy(self.intervals)
        del self.intervals["raw_provider_data"]
        rows = self.read(selector.activity_rows)
        self.assertEqual(
            [row["id"] for row in rows],
            ["i-act-005", "i-act-004", "i-act-001", "i-act-003", "i-act-002"],
        )
        self.assertTrue(self.read(selector.activities_need_refresh))

    def test_complete_backfill_serves_tables_without_any_snapshot_rows(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.intervals = copy.deepcopy(self.intervals)
        del self.intervals["raw_provider_data"]
        del self.intervals["recent_activities"]
        rows = self.read(selector.activity_rows)
        self.assertEqual(list(rows), list(self.read(self.table.activity_rows)))
        self.assertTrue(rows)

    def test_selector_passes_bounds_to_the_active_source(self) -> None:
        populate(self)
        selector = make_selector(self)
        day = date(2026, 10, 8)
        self.assertEqual(
            [r["id"] for r in self.read(selector.activity_rows, start=day, end=day)],
            ["i-act-001"],
        )
