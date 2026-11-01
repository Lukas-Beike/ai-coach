"""Season preparation inputs: read only from the tables, without snapshot sections."""

from __future__ import annotations

import unittest
from datetime import date
from typing import Any

from canonical_read_support import CanonicalReadFixture, make_selector, populate

from backend.activities.activity_summary import stored_activity_key
from backend.performance.season_inputs import (
    SeasonSource,
    read_activity_summaries,
    read_season_load_inputs,
)
from backend.planning.season_preparation import load_scenarios, season_preparation

ZONE = "Europe/Berlin"
# The fixture wellness rows end on 2026-10-10; the first falls on 2026-10-08.
TODAY = date(2026, 10, 9)
ACTIVITY_DAY = date(2026, 10, 8)
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
                snapshot.get("synced_at"),
                [EVENT],
                TODAY,
                ZONE,
                activity_summaries=lambda start, end: read_activity_summaries(
                    source, db, start, end
                ),
            )

    def _scenarios(
        self, selector: Any, snapshot: dict[str, Any], today: date
    ) -> dict[str, Any]:
        source = self._source(selector)
        with self.manager.unit_of_work() as db:
            inputs = read_season_load_inputs(source, db, today=today, timezone=ZONE)
            return load_scenarios(
                snapshot.get("synced_at"),
                {},
                today,
                {"end": "2026-10-20"},
                inputs=inputs,
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

    def test_scenarios_read_the_load_basis_only_from_the_tables(self) -> None:
        pending_selector = make_selector(self)
        self.assertFalse(self.write(pending_selector.serves_tables))
        pending = self._scenarios(pending_selector, self.intervals, TODAY)["basis"]
        self.assertEqual((None, None), (pending["ctl"], pending["atl"]))
        selector = self._tables()
        basis = self._scenarios(selector, self.intervals, TODAY)["basis"]
        self.assertEqual(
            ("2026-10-08", 52.1, 60.4), (basis["as_of"], basis["ctl"], basis["atl"])
        )

    def test_scenarios_do_not_need_the_snapshot_wellness_or_activities(self) -> None:
        selector = self._tables()
        stripped = {"synced_at": self.intervals["synced_at"]}
        for today in (TODAY, ACTIVITY_DAY):
            with self.subTest(today=today):
                self.assertEqual(
                    self._scenarios(selector, stripped, today),
                    self._scenarios(selector, self.intervals, today),
                )

    def test_activities_completed_today_come_from_the_rows(self) -> None:
        selector = self._tables()
        source = self._source(selector)
        with self.manager.unit_of_work() as db:
            inputs = read_season_load_inputs(
                source, db, today=ACTIVITY_DAY, timezone=ZONE
            )
        self.assertEqual(
            ["i-act-001"], [stored_activity_key(row) for row in inputs.completed_today]
        )


if __name__ == "__main__":
    unittest.main()
