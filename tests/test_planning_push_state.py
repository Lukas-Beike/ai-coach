"""The calendar sync button reads which explicit pushes a planned unit still needs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backend.canonical.vocabulary import RemoteEntityKind, RemoteLinkState
from backend.db import DatabaseManager, row_factory
from backend.db.remote_links import RemoteLink, RemoteLinkRepository
from backend.db.schema import initialize_schema
from backend.planning.push_state import attach_push_state, garmin_baselines

STRENGTH = {
    "sport": "WeightTraining",
    "date": "2026-11-09",
    "strength_structure": [{"name": "Kniebeuge", "sets": 3, "reps": 5}],
}
RIDE = {"sport": "Ride", "date": "2026-11-09", "description": "- 30m 60%"}


def _digest(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
        self.assertEqual(_digest(strength), projected[0]["payload_hash"])
        self.assertEqual(
            {"intervals": True, "garmin": True}, projected[0]["push_pending"]
        )
        # Endurance units never offer Garmin; a synced unit needs no Intervals push.
        self.assertEqual({"intervals": False}, projected[1]["push_pending"])

    def test_garmin_is_pending_until_the_current_payload_was_pushed(self) -> None:
        raw = json.dumps(STRENGTH)
        self.link("s1", _digest(raw))
        current = self.project(
            [{"local_id": "s1", "payload": raw, "sync_state": "synced"}]
        )
        self.assertEqual(
            {"intervals": False, "garmin": False}, current[0]["push_pending"]
        )
        edited = json.dumps({**STRENGTH, "name": "Neu"})
        changed = self.project(
            [{"local_id": "s1", "payload": edited, "sync_state": "local"}]
        )
        self.assertEqual(
            {"intervals": True, "garmin": True}, changed[0]["push_pending"]
        )

    def test_conflicts_and_strength_without_structure_offer_nothing_extra(self) -> None:
        bare = json.dumps({**STRENGTH, "strength_structure": None})
        projected = self.project(
            [{"local_id": "s2", "payload": bare, "sync_state": "conflict"}]
        )
        self.assertEqual({"intervals": False}, projected[0]["push_pending"])


if __name__ == "__main__":
    unittest.main()
