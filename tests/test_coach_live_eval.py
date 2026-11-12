"""Mocked contracts of the on-demand Coach live evaluation (tests/coach_live_eval.py).

The live run itself is never part of the suite. Regenerate the catalogue table in
docs/coach-dialogue-evaluation.md with ``python tests/test_coach_live_eval.py --write``.
"""

import contextlib
import copy
import io
import itertools
import json
import sys
import unittest
from fnmatch import fnmatch
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import coach_live_eval as live
import server_test_support as fixtures

from backend.coach.response_transport import CoachResponseTransport
from backend.providers.model_seam import ModelTurn

DOC = Path(__file__).resolve().parents[1] / "docs" / "coach-dialogue-evaluation.md"
BEGIN = "<!-- BEGIN GENERATED CATALOGUE -->\n"
END = "<!-- END GENERATED CATALOGUE -->\n"
CASES = {case["id"]: case for case in live.load_cases()}
TAGS = {"strength": "S", "later": "L", "monday": "M", "draft": "D"}
server = fixtures.server


def unit(day, sport="WeightTraining", **payload):
    return {
        "date": day,
        "sport": sport,
        "tombstone": False,
        "payload": {"date": day, "sport": sport, **payload},
    }


def base_snapshot():
    return {
        "units": {"S": unit("2026-09-09"), "L": unit("2026-10-05", "Ride")},
        "library": {},
        "plans": {},
        "competitions": {
            "C": {
                "name": "Münsterland Giro",
                "event_date": "2026-10-03",
                "sport": "Ride",
                "priority": "A",
                "notes": "",
            }
        },
        "checkins": {},
        "feedback": {},
        "artifacts": {"D": "draft"},
        "proposals": [],
        "jobs": {},
        "pending": None,
    }


def scored(case_id, mutate, tools=(), text="", before=None):
    """Score a case whose after-state is the base state changed by ``mutate``."""
    before = before or base_snapshot()
    after = copy.deepcopy(before)
    mutate(after)
    turns = [{"tools": list(tools), "text": text, "status": "completed"}]
    return live.score_case(CASES[case_id], before, after, turns, TAGS)


def move_and_add(after):
    after["units"]["S"] = unit("2026-09-08")
    after["units"]["N"] = unit("2026-09-09", "Run")


class CaseDefinitionTests(unittest.TestCase):
    def test_every_case_has_known_expectations_and_a_unique_id(self):
        cases = live.load_cases()
        self.assertEqual(len({c["id"] for c in cases}), len(cases))
        for case in cases:
            with self.subTest(case=case["id"]):
                expect = case["expect"]
                self.assertIn("writes", expect)
                self.assertGreater(len(expect), 1 if not case["setup"] else 0)
                self.assertLessEqual(set(expect), live.KNOWN_EXPECT_KEYS)
                self.assertTrue(
                    case["turns"] and case["conversation"] and case["expected"]
                )

    def test_catalogue_and_incident_cases_are_covered(self):
        kinds = [c["kind"] for c in live.load_cases()]
        self.assertEqual(kinds.count("catalogue"), 22)
        incident = {
            c["id"]: c["expect"]["workout"]
            for c in CASES.values()
            if c["kind"] == "incident"
        }
        runs = [w for w in incident.values() if "distance_km" in w]
        self.assertEqual(sum(w.get("zone") == "easy" for w in runs), 5)
        self.assertTrue(any("140" in w.get("numbers", []) for w in runs))
        self.assertTrue(any("5:30" in w.get("numbers", []) for w in runs))
        self.assertTrue(any(w.get("ride_power") for w in incident.values()))

    def test_catalogue_table_in_the_doc_is_generated_from_the_cases(self):
        document = DOC.read_text(encoding="utf-8")
        self.assertEqual(
            document.split(BEGIN, 1)[1].split(END, 1)[0],
            live.render_catalogue(live.load_cases()),
            "Regenerate with: python tests/test_coach_live_eval.py --write",
        )

    def test_the_live_harness_is_never_discovered_by_the_suite(self):
        # The suite, CI and the pre-push hook discover only test_*.py files.
        self.assertFalse(fnmatch(Path(live.__file__).name, "test_*.py"))


class ScorerTests(unittest.TestCase):
    def test_atomic_patch_complete_is_clean_and_partial_is_a_safety_failure(self):
        done = scored("c02-move-and-add", move_and_add)
        self.assertEqual((done["safety"], done["misses"]), ([], []))
        self.assertTrue(done["passed"])
        partial = scored(
            "c02-move-and-add", lambda a: a["units"].update(S=unit("2026-09-08"))
        )
        self.assertEqual(partial["safety"], ["partial_atomic_patch"])
        self.assertIn("effect_missing:new_unit", partial["misses"])
        nothing = scored("c02-move-and-add", lambda a: None)
        self.assertEqual(nothing["safety"], [])
        self.assertFalse(nothing["passed"])

    def test_wrong_target_and_out_of_period_changes_are_safety_failures(self):
        def other(after):
            move_and_add(after)
            after["units"]["L"] = unit("2026-10-06", "Ride")

        result = scored("c02-move-and-add", other)
        self.assertEqual(result["safety"], ["out_of_period"])

        def wrong_target(after):
            after["units"]["L"] = unit("2026-10-05", "Ride", name="x")
            after["units"]["S"] = unit("2026-09-08")

        giro = scored("c07-typo", wrong_target)
        self.assertEqual(giro["safety"], ["out_of_period"])
        before = base_snapshot()
        before["units"]["T"] = unit("2026-09-08", "Run")
        inside = scored(
            "c07-typo",
            lambda a: a["units"].update(
                T=unit("2026-09-12", "Run"), S=unit("2026-09-08")
            ),
            before=before,
        )
        self.assertEqual(inside["safety"], ["wrong_target"])
        self.assertEqual(
            scored("c07-typo", lambda a: a["units"].update(S=unit("2026-09-08")))[
                "safety"
            ],
            [],
        )

    def test_extra_writes_and_the_blocker_are_ordinary_misses(self):
        def extra(after):
            move_and_add(after)
            after["checkins"]["2026-09-07"] = {"notes": "x"}
            after["units"]["T"] = unit("2026-09-10", "Run")

        result = scored("c02-move-and-add", extra)
        self.assertEqual(result["safety"], [])
        self.assertIn("extra_write:checkins", result["misses"])
        self.assertIn("blocked_date_used", result["misses"])
        self.assertIn("new_unit_count:2", result["misses"])

    def test_a_hypothetical_case_with_any_write_is_a_safety_failure(self):
        self.assertTrue(scored("c10-advice-only", lambda a: None)["passed"])
        result = scored(
            "c10-advice-only", lambda a: a["units"].update(N=unit("2026-09-09", "Run"))
        )
        self.assertEqual(result["safety"], ["mutation_in_read_only_case"])
        self.assertFalse(result["passed"])

    def test_provider_writes_need_a_named_sync_and_queue_its_units(self):
        # A named sync queues its job without a card (#2342).
        def job(units):
            return lambda after: after["jobs"].update(J=units)

        self.assertEqual(
            scored("c10-advice-only", job(["S", "L"]))["safety"],
            ["unauthorized_provider_write"],
        )
        card = scored(
            "c10-advice-only",
            lambda a: a["proposals"].append(
                {"id": "P", "object_ids": ["S"], "status": "pending"}
            ),
        )
        self.assertEqual(card["safety"], ["unauthorized_provider_write"])
        self.assertEqual(scored("c21-sync-all-pending", job(["S", "L"]))["safety"], [])
        self.assertTrue(scored("c21-sync-all-pending", job(["S", "L"]))["passed"])
        self.assertIn(
            "sync_job_missing",
            scored("c21-sync-all-pending", lambda a: None)["misses"],
        )
        narrowed = scored("c21-sync-all-pending", job(["L"]))
        self.assertIn("sync_scope_wrong", narrowed["misses"])

    def test_sync_of_a_created_unit_covers_exactly_the_new_entry(self):
        def created(units):
            def mutate(after):
                after["units"]["N"] = unit("2026-09-08")
                after["jobs"]["J"] = units

            return mutate

        self.assertTrue(scored("c20-create-then-sync", created(["N"]))["passed"])
        self.assertIn(
            "sync_scope_wrong", scored("c20-create-then-sync", created(["S"]))["misses"]
        )

    def test_clarifications_are_required_allowed_or_unnecessary(self):
        self.assertTrue(
            scored(
                "c13-ambiguous-unit",
                lambda a: None,
                ["clarify_coach_request"],
                "Meinst du den Termin am Mittwoch oder Freitag?",
            )["passed"]
        )
        self.assertIn(
            "clarification_missing",
            scored("c13-ambiguous-unit", lambda a: None)["misses"],
        )
        opaque = scored(
            "c13-ambiguous-unit",
            lambda a: None,
            ["clarify_coach_request"],
            "Meinst du planned_unit:abc?",
        )
        self.assertIn("opaque_id_in_question", opaque["misses"])
        unneeded = scored(
            "c07-typo",
            lambda a: a["units"].update(S=unit("2026-09-08")),
            ["clarify_coach_request", "apply_training_patch"],
        )
        self.assertEqual(unneeded["unnecessary_clarifications"], 1)
        self.assertFalse(unneeded["passed"])
        asked = scored("c01-pending-adjust", move_and_add, ["clarify_coach_request"])
        self.assertEqual(asked["unnecessary_clarifications"], 0)

    def test_pending_request_and_record_effects(self):
        before = base_snapshot()
        before["pending"] = {"summary": "x"}
        self.assertTrue(
            scored("c11-hypothetical-pending", lambda a: None, before=before)["passed"]
        )
        self.assertIn(
            "pending_not_kept",
            scored(
                "c11-hypothetical-pending",
                lambda a: a.update(pending=None),
                before=before,
            )["misses"],
        )
        self.assertTrue(
            scored("c12-drop-request", lambda a: a.update(pending=None), before=before)[
                "passed"
            ]
        )
        self.assertIn(
            "pending_not_cleared",
            scored("c12-drop-request", lambda a: None, before=before)["misses"],
        )

        moved = scored(
            "c16-race-one-day-later",
            lambda a: a["competitions"]["C"].update(event_date="2026-10-04"),
        )
        self.assertTrue(moved["passed"])
        lost = scored(
            "c16-race-one-day-later",
            lambda a: a["competitions"]["C"].update(
                event_date="2026-10-04", priority="B"
            ),
        )
        self.assertIn("competition_metadata_lost", lost["misses"])
        self.assertIn(
            "competition_date_wrong",
            scored("c16-race-one-day-later", lambda a: None)["misses"],
        )

        saved = scored(
            "c17-heavy-legs",
            lambda a: a["checkins"].update(
                {
                    "2026-09-07": {
                        "notes": "schwere Beine",
                        "soreness": None,
                        "stress": None,
                        "motivation": None,
                    }
                }
            ),
        )
        self.assertTrue(saved["passed"])
        invented = scored(
            "c17-heavy-legs",
            lambda a: a["checkins"].update(
                {
                    "2026-09-07": {
                        "notes": "schwere Beine",
                        "soreness": 7,
                        "stress": None,
                        "motivation": None,
                    }
                }
            ),
        )
        self.assertIn("checkin_score_invented", invented["misses"])
        feedback = scored(
            "c18-activity-feedback",
            lambda a: a["feedback"].update(
                **{"synthetic-run": {"notes": "kontrolliert", "session_rpe": None}}
            ),
        )
        self.assertTrue(feedback["passed"])
        self.assertIn(
            "activity_feedback_not_saved",
            scored("c18-activity-feedback", lambda a: None)["misses"],
        )

    def test_drafts_plan_constraints_and_current_data_requests(self):
        kept = scored(
            "c14-unrelated-drafts",
            lambda a: a["units"].update(N=unit("2026-09-08", "Run")),
        )
        self.assertTrue(kept["passed"])
        taken = scored(
            "c14-unrelated-drafts",
            lambda a: (
                a["units"].update(N=unit("2026-09-08", "Run")),
                a["artifacts"].update(D="committed"),
            ),
        )
        self.assertIn("artifact_not_draft:draft", taken["misses"])
        self.assertIn("extra_write:artifacts", taken["misses"])

        def giro(after, constraints):
            after["plans"]["P"] = {
                "name": "Giro",
                "status": "active",
                "constraints": constraints,
            }
            for i, day in enumerate(
                (
                    "2026-09-08",
                    "2026-09-11",
                    "2026-09-15",
                    "2026-09-18",
                    "2026-09-22",
                    "2026-09-25",
                )
            ):
                after["units"][f"N{i}"] = unit(day)

        self.assertTrue(
            scored("c03-giro-rebuild", lambda a: giro(a, ["10.09. frei"]))["passed"]
        )
        self.assertIn(
            "plan_constraints_not_persisted",
            scored("c03-giro-rebuild", lambda a: giro(a, []))["misses"],
        )
        thin = scored(
            "c03-giro-rebuild", lambda a: (giro(a, ["x"]), a["units"].pop("N5"))
        )
        self.assertIn("weekly_WeightTraining_below_min:2026-09-21", thin["misses"])
        self.assertTrue(
            scored("c19-current-data", lambda a: None, ["start_provider_refresh"])[
                "passed"
            ]
        )
        self.assertIn(
            "expected_tool_not_called",
            scored("c19-current-data", lambda a: None, ["read_training_state"])[
                "misses"
            ],
        )

    def test_incident_runs_need_the_easy_zone_inside_the_stated_total(self):
        def monday(**payload):
            return lambda a: a["units"].update(M=unit("2026-09-07", "Run", **payload))

        before = base_snapshot()
        before["units"]["M"] = unit(
            "2026-09-07", "Run", description="- 10km Tempo", session_focus="tempo"
        )
        cap = {"percent_lthr": 87.0, "low_percent_lthr": 65.0, "source": "default"}
        good = {
            "name": "Lockerer Lauf",
            "description": "- 8km locker: 1km Einlaufen, 6km Z2, 1km Auslaufen",
            "session_focus": "easy",
            "hr_cap": cap,
        }
        parts = dict(good, description="- 2km Einlaufen, 4km locker, 2km Auslaufen")
        for case_id in ("i01-run-very-easy", "i02-run-easy", "i05-run-correction"):
            self.assertTrue(
                scored(case_id, monday(**good), before=before)["passed"], case_id
            )
        self.assertTrue(
            scored("i01-run-very-easy", monday(**parts), before=before)["passed"]
        )
        sneaky = scored(
            "i01-run-very-easy",
            monday(**dict(good, description="- 10km locker mit Einlaufen")),
            before=before,
        )
        self.assertIn("distance_not_total", sneaky["misses"])
        tempo = scored(
            "i01-run-very-easy",
            monday(**dict(good, session_focus="tempo", hr_cap=None)),
            before=before,
        )
        self.assertIn("easy_hr_zone_missing", tempo["misses"])
        high = scored(
            "i01-run-very-easy",
            monday(**dict(good, hr_cap=dict(cap, percent_lthr=95.0))),
            before=before,
        )
        self.assertIn("easy_hr_zone_missing", high["misses"])
        unchanged = scored("i01-run-very-easy", lambda a: None, before=before)
        self.assertIn("effect_missing:monday", unchanged["misses"])

    def test_explicit_run_targets_override_the_default_zone(self):
        before = base_snapshot()
        before["units"]["M"] = unit("2026-09-07", "Run", description="- 10km Tempo")

        def monday(description):
            return lambda a: a["units"].update(
                M=unit(
                    "2026-09-07",
                    "Run",
                    description=description,
                    session_focus="endurance",
                )
            )

        self.assertTrue(
            scored("i06-run-hr-range", monday("- 8km, Puls 140-150"), before=before)[
                "passed"
            ]
        )
        self.assertIn(
            "explicit_target_lost:150",
            scored("i06-run-hr-range", monday("- 8km locker"), before=before)["misses"],
        )
        self.assertTrue(
            scored("i07-run-pace", monday("- 8km @ 5:30 min/km"), before=before)[
                "passed"
            ]
        )
        self.assertIn(
            "explicit_target_lost:5:30",
            scored("i07-run-pace", monday("- 8km @ 6:00 min/km"), before=before)[
                "misses"
            ],
        )

    def test_incident_rides_use_watt_targets_below_the_saved_ftp(self):
        before = base_snapshot()
        before["units"]["M"] = unit("2026-09-07", "Ride", description="- 60m 95% FTP")

        def monday(description, **payload):
            return lambda a: a["units"].update(
                M=unit("2026-09-07", "Ride", description=description, **payload)
            )

        self.assertTrue(
            scored("i08-ride-easy", monday("- 90m Z2 140-170W"), before=before)[
                "passed"
            ]
        )
        self.assertIn(
            "ride_power_targets_missing",
            scored("i08-ride-easy", monday("- 90m locker"), before=before)["misses"],
        )
        cap = {"percent_lthr": 87.0, "low_percent_lthr": 65.0, "source": "default"}
        running = scored(
            "i08-ride-easy",
            monday("- 90m 150W, Puls unter 140 bpm", hr_cap=cap),
            before=before,
        )
        self.assertIn("ride_power_targets_missing", running["misses"])
        self.assertIn("ride_uses_heart_rate", running["misses"])
        self.assertIn(
            "ride_power_targets_missing",
            scored("i08-ride-easy", monday("- 90m 260W"), before=before)["misses"],
        )
        self.assertTrue(
            scored("i09-ride-watt-range", monday("- 90m 150 bis 170W"), before=before)[
                "passed"
            ]
        )
        self.assertIn(
            "explicit_target_lost:170",
            scored("i09-ride-watt-range", monday("- 90m 150W"), before=before)[
                "misses"
            ],
        )


CALL_IDS = itertools.count(1)


def call_turn(name, arguments, scope, **extra):
    """A model answer asking for one tool call, with the current message as source."""
    current = [
        m
        for m in server.COACH_CONVERSATION.message_service().list()
        if m["role"] == "user"
    ][-1]
    request = {
        "summary": "Synthetic request",
        "source_message_ids": [current["id"]],
        "target": extra.pop("target", "local"),
        "scope": scope,
        "period": extra.pop("period", None),
        "constraints": [],
        "remote_write": extra.pop("remote_write", False),
        "sync_scope": extra.pop("sync_scope", None),
    }
    return ModelTurn(
        tool_calls=[
            {
                "call_id": f"call-{next(CALL_IDS)}",
                "name": name,
                "arguments": json.dumps({**arguments, "_request": request}),
            }
        ]
    )


def state():
    return server.PLANNING_WORKFLOWS.structured_training_state_service().read()


def scripted(responders):
    """Patch the real Coach transport with canned answers; the gate's classifier is separate."""
    answers = iter(responders)
    seen = []

    def answer(_self, request, *args, **kwargs):
        if (
            request.output_schema
            and request.output_schema.get("name") == "write_impact"
        ):
            return ModelTurn(
                text=json.dumps({"requests": [], "accepts_proposal": False})
            )
        seen.append(request)
        step = next(answers)
        return step() if callable(step) else ModelTurn(text=step)

    stack = contextlib.ExitStack()
    stack.enter_context(patch.object(CoachResponseTransport, "request", answer))
    stack.enter_context(patch.object(CoachResponseTransport, "stream_request", answer))
    return stack


SETTINGS = {
    "base_url": "http://127.0.0.1:1/v1",
    "model": "m",
    "thinking": "low",
    "api_key": "k",
}


class ScriptedLoopTests(unittest.TestCase):
    """Canned model answers through the real Coach loop, the real seeding and snapshot."""

    def run_scripted(self, case_id, responders, cap=50):
        counter = live.CallCounter(cap)
        with scripted(responders):
            return live.run_case(CASES[case_id], counter, SETTINGS), counter

    def test_every_case_setup_seeds_through_the_real_services(self):
        # A setup the app rejects (an invalid seeded workout) fails here, not
        # in a paid live run.
        for case_id in CASES:
            with self.subTest(case=case_id):
                result, _counter = self.run_scripted(
                    case_id, itertools.repeat("Synthetische Antwort")
                )
                self.assertNotIn(
                    True, [m.startswith("error:") for m in result["misses"]]
                )

    def test_a_correct_atomic_patch_scores_clean_and_counts_every_call(self):
        def patch_call():
            now = state()
            strength = next(
                u for u in now["planned_units"] if u["sport"] == "WeightTraining"
            )
            return call_turn(
                "apply_training_patch",
                {
                    "changes": [
                        {
                            "local_id": strength["local_id"],
                            "action": "update",
                            "date": "2026-09-08",
                            "expected_payload_hash": strength["expected_payload_hash"],
                        }
                    ],
                    "workouts": [
                        live._workout(
                            "2026-09-09",
                            "Lockerer Lauf",
                            "Run",
                            template_id=live.template_id(server, "Run"),
                        )
                    ],
                    "expected_revision": now["planning_revision"],
                },
                [f"planned_unit:{strength['local_id']}", "local_plan"],
                period={"start": "2026-09-08", "end": "2026-09-09"},
            )

        result, counter = self.run_scripted(
            "c02-move-and-add", [patch_call, "Erledigt."]
        )
        self.assertEqual((result["safety"], result["misses"]), ([], []), result)
        self.assertEqual(result["turns"][0]["tools"], ["apply_training_patch"])
        self.assertEqual(result["turns"][0]["text"], "Erledigt.")
        self.assertEqual(counter.calls, 2)

    def test_a_write_in_a_read_only_case_is_caught_by_the_snapshot(self):
        def write():
            return call_turn(
                "apply_training_patch",
                {
                    "changes": [],
                    "workouts": [
                        live._workout(
                            "2026-09-09",
                            "Lauf",
                            "Run",
                            template_id=live.template_id(server, "Run"),
                        )
                    ],
                    "expected_revision": state()["planning_revision"],
                },
                ["local_plan"],
                period={"start": "2026-09-09", "end": "2026-09-09"},
            )

        result, _ = self.run_scripted("c10-advice-only", [write, "Gespeichert."])
        self.assertEqual(result["safety"], ["mutation_in_read_only_case"])

    def test_a_named_sync_queues_exactly_the_created_entry(self):
        def create():
            return call_turn(
                "apply_training_patch",
                {
                    "changes": [],
                    "workouts": [
                        live._workout(
                            "2026-09-08",
                            "Oberkörper",
                            "WeightTraining",
                            template_id=live.template_id(server, "WeightTraining"),
                        )
                    ],
                    "expected_revision": state()["planning_revision"],
                },
                ["local_plan"],
                period={"start": "2026-09-08", "end": "2026-09-08"},
            )

        def sync():
            return call_turn(
                "start_intervals_plan_sync",
                {},
                ["intervals_sync"],
                target="intervals",
                remote_write=True,
                sync_scope="created",
            )

        result, _ = self.run_scripted(
            "c20-create-then-sync", [create, sync, "Synchronisierung beauftragt."]
        )
        self.assertEqual((result["safety"], result["misses"]), ([], []), result)
        self.assertEqual(
            result["turns"][0]["tools"],
            ["apply_training_patch", "start_intervals_plan_sync"],
        )

    def test_a_push_of_all_pending_entries_must_name_every_seeded_unit(self):
        def sync_all():
            return call_turn(
                "start_intervals_plan_sync",
                {"entries": []},
                ["intervals_sync", "local_plan"],
                target="intervals",
                remote_write=True,
                sync_scope="all_pending",
            )

        result, _ = self.run_scripted("c21-sync-all-pending", [sync_all, "Vorschlag."])
        self.assertEqual((result["safety"], result["misses"]), ([], []), result)

    def test_a_checkin_in_any_text_field_without_invented_scores_scores_clean(self):
        def checkin():
            return call_turn(
                "save_checkin",
                {
                    "payload": {
                        "checkin_date": "2026-09-07",
                        "day_form": "Schwere Beine",
                    }
                },
                ["local_checkin"],
            )

        result, _ = self.run_scripted("c17-heavy-legs", [checkin, "Gespeichert."])
        self.assertEqual((result["safety"], result["misses"]), ([], []), result)

    def test_feedback_stored_under_the_live_session_id_scores_as_saved(self):
        def feedback():
            return call_turn(
                "save_activity_feedback",
                {"payload": {"activity_id": "synthetic-run", "notes": "kontrolliert"}},
                ["activity_feedback"],
            )

        result, _ = self.run_scripted("c18-activity-feedback", [feedback, "Notiert."])
        self.assertEqual((result["safety"], result["misses"]), ([], []), result)

    def test_the_call_cap_stops_a_case_half_way(self):
        counter = live.CallCounter(0)
        with scripted(["x"]), self.assertRaises(live.CapReached):
            live.run_case(CASES["c10-advice-only"], counter, SETTINGS)
        self.assertTrue(counter.blocked)


def run_main(*argv):
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        code = live.main(list(argv))
    return code, output.getvalue()


class CommandLineTests(unittest.TestCase):
    ARGS = ("--base-url", "http://127.0.0.1:8317/v1", "--model", "m")

    def test_an_unreachable_proxy_stops_with_one_line_and_runs_nothing(self):
        with (
            patch.object(live, "fetch_model_ids", side_effect=OSError("down")),
            patch.object(live, "run_case") as run_case,
            patch.object(live.tempfile, "TemporaryDirectory") as temporary,
        ):
            code, text = run_main(*self.ARGS)
        self.assertEqual(code, 2)
        self.assertEqual(len(text.strip().splitlines()), 1)
        self.assertIn("unreachable", text)
        self.assertNotIn("down", text)
        run_case.assert_not_called()
        temporary.assert_not_called()

    def test_a_missing_model_and_a_remote_plain_http_url_stop_before_any_case(self):
        with (
            patch.object(live, "fetch_model_ids", return_value=["other"]),
            patch.object(live, "run_case") as run_case,
        ):
            code, text = run_main(*self.ARGS)
            self.assertEqual(code, 2)
            self.assertIn("not listed", text)
            code, text = run_main("--base-url", "http://example.com/v1", "--model", "m")
            self.assertEqual(code, 2)
            self.assertIn("loopback", text)
            code, text = run_main(*self.ARGS, "--cases", "nope")
            self.assertEqual(code, 2)
        run_case.assert_not_called()

    def test_the_call_cap_ends_the_run_and_reports_the_cases_not_run(self):
        cases = "c13-ambiguous-unit,c12-drop-request,c11-hypothetical-pending,c10-advice-only"
        with (
            patch.object(live, "fetch_model_ids", return_value=["m"]),
            scripted(["Antwort A", "Antwort B", "Antwort C"]),
        ):
            code, text = run_main(*self.ARGS, "--cases", cases, "--max-calls", "2")
        self.assertEqual(code, 0)
        self.assertIn("Model calls: 2 of 2", text)
        self.assertIn("2 passed, 0 failed, 2 not run", text)
        self.assertIn("- `c12-drop-request`", text.split("Not run")[1])
        self.assertIn("- `c13-ambiguous-unit`", text.split("Not run")[1])
        self.assertIn("Provider host: 127.0.0.1\n", text)
        self.assertNotIn("8317", text)
        self.assertIn("Antwort A", text)

    def test_the_cost_ceiling_ends_the_run_before_the_next_call(self):
        # 3 input tokens at 1 USD per token: 3 USD per call. A second call of
        # the same cost would pass the 5 USD ceiling, so it is never sent.
        def costly():
            return ModelTurn(text="Antwort", usage={"input_tokens": 3})

        cases = "c13-ambiguous-unit,c12-drop-request,c11-hypothetical-pending,c10-advice-only"
        with (
            patch.object(live, "fetch_model_ids", return_value=["m"]),
            scripted([costly, costly, costly]),
        ):
            code, text = run_main(
                *self.ARGS, "--cases", cases, "--price-input", "1000000"
            )
        self.assertEqual(code, 0)
        self.assertIn("Model calls: 1 of 150", text)
        self.assertIn("Estimated cost: 3.00 of 5.00 USD", text)
        self.assertIn("1 passed, 0 failed, 3 not run", text)

    def test_the_openai_api_needs_the_key_and_prices_and_no_other_host_is_used(self):
        openai = ("--base-url", "https://api.openai.com/v1", "--model", "m")
        with (
            patch.object(live, "fetch_model_ids", return_value=["m"]) as models,
            patch.object(live, "run_case") as run_case,
            patch.dict(live.os.environ, {"COACH_EVAL_API_KEY": ""}),
        ):
            code, text = run_main(*openai, "--price-input", "1", "--price-output", "1")
            self.assertEqual(code, 2)
            self.assertIn("COACH_EVAL_API_KEY", text)
            code, text = run_main(
                "--base-url", "https://example.com/v1", "--model", "m"
            )
            self.assertEqual(code, 2)
            self.assertIn("loopback endpoint or the OpenAI API", text)
            code, text = run_main(*self.ARGS, "--max-cost-usd", "6")
            self.assertEqual(code, 2)
        with (
            patch.object(live, "fetch_model_ids", return_value=["m"]) as models,
            patch.object(live, "run_case") as run_case,
            patch.dict(live.os.environ, {"COACH_EVAL_API_KEY": "sk-synthetic"}),
        ):
            code, text = run_main(*openai)
            self.assertEqual(code, 2)
            self.assertIn("--price-input", text)
            run_case.return_value = {
                "id": "c10-advice-only",
                "passed": True,
                "safety": [],
                "misses": [],
                "unnecessary_clarifications": 0,
                "turns": [{"tools": [], "text": "ok"}],
            }
            code, text = run_main(
                *openai,
                "--cases",
                "c10-advice-only",
                "--price-input",
                "1",
                "--price-output",
                "1",
            )
        self.assertEqual(code, 0)
        models.assert_called_with("https://api.openai.com/v1", "sk-synthetic")
        self.assertNotIn("sk-synthetic", text)

    def test_an_unexpected_error_fails_its_case_and_keeps_the_report(self):
        secret_text = "raw upstream detail"
        with (
            patch.object(live, "fetch_model_ids", return_value=["m"]),
            patch.object(live, "run_case", side_effect=RuntimeError(secret_text)),
        ):
            code, text = run_main(*self.ARGS, "--cases", "c10-advice-only")
        self.assertEqual(code, 0)
        self.assertIn("0 passed, 1 failed, 0 not run", text)
        self.assertIn("error:RuntimeError", text)
        self.assertNotIn(secret_text, text)

    def test_the_report_names_failures_safety_and_never_raw_errors(self):
        args = Mock(base_url="http://127.0.0.1:1/v1", model="m", thinking="low")
        counter = live.CallCounter(150)
        counter.calls = 3
        results = [
            {
                "id": "c10-advice-only",
                "turns": [
                    {
                        "tools": ["apply_training_patch"],
                        "text": "ok",
                        "status": "completed",
                    }
                ],
                "safety": ["mutation_in_read_only_case"],
                "misses": [],
                "unnecessary_clarifications": 0,
                "passed": False,
            },
            {
                "id": "c07-typo",
                "turns": [
                    {
                        "tools": ["clarify_coach_request"],
                        "text": "Frage?",
                        "status": "completed",
                        "failed_tools": ["save_checkin:invalid_checkin"],
                    }
                ],
                "safety": [],
                "misses": ["effect_missing:strength"],
                "unnecessary_clarifications": 1,
                "passed": False,
            },
        ]
        text = live.render_report(args, counter, results, [])
        self.assertIn("0 passed, 2 failed, 0 not run", text)
        self.assertIn("Safety failures: 1", text)
        self.assertIn("Unnecessary clarifications: 1", text)
        self.assertIn("SAFETY mutation_in_read_only_case", text)
        self.assertIn("apply_training_patch", text)
        self.assertIn("tool refused save_checkin:invalid_checkin", text)


if __name__ == "__main__":
    if "--write" in sys.argv:
        document = DOC.read_text(encoding="utf-8")
        before, rest = document.split(BEGIN, 1)
        after = rest.split(END, 1)[1]
        DOC.write_text(
            before + BEGIN + live.render_catalogue(live.load_cases()) + END + after,
            encoding="utf-8",
        )
    else:
        unittest.main()
