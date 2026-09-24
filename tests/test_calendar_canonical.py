import copy
import unittest

from backend.calendar.canonical import (
    ISO_MIDNIGHT_SUFFIX,
    LOCAL_INTERVALS_SCOPE,
    canonical_planned_workouts,
)


class CanonicalPlannedWorkoutsTests(unittest.TestCase):
    def test_constants_match_server_contract(self):
        self.assertEqual(ISO_MIDNIGHT_SUFFIX, "T00:00:00")
        self.assertEqual(LOCAL_INTERVALS_SCOPE, "local+intervals")

    def test_join_by_remote_id_preserves_local_fields_and_identity(self):
        remote = {
            "id": "remote-1",
            "external_id": "external-1",
            "name": "Remote name",
            "start_date_local": "2026-09-16T07:00:00",
            "compliance": {"status": "planned"},
        }
        local = {
            "id": "local-1",
            "date": "2026-09-16",
            "name": "Local name",
            "sport": "Ride",
            "remote_event_id": " remote-1 ",
            "sync_status": "synced",
        }

        result = canonical_planned_workouts([remote], [local])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Local name")
        self.assertEqual(result[0]["id"], "remote-1")
        self.assertEqual(result[0]["local_id"], "local-1")
        self.assertEqual(result[0]["remote_id"], "remote-1")
        self.assertEqual(result[0]["external_id"], "external-1")
        self.assertEqual(result[0]["sync_source"], LOCAL_INTERVALS_SCOPE)
        self.assertEqual(result[0]["sync_status"], "synced")
        self.assertEqual(result[0]["compliance"], remote["compliance"])

    def test_join_by_remote_external_id(self):
        remote = {"id": "remote-2", "external_id": "external-2", "name": "Remote"}
        local = {
            "id": "local-2",
            "date": "2026-09-17",
            "remote_event_external_id": " external-2 ",
        }

        result = canonical_planned_workouts([remote], [local])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["remote_id"], "remote-2")
        self.assertEqual(result[0]["external_id"], "external-2")
        self.assertTrue(result[0]["is_remote"])

    def test_dirty_and_conflict_local_status_overrides_stale_remote_state(self):
        remote = [
            {
                "id": "remote-dirty",
                "external_id": "external-dirty",
                "sync_status": "synced",
            },
            {
                "id": "remote-conflict",
                "external_id": "external-conflict",
                "sync_status": "synced",
            },
        ]
        local = [
            {
                "id": "local-dirty",
                "remote_event_id": "remote-dirty",
                "sync_status": "dirty",
                "date": "2026-09-18",
            },
            {
                "id": "local-conflict",
                "remote_event_id": "remote-conflict",
                "sync_status": "conflict",
                "date": "2026-09-19",
            },
        ]

        result = canonical_planned_workouts(remote, local)

        by_local_id = {item["local_id"]: item for item in result}
        self.assertEqual(by_local_id["local-dirty"]["sync_status"], "dirty")
        self.assertEqual(by_local_id["local-conflict"]["sync_status"], "conflict")

    def test_compliance_is_copied_only_from_the_linked_remote_event(self):
        remote = [
            {
                "id": "linked",
                "name": "same day",
                "start_date_local": "2026-09-20T07:00:00",
                "compliance": {"status": "completed"},
            },
            {
                "id": "unlinked",
                "name": "same day",
                "start_date_local": "2026-09-20T07:00:00",
                "compliance": {"status": "missed"},
            },
        ]
        local = [
            {"id": "local-linked", "date": "2026-09-20", "remote_event_id": "linked"},
            {"id": "local-unlinked", "date": "2026-09-20", "name": "same day"},
        ]

        result = canonical_planned_workouts(remote, local)

        linked = next(item for item in result if item.get("local_id") == "local-linked")
        unlinked = next(
            item for item in result if item.get("local_id") == "local-unlinked"
        )
        self.assertEqual(linked["compliance"], {"status": "completed"})
        self.assertNotIn("compliance", unlinked)
        self.assertEqual(sum(item.get("remote_id") == "unlinked" for item in result), 1)

    def test_unjoined_remote_events_remain_visible_and_local_is_source_of_truth(self):
        remote = [{"id": "remote-only", "name": "Remote only", "type": "Run"}]
        local = [
            {
                "id": "local-only",
                "name": "Local only",
                "date": "2026-09-21",
                "type": "Ride",
            }
        ]

        result = canonical_planned_workouts(remote, local)

        self.assertEqual(
            {item["name"] for item in result}, {"Remote only", "Local only"}
        )
        local_result = next(item for item in result if item["local_id"] == "local-only")
        remote_result = next(
            item for item in result if item["remote_id"] == "remote-only"
        )
        self.assertEqual(local_result["sync_source"], "local")
        self.assertEqual(local_result["sync_status"], "local")
        self.assertTrue(local_result["is_local"])
        self.assertFalse(remote_result["is_local"])
        self.assertEqual(remote_result["sync_source"], "intervals")
        self.assertEqual(remote_result["sync_status"], "remote")

    def test_sorting_uses_start_name_and_identity_with_stable_ties(self):
        remote = [
            {
                "id": "remote-b",
                "start_date_local": "2026-09-22T08:00:00",
                "name": "alpha",
            },
            {
                "id": "remote-a",
                "start_date_local": "2026-09-22T08:00:00",
                "name": "ALPHA",
            },
            {
                "id": "remote-late",
                "start_date_local": "2026-09-23T08:00:00",
                "name": "first",
            },
        ]
        local = [
            {"id": "local-no-date", "name": "zulu"},
            {"id": "local-date", "date": "2026-09-21", "name": "bravo"},
        ]

        result = canonical_planned_workouts(remote, local)

        self.assertEqual(
            [item.get("local_id") or item.get("remote_id") for item in result],
            [
                "local-date",
                "remote-a",
                "remote-b",
                "remote-late",
                "local-no-date",
            ],
        )

    def test_malformed_and_non_dict_rows_are_ignored(self):
        result = canonical_planned_workouts(
            [None, "remote", 3, ["nested"], {"id": "valid-remote"}],
            [None, "local", 3, ["nested"], {"id": "valid-local", "date": "2026-09-24"}],
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(
            {item.get("local_id") or item.get("remote_id") for item in result},
            {"valid-local", "valid-remote"},
        )

    def test_limit_is_clamped_to_one_and_one_thousand(self):
        rows = [
            {
                "id": f"remote-{index:04d}",
                "start_date_local": f"2026-10-{(index % 28) + 1:02d}",
            }
            for index in range(1005)
        ]

        self.assertEqual(len(canonical_planned_workouts(rows, [], limit=-10)), 1)
        self.assertEqual(len(canonical_planned_workouts(rows, [], limit=0)), 1)
        self.assertEqual(len(canonical_planned_workouts(rows, [], limit=10)), 10)
        self.assertEqual(len(canonical_planned_workouts(rows, [], limit=5000)), 1000)

    def test_inputs_are_not_mutated(self):
        remote = [{"id": "remote-1", "meta": {"source": "fixture"}}]
        local = [{"id": "local-1", "date": "2026-09-25", "meta": {"source": "fixture"}}]
        before_remote, before_local = copy.deepcopy(remote), copy.deepcopy(local)

        canonical_planned_workouts(remote, local)

        self.assertEqual(remote, before_remote)
        self.assertEqual(local, before_local)


if __name__ == "__main__":
    unittest.main()
