import copy
import unittest

from backend.calendar.canonical import ISO_MIDNIGHT_SUFFIX, canonical_planned_workouts


class CanonicalPlannedWorkoutsTests(unittest.TestCase):
    def test_constants_match_server_contract(self):
        self.assertEqual(ISO_MIDNIGHT_SUFFIX, "T00:00:00")

    def test_local_entry_keeps_its_fields_and_identity(self):
        local = {
            "id": "local-1",
            "date": "2026-09-16",
            "name": "Local name",
            "sport": "Ride",
            "remote_event_id": "remote-1",
            "remote_event_external_id": "external-1",
            "sync_status": "synced",
        }

        result = canonical_planned_workouts([local])

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "Local name")
        self.assertEqual(result[0]["id"], "remote-1")
        self.assertEqual(result[0]["local_id"], "local-1")
        self.assertEqual(result[0]["remote_id"], "remote-1")
        self.assertEqual(result[0]["external_id"], "external-1")
        self.assertEqual(result[0]["starts_at_local"], "2026-09-16T00:00:00")
        self.assertEqual(result[0]["sync_source"], "local")
        self.assertEqual(result[0]["sync_status"], "synced")
        self.assertTrue(result[0]["is_local"])
        self.assertFalse(result[0]["is_remote"])

    def test_local_status_defaults_and_is_kept(self):
        local = [
            {"id": "local-new", "date": "2026-09-17"},
            {"id": "local-dirty", "sync_status": "dirty", "date": "2026-09-18"},
            {"id": "local-conflict", "sync_status": "conflict", "date": "2026-09-19"},
        ]

        by_local_id = {
            item["local_id"]: item for item in canonical_planned_workouts(local)
        }

        self.assertEqual(by_local_id["local-new"]["sync_status"], "local")
        self.assertEqual(by_local_id["local-dirty"]["sync_status"], "dirty")
        self.assertEqual(by_local_id["local-conflict"]["sync_status"], "conflict")

    def test_no_remote_compliance_is_copied(self):
        local = [{"id": "local-linked", "date": "2026-09-20", "remote_event_id": "r"}]

        (item,) = canonical_planned_workouts(local)

        self.assertNotIn("compliance", item)

    def test_sorting_uses_start_name_and_identity_with_stable_ties(self):
        local = [
            {"id": "local-no-date", "name": "zulu"},
            {"id": "local-b", "date": "2026-09-22", "name": "alpha"},
            {"id": "local-a", "date": "2026-09-22", "name": "ALPHA"},
            {"id": "local-late", "date": "2026-09-23", "name": "first"},
            {"id": "local-date", "date": "2026-09-21", "name": "bravo"},
        ]

        result = canonical_planned_workouts(local)

        self.assertEqual(
            [item["local_id"] for item in result],
            ["local-date", "local-a", "local-b", "local-late", "local-no-date"],
        )

    def test_malformed_and_non_dict_rows_are_ignored(self):
        result = canonical_planned_workouts(
            [None, "local", 3, ["nested"], {"id": "valid-local", "date": "2026-09-24"}]
        )

        self.assertEqual([item["local_id"] for item in result], ["valid-local"])

    def test_limit_is_clamped_to_one_and_one_thousand(self):
        rows = [
            {"id": f"local-{index:04d}", "date": f"2026-10-{(index % 28) + 1:02d}"}
            for index in range(1005)
        ]

        self.assertEqual(len(canonical_planned_workouts(rows, limit=-10)), 1)
        self.assertEqual(len(canonical_planned_workouts(rows, limit=0)), 1)
        self.assertEqual(len(canonical_planned_workouts(rows, limit=10)), 10)
        self.assertEqual(len(canonical_planned_workouts(rows, limit=5000)), 1000)

    def test_inputs_are_not_mutated(self):
        local = [{"id": "local-1", "date": "2026-09-25", "meta": {"source": "fixture"}}]
        before = copy.deepcopy(local)

        canonical_planned_workouts(local)

        self.assertEqual(local, before)


if __name__ == "__main__":
    unittest.main()
