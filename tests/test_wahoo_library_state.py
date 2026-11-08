"""Wahoo sync state of library workouts: changed after an edit or a reference change."""

from __future__ import annotations

import json
import unittest
from typing import Any

from test_wahoo_plan_push import NOW, RIDE, W1, W2, PushCase

from backend.http_api.library_page import LibraryPageService
from backend.planning import library as planning_library
from backend.planning.library_service import WorkoutLibraryService
from backend.providers.wahoo_plan_mapping import WahooPlanReferences
from backend.sync.wahoo_library_state import WahooLibraryState
from backend.sync.wahoo_workout_export import WahooWorkoutExport

PERCENT = {**RIDE, "description": "- 10m 88%"}


class LibraryStateCase(PushCase):
    def setUp(self) -> None:
        super().setUp()
        self.references = {"ftp": 250}
        self.export = WahooWorkoutExport(
            lambda: self.wahoo,
            now=lambda: NOW,
            references=lambda sport: WahooPlanReferences(**self.references),
        )
        self.state = WahooLibraryState(
            configured=lambda: self.connected,
            database_manager=lambda: self.database_manager,
            export=lambda: self.export,
        )

    def rows(self) -> list[dict[str, Any]]:
        with self.database_manager.reader() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT local_id, payload FROM workout_library ORDER BY local_id"
                ).fetchall()
            ]

    def states(self) -> dict[str, dict[str, str]]:
        return self.state.states(self.rows())

    def edit(self, local_id: str, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload)
        with self.database_manager.unit_of_work() as db:
            db.execute(
                "UPDATE workout_library SET payload=? WHERE local_id=?",
                (raw, local_id),
            )
        return planning_library.library_payload_hash(raw)


class StateTests(LibraryStateCase):
    def test_a_workout_never_sent_has_no_wahoo_state(self) -> None:
        self.insert(W1, RIDE)

        self.assertEqual({}, self.states())

    def test_a_pushed_workout_is_synced(self) -> None:
        digest = self.insert(W1, PERCENT)
        self.push((W1, digest))

        self.assertEqual(
            {W1: {"state": "synced", "payload_hash": digest}}, self.states()
        )

    def test_an_ftp_change_marks_a_percent_workout_changed_until_re_pushed(
        self,
    ) -> None:
        digest = self.insert(W1, PERCENT)
        self.push((W1, digest))
        self.references["ftp"] = 280

        self.assertEqual("changed", self.states()[W1]["state"])

        self.push((W1, digest))

        self.assertEqual("synced", self.states()[W1]["state"])

    def test_an_ftp_change_leaves_an_absolute_workout_synced(self) -> None:
        digest = self.insert(W1, RIDE)
        self.push((W1, digest))
        self.references["ftp"] = 280

        self.assertEqual("synced", self.states()[W1]["state"])

    def test_editing_the_workout_text_marks_it_changed(self) -> None:
        digest = self.insert(W1, RIDE)
        self.push((W1, digest))
        edited = self.edit(W1, {**RIDE, "description": "- 20m 200W"})

        self.assertEqual(
            {"state": "changed", "payload_hash": edited}, self.states()[W1]
        )

    def test_another_providers_sync_does_not_mark_it_changed(self) -> None:
        digest = self.insert(W1, RIDE)
        self.push((W1, digest))
        self.edit(W1, {**RIDE, "sync_status": "synced", "external_id": "77"})

        self.assertEqual("synced", self.states()[W1]["state"])

    def test_a_workout_wahoo_cannot_take_any_more_counts_as_changed(self) -> None:
        digest = self.insert(W1, RIDE)
        self.push((W1, digest))
        self.edit(W1, {**RIDE, "description": "- 10m Z2"})

        self.assertEqual("changed", self.states()[W1]["state"])

    def test_reading_the_state_never_writes_to_wahoo(self) -> None:
        digest = self.insert(W1, PERCENT)
        self.push((W1, digest))
        self.references["ftp"] = 280
        writes = list(self.wahoo.writes())

        self.states()

        self.assertEqual(writes, self.wahoo.writes())

    def test_no_state_while_wahoo_is_not_connected(self) -> None:
        digest = self.insert(W1, RIDE)
        self.push((W1, digest))
        self.connected = False

        self.assertEqual({}, self.states())

    def test_each_workout_has_its_own_state(self) -> None:
        first = self.insert(W1, PERCENT)
        second = self.insert(W2, RIDE)
        self.push((W1, first), (W2, second))
        self.edit(W2, {**RIDE, "name": "Renamed"})

        self.assertEqual(
            {W1: "synced", W2: "changed"},
            {key: value["state"] for key, value in self.states().items()},
        )


class PageTests(LibraryStateCase):
    def test_the_library_page_carries_the_state_of_exported_workouts_only(
        self,
    ) -> None:
        named = {"sport": "ride", "name": "A"}
        digest = self.insert(W1, {**PERCENT, **named})
        self.insert(W2, {**RIDE, "sport": "ride", "name": "B"})
        self.push((W1, digest))
        self.edit(W1, {**PERCENT, **named, "description": "- 20m 90%"})
        library = WorkoutLibraryService(
            self.database_manager, lambda: "", lambda: "id", lambda: None
        )
        page = LibraryPageService(
            self.database_manager, library, wahoo_states=self.state.states
        )

        workouts = {item["name"]: item for item in page.page(limit=10)["workouts"]}

        self.assertEqual("changed", workouts["A"]["wahoo_state"]["state"])
        self.assertNotIn("wahoo_state", workouts["B"])


if __name__ == "__main__":
    unittest.main()
