import hashlib
import json
import unittest
from copy import deepcopy

from backend.planning import competitions


class PlanningCompetitionSyncPlanTests(unittest.TestCase):
    def test_remote_indexes_and_match_priority(self) -> None:
        id_event = {
            "id": "remote-id",
            "external_id": "shared-external",
            "name": "Different Remote Name",
            "start_date_local": "2026-10-04T09:00:00",
            "type": "Ride",
        }
        external_event = {
            "id": "remote-external",
            "external_id": "shared-external",
            "name": "External Match",
            "start_date_local": "2026-10-05T09:00:00",
            "type": "Run",
        }
        identity_event = {
            "id": "remote-identity",
            "external_id": "identity-external",
            "name": "Fall Race",
            "start_date_local": "2026-10-04T08:00:00",
            "type": "Ride",
        }
        by_external, by_id, by_identity = competitions.competition_remote_indexes(
            [id_event, external_event, identity_event]
        )

        self.assertIs(by_external["shared-external"], external_event)
        self.assertIs(by_id["remote-id"], id_event)
        self.assertIs(by_identity[("fall race", "2026-10-04", "Ride")], identity_event)

        row = {
            "id": "local-id-priority",
            "intervals_event_id": "remote-id",
            "external_id": "shared-external",
            "name": "Fall Race",
            "event_date": "2026-10-04",
            "sport": "Cycling",
        }
        remote, identity_remote = competitions.competition_remote_match(
            row, by_external, by_id, by_identity
        )
        self.assertIs(remote, id_event)
        self.assertIsNone(identity_remote)

        row.pop("intervals_event_id")
        remote, identity_remote = competitions.competition_remote_match(
            row, by_external, by_id, by_identity
        )
        self.assertIs(remote, external_event)
        self.assertIs(identity_remote, identity_event)

        row["intervals_event_id"] = "missing-id"
        remote, identity_remote = competitions.competition_remote_match(
            row, by_external, by_id, by_identity
        )
        self.assertIs(remote, external_event)
        self.assertIsNone(identity_remote)

        row.pop("intervals_event_id")
        row.pop("external_id")
        remote, identity_remote = competitions.competition_remote_match(
            row, by_external, by_id, by_identity
        )
        self.assertIs(remote, identity_event)
        self.assertIs(identity_remote, identity_event)

    def test_identity_conflict_local_override_and_missing_remote(self) -> None:
        remote_event = {
            "id": "remote-identity",
            "name": "Fall Race",
            "start_date_local": "2026-10-04T00:00:00",
            "type": "Ride",
        }
        indexes = competitions.competition_remote_indexes([remote_event])
        row = {
            "id": "local-race",
            "name": "Fall Race",
            "event_date": "2026-10-04",
            "sport": "Cycling",
            "sync_dirty": 1,
        }

        payload, action = competitions.competition_dirty_row_action(row, *indexes)
        self.assertIsNone(payload)
        self.assertEqual(action["type"], "conflict")
        self.assertEqual(action["reason"], "remote_identity_changed")
        self.assertEqual(action["remote_id"], "remote-identity")

        override = {**row, "sync_state": "local_override"}
        payload, action = competitions.competition_dirty_row_action(override, *indexes)
        self.assertEqual(payload["name"], "Fall Race")
        self.assertEqual(action["type"], "change")
        self.assertEqual(action["remote_id"], "remote-identity")

        missing = {**row, "intervals_event_id": "remote-gone"}
        payload, action = competitions.competition_dirty_row_action(missing, *indexes)
        self.assertIsNone(payload)
        self.assertEqual(action["type"], "conflict")
        self.assertEqual(action["reason"], "remote_missing")
        self.assertEqual(action["remote_id"], "remote-gone")

    def test_create_change_unsupported_sport_tombstones_and_summary(self) -> None:
        local_rows = [
            {
                "id": "new-race",
                "name": "New Race",
                "event_date": "2026-10-06",
                "sport": "Running",
                "sync_dirty": 1,
            },
            {
                "id": "changed-race",
                "intervals_event_id": "remote-changed",
                "name": "Changed Race",
                "event_date": "2026-10-07",
                "sport": "Cycling",
                "sync_dirty": 1,
            },
            {
                "id": "unsupported-race",
                "name": "Unsupported Race",
                "event_date": "2026-10-08",
                "sport": "Swimming",
                "sync_dirty": 1,
            },
            {
                "id": "clean-race",
                "name": "Clean Race",
                "event_date": "2026-10-09",
                "sport": "Running",
                "sync_dirty": 0,
            },
        ]
        tombstones = [
            {"intervals_event_id": 731, "external_id": "ignored-external"},
            {"external_id": "deleted-external"},
            {"id": "without-identifier"},
        ]
        remote_events = [
            {
                "id": "remote-changed",
                "name": "Remote Name",
                "start_date_local": "2026-10-07T08:00:00",
                "type": "Ride",
            }
        ]
        originals = deepcopy((local_rows, tombstones, remote_events))

        plan = competitions.competition_sync_plan(local_rows, tombstones, remote_events)

        self.assertEqual(
            [action["type"] for action in plan["actions"]],
            ["create", "change", "delete", "delete"],
        )
        self.assertEqual(
            [payload["name"] for payload in plan["outbound"]],
            ["New Race", "Changed Race"],
        )
        self.assertEqual(
            plan["delete_identifiers"],
            [{"id": 731}, {"external_id": "deleted-external"}],
        )
        self.assertEqual(plan["dirty_count"], 3)
        self.assertEqual(plan["skipped"], 1)
        self.assertEqual(
            plan["summary"],
            {"create": 1, "change": 1, "delete": 2, "conflict": 0},
        )
        self.assertEqual(plan["actions"][0]["local_id"], "new-race")
        self.assertEqual(plan["actions"][1]["remote_id"], "remote-changed")
        for action, payload in zip(plan["actions"][:2], plan["outbound"]):
            expected_hash = hashlib.sha256(
                json.dumps(
                    payload,
                    sort_keys=True,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(action["payload_hash"], expected_hash)
        self.assertIs(plan["remote_events"], remote_events)
        self.assertIs(plan["remote_by_id"]["remote-changed"], remote_events[0])
        self.assertEqual((local_rows, tombstones, remote_events), originals)

    def test_plan_summary_counts_conflicts_and_skipped_rows(self) -> None:
        identity_event = {
            "id": "remote-identity",
            "name": "Identity Conflict",
            "start_date_local": "2026-10-04T00:00:00",
            "type": "Ride",
        }
        local_rows = [
            {
                "id": "identity-conflict",
                "name": "Identity Conflict",
                "event_date": "2026-10-04",
                "sport": "Cycling",
                "sync_dirty": 1,
            },
            {
                "id": "missing-conflict",
                "intervals_event_id": "remote-gone",
                "name": "Missing Conflict",
                "event_date": "2026-10-05",
                "sport": "Running",
                "sync_dirty": 1,
            },
            {
                "id": "unsupported",
                "name": "Unsupported",
                "event_date": "2026-10-06",
                "sport": "Swimming",
                "sync_dirty": 1,
            },
        ]

        plan = competitions.competition_sync_plan(local_rows, [], [identity_event])

        self.assertEqual(
            [action["reason"] for action in plan["actions"]],
            ["remote_identity_changed", "remote_missing"],
        )
        self.assertEqual(
            plan["summary"],
            {"create": 0, "change": 0, "delete": 0, "conflict": 2},
        )
        self.assertEqual(plan["dirty_count"], 3)
        self.assertEqual(plan["skipped"], 1)

    def test_remote_signature_and_fingerprint_are_sorted_and_deterministic(
        self,
    ) -> None:
        first = {
            "id": "2",
            "external_id": "second",
            "name": "Second Race",
            "type": "Run",
            "description": "Second",
            "ignored": "not in signature",
        }
        second = {
            "id": "1",
            "external_id": "first",
            "name": "First Race",
            "type": "Ride",
            "description": "First",
        }
        remote_events = [first, second]
        original = deepcopy(remote_events)

        signature = competitions.competition_remote_signature(remote_events)
        forward = competitions.competition_sync_plan([], [], remote_events)
        reverse = competitions.competition_sync_plan(
            [], [], list(reversed(remote_events))
        )

        self.assertEqual([event["id"] for event in signature], ["1", "2"])
        self.assertEqual(
            set(signature[0]),
            {
                "id",
                "external_id",
                "name",
                "start_date_local",
                "type",
                "category",
                "distance",
                "moving_time",
                "target",
                "description",
            },
        )
        self.assertEqual(forward["fingerprint"], reverse["fingerprint"])
        self.assertIs(forward["remote_events"], remote_events)
        self.assertEqual(remote_events, original)


if __name__ == "__main__":
    unittest.main()
