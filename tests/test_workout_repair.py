"""Real Coach/job execution with synthetic model and provider responses."""

from copy import deepcopy
from datetime import date, timedelta
import uuid
import unittest
import threading
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

    def test_multi_unit_repair_reads_calendar_twice_and_checks_all_final_results(self):
        ids = []
        for offset in range(3):
            entry = server.save_workout_library_entries([{
                "date": (date(2026, 9, 9) + timedelta(days=offset)).isoformat(),
                "name": f"Synthetic run {offset}", "sport": "Run",
                "description": "- 75m Z1 HR", "duration_minutes": 75,
            }])[0]
            ids.append(entry["id"])
            remote = {"id": f"event-{offset}", "external_id": server.COACH_EVENT_EXTERNAL_PREFIX + entry["id"],
                      "category": "WORKOUT", "start_date_local": entry["date"] + "T00:00:00", "name": entry["name"], "type": "Run"}
            self.remote[remote["id"]] = remote
            server.update_planned_unit_sync_state(entry["id"], "synced", remote_event=remote)

        for corrupt in (False, True):
            calls = []

            def read(*args, **kwargs):
                calls.append(1)
                if len(calls) == 2:
                    self.assertTrue(all(item["sync_status"] == "syncing" for item in server.list_planned_units()))
                    if corrupt:
                        self.remote["unexpected-copy"] = {**self.remote["event-0"], "id": "unexpected-copy"}
                return deepcopy(list(self.remote.values()))

            with patch.object(server.IntervalsClient, "get_paged_collection", side_effect=read):
                result = server._sync_selected_workout_library({"repair": True, "entries": [self.selection(identity) for identity in ids]})
            self.assertEqual(len(calls), 2)
            self.assertEqual(result["ok"], not corrupt)
            self.assertEqual(result["failed_object_ids"], [ids[0]] if corrupt else [])

    def test_open_water_recovery_uses_pace_like_pool_swimming(self):
        workout = server.adaptive_recovery_replacement({"sport": "OpenWaterSwim", "duration_minutes": 60}, "Synthetic recovery", 30)
        self.assertEqual(workout["sport"], "OpenWaterSwim")
        self.assertIn("- 30m Z1 Pace", workout["description"])
        self.assertEqual(server.validate_workout_description(workout), 1800)
        server.validate_intervals_workout_result(workout, parsed_workout_fixture(1800, sport="OpenWaterSwim", kind="pace", units="pace_zone", value=1))

    def test_planned_edit_clears_stale_metrics_and_repair_persists_verified_values(self):
        local_id = self.seed()
        old = {**self.remote["existing"], **parsed_workout_fixture(9000, sport="Run"), "icu_training_load": 150, "icu_intensity": 95}
        server.update_planned_unit_sync_state(local_id, "synced", remote_event=old)
        server.update_local_planned_workout(local_id, {"description": "- 75m Z1 HR", "duration_minutes": 75})
        edited = server.list_planned_units()[0]
        self.assertEqual(edited["moving_time"], 4500)
        for key in ("workout_doc", "icu_training_load", "icu_intensity"):
            self.assertNotIn(key, edited)

        def upsert_with_intensity(payloads):
            result = self.upsert(payloads)
            self.remote[result[0]["id"]]["icu_intensity"] = 55
            return result

        with patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=upsert_with_intensity):
            self.assertTrue(self.repair(local_id)["ok"])
        current = server.list_planned_units()[0]
        self.assertEqual(current["moving_time"], 4500)
        self.assertEqual(current["icu_training_load"], 20)
        self.assertEqual(current["icu_intensity"], 55)
        self.assertEqual(current["workout_doc"], self.remote["existing"]["workout_doc"])

    def test_adaptive_swim_uses_pace_and_clears_old_load_before_sync(self):
        entry = server.save_workout_library_entries([{
            "date": "2026-09-09", "name": "Synthetic swim", "sport": "Swim",
            "description": "- 60m Z3 Pace", "duration_minutes": 60,
        }])[0]
        server.update_planned_unit_sync_state(entry["id"], "synced", remote_event={
            "id": "swim-event", **parsed_workout_fixture(3600, sport="Swim", kind="pace", units="pace_zone", value=3), "icu_intensity": 90,
        })
        with patch.object(server, "local_feedback_context", return_value={"today": {"available_minutes": 30}}), patch.object(
            server, "weather_state", return_value={}
        ), patch.object(server, "list_external_calendar_events", return_value=[]):
            preview = server.adaptive_replan_preview()
        self.assertEqual(server.apply_adaptive_replan(preview["id"])["updated"], 1)
        current = server.list_planned_units()[0]
        self.assertEqual(current["sport"], "Swim")
        self.assertIn("- 30m Z1 Pace", current["description"])
        self.assertEqual(current["moving_time"], 1800)
        for key in ("workout_doc", "icu_training_load", "icu_intensity"):
            self.assertNotIn(key, current)
        parsed = parsed_workout_fixture(1800, sport="Swim", kind="pace", units="pace_zone", value=1)
        with patch.object(server.IntervalsClient, "upsert_calendar_events", return_value=[{"id": "swim-event", **parsed}]):
            self.assertTrue(server._sync_selected_workout_library({"entries": server._pending_plan_push_entries()})["ok"])
        self.assertEqual(server.list_planned_units()[0]["icu_training_load"], 20)

    def test_provider_io_allows_database_polling_and_excludes_same_unit_push(self):
        local_id = self.seed()
        polled = threading.Event()
        threads = []

        def poll():
            server.list_planned_units()
            polled.set()

        def slow_upsert(payloads):
            thread = threading.Thread(target=poll)
            threads.append(thread)
            thread.start()
            self.assertTrue(polled.wait(2), "Provider I/O blocks database polling")
            with self.assertRaises(server.AppError) as caught:
                server._sync_local_planned_unit_calendar_entry(local_id)
            self.assertEqual(caught.exception.reason, "planned_unit_sync_running")
            return self.upsert(payloads)

        try:
            with patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=slow_upsert):
                self.assertTrue(self.repair(local_id)["ok"])
        finally:
            for thread in threads:
                thread.join(3)
        self.assertNotIn(local_id, server.PLANNED_UNIT_SYNCS)

    def test_edit_during_upsert_keeps_new_content_and_remote_identity_without_cleanup(self):
        local_id = self.seed()
        self.remote.pop("existing")
        self.remote.pop("duplicate")

        def edit_during_upsert(payloads):
            server.update_local_planned_workout(local_id, {"name": "Edited during sync"})
            return self.upsert(payloads)

        with patch.object(server.IntervalsClient, "upsert_calendar_events", side_effect=edit_during_upsert):
            self.assertFalse(self.repair(local_id)["ok"])
        current = server.list_planned_units()[0]
        self.assertEqual(current["name"], "Edited during sync")
        self.assertEqual(current["remote_event_id"], "new-synthetic-event")
        self.assertEqual(current["sync_status"], "sync_error")
        self.assertFalse(any(kind == "delete" for kind, _ in self.mutations))
        self.assertTrue(self.repair(local_id)["ok"])
        self.assertEqual(set(self.remote), {"new-synthetic-event", "race"})

    def test_edit_during_readback_is_not_marked_synced(self):
        local_id = self.seed()
        calls = 0

        def read(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                server.update_local_planned_workout(local_id, {"action": "archive"})
            return deepcopy(list(self.remote.values()))

        with patch.object(server.IntervalsClient, "get_paged_collection", side_effect=read):
            self.assertFalse(self.repair(local_id)["ok"])
        self.assertTrue(self.repair(local_id)["ok"])
        self.assertEqual(set(self.remote), {"race"})

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

    def approve_illness_pause(self):
        with patch.object(server, "local_feedback_context", return_value={"today": {"illness": "Synthetic illness"}}), patch.object(
            server, "weather_state", return_value={}
        ), patch.object(server, "list_external_calendar_events", return_value=[]):
            preview = server.adaptive_replan_preview()
        self.assertEqual(preview["changes"][0]["after"]["duration_minutes"], 0)
        self.assertEqual(server.apply_adaptive_replan(preview["id"])["updated"], 1)
        self.assertEqual(server.list_planned_units(), [])
        self.assertEqual(self.mutations, [])

    def test_approved_illness_pause_all_pending_sync_removes_workout_without_placeholder(self):
        local_id = self.seed()
        self.remote.pop("duplicate")
        self.approve_illness_pause()
        result = server._sync_selected_workout_library({"entries": server._pending_plan_push_entries()})
        self.assertTrue(result["ok"], result)
        self.assertEqual(set(self.remote), {"race"})
        self.assertEqual(self.mutations, [("delete", "existing")])
        self.assertEqual(server.list_planned_units(include_archived=True)[0]["id"], local_id)
        self.assertEqual(server._pending_plan_push_entries(), [])

    def test_approved_illness_pause_repair_removes_all_identified_workout_copies(self):
        local_id = self.seed()
        self.approve_illness_pause()
        self.assertTrue(self.repair(local_id)["ok"])
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

    def test_training_state_pages_every_active_unit_and_archived_predecessor(self):
        expected = set()
        with server.DB_LOCK, server.database() as db:
            for offset in range(366):
                for archived in (False, True):
                    local_id = str(uuid.uuid4())
                    expected.add(local_id)
                    entry = server.normalize_planned_unit({
                        "date": (date(2026, 9, 9) + timedelta(days=offset)).isoformat(),
                        "sport": "Run", "name": "Same name and date", "description": "- 30m Z1 HR",
                        "duration_minutes": 30, "archived": archived,
                    }, local_id=local_id)
                    server._insert_planned_unit(db, entry)
            server._bump_planning_revision(db)
        first = server._structured_training_state(include_inactive=True)
        self.assertEqual(len(first["planned_units"]), 366)
        self.assertTrue(first["planned_units_page"]["has_more"])
        second = server._structured_training_state(include_inactive=True, cursor=first["planned_units_page"]["next_cursor"])
        combined = first["planned_units"] + second["planned_units"]
        self.assertEqual(len(combined), 732)
        self.assertEqual({item["local_id"] for item in combined}, expected)
        self.assertEqual(sum(item["archived"] for item in combined), 366)
        self.assertFalse(second["planned_units_page"]["has_more"])
        self.assertIsNone(second["planned_units_page"]["next_cursor"])

        active = server._structured_training_state()
        self.assertEqual(len(active["planned_units"]), 366)
        self.assertFalse(active["planned_units_page"]["has_more"])
        cursor = first["planned_units_page"]["next_cursor"]
        with self.assertRaises(server.AppError):
            server._structured_training_state(cursor=cursor)
        server.update_local_planned_workout(active["planned_units"][0]["local_id"], {"name": "Changed after page one"})
        with self.assertRaises(server.AppError) as caught:
            server._structured_training_state(include_inactive=True, cursor=cursor)
        self.assertEqual(caught.exception.reason, "planning_revision_conflict")
        for malformed in ("invalid", server.encode_page_cursor(["not-a-state-cursor"])):
            with self.assertRaises(server.AppError):
                server._structured_training_state(cursor=malformed)

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
