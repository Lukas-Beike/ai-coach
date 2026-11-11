"""The calendar sync button reads which explicit pushes a planned unit still needs."""

from __future__ import annotations

import hashlib
import json
import unittest
from datetime import date
from typing import Any

from support import temp_database

from backend.canonical.vocabulary import RemoteEntityKind, RemoteLinkState
from backend.db import row_factory
from backend.db.remote_links import RemoteLink, RemoteLinkRepository
from backend.planning import strength_structure
from backend.planning.exercise_mappings import remembered_exercises
from backend.planning.garmin_orphans import GarminOrphan
from backend.planning.intervals_orphans import IntervalsOrphan
from backend.planning.push_state import (
    attach_push_state,
    garmin_baselines,
    garmin_fingerprint,
)
from backend.planning.wahoo_orphans import WahooOrphan
from backend.providers.garmin_strength_workout import catalogue_available

STRENGTH = {
    "sport": "WeightTraining",
    "date": "2026-11-09",
    "strength_structure": [{"name": "Kniebeuge", "sets": 3, "reps": 5}],
}
RIDE = {"sport": "Ride", "date": "2026-11-09", "description": "- 30m 60%"}


# Content-only plan push hash of STRENGTH; sync fields never move it.
STRENGTH_PAYLOAD_HASH = (
    "5e4ddd5f874ce338d22c1445f4b633a742d8f3e5629cee7e5a337fb95dfecad4"
)


class PushStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = temp_database(
            self, "push.sqlite", row_factory=row_factory, schema=True
        )

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

    def test_leftovers_ride_on_a_unit_even_when_no_provider_waits(self) -> None:
        orphan = GarminOrphan("o1", "Alte Kraft", "2026-11-05")
        wahoo = WahooOrphan("w1")
        rows = [
            {"local_id": "r1", "payload": json.dumps(RIDE), "sync_state": "synced"},
            {
                "local_id": "r2",
                "payload": json.dumps({**RIDE, "date": "2026-11-12"}),
                "sync_state": "synced",
            },
        ]
        pairs = [(row, json.loads(row["payload"])) for row in rows]

        attach_push_state(
            pairs,
            {},
            orphans=[orphan],
            wahoo_orphans=[wahoo],
            today=date(2026, 11, 10),
        )

        self.assertNotIn("push_cleanup", pairs[0][1])
        self.assertEqual(
            {
                "garmin": [{"id": "o1", "name": "Alte Kraft", "date": "2026-11-05"}],
                "wahoo": [{"id": "w1", "name": wahoo.name, "date": ""}],
            },
            pairs[1][1]["push_cleanup"],
        )

    def test_a_deleted_unit_nearest_today_never_carries_the_leftovers(self) -> None:
        rows = [
            {
                "local_id": "gone",
                "payload": json.dumps(
                    {**RIDE, "date": "2026-11-10", "local_deleted": True}
                ),
                "sync_state": "synced",
            },
            {
                "local_id": "shown",
                "payload": json.dumps({**RIDE, "date": "2026-11-14"}),
                "sync_state": "synced",
            },
        ]
        pairs = [(row, json.loads(row["payload"])) for row in rows]

        attach_push_state(
            pairs,
            {},
            orphans=[GarminOrphan("o1", "Alte Kraft", "2026-11-05")],
            wahoo_orphans=[],
            today=date(2026, 11, 10),
        )

        self.assertNotIn("push_cleanup", pairs[0][1])
        self.assertIn("garmin", pairs[1][1]["push_cleanup"])

    def test_a_pending_unit_keeps_the_leftovers_instead_of_a_second_carrier(
        self,
    ) -> None:
        rows = [
            {"local_id": "r1", "payload": json.dumps(RIDE), "sync_state": "synced"},
            {
                "local_id": "r2",
                "payload": json.dumps({**RIDE, "date": "2026-11-12"}),
                "sync_state": "local",
            },
        ]
        pairs = [(row, json.loads(row["payload"])) for row in rows]

        attach_push_state(
            pairs,
            {},
            intervals_orphans=[IntervalsOrphan("i1", "Alt", "2026-11-11", "h")],
            today=date(2026, 11, 10),
        )

        self.assertEqual(
            [False, True], ["push_cleanup" in payload for _row, payload in pairs]
        )

    @unittest.skipUnless(catalogue_available(), "garminconnect is not installed")
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

    def test_a_strength_event_not_sent_as_a_note_is_pending_again(self) -> None:
        # A strength unit sent before #1807 is a WORKOUT event that Intervals.icu
        # forwards to Garmin; no category was recorded then (#2185).
        sent = {**STRENGTH, "remote_event_id": "e1"}
        cases = [
            (sent, True),
            ({**sent, "remote_event_category": "WORKOUT"}, True),
            ({**sent, "remote_event_category": "NOTE"}, False),
            ({**RIDE, "remote_event_id": "e2"}, False),
            ({**RIDE, "remote_event_id": "e2", "remote_event_category": "NOTE"}, True),
            (STRENGTH, False),
        ]
        projected = self.project(
            [
                {
                    "local_id": f"u{index}",
                    "payload": json.dumps(payload),
                    "sync_state": "synced",
                }
                for index, (payload, _pending) in enumerate(cases)
            ]
        )
        self.assertEqual(
            [pending for _payload, pending in cases],
            [unit["push_pending"]["intervals"] for unit in projected],
        )

    @unittest.skipUnless(catalogue_available(), "garminconnect is not installed")
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

    @unittest.skipUnless(catalogue_available(), "garminconnect is not installed")
    def test_a_unit_sent_in_the_gram_weight_form_is_pending_again(self) -> None:
        # The baseline an earlier release stored: the same content without a
        # payload version, spelled out here instead of derived from the code.
        content = {
            "name": "",
            "date": STRENGTH["date"][:10],
            "exercises": strength_structure.normalize_structure(
                STRENGTH["strength_structure"]
            ),
        }
        legacy = hashlib.sha256(
            json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        self.link("s1", legacy)

        projected = self.project(
            [
                {
                    "local_id": "s1",
                    "payload": json.dumps(STRENGTH),
                    "sync_state": "synced",
                }
            ]
        )

        self.assertNotEqual(legacy, garmin_fingerprint(STRENGTH))
        self.assertTrue(projected[0]["push_pending"]["garmin"])

    @unittest.skipUnless(catalogue_available(), "garminconnect is not installed")
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

    @unittest.skipUnless(catalogue_available(), "garminconnect is not installed")
    def test_a_confirmed_exercise_is_remembered_for_other_units(self) -> None:
        confirmed: dict[str, Any] = {
            **STRENGTH,
            "strength_structure": [
                {
                    "name": "Kabelrudern eng",
                    "sets": 3,
                    "reps": 10,
                    "garmin_exercise": "V-grip Cable Row",
                    "garmin_pair": {"category": "ROW", "exercise": "V_GRIP_CABLE_ROW"},
                }
            ],
        }
        later = {
            **STRENGTH,
            "date": "2026-11-16",
            "strength_structure": [{"name": "Kabelrudern  eng", "sets": 4, "reps": 8}],
        }
        with self.manager.unit_of_work() as db:
            wrong = {
                **confirmed,
                "strength_structure": [
                    {
                        **confirmed["strength_structure"][0],
                        "garmin_exercise": "Seated Cable Row",
                        "garmin_pair": {
                            "category": "ROW",
                            "exercise": "SEATED_CABLE_ROW",
                        },
                    }
                ],
            }
            for local_id, payload, tombstone in (
                ("c1", confirmed, 0),
                # A deleted or archived unit's confirmation does not count.
                ("c2", {**wrong, "local_deleted": True}, 0),
                ("c3", {**wrong, "archived": True}, 0),
                ("c4", wrong, 1),
            ):
                db.execute(
                    "INSERT INTO planned_units(id, local_id, payload, tombstone, "
                    "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (local_id, local_id, json.dumps(payload), tombstone, "t", local_id),
                )
        with self.manager.reader() as db:
            remembered = remembered_exercises(db)
        self.assertEqual(["kabelruderneng"], list(remembered))
        self.assertEqual("V-grip Cable Row", remembered["kabelruderneng"].name)
        rows = [{"local_id": "l1", "payload": json.dumps(later), "sync_state": "local"}]
        pairs = [(row, json.loads(row["payload"])) for row in rows]
        attach_push_state(pairs, {}, remembered)
        self.assertTrue(pairs[0][1]["push_pending"]["garmin"])
        self.assertEqual({}, pairs[0][1]["push_blocked"])
        attach_push_state(pairs, {})
        self.assertEqual({"garmin": "unmapped"}, pairs[0][1]["push_blocked"])

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
