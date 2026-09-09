"""Executable tool coverage, not an evaluation of language-model recognition.

Model responses and provider reads are scripted; the real chat loop, request
validation, tools, transactions and receipts execute against disposable state.
Each coverage claim must be observed as a successful tool receipt at runtime.
"""
import functools
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from test_coach_dialogue import DialogueHarness, server


def covers(*cases):
    def decorate(test):
        @functools.wraps(test)
        def checked(self):
            test(self)
            self.assertFalse(set(cases) - self.observed, "Declared successful tool cases were not executed: " +
                             ", ".join(sorted(set(cases) - self.observed)))
        checked.tool_cases = frozenset(cases)
        return checked
    return decorate


REQUIRED_VARIANTS = {
    "manage_training_templates": {"create", "update", "archive", "restore", "delete"},
    "apply_training_patch": {"create", "update", "move", "archive", "restore", "delete"},
    "save_competition": {"create", "update"},
    "update_training_plan": {"update", "archive", "delete"},
    "start_provider_refresh": {"intervals", "garmin", "calendar", "weather"},
    "start_intervals_plan_sync": {"selected", "created", "all_pending"},
    "resolve_training_sync_conflict": {"keep_local", "adopt_remote", "retry_push", "retry_read"},
    "apply_adaptive_replan": {"local", "intervals"},
}


def variants(name, arguments, result):
    if name == "manage_training_templates":
        return {item.get("action", "create") for item in arguments["templates"]}
    if name == "apply_training_patch":
        result = {item["action"] for item in arguments.get("changes", [])}
        if arguments.get("workouts"):
            result.add("create")
        if any(item.get("date") for item in arguments.get("changes", [])):
            result.add("move")
        return result
    if name == "save_competition":
        return {"update" if arguments["payload"].get("competition_id") else "create"}
    if name == "update_training_plan":
        payload = arguments["payload"]
        return {"archive" if payload.get("status") == "archived" else payload.get("action", "update")}
    if name == "start_provider_refresh":
        return {arguments["_request"]["target"]}
    if name == "start_intervals_plan_sync":
        return {arguments["_request"]["sync_scope"]}
    if name == "resolve_training_sync_conflict":
        if arguments.get("local_id"):
            return {arguments["strategy"]}
        return {"retry_push" if result["job"]["type"] in {"plan_push", "competition_push"} else "retry_read"}
    if name == "apply_adaptive_replan":
        return {"intervals" if arguments.get("sync_illness_to_intervals") else "local"}
    return {"success"}


class CoachToolCoverageTests(DialogueHarness, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.observed = set()
        self.issued = {}
        for name in ("http_json", "urlopen"):
            guard = patch.object(server, name, side_effect=AssertionError("Unexpected network access in synthetic Coach test"))
            guard.start()
            self.addCleanup(guard.stop)

    def call(self, *args, **kwargs):
        response = super().call(*args, **kwargs)
        item = response["output"][0]
        self.issued[item["call_id"]] = json.loads(item["arguments"])
        return response

    def turn(self, *args, **kwargs):
        receipt, model = super().turn(*args, **kwargs)
        for step in receipt.get("command_receipts", []):
            if step.get("result", {}).get("ok") and step["call_id"] in self.issued:
                for variant in variants(step["tool"], self.issued[step["call_id"]], step["result"]):
                    self.observed.add(step["tool"] + ":" + variant)
        return receipt, model

    def run_tool(self, name, arguments=None, scope=None, message="Bitte so ausführen.", **kwargs):
        receipt, _ = self.turn(message, [lambda _: self.call(name, arguments, scope, **kwargs),
                                       {"output_text": "Synthetischer Ergebnistext."}])
        self.assertEqual(receipt["status"], "completed", [step["result"].get("reason") for step in receipt["command_receipts"]])
        step = receipt["command_receipts"][0]
        self.assertTrue(step["result"]["ok"])
        return step["result"]

    def athlete_state(self):
        """Exclude dialogue bookkeeping, include all state the tools can change."""
        tables = ("planned_units", "workout_library", "training_plans", "competitions", "competition_sync_tombstones",
                  "athlete_checkins", "activity_feedback", "plan_adjustments", "change_history", "sync_jobs",
                  "sync_job_items", "coach_plan_artifacts", "coach_action_proposals", "planning_state", "snapshots")
        with server.database() as db:
            return {"profile": server.get_profile(), **{table: [dict(row) for row in db.execute("SELECT * FROM " + table)] for table in tables}}

    def seed_activity(self):
        activity = {"id": "synthetic-run", "type": "Run", "name": "Synthetic run", "start_date_local": "2026-09-06T10:00:00",
                    "moving_time": 1800, "distance": 5000}
        server.save_snapshot_view({"recent_activities": [activity], "recent_wellness": [], "planned_workouts": []})
        return activity

    @covers("read_profile:success", "update_profile:success")
    def test_permanent_profile_acceptance_reads_and_preserves_existing_facts(self):
        server.save_profile({"name": "Synthetic athlete", "training_background": "Regular cycling.", "equipment": "Indoor bike"})
        before = self.athlete_state()
        self.turn("Spaziergänge gehören bei mir zum Alltag.", [{"output_text": "Soll ich tägliche Spaziergänge dauerhaft im Profil ergänzen?"}])
        self.assertEqual(self.athlete_state(), before)
        def save(payload):
            profile = json.loads(payload["input"][0]["output"])["profile"]
            return self.call("update_profile", {"changes": [{"field": "training_background", "expected_value": profile["training_background"],
                "value": profile["training_background"] + " Daily walking."}]}, ["local_profile"])
        receipt, _ = self.turn("Ja, bitte dauerhaft hinzufügen.", [lambda _: self.call("read_profile"), save, {"output_text": "Gespeichert."}])
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual(server.get_profile()["training_background"], "Regular cycling. Daily walking.")
        self.assertEqual(server.get_profile()["equipment"], "Indoor bike")
        self.assertEqual(server.sync_jobs_state(), [])

    @covers("read_training_state:success", "list_planned_workouts:success", "list_workout_library:success",
            "list_training_plans:success", "list_competitions:success", "list_change_history:success", "list_recent_activities:success")
    def test_read_tools_return_seeded_objects_without_mutating_them(self):
        planned = server.save_workout_library_entries([self.workout()], plan_name="Synthetic plan")[0]
        server.create_local_library_template({"name": "Synthetic template", "sport": "Run", "description": "- 30m 60% Easy", "duration_minutes": 30})
        server.save_coach_competition({"name": "Synthetic race", "event_date": "2026-10-03", "sport": "Run", "priority": "A"})
        self.seed_activity()
        before = self.athlete_state()
        for tool, expected in (("read_training_state", planned["id"]), ("list_planned_workouts", planned["id"]),
                               ("list_workout_library", "Synthetic template"), ("list_training_plans", "Synthetic plan"),
                               ("list_competitions", "Synthetic race"), ("list_change_history", "entity_type"),
                               ("list_recent_activities", "synthetic-run")):
            with self.subTest(tool=tool):
                result = self.run_tool(tool, message="Zeig mir den aktuellen Stand.")
                self.assertIn(expected, json.dumps(result))
                self.assertEqual(self.athlete_state(), before)

    @covers("manage_training_templates:create", "manage_training_templates:update", "manage_training_templates:archive",
            "manage_training_templates:restore", "manage_training_templates:delete", "apply_workout_library_plan:success")
    def test_template_lifecycle_and_scheduling_preserve_the_scheduled_copy(self):
        self.run_tool("manage_training_templates", {"templates": [{"action": "create", "name": "Synthetic easy run", "sport": "Run",
            "description": "- 30m 60% Synthetic easy instructions", "duration_minutes": 30}]}, ["local_template"], message="Speichere das als wiederverwendbare Vorlage.")
        template = server.list_workout_library()[0]
        local_id = template["id"]
        self.assertFalse(template.get("date"))
        self.run_tool("manage_training_templates", {"templates": [{"action": "update", "local_id": local_id, "duration_minutes": 40, "description": "- 40m 60%"}]}, ["library_workout:" + local_id])
        self.assertEqual(server.list_workout_library()[0]["duration_minutes"], 40)
        self.run_tool("apply_workout_library_plan", {"entries": [{"library_workout_id": local_id, "date": "2026-09-09"}]},
                      ["library_workout:" + local_id], period={"start": "2026-09-09", "end": "2026-09-09"}, message="Plane diese Vorlage am Mittwoch ein.")
        planned_before = self.state()["planned_units"]
        self.assertEqual(len(planned_before), 1)
        self.assertEqual(planned_before[0]["date"], "2026-09-09")
        for action in ("archive", "restore", "delete"):
            self.run_tool("manage_training_templates", {"templates": [{"action": action, "local_id": local_id}]}, ["library_workout:" + local_id])
            templates = server.list_workout_library(include_archived=True)
            if action == "delete":
                self.assertEqual(templates, [])
            else:
                self.assertEqual(templates[0]["archived"], action == "archive")
            self.assertEqual(self.state()["planned_units"], planned_before)
        self.assertEqual(server.sync_jobs_state(), [])

    @covers("apply_training_patch:create", "apply_training_patch:update", "apply_training_patch:move",
            "apply_training_patch:archive", "apply_training_patch:restore", "apply_training_patch:delete")
    def test_planned_unit_lifecycle_keeps_identity_until_deleted(self):
        period = {"start": "2026-09-09", "end": "2026-09-11"}
        self.run_tool("apply_training_patch", {"workouts": [self.workout()], "expected_revision": self.state()["planning_revision"]}, ["local_plan"], period=period)
        local_id = self.state()["planned_units"][0]["local_id"]
        for action, extra in (("update", {"name": "Synthetic renamed", "date": "2026-09-11"}), ("archive", {}), ("restore", {}), ("delete", {})):
            with server.database() as db:
                row = db.execute("SELECT payload FROM planned_units WHERE local_id=?", (local_id,)).fetchone()
            self.run_tool("apply_training_patch", {"changes": [{"local_id": local_id, "action": action, **extra,
                "expected_payload_hash": server._library_payload_hash(row["payload"])}], "expected_revision": self.state()["planning_revision"]},
                ["planned_unit:" + local_id], period=period)
            units = self.state()["planned_units"]
            if action in {"archive", "delete"}:
                self.assertEqual(units, [])
            else:
                self.assertEqual([(u["local_id"], u["date"], u["name"]) for u in units], [(local_id, "2026-09-11", "Synthetic renamed")])
        self.assertEqual(server.sync_jobs_state(), [])

    @covers("stage_training_plan:success", "commit_training_plan:success", "update_training_plan:update",
            "update_training_plan:archive", "update_training_plan:delete")
    def test_requested_draft_commit_and_metadata_lifecycle(self):
        period = {"start": "2026-09-09", "end": "2026-09-09"}
        draft = self.run_tool("stage_training_plan", {"payload": {"plan_name": "Synthetic draft", "goal": "Easy week", "workouts": [self.workout()]}},
                              ["local_plan"], period=period, message="Erstelle zunächst nur einen Entwurf.")
        self.assertEqual(self.state()["planned_units"], [])
        source = [m["id"] for m in server.list_messages() if m["role"] == "user"][-1]
        def commit(_):
            response = self.call("commit_training_plan", {"artifact_id": draft["artifact_id"]}, ["artifact:" + draft["artifact_id"]], period=period)
            args = json.loads(response["output"][0]["arguments"])
            args["_request"]["source_message_ids"].append(source)
            response["output"][0]["arguments"] = json.dumps(args)
            return response
        result, _ = self.turn("Ja, diesen Entwurf speichern.", [commit, {"output_text": "Gespeichert."}])
        self.assertEqual(result["status"], "completed")
        plan_id = server.list_training_plans()[0]["id"]
        units = self.state()["planned_units"]
        for payload in ({"name": "Synthetic renamed plan"}, {"status": "archived"}, {"action": "delete"}):
            self.run_tool("update_training_plan", {"payload": {"plan_id": plan_id, **payload}}, ["training_plan:" + plan_id])
            self.assertEqual(self.state()["planned_units"], units)
            if "name" in payload:
                self.assertEqual(server.list_training_plans()[0]["name"], payload["name"])
            elif "status" in payload:
                self.assertEqual(server.list_training_plans()[0]["status"], "archived")
        self.assertEqual(server.list_training_plans(), [])

    @covers("replace_training_plan:success")
    def test_replacement_changes_only_requested_period(self):
        units = server.save_workout_library_entries([self.workout(), self.workout("2026-10-05", "Synthetic later")])
        self.run_tool("replace_training_plan", {"payload": {"plan_name": "Synthetic replacement", "goal": "Easy",
            "workouts": [self.workout("2026-09-11", "Synthetic replacement workout")]}, "expected_revision": self.state()["planning_revision"]},
            ["local_plan"], period={"start": "2026-09-07", "end": "2026-09-13"}, message="Plane nur diese Woche neu.")
        result = self.state()["planned_units"]
        self.assertEqual([u["date"] for u in result], ["2026-09-11", "2026-10-05"])
        self.assertEqual(result[-1]["local_id"], units[-1]["id"])
        self.assertEqual(server.sync_jobs_state(), [])

    @covers("save_checkin:success", "save_activity_feedback:success", "delete_activity_feedback:success")
    def test_daily_feedback_and_activity_feedback_are_separate_from_profile(self):
        self.seed_activity()
        profile = server.get_profile()
        self.run_tool("save_checkin", {"payload": {"soreness": 6, "notes": "Synthetic heavy legs"}}, ["local_checkin"], message="Heute sind die Beine schwer.")
        self.assertEqual(server.list_checkins()[0]["soreness"], 6)
        self.run_tool("save_activity_feedback", {"payload": {"activity_id": "synthetic-run", "activity_name": "Synthetic run",
            "activity_date": "2026-09-06", "notes": "Synthetic easy finish"}}, ["activity_feedback"], message="Notiere zum gestrigen Lauf: entspanntes Ende.")
        self.assertEqual(server.list_activity_feedback()[0]["notes"], "Synthetic easy finish")
        self.run_tool("delete_activity_feedback", {"activity_id": "synthetic-run"}, ["activity_feedback"], message="Entferne diese Notiz wieder.")
        self.assertEqual(server.list_activity_feedback(), [])
        self.assertEqual(server.list_checkins()[0]["soreness"], 6)
        self.assertEqual(server.get_profile(), profile)

    @covers("save_competition:create", "save_competition:update", "delete_competition:success", "sync_competitions:success")
    def test_competition_lifecycle_syncs_only_after_explicit_followup(self):
        self.run_tool("save_competition", {"payload": {"name": "Synthetic race", "event_date": "2026-10-03", "sport": "Run", "priority": "A"}}, ["local_competitions"])
        competition_id = server.list_competitions()[0]["id"]
        self.run_tool("save_competition", {"payload": {"competition_id": competition_id, "event_date": "2026-10-04"}}, ["competition:" + competition_id], message="Den bitte einen Tag später.")
        self.assertEqual(server.list_competitions()[0]["event_date"], "2026-10-04")
        self.assertEqual(server.sync_jobs_state(), [])
        self.run_tool("sync_competitions", {}, ["local_competitions", "intervals_sync"], target="intervals", remote_write=True, message="Übertrage die Wettkämpfe zu Intervals.")
        self.assertEqual([(j["provider"], j["type"]) for j in server.sync_jobs_state()], [("intervals", "competition_push")])
        self.run_tool("delete_competition", {"competition_id": competition_id}, ["competition:" + competition_id], message="Entferne diesen Wettkampf lokal.")
        self.assertEqual(server.list_competitions(), [])
        self.assertEqual(len(server.sync_jobs_state()), 1)

    @covers("start_provider_refresh:intervals", "start_provider_refresh:garmin", "start_provider_refresh:calendar",
            "start_provider_refresh:weather", "refresh_current_performance:success", "get_sync_job:success")
    def test_provider_reads_and_job_status_use_correct_provider(self):
        with patch.object(server, "sync_intervals", return_value={"status": "ok", "activity_days": 7}) as sync:
            result = self.run_tool("start_provider_refresh", {"days": 7}, ["intervals_refresh"], target="intervals")
            self.assertEqual(result["status"], "completed")
            sync.assert_called_once()
            self.assertEqual(sync.call_args.kwargs["activity_days"], 7)
        for provider in ("garmin", "calendar", "weather"):
            result = self.run_tool("start_provider_refresh", {"days": 7} if provider == "garmin" else {}, [provider + "_refresh"], target=provider)
            job = self.run_tool("get_sync_job", {"job_id": result["sync_job_id"]})["job"]
            self.assertEqual((job["provider"], job["type"], job["status"]), (provider, "refresh", "queued"))
        result = self.run_tool("refresh_current_performance", {}, ["intervals_refresh"], target="intervals")
        self.assertEqual(server.sync_job_state(result["sync_job_id"])["type"], "performance_refresh")
        self.assertTrue(all(j["type"] not in {"plan_push", "competition_push"} for j in server.sync_jobs_state()))

    @covers("start_intervals_plan_sync:created", "start_intervals_plan_sync:selected", "start_intervals_plan_sync:all_pending")
    def test_new_plan_sync_and_later_selected_sync_use_real_ids(self):
        period = {"start": "2026-09-09", "end": "2026-09-09"}
        result, _ = self.turn("Mittwoch locker trainieren und anschließend übertragen.", [
            lambda _: self.call("apply_training_patch", {"workouts": [self.workout()], "expected_revision": self.state()["planning_revision"]}, ["local_plan"], period=period),
            lambda _: self.call("start_intervals_plan_sync", {}, ["intervals_sync"], target="intervals", remote_write=True, sync_scope="created"),
            {"output_text": "Lokal gespeichert, Übertragung beauftragt."}])
        self.assertEqual(result["status"], "completed")
        local_id = self.state()["planned_units"][0]["local_id"]
        server.save_workout_library_entries([self.workout("2026-09-13", "Synthetic preserved Sunday")])
        entry = next(e for e in server._pending_plan_push_entries() if e["library_workout_id"] == local_id)
        selected = self.run_tool("start_intervals_plan_sync", {"entries": [entry]}, ["planned_unit:" + local_id, "intervals_sync"],
                                 target="intervals", remote_write=True, sync_scope="selected", message="Nur diese Einheit erneut übertragen.")
        self.assertEqual(selected["entries"], 1)
        with server.database() as db:
            job = db.execute("SELECT payload FROM sync_jobs WHERE id=?", (selected["sync_job_ids"][0],)).fetchone()
        self.assertEqual([e["library_workout_id"] for e in json.loads(job["payload"])["entries"]], [local_id])
        all_pending = self.run_tool("start_intervals_plan_sync", {}, ["local_plan", "intervals_sync"], target="intervals", remote_write=True,
                                    sync_scope="all_pending", message="Jetzt alle offenen Einheiten übertragen.")
        self.assertEqual(all_pending["entries"], 2)

    @covers("resolve_training_sync_conflict:keep_local", "resolve_training_sync_conflict:adopt_remote",
            "resolve_training_sync_conflict:retry_push", "resolve_training_sync_conflict:retry_read")
    def test_conflict_choices_and_failed_job_retries(self):
        local_id = server.save_workout_library_entries([self.workout()])[0]["id"]
        for strategy in ("keep_local", "adopt_remote"):
            with server.database() as db:
                db.execute("UPDATE planned_units SET sync_state='conflict', sync_conflict=? WHERE local_id=?",
                           (json.dumps({"type": "remote_missing", "remote": None}), local_id))
            self.run_tool("resolve_training_sync_conflict", {"local_id": local_id, "strategy": strategy}, ["planned_unit:" + local_id])
            self.assertEqual(len(self.state()["planned_units"]), 1 if strategy == "keep_local" else 0)
        for provider, kind, remote in (("intervals", "competition_push", True), ("garmin", "refresh", False)):
            job = server.enqueue_sync_job(provider, kind, {"reason": "Synthetic", **({} if remote else {"days": 7})}, requested_by="coach")
            with server.database() as db:
                db.execute("UPDATE sync_jobs SET status='failed' WHERE id=?", (job["id"],))
            self.run_tool("resolve_training_sync_conflict", {"job_id": job["id"]}, ["sync_job:" + job["id"], "intervals_sync" if remote else "garmin_refresh"], target=provider, remote_write=remote)
            self.assertEqual(server.sync_job_state(job["id"])["status"], "queued")

    @covers("preview_adaptive_replan:success", "apply_adaptive_replan:local")
    def test_adaptive_preview_requires_later_acceptance_before_changing_workout(self):
        server.save_workout_library_entries([{**self.workout(), "duration_minutes": 90}])
        server.save_checkin({"soreness": 8, "available_minutes": 30})
        before = self.state()["planned_units"]
        preview = self.run_tool("preview_adaptive_replan", {}, ["adaptive_replan"], message="Was würdest du wegen meiner müden Beine anpassen?")
        self.assertTrue(preview["changes"])
        self.assertEqual(self.state()["planned_units"], before)
        applied = self.run_tool("apply_adaptive_replan", {"adjustment_id": preview["id"]}, ["adaptive_replan:" + preview["id"]], message="Ja, diese vorgeschlagene Anpassung übernehmen.")
        self.assertEqual(applied["updated"], 1)
        self.assertLess(server.list_planned_units()[0]["duration_minutes"], 90)
        self.assertEqual(server.sync_jobs_state(), [])

    @covers("apply_adaptive_replan:intervals")
    def test_illness_sync_requires_explicit_remote_acceptance_after_preview(self):
        server.save_workout_library_entries([self.workout()])
        server.save_checkin({"illness": "Synthetic cold"})
        preview = self.run_tool("preview_adaptive_replan", {}, ["adaptive_replan"])
        before = self.state()["planned_units"]
        arguments = {"adjustment_id": preview["id"], "sync_illness_to_intervals": True}
        with patch.object(server, "sync_illness_pause_to_intervals", return_value={"status": "ok", "synced": 3}) as remote:
            denied, _ = self.turn("Nur lokal übernehmen.", [lambda _: self.call("apply_adaptive_replan", arguments, ["adaptive_replan:" + preview["id"]]),
                                                          {"output_text": "Nicht übertragen."}])
            self.assertEqual(denied["status"], "failed")
            self.assertEqual(self.state()["planned_units"], before)
            remote.assert_not_called()
            result = self.run_tool("apply_adaptive_replan", arguments, ["adaptive_replan:" + preview["id"], "intervals_sync"],
                                   target="intervals", remote_write=True, message="Diese Pause übernehmen und zu Intervals übertragen.")
            remote.assert_called_once()
        self.assertEqual(result["updated"], 1)
        self.assertGreater(result["updated_checkins"], 0)
        self.assertEqual(result["intervals_sync"]["status"], "ok")

    @covers("undo_training_change:success")
    def test_undo_is_a_bound_preview_until_explicit_confirmation(self):
        server.create_local_library_template({"name": "Synthetic undo template", "description": "- 30m 60% Easy", "duration_minutes": 30})
        change = server.list_change_history()[0]
        before = server.list_workout_library()
        result = self.run_tool("undo_training_change", {"change_id": change["id"]}, ["change:" + change["id"]], message="Das möchte ich rückgängig machen.")
        self.assertEqual(result["proposed_action"]["status"], "preview")
        self.assertEqual(server.list_workout_library(), before)

    @covers("inspect_activity_duplicates:success")
    def test_duplicate_inspection_returns_preview_without_deleting_provider_data(self):
        common = {"type": "Ride", "start_date_local": "2026-09-06T10:00:00", "moving_time": 3600, "distance": 30000}
        snapshot = {"recent_activities": [{**common, "id": "synthetic-wahoo", "source": "Wahoo"}, {**common, "id": "synthetic-garmin", "source": "GARMIN_CONNECT"}]}
        server.save_snapshot_view(snapshot)
        result = self.run_tool("inspect_activity_duplicates", message="Ist die letzte Radausfahrt doppelt vorhanden?")
        self.assertIsNotNone(result["duplicate"])
        self.assertEqual(result["duplicate"]["canonical_id"], "synthetic-wahoo")
        self.assertEqual(result["proposed_action"]["action_type"], "delete_duplicate_intervals_activity")
        self.assertEqual(result["proposed_action"]["status"], "preview")
        self.assertEqual(server.latest_snapshot()["recent_activities"], snapshot["recent_activities"])
        self.assertEqual(server.sync_jobs_state(), [])

    @covers("clarify_coach_request:success", "cancel_coach_request:success")
    def test_clarification_and_cancellation_preserve_athlete_data(self):
        server.save_workout_library_entries([self.workout(), self.workout("2026-09-11")])
        before = self.athlete_state()
        def ask(_):
            return self.call("clarify_coach_request", {"source_message_ids": self.request([])["source_message_ids"],
                "summary": "Eine der beiden Einheiten verschieben", "question": "Die Einheit am Mittwoch oder Freitag?"})
        result, _ = self.turn("Diese Einheit bitte verschieben.", [ask, {"output_text": "Welche Einheit?"}])
        self.assertTrue(result["awaiting_clarification"])
        self.assertIsNotNone(json.loads(server.get_kv("coach_pending_request")))
        result, _ = self.turn("Lass es unverändert.", [lambda _: self.call("cancel_coach_request"), {"output_text": "Abgebrochen."}])
        self.assertEqual(result["status"], "cancelled")
        self.assertIsNone(json.loads(server.get_kv("coach_pending_request")))
        self.assertEqual(self.athlete_state(), before)

    def test_matrix_has_observed_success_case_for_every_available_tool_and_variant(self):
        declared = set().union(*(getattr(getattr(type(self), name), "tool_cases", set()) for name in dir(type(self)) if name.startswith("test_")))
        tools = {tool["name"] for tool in server.COACH_DIALOGUE_TOOLS}
        self.assertEqual({case.split(":")[0] for case in declared}, tools)
        for tool, required in REQUIRED_VARIANTS.items():
            self.assertTrue({tool + ":" + variant for variant in required} <= declared, tool)
        document = (Path(__file__).resolve().parents[1] / "docs" / "coach-tool-coverage.md").read_text(encoding="utf-8")
        documented = set()
        for line in document.splitlines():
            if line.startswith("| `"):
                name, variants_text, _ = line.split("|")[1:4]
                documented.update(name.strip().strip("`") + ":" + value.strip().strip("`") for value in variants_text.split(","))
        self.assertEqual(documented, declared)

    def test_every_mutating_tool_rejects_missing_user_authorization_without_effect(self):
        exceptions = server.STRUCTURED_READ_ONLY_TOOLS | {"clarify_coach_request", "cancel_coach_request"}
        for tool in server.COACH_DIALOGUE_TOOLS:
            if tool["name"] in exceptions:
                continue
            with self.subTest(tool=tool["name"]):
                before = self.athlete_state()
                result, _ = self.turn("Nur eine hypothetische Frage.", [lambda _, name=tool["name"]: self.call(name, {}), {"output_text": "Keine Änderung."}])
                self.assertEqual(result["status"], "failed")
                self.assertEqual(result["command_receipts"][0]["result"]["reason"], "request_invalid")
                self.assertEqual(self.athlete_state(), before)

    def test_advice_and_negation_scripts_leave_state_unchanged(self):
        server.save_workout_library_entries([self.workout()])
        before = self.athlete_state()
        for message in ("Was wäre, wenn ich Freitag laufen würde?", "Bitte noch nichts speichern.", "Nicht zu Intervals übertragen."):
            result, _ = self.turn(message, [{"output_text": "Synthetische Beratung ohne Werkzeugaufruf."}])
            self.assertEqual(result["command_receipts"], [])
            self.assertEqual(self.athlete_state(), before)

    def test_friday_correction_retry_and_sync_keep_sunday_unchanged(self):
        units = server.save_workout_library_entries([self.workout("2026-09-11", "Synthetic Friday strength"),
                                                     self.workout("2026-09-13", "Synthetic Sunday strength")])
        friday, sunday = units[0]["id"], units[1]["id"]
        initial = self.state()
        sunday_before = next(u for u in initial["planned_units"] if u["local_id"] == sunday)
        period = {"start": "2026-09-11", "end": "2026-09-13"}
        change = {"local_id": friday, "action": "update", "sport": "Run", "name": "Synthetic easy 8 km run",
                  "description": "- 50m Z1 HR Synthetic very easy run", "duration_minutes": 50,
                  "expected_payload_hash": next(u["expected_payload_hash"] for u in initial["planned_units"] if u["local_id"] == friday)}
        corrected = {}
        def repair(payload):
            self.assertEqual(self.state()["planned_units"], initial["planned_units"])
            current = json.loads(payload["input"][0]["output"])
            corrected.update(changes=[change], expected_revision=current["planning_revision"])
            return self.call("apply_training_patch", corrected, ["planned_unit:" + friday], period=period)
        with patch.object(server, "_apply_training_patch", wraps=server._apply_training_patch) as apply:
            result, _ = self.turn("Freitag lieber einen sehr lockeren 8-km-Lauf, Sonntag Kraft behalten.", [
                lambda _: self.call("apply_training_patch", {"changes": [change], "expected_revision": -1}, ["planned_unit:" + friday], period=period),
                lambda _: self.call("read_training_state"), repair,
                lambda _: self.call("apply_training_patch", corrected, ["planned_unit:" + friday], period=period),
                {"output_text": "Freitag geändert, Sonntag bleibt bestehen."},
            ], turn="friday-repair")
        self.assertEqual(result["status"], "completed")
        self.assertTrue(result["command_receipts"][0]["resolved"])
        self.assertEqual(apply.call_count, 2)  # One rejected attempt, one successful write; replay is cached.
        self.assertEqual(self.state()["planning_revision"], initial["planning_revision"] + 1)
        self.assertEqual(next(u for u in self.state()["planned_units"] if u["local_id"] == sunday), sunday_before)
        self.assertEqual(next(u["sport"] for u in self.state()["planned_units"] if u["local_id"] == friday), "Run")
        self.assertEqual(server.sync_jobs_state(), [])
        replay, model = self.turn("Freitag lieber einen sehr lockeren 8-km-Lauf, Sonntag Kraft behalten.", [], turn="friday-repair")
        model.assert_not_called()
        self.assertEqual(replay, result)
        def sync_read_selection(payload):
            current = json.loads(payload["input"][0]["output"])
            entry = next(u for u in current["planned_units"] if u["local_id"] == friday)
            return self.call("start_intervals_plan_sync", {"entries": [{"library_workout_id": entry["local_id"], "expected_payload_hash": entry["expected_payload_hash"]}]},
                             ["intervals_sync", "planned_unit:" + friday], target="intervals", remote_write=True, sync_scope="selected")
        synced, _ = self.turn("Bitte diese geänderte Einheit zu Intervals synchronisieren.", [lambda _: self.call("read_training_state"), sync_read_selection,
                                                                                             {"output_text": "Synchronisierung beauftragt."}])
        self.assertEqual(synced["status"], "completed")
        with server.database() as db:
            job = db.execute("SELECT payload FROM sync_jobs WHERE id=?", (synced["sync_job_ids"][0],)).fetchone()
        self.assertEqual([e["library_workout_id"] for e in json.loads(job["payload"])["entries"]], [friday])
        self.assertEqual(next(u for u in self.state()["planned_units"] if u["local_id"] == sunday), sunday_before)

    def test_short_answer_completes_persisted_clarification_after_an_intervening_read(self):
        units = server.save_workout_library_entries([self.workout("2026-09-09"), self.workout("2026-09-11")])
        before = self.state()
        def ask(_):
            return self.call("clarify_coach_request", {"source_message_ids": self.request([])["source_message_ids"],
                "summary": "Eine Oberkörpereinheit auf Samstag verschieben; die andere erhalten.", "question": "Die erste am Mittwoch oder die zweite am Freitag?"})
        self.turn("Verschiebe eine der Oberkörpereinheiten auf Samstag.", [ask, {"output_text": "Welche Einheit?"}])
        pending = json.loads(server.get_kv("coach_pending_request"))
        self.run_tool("list_planned_workouts", message="Zeig mir die Woche nochmal.")
        self.assertEqual(json.loads(server.get_kv("coach_pending_request")), pending)
        def choose(payload):
            context = json.loads(payload["input"])["dialogue"]
            self.assertEqual(context["pending_request"], pending)
            selected = before["planned_units"][1]
            response = self.call("apply_training_patch", {"expected_revision": before["planning_revision"], "changes": [{
                "local_id": selected["local_id"], "action": "update", "date": "2026-09-12", "expected_payload_hash": selected["expected_payload_hash"]}]},
                ["planned_unit:" + selected["local_id"]], period={"start": "2026-09-11", "end": "2026-09-12"})
            args = json.loads(response["output"][0]["arguments"])
            args["_request"]["source_message_ids"] += pending["source_message_ids"]
            response["output"][0]["arguments"] = json.dumps(args)
            return response
        result, _ = self.turn("Die zweite.", [choose, {"output_text": "Die Freitagseinheit liegt jetzt am Samstag."}])
        self.assertEqual(result["status"], "completed")
        self.assertEqual([(u["local_id"], u["date"]) for u in self.state()["planned_units"]], [(units[0]["id"], "2026-09-09"), (units[1]["id"], "2026-09-12")])
        self.assertIsNone(json.loads(server.get_kv("coach_pending_request")))

    def test_invalid_arguments_and_missing_objects_do_not_partially_write(self):
        unit = server.save_workout_library_entries([self.workout()], plan_name="Synthetic validation plan")[0]
        server.create_local_library_template({"name": "Synthetic template", "description": "- 30m 60% Easy", "duration_minutes": 30})
        template_id = server.list_workout_library()[0]["id"]
        plan_id = server.list_training_plans()[0]["id"]
        period = {"start": "2026-09-09", "end": "2026-09-09"}
        cases = [
            ("update_profile", {"changes": [{"field": "name", "expected_value": "", "value": None}]}, ["local_profile"], {}),
            ("manage_training_templates", {"templates": [{"action": "create", "name": "Must roll back", "description": "Easy"}, {"action": "invalid"}]}, ["local_template"], {}),
            ("save_checkin", {"payload": {"soreness": 11}}, ["local_checkin"], {}),
            ("save_activity_feedback", {"payload": {"activity_id": "missing", "notes": "Synthetic"}}, ["activity_feedback"], {}),
            ("delete_activity_feedback", {"activity_id": ""}, ["activity_feedback"], {}),
            ("save_competition", {"payload": {"name": "Synthetic", "event_date": "2026-99-99", "sport": "Run"}}, ["local_competitions"], {}),
            ("delete_competition", {"competition_id": "missing"}, ["competition:missing"], {}),
            ("stage_training_plan", {"payload": {"plan_name": "Invalid draft", "goal": "Synthetic", "workouts": []}}, ["local_plan"], {"period": period}),
            ("commit_training_plan", {"artifact_id": "missing"}, ["artifact:missing"], {"period": period}),
            ("replace_training_plan", {"payload": {"plan_name": "Invalid replacement", "goal": "Synthetic", "workouts": [self.workout()]}, "expected_revision": -1}, ["local_plan"], {"period": period}),
            ("apply_training_patch", {"workouts": [self.workout()], "expected_revision": -1}, ["local_plan"], {"period": period}),
            ("apply_workout_library_plan", {"entries": [{"library_workout_id": template_id, "date": "2026-99-99"}]}, ["library_workout:" + template_id], {"period": period}),
            ("update_training_plan", {"payload": {"plan_id": plan_id, "start_date": "invalid"}}, ["training_plan:" + plan_id], {}),
            ("undo_training_change", {"change_id": "missing"}, ["change:missing"], {}),
            ("resolve_training_sync_conflict", {"local_id": unit["id"], "strategy": "keep_local"}, ["planned_unit:" + unit["id"]], {}),
            ("apply_adaptive_replan", {"adjustment_id": "missing"}, ["adaptive_replan:missing"], {}),
            ("start_provider_refresh", {"days": 4000}, ["garmin_refresh"], {"target": "garmin"}),
            ("refresh_current_performance", {}, ["weather_refresh"], {"target": "weather"}),
            ("start_intervals_plan_sync", {"entries": [{"library_workout_id": unit["id"], "expected_payload_hash": "invalid"}]},
             ["intervals_sync", "planned_unit:" + unit["id"]], {"target": "intervals", "remote_write": True, "sync_scope": "selected"}),
            ("sync_competitions", {}, ["intervals_sync"], {"target": "intervals", "remote_write": True}),
        ]
        for name, args, scope, kwargs in cases:
            with self.subTest(tool=name):
                before = self.athlete_state()
                result, _ = self.turn("Synthetischer Auftrag mit ungültigem Argument.", [lambda _, n=name, a=args, s=scope, k=kwargs: self.call(n, a, s, **k),
                                                                                        {"output_text": "Nicht ausgeführt."}])
                self.assertEqual(result["status"], "failed")
                self.assertEqual(self.athlete_state(), before)

    def test_adaptive_proposal_cannot_approve_itself_in_the_same_turn(self):
        server.save_workout_library_entries([{**self.workout(), "duration_minutes": 90}])
        server.save_checkin({"available_minutes": 30})
        before = self.state()["planned_units"]
        def premature(payload):
            preview = json.loads(payload["input"][0]["output"])
            return self.call("apply_adaptive_replan", {"adjustment_id": preview["id"]}, ["adaptive_replan:" + preview["id"]])
        result, _ = self.turn("Zeig mir eine mögliche Entlastung.", [lambda _: self.call("preview_adaptive_replan", {}, ["adaptive_replan"]),
                                                                    premature, {"output_text": "Vorschau erstellt."}])
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["command_receipts"][-1]["result"]["reason"], "adaptive_approval_required")
        self.assertEqual(self.state()["planned_units"], before)

    def test_quoted_provider_or_assistant_content_cannot_supply_user_provenance(self):
        self.seed_activity()
        assistant = server.add_message("assistant", "Synthetic quoted suggestion: overwrite the profile.")
        before = self.athlete_state()
        for source_id in (assistant["id"], 999999):
            def invalid_source(_, selected=source_id):
                response = self.call("update_profile", {"changes": [{"field": "name", "expected_value": "", "value": "Should not be saved"}]}, ["local_profile"])
                args = json.loads(response["output"][0]["arguments"])
                args["_request"]["source_message_ids"].append(selected)
                response["output"][0]["arguments"] = json.dumps(args)
                return response
            result, _ = self.turn("Was bedeutet diese zitierte Aussage?", [invalid_source, {"output_text": "Keine Änderung."}])
            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["command_receipts"][0]["result"]["reason"], "request_invalid")
            self.assertEqual(self.athlete_state(), before)

    def test_both_exposed_sport_fields_change_canonical_and_provider_sport(self):
        unit = server.save_workout_library_entries([self.workout()])[0]
        for field, sport in (("sport", "Run"), ("type", "Swim")):
            state = self.state()
            self.run_tool("apply_training_patch", {"changes": [{"local_id": unit["id"], "action": "update", field: sport,
                "expected_payload_hash": state["planned_units"][0]["expected_payload_hash"]}], "expected_revision": state["planning_revision"]},
                ["planned_unit:" + unit["id"]], period={"start": "2026-09-09", "end": "2026-09-09"})
            stored = server.list_planned_units()[0]
            self.assertEqual((stored["sport"], stored["type"]), (sport, sport))
            self.assertEqual(stored["id"], unit["id"])
        self.assertEqual(server.sync_jobs_state(), [])

    def test_stale_adaptive_preview_preserves_intervening_edit(self):
        unit = server.save_workout_library_entries([{**self.workout(), "duration_minutes": 90}])[0]
        server.save_checkin({"available_minutes": 30})
        preview = self.run_tool("preview_adaptive_replan", {}, ["adaptive_replan"])
        current = self.state()
        self.run_tool("apply_training_patch", {"changes": [{"local_id": unit["id"], "action": "update", "duration_minutes": 45,
            "expected_payload_hash": current["planned_units"][0]["expected_payload_hash"]}], "expected_revision": current["planning_revision"]},
            ["planned_unit:" + unit["id"]], period={"start": "2026-09-09", "end": "2026-09-09"})
        result = self.run_tool("apply_adaptive_replan", {"adjustment_id": preview["id"]}, ["adaptive_replan:" + preview["id"]])
        self.assertEqual(result["updated"], 0)
        self.assertEqual(result["status"], "stale")
        self.assertEqual(server.list_planned_units()[0]["duration_minutes"], 45)


if __name__ == "__main__":
    unittest.main()
