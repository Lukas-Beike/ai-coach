"""Season preparation inputs: read only from the tables, without snapshot sections."""

from __future__ import annotations

import unittest
from datetime import date
from typing import Any

from canonical_read_support import CanonicalReadFixture, make_selector, populate

from backend.performance.season_inputs import (
    SeasonSource,
    read_activity_summaries,
)
from backend.planning.season_preparation import season_preparation

ZONE = "Europe/Berlin"
# The fixture wellness rows end on 2026-10-10; the first falls on 2026-10-08.
TODAY = date(2026, 10, 9)
EVENT = {
    "id": "race",
    "event_date": "2026-10-20",
    "sport": "Cycling",
    "priority": "A",
    "name": "Synthetic race",
}


class SeasonCanonicalReadTests(CanonicalReadFixture):
    def _source(self, selector: Any) -> SeasonSource:
        return SeasonSource(
            database_manager=lambda: self.manager,
            observation_reader=lambda: selector,
            activity_summaries=lambda: selector,
        )

    def _season(self, selector: Any, snapshot: dict[str, Any]) -> dict[str, Any]:
        source = self._source(selector)
        with self.manager.unit_of_work() as db:
            return season_preparation(
                [EVENT],
                TODAY,
                ZONE,
                activity_summaries=lambda start, end: read_activity_summaries(
                    source, db, start, end
                ),
            )

    def _tables(self) -> Any:
        populate(self)
        selector = make_selector(self)
        self.assertTrue(self.write(selector.serves_tables))
        return selector

    def test_season_reads_nothing_until_the_tables_serve(self) -> None:
        pending_selector = make_selector(self)
        self.assertFalse(self.write(pending_selector.serves_tables))
        pending = self._season(pending_selector, self.intervals)
        self.assertEqual(
            "insufficient_data", pending["events"][0]["preparation"]["status"]
        )
        served = self._season(self._tables(), self.intervals)
        self.assertEqual("observations", served["events"][0]["preparation"]["status"])

    def test_season_does_not_need_the_snapshot_activity_sections(self) -> None:
        selector = self._tables()
        stripped = {"synced_at": self.intervals["synced_at"]}
        self.assertEqual(
            self._season(selector, stripped), self._season(selector, self.intervals)
        )


if __name__ == "__main__":
    unittest.main()
