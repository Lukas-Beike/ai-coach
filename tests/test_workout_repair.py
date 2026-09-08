"""Real Coach/job execution with synthetic model and provider responses."""

from copy import deepcopy
import unittest
from unittest.mock import patch

from test_coach_dialogue import DialogueHarness, server
from test_server import parsed_workout_fixture


class WorkoutRepairTests(DialogueHarness, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.remote = {}
        self.mutations = []
        self.bad_parse = False
        self.fail_delete = False
        self.enterContext(patch.object(server, "http_json", side_effect=AssertionError("Unexpected live network")))
        self.enterContext(patch.object(server.IntervalsClient, "get_paged_collection", side_effect=lambda *a, **k: deepcopy(list(self.remote.values()))))
        self.enterContext(patch.object(server.IntervalsClient, "get", side_effect=server.AppError(404, "Synthetic missing event")))
        self.enterContext(patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=self.upsert))
        self.enterContext(patch.object(server.IntervalsClient, "delete_event", side_effect=self.delete))

    def upsert(self, payloads):
        results = []
        for payload in payloads:
            self.mutations.append(("upsert", deepcopy(payload)))
            identity = str(payload.get("id") or "new-synthetic-event")
            parsed = parsed_workout_fixture(4500, sport=payload["type"], kind="hr", units="hr_zone", value=1)
            result = {**payload, **parsed, "id": identity}
            if self.bad_parse:
                result["workout_doc"] = {"steps": []}
            self.remote[identity] = result
            results.append(deepcopy(result))
        return results

    def delete(self, identity):
        self.mutations.append(("delete", identity))
        if self.fail_delete:
            raise server.AppError(502, "Synthetic delete failure")
        self.remote.pop(identity, None)

    def seed(self, wrong_sport=False):
        entry = server.save_workout_library_entries([{
            "date": "2026-09-09", "name": "Lockerer 10-km-Lauf",
            "sport": "WeightTraining" if wrong_sport else "Run",
            "description": "Locker laufen" if wrong_sport else "- 75m Z1 HR",
            "duration_minutes": 75, "target": "AUTO",
        }])[0]
        identity = server.COACH_EVENT_EXTERNAL_PREFIX + entry["id"]
        remote = {"id": "existing", "external_id": identity, "category": "WORKOUT",
                  "start_date_local": "2026-09-09T00:00:00", "name": entry["name"], "type": "WeightTraining"}
        self.remote["existing"] = remote
        self.remote["duplicate"] = {**remote, "id": "duplicate"}
        self.remote["race"] = {"id": "race", "category": "RACE_A", "name": "Synthetic race", "start_date_local": "2026-09-09T00:00:00"}
        server.update_planned_unit_sync_state(entry["id"], "synced", remote_event=remote)
        return entry["id"]

    def selection(self, local_id):
        return next({"library_workout_id": item["local_id"], "expected_payload_hash": item["expected_payload_hash"]}
                    for item in server._structured_training_state(include_inactive=True)["planned_units"] if item["local_id"] == local_id)

    def repair(self, local_id):
        return server._sync_selected_workout_library({"repair": True, "entries": [self.selection(local_id)]})

    def test_coach_corrects_sport_and_repair_job_removes_duplicate_without_recreation(self):
        local_id = self.seed(wrong_sport=True)
        period = {"start": "2026-09-09", "end": "2026-09-09"}

        def correct(_):
            return self.call("apply_training_patch", {"expected_revision": self.state()["planning_revision"], "changes": [{
                "local_id": local_id, "action": "update", "sport": "Run", "description": "- 75m Z1 HR",
                "expected_payload_hash": self.selection(local_id)["expected_payload_hash"],
            }]}, ["planned_unit:" + local_id], period=period)

        def sync(_):
            return self.call("start_intervals_plan_sync", {"repair": True, "entries": [self.selection(local_id)]},
                             ["intervals_sync", "planned_unit:" + local_id], period=period,
                             target="intervals", remote_write=True, sync_scope="selected")

        receipt, _ = self.turn("Korrigiere den Lauf und gleiche alle Einheiten erneut mit Intervals ab, ohne doppelte Eintraege.", [
            lambda _: self.call("list_planned_workouts"),
            lambda _: self.call("read_training_state", {"include_inactive": True}),
            correct, lambda _: self.call("read_training_state", {"include_inactive": True}), sync,
            {"output_text": "Reparatur-Sync gestartet."},
        ])
        self.assertEqual(receipt["status"], "completed", receipt.get("failed_command_receipts"))
        job = server._claim_sync_job()
        result = server._execute_sync_job(job)
        self.assertTrue(result["ok"], result)
        server._sync_job_update_from_result(job["id"], result, fallback_status="completed")
        self.assertEqual(server.sync_job_state(job["id"])["status"], "completed")
        self.assertEqual(set(self.remote), {"existing", "race"})
        self.assertEqual(self.remote["existing"]["type"], "Run")
        self.assertEqual(self.remote["existing"]["moving_time"], 4500)
        self.assertEqual(server.list_planned_units()[0]["id"], local_id)
        # Already-synced units remain selectable for another repair.
        self.assertTrue(self.repair(local_id)["ok"])
        self.assertEqual(set(self.remote), {"existing", "race"})
        self.assertEqual([value["id"] for kind, value in self.mutations if kind == "upsert"], ["existing", "existing"])
        self.assertEqual([value for kind, value in self.mutations if kind == "delete"], ["duplicate"])

    def test_bad_parse_never_deletes_old_copies_or_reports_success(self):
        local_id = self.seed()
        self.bad_parse = True
        self.assertFalse(self.repair(local_id)["ok"])
        self.assertIn("duplicate", self.remote)
        self.assertFalse(any(kind == "delete" for kind, _ in self.mutations))
        self.assertEqual(server.list_planned_units()[0]["sync_status"], "sync_error")

    def test_cleanup_failure_retries_same_remote_identity(self):
        local_id = self.seed()
        self.fail_delete = True
        self.assertFalse(self.repair(local_id)["ok"])
        self.fail_delete = False
        self.assertTrue(self.repair(local_id)["ok"])
        self.assertEqual(set(self.remote), {"existing", "race"})
        self.assertTrue(all(value["id"] == "existing" for kind, value in self.mutations if kind == "upsert"))

    def test_selected_archived_unit_removes_only_its_identified_remote_copies(self):
        local_id = self.seed()
        server.update_local_planned_workout(local_id, {"action": "archive"})
        self.assertFalse(server._structured_training_state()["planned_units"])
        self.assertTrue(self.repair(local_id)["ok"])
        self.assertEqual(set(self.remote), {"race"})
        self.assertFalse(any(kind == "upsert" for kind, _ in self.mutations))

    def test_same_title_without_identity_is_a_conflict_before_writing(self):
        local_id = self.seed()
        self.remote["unknown"] = {**self.remote["existing"], "id": "unknown", "external_id": "some-other-app"}
        self.assertFalse(self.repair(local_id)["ok"])
        self.assertEqual(self.mutations, [])
        self.assertIn("unknown", self.remote)

    def test_replacement_and_archived_predecessor_can_be_reconciled_in_either_order(self):
        old_id = self.seed()
        server.update_local_planned_workout(old_id, {"action": "archive"})
        new_id = server.save_workout_library_entries([{
            "date": "2026-09-09", "name": "Lockerer 10-km-Lauf", "sport": "Run",
            "description": "- 75m Z1 HR", "duration_minutes": 75,
        }])[0]["id"]
        self.assertTrue(self.repair(new_id)["ok"])
        self.assertTrue(self.repair(old_id)["ok"])
        self.assertEqual(set(self.remote), {"new-synthetic-event", "race"})

    def test_related_completed_workout_is_not_overwritten_or_deleted(self):
        local_id = self.seed()
        self.remote["existing"]["paired_activity_id"] = "synthetic-completed-activity"
        self.assertFalse(self.repair(local_id)["ok"])
        self.assertEqual(self.mutations, [])

    def test_readback_date_mismatch_remains_an_error(self):
        local_id = self.seed()
        original = self.upsert
        def wrong_date(payloads):
            result = original(payloads)
            self.remote[result[0]["id"]]["start_date_local"] = "2026-09-10T00:00:00"
            return result
        with patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=wrong_date):
            self.assertFalse(self.repair(local_id)["ok"])
        self.assertEqual(server.list_planned_units()[0]["sync_status"], "sync_error")

    def test_verified_missing_remote_is_created_once(self):
        local_id = self.seed()
        self.remote.pop("existing")
        self.remote.pop("duplicate")
        self.assertTrue(self.repair(local_id)["ok"])
        self.assertTrue(self.repair(local_id)["ok"])
        self.assertEqual(set(self.remote), {"new-synthetic-event", "race"})

    def test_repair_job_requires_a_boolean_flag(self):
        local_id = self.seed()
        with self.assertRaises(server.AppError):
            server._sync_job_payload("intervals", "plan_push", {"entries": [self.selection(local_id)], "repair": "false"})

    def test_coach_repair_requires_remote_authorization_and_selected_scope(self):
        local_id = self.seed()
        for remote_write, sync_scope in ((False, "selected"), (True, "all_pending")):
            with self.subTest(remote_write=remote_write, sync_scope=sync_scope):
                receipt, _ = self.turn("Pruefe den Kalender.", [
                    lambda _: self.call("start_intervals_plan_sync", {"repair": True, "entries": [self.selection(local_id)]},
                                        ["intervals_sync", "planned_unit:" + local_id],
                                        period={"start": "2026-09-09", "end": "2026-09-09"},
                                        target="intervals", remote_write=remote_write, sync_scope=sync_scope),
                    {"output_text": "Keine Reparatur gestartet."},
                ])
                self.assertEqual(receipt["status"], "failed")
                self.assertIsNone(server._claim_sync_job())
        self.assertEqual(self.mutations, [])


if __name__ == "__main__":
    unittest.main()
