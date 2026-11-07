"""The calendar sync button reads which explicit pushes a planned unit still needs."""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.canonical.vocabulary import RemoteEntityKind, RemoteLinkState
from backend.db import DatabaseManager, row_factory
from backend.db.remote_links import RemoteLink, RemoteLinkRepository
from backend.db.schema import initialize_schema
from backend.planning.push_state import (
    attach_push_state,
    garmin_baselines,
    garmin_fingerprint,
)
from backend.providers.garmin_strength_workout import catalogue_available

STRENGTH = {
    "sport": "WeightTraining",
    "date": "2026-11-09",
    "strength_structure": [{"name": "Kniebeuge", "sets": 3, "reps": 5}],
}
RIDE = {"sport": "Ride", "date": "2026-11-09", "description": "- 30m 60%"}


# sha256 of json.dumps(STRENGTH), the raw stored payload string.
STRENGTH_PAYLOAD_HASH = (
    "ceca587e328bdd0d119e9bc7a7ea56d3e82f5a7b7d01f900c18dadeb3f0d8dae"
)


class PushStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.manager = DatabaseManager(
            Path(self.directory.name) / "push.sqlite", sqlite3, row_factory=row_factory
        )
        with self.manager.unit_of_work() as db:
            initialize_schema(db)

    def tearDown(self) -> None:
        self.manager.close()
        self.directory.cleanup()

    def project(self, rows: list[dict]) -> list[dict]:
        pairs = [(row, json.loads(row["payload"])) for row in rows]
        with self.manager.reader() as db:
            attach_push_state(pairs, garmin_baselines(db))
        return [payload for _row, payload in pairs]

    def link(self, local_id: str, baseline: str) -> None:
        with self.manager.unit_of_work() as db:
            RemoteLinkRepository().upsert(
                db,
                RemoteLink(
                    entity_kind=RemoteEntityKind.PLANNED_UNIT,
                    local_id=local_id,
                    provider="garmin",
                    sync_state=RemoteLinkState.SYNCED,
                    remote_id="501",
                    baseline_hash=baseline,
                ),
            )

    def test_each_unit_carries_its_push_hash_and_pending_targets(self) -> None:
        strength, ride = json.dumps(STRENGTH), json.dumps(RIDE)
        projected = self.project(
            [
                {"local_id": "s1", "payload": strength, "sync_state": "local"},
                {"local_id": "r1", "payload": ride, "sync_state": "synced"},
            ]
        )
        self.assertEqual(STRENGTH_PAYLOAD_HASH, projected[0]["payload_hash"])
        self.assertEqual(
            {"intervals": True, "garmin": True}, projected[0]["push_pending"]
        )
        # Endurance units never offer Garmin; a synced unit needs no Intervals push.
        self.assertEqual({"intervals": False}, projected[1]["push_pending"])

    def test_garmin_is_pending_until_its_content_was_pushed(self) -> None:
        raw = json.dumps(STRENGTH)
        self.link("s1", garmin_fingerprint(STRENGTH) or "")
        current = self.project(
            [{"local_id": "s1", "payload": raw, "sync_state": "synced"}]
        )
        self.assertEqual(
            {"intervals": False, "garmin": False}, current[0]["push_pending"]
        )
        # An Intervals.icu sync rewrites the payload but not what Garmin holds.
        synced = json.dumps(
            {**STRENGTH, "sync_status": "synced", "remote_event_id": "e1"}
        )
        after_intervals = self.project(
            [{"local_id": "s1", "payload": synced, "sync_state": "synced"}]
        )
        self.assertEqual(
            {"intervals": False, "garmin": False}, after_intervals[0]["push_pending"]
        )
        for changed in (
            {**STRENGTH, "name": "Neu"},
            {**STRENGTH, "date": "2026-11-10"},
            {
                **STRENGTH,
                "strength_structure": [{"name": "Kniebeuge", "sets": 4, "reps": 5}],
            },
        ):
            with self.subTest(changed=changed):
                projected = self.project(
                    [
                        {
                            "local_id": "s1",
                            "payload": json.dumps(changed),
                            "sync_state": "synced",
                        }
                    ]
                )
                self.assertTrue(projected[0]["push_pending"]["garmin"])

    def test_a_conflicted_unit_offers_no_provider(self) -> None:
        conflicted = self.project(
            [
                {
                    "local_id": "s4",
                    "payload": json.dumps(STRENGTH),
                    "sync_state": "conflict",
                }
            ]
        )
        self.assertEqual(
            {"intervals": False, "garmin": False}, conflicted[0]["push_pending"]
        )

    @unittest.skipUnless(catalogue_available(), "garminconnect is not installed")
    def test_an_unmapped_exercise_offers_no_garmin_push(self) -> None:
        unmapped = json.dumps(
            {
                **STRENGTH,
                "strength_structure": [
                    {"name": "Copenhagen Plank", "sets": 2, "reps": 8}
                ],
            }
        )
        projected = self.project(
            [{"local_id": "s5", "payload": unmapped, "sync_state": "synced"}]
        )
        self.assertEqual({"intervals": False}, projected[0]["push_pending"])
        self.assertEqual({"garmin": "unmapped"}, projected[0]["push_blocked"])

    def test_an_invalid_structure_offers_no_garmin_push(self) -> None:
        invalid = json.dumps({**STRENGTH, "strength_structure": [{"name": ""}]})
        projected = self.project(
            [{"local_id": "s3", "payload": invalid, "sync_state": "synced"}]
        )
        self.assertEqual({"intervals": False}, projected[0]["push_pending"])
        self.assertEqual({"garmin": "no_structure"}, projected[0]["push_blocked"])

    def test_free_text_strength_says_why_garmin_is_blocked(self) -> None:
        free_text = json.dumps(
            {
                "sport": "WeightTraining",
                "date": "2026-11-09",
                "description": "Face Pulls: 4 Sätze",
            }
        )
        projected = self.project(
            [
                {"local_id": "s6", "payload": free_text, "sync_state": "local"},
                {"local_id": "r1", "payload": json.dumps(RIDE), "sync_state": "local"},
            ]
        )
        self.assertEqual({"intervals": True}, projected[0]["push_pending"])
        self.assertEqual({"garmin": "no_structure"}, projected[0]["push_blocked"])
        self.assertEqual({}, projected[1]["push_blocked"])

    def test_conflicts_and_strength_without_structure_offer_nothing_extra(self) -> None:
        bare = json.dumps({**STRENGTH, "strength_structure": None})
        projected = self.project(
            [{"local_id": "s2", "payload": bare, "sync_state": "conflict"}]
        )
        self.assertEqual({"intervals": False}, projected[0]["push_pending"])


if __name__ == "__main__":
    unittest.main()
