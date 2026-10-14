"""Coach write gate: impact tiers, never a grant of authority."""

import json
import unittest
from dataclasses import FrozenInstanceError

from backend.coach import write_gate as gate
from backend.coach.authorization import dialogue_tools
from backend.coach.proposal_models import (
    LOCAL_COACH_WRITE_TOOLS,
    REMOTE_COACH_WRITE_TOOLS,
)
from backend.coach.tool_registry import build_tool_contracts

_DELETE_TOOLS = (
    "delete_competition",
    "delete_activity_feedback",
    "delete_nutrition_entry",
    "delete_nutrition_template",
)


def _authority(text, previous="", message_id=7, pending_origin=None):
    return gate.build_turn_authority(message_id, text, previous, pending_origin)


def _check(tool, text, previous="", **kwargs):
    authority = kwargs.pop("authority", None) or _authority(text, previous)
    return gate.check_write(
        tool,
        authority,
        current_text=text,
        previous_assistant_text=previous,
        **kwargs,
    )


def _verdict(domains=(), delete=False, bulk=False):
    listed = frozenset(domains)
    return gate.ImpactVerdict(
        listed, listed if delete else frozenset(), listed if bulk else frozenset()
    )


class _Classifier:
    def __init__(self, result=gate.NO_IMPACT, error=None):
        self.result = result
        self.error = error
        self.calls = []

    def __call__(self, current_text, previous_assistant_text, origin_text):
        self.calls.append((current_text, previous_assistant_text, origin_text))
        if self.error:
            raise self.error
        return self.result


class RegistryCoverageTests(unittest.TestCase):
    def test_every_non_read_registry_tool_is_gated_or_explicitly_ungated(self):
        _names, structured, read_only, dialogue, _caps = build_tool_contracts(
            default_profile={},
            checkin_text_limits={},
            checkin_score_fields=(),
            training_change_limit=366,
            library_bulk_max_entries=100,
            training_plan_statuses=(),
            dialogue_tools=dialogue_tools,
        )
        names = {tool["name"] for tool in structured + dialogue}
        non_read = names - read_only
        self.assertTrue(non_read)
        self.assertEqual(non_read - set(gate.TOOL_DOMAIN) - gate.UNGATED_TOOLS, set())
        self.assertFalse(set(gate.TOOL_DOMAIN) & gate.UNGATED_TOOLS)
        self.assertFalse(set(gate.TOOL_DOMAIN) & read_only)
        # No stale entries for tools that no longer exist.
        self.assertEqual((set(gate.TOOL_DOMAIN) | gate.UNGATED_TOOLS) - names, set())

    def test_domains_are_known_and_proposal_tools_are_covered(self):
        self.assertLessEqual(set(gate.TOOL_DOMAIN.values()), gate.DOMAINS)
        proposal_tools = REMOTE_COACH_WRITE_TOOLS | LOCAL_COACH_WRITE_TOOLS
        self.assertLessEqual(proposal_tools, set(gate.TOOL_DOMAIN))
        # Remote tools need a named sync; adaptive apply is local unless flagged.
        for tool in REMOTE_COACH_WRITE_TOOLS - {"apply_adaptive_replan"}:
            self.assertEqual(gate.TOOL_DOMAIN[tool], "remote_intervals", tool)
        self.assertEqual(gate.TOOL_DOMAIN["apply_adaptive_replan"], "planning")
        self.assertEqual(gate.TOOL_DOMAIN["undo_training_change"], "undo")
        for tool in _DELETE_TOOLS:
            self.assertIn(tool, gate.TOOL_DOMAIN)

    def test_unknown_non_read_tool_is_denied(self):
        decision = _check("brand_new_write_tool", "Schieb den Lauf auf Mittwoch")
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "unknown_tool")

    def test_refresh_and_control_tools_are_not_gated(self):
        for tool in sorted(gate.UNGATED_TOOLS):
            with self.subTest(tool=tool):
                decision = _check(tool, "danke")
                self.assertTrue(decision.allowed)
                self.assertIsNone(decision.domain)


class NormalizeTests(unittest.TestCase):
    def test_spellings_fold_together(self):
        for left, right in (
            ("Löschen", "loeschen"),
            ("KÜRZER", "kuerzer"),
            ("Frühstück", "fruehstueck"),
            ("Größe", "groesse"),
            ("äöü", "aeoeue"),
            ("  viele   Leerzeichen ", "viele leerzeichen"),
        ):
            with self.subTest(left=left):
                self.assertEqual(gate.normalize(left), gate.normalize(right))

    def test_decomposed_umlauts_match(self):
        self.assertEqual(gate.normalize("übernimm"), "uebernimm")


class LocalTierTests(unittest.TestCase):
    def test_reversible_local_writes_need_no_domain_wording(self):
        local_tools = (
            set(gate.TOOL_DOMAIN)
            - set(_DELETE_TOOLS)
            - {
                "replace_training_plan",
                "commit_training_plan",
            }
        )
        for text in ("danke", "Das war gestern lecker", "👍", ""):
            for tool in sorted(local_tools):
                if gate.TOOL_DOMAIN[tool] == "remote_intervals":
                    continue
                with self.subTest(text=text, tool=tool):
                    decision = _check(tool, text, classifier=_Classifier())
                    self.assertTrue(decision.allowed, decision)
                    self.assertEqual(decision.domain, gate.TOOL_DOMAIN[tool])
                    self.assertFalse(decision.classifier_used)

    def test_a_turn_without_a_stored_athlete_message_writes_nothing(self):
        authority = _authority("Schieb den Lauf auf Mittwoch", message_id=0)
        self.assertFalse(authority.athlete_started)
        decision = gate.check_write("update_profile", authority)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "no_athlete_message")

    def test_small_edits_and_creates_stay_local(self):
        arguments = {
            "changes": [
                {"local_id": "a", "action": "update", "date": "2026-10-15"},
                {"local_id": "b", "action": "restore"},
            ],
            "workouts": [{"date": "2026-10-16"}],
        }
        self.assertEqual(gate.call_impact("apply_training_patch", arguments), set())
        self.assertTrue(
            _check("apply_training_patch", "ok", arguments=arguments).allowed
        )
        create = {"templates": [{"action": "create"}, {"action": "update"}]}
        self.assertTrue(
            _check("manage_training_templates", "ok", arguments=create).allowed
        )
        plan = {"payload": {"plan_id": "p", "name": "Neu", "status": "active"}}
        self.assertTrue(_check("update_training_plan", "ok", arguments=plan).allowed)

    def test_authority_is_frozen(self):
        authority = _authority("ja", "Einheit kürzen?")
        with self.assertRaises(FrozenInstanceError):
            authority.remote_requested = True  # type: ignore[misc]


class DestructiveTierTests(unittest.TestCase):
    def test_delete_tools_need_a_confirmed_delete(self):
        for tool in _DELETE_TOOLS:
            domain = gate.TOOL_DOMAIN[tool]
            with self.subTest(tool=tool):
                self.assertEqual(gate.call_impact(tool, {}), {"delete"})
                self.assertEqual(
                    _check(tool, "weg damit").reason, "impact_not_confirmed"
                )
                for verdict in (
                    _verdict([domain]),
                    _verdict([], delete=True),
                    _verdict(["planning" if domain != "planning" else "profile"], True),
                ):
                    decision = _check(
                        tool, "weg damit", classifier=_Classifier(verdict)
                    )
                    self.assertFalse(decision.allowed)
                    self.assertTrue(decision.classifier_used)
                confirmed = _check(
                    tool, "weg damit", classifier=_Classifier(_verdict([domain], True))
                )
                self.assertTrue(confirmed.allowed, confirmed)

    def test_delete_confirmation_is_bound_to_its_domain(self):
        verdict = gate.ImpactVerdict(
            frozenset({"competition", "nutrition"}), delete=frozenset({"nutrition"})
        )
        mixed = _Classifier(verdict)
        self.assertFalse(_check("delete_competition", "x", classifier=mixed).allowed)
        self.assertTrue(_check("delete_nutrition_entry", "x", classifier=mixed).allowed)
        bulk = _Classifier(
            gate.ImpactVerdict(
                frozenset({"planning", "nutrition"}), bulk=frozenset({"nutrition"})
            )
        )
        self.assertFalse(_check("replace_training_plan", "x", classifier=bulk).allowed)

    def test_archiving_equipment_is_a_delete(self):
        archive = {"status": "archived"}
        self.assertEqual(gate.call_impact("save_equipment", archive), {"delete"})
        self.assertEqual(
            gate.call_impact("save_equipment", {"status": "active"}), set()
        )
        self.assertTrue(_check("save_equipment", "Neues Rad").allowed)
        self.assertFalse(
            _check(
                "save_equipment",
                "Das Rad ist gut",
                arguments=archive,
                classifier=_Classifier(_verdict(["profile"])),
            ).allowed
        )
        self.assertTrue(
            _check(
                "save_equipment",
                "Archivier das alte Rad",
                arguments=archive,
                classifier=_Classifier(_verdict(["profile"], delete=True)),
            ).allowed
        )

    def test_removing_actions_inside_plan_tools_are_deletes(self):
        for tool, arguments in (
            ("apply_training_changes", {"changes": [{"action": "archive"}]}),
            ("apply_training_patch", {"changes": [{"action": "delete"}]}),
            ("manage_training_templates", {"templates": [{"action": "delete"}]}),
            ("manage_training_templates", {"templates": [{"action": "archive"}]}),
            ("update_training_plan", {"payload": {"action": "delete"}}),
            ("update_training_plan", {"payload": {"status": "archived"}}),
        ):
            with self.subTest(tool=tool, arguments=arguments):
                self.assertIn("delete", gate.call_impact(tool, arguments))
                self.assertFalse(
                    _check(
                        tool,
                        "Mach das",
                        arguments=arguments,
                        classifier=_Classifier(_verdict(["planning"])),
                    ).allowed
                )
                self.assertTrue(
                    _check(
                        tool,
                        "Lösch das",
                        arguments=arguments,
                        classifier=_Classifier(_verdict(["planning"], delete=True)),
                    ).allowed
                )

    def test_whole_plan_tools_need_a_confirmed_bulk_change(self):
        for tool in ("replace_training_plan", "commit_training_plan"):
            with self.subTest(tool=tool):
                self.assertEqual(gate.call_impact(tool, {}), {"bulk"})
                self.assertFalse(
                    _check(
                        tool, "ok", classifier=_Classifier(_verdict(["planning"]))
                    ).allowed
                )
                self.assertTrue(
                    _check(
                        tool,
                        "Erstell mir einen Plan für acht Wochen",
                        classifier=_Classifier(_verdict(["planning"], bulk=True)),
                    ).allowed
                )

    def test_many_records_in_one_turn_need_a_confirmed_bulk_change(self):
        week = {"changes": [{"action": "update"}] * gate.BULK_THRESHOLD}
        self.assertEqual(gate.call_impact("apply_training_changes", week), set())
        more = {"changes": [{"action": "update"}] * (gate.BULK_THRESHOLD + 1)}
        self.assertEqual(gate.call_impact("apply_training_changes", more), {"bulk"})
        library = {"entries": [{}] * (gate.BULK_THRESHOLD + 1)}
        self.assertEqual(
            gate.call_impact("apply_workout_library_plan", library), {"bulk"}
        )

        # Small calls add up across the turn.
        authority = _authority("Verschieb alles")
        classifier = _Classifier()
        state = gate.TurnGateState()
        for _ in range(gate.BULK_THRESHOLD):
            self.assertTrue(
                gate.check_write(
                    "update_profile", authority, state=state, classifier=classifier
                ).allowed
            )
        self.assertEqual(state.records_count, gate.BULK_THRESHOLD)
        decision = gate.check_write(
            "update_profile", authority, state=state, classifier=classifier
        )
        self.assertEqual(decision.reason, "impact_not_confirmed")
        self.assertEqual(state.records_count, gate.BULK_THRESHOLD)

    def test_drafts_previews_and_adaptive_apply_count_no_records(self):
        for tool in (
            "stage_training_plan",
            "preview_adaptive_replan",
            "apply_adaptive_replan",
        ):
            with self.subTest(tool=tool):
                self.assertEqual(gate.record_count(tool, {"workouts": [{}] * 50}), 0)
                self.assertEqual(gate.call_impact(tool, {}, 100), set())

    def test_no_classifier_and_failures_fail_closed(self):
        tool = "delete_competition"
        self.assertFalse(_check(tool, "Lösch das Rennen").allowed)
        for classifier in (
            _Classifier(error=RuntimeError("synthetic")),
            _Classifier(result=frozenset({"competition"})),
            _Classifier(result=None),
        ):
            with self.subTest(classifier=classifier.result):
                decision = _check(tool, "Lösch das Rennen", classifier=classifier)
                self.assertFalse(decision.allowed)
                self.assertTrue(decision.classifier_used)

    def test_classifier_runs_once_per_turn_and_only_for_high_impact(self):
        classifier = _Classifier(_verdict(["competition"], delete=True))
        authority = _authority("Lösch das Rennen", "Soll ich es löschen?")
        state = gate.TurnGateState()
        kwargs = {
            "state": state,
            "classifier": classifier,
            "current_text": "Lösch das Rennen",
            "previous_assistant_text": "Soll ich es löschen?",
        }
        self.assertTrue(gate.check_write("update_profile", authority, **kwargs).allowed)
        self.assertEqual(classifier.calls, [])
        self.assertTrue(
            gate.check_write("delete_competition", authority, **kwargs).allowed
        )
        self.assertFalse(
            gate.check_write("delete_nutrition_entry", authority, **kwargs).allowed
        )
        self.assertEqual(
            classifier.calls, [("Lösch das Rennen", "Soll ich es löschen?", "")]
        )
        self.assertFalse(gate.TurnGateState().classifier_used)

    def test_classifier_sees_the_original_pending_request(self):
        classifier = _Classifier(_verdict(["competition"], delete=True))
        origin = gate.PendingOrigin(3, "Lösch den Wettkampf in Roth")
        authority = _authority("Ja, den", "Welchen meinst du?", pending_origin=origin)
        self.assertEqual(authority.allowed_message_ids, {3, 7})
        decision = _check(
            "delete_competition",
            "Ja, den",
            "Welchen meinst du?",
            authority=authority,
            classifier=classifier,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(
            classifier.calls,
            [("Ja, den", "Welchen meinst du?", "Lösch den Wettkampf in Roth")],
        )

    def test_classifier_output_outside_its_domains_is_ignored(self):
        classifier = _Classifier(_verdict(["remote_intervals", "admin"], True, True))
        decision = _check("delete_competition", "x", classifier=classifier)
        self.assertFalse(decision.allowed)


class RemoteTierTests(unittest.TestCase):
    REMOTE = (
        ("Synchronisier den Plan mit Intervals", "start_intervals_plan_sync"),
        ("Sync die Wettkämpfe zu Intervals.icu", "sync_competitions"),
        ("Übertrag die Ernährung in den Intervals Kalender", "sync_nutrition"),
        ("Lösche die Dublette bei Intervals", "delete_duplicate_intervals_activity"),
        ("Kannst du meinen Plan zu Intervals hochladen?", "start_intervals_plan_sync"),
        ("Please upload it to my calendar", "start_intervals_plan_sync"),
        ("Bitte den Konflikt reparieren", "resolve_training_sync_conflict"),
    )

    def test_named_sync_requests_allow_remote_tools_without_the_classifier(self):
        for text, tool in self.REMOTE:
            with self.subTest(text=text):
                self.assertTrue(gate.remote_requested(text))
                classifier = _Classifier()
                decision = _check(tool, text, classifier=classifier)
                self.assertTrue(decision.allowed, decision)
                self.assertEqual(classifier.calls, [])

    def test_unnamed_negated_or_asked_syncs_are_denied(self):
        for text in (
            "Schieb den Lauf auf Mittwoch",
            "danke",
            "Do not sync anything to Intervals",
            "Synchronisier nichts mit Intervals",
            "Bitte nicht zu Intervals hochladen",
            "Don't upload it to Intervals",
            "Lade das doch nicht zu Intervals hoch",
            "How can I sync my plan to Intervals?",
            "Wie kann ich meinen Plan zu Intervals synchronisieren?",
        ):
            with self.subTest(text=text):
                self.assertFalse(gate.remote_requested(text))
                decision = _check(
                    "start_intervals_plan_sync",
                    text,
                    classifier=_Classifier(_verdict(sorted(gate.DOMAINS), True, True)),
                )
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.reason, "remote_not_requested")
                self.assertFalse(decision.classifier_used)

    def test_unnegated_clause_still_requests_the_sync(self):
        self.assertTrue(
            gate.remote_requested("Ändere den Plan nicht, aber sync ihn zu Intervals")
        )
        self.assertFalse(
            gate.remote_requested(
                "Nicht zu Intervals hochladen, aber den Plan anpassen"
            )
        )

    def test_remote_flags_on_local_tools_need_a_named_sync(self):
        text = "Schieb den Lauf auf Mittwoch"
        self.assertTrue(_check("apply_adaptive_replan", text).allowed)
        flagged = {"sync_illness_to_intervals": True}
        self.assertFalse(
            _check("apply_adaptive_replan", text, arguments=flagged).allowed
        )
        remote_request = {"_request": {"remote_write": True}}
        self.assertFalse(
            _check("apply_training_patch", text, arguments=remote_request).allowed
        )
        named = text + " und synchronisier es mit Intervals"
        self.assertTrue(
            _check("apply_adaptive_replan", named, arguments=flagged).allowed
        )
        self.assertTrue(
            _check("apply_training_patch", named, arguments=remote_request).allowed
        )
        local = {"_request": {"remote_write": False}}
        self.assertTrue(_check("apply_training_patch", text, arguments=local).allowed)

    def test_affirmation_inherits_a_sync_offer(self):
        previous = "Soll ich den Plan zu Intervals synchronisieren?"
        for reply in ("ja", "Ja!", "ok", "passt", "mach das", "Ja, bitte", "yes"):
            with self.subTest(reply=reply):
                self.assertTrue(_authority(reply, previous).remote_requested)
        for reply in ("nein", "doch nicht", "lieber nicht", "ja?", "danke",
                      "ja ich glaube schon dass das gut ist"):  # fmt: skip
            with self.subTest(reply=reply):
                self.assertFalse(_authority(reply, previous).remote_requested)
        self.assertFalse(_authority("ja", "Soll ich den Lauf kürzen?").remote_requested)

    def test_pending_origin_carries_a_sync_request(self):
        origin = gate.PendingOrigin(3, "Sync den Plan zu Intervals")
        self.assertTrue(_authority("nochmal", pending_origin=origin).remote_requested)

    def test_bare_affirmation_table(self):
        for text, expected in (
            ("ja", True), ("Jo.", True), ("OK", True), ("okay", True),
            ("passt", True), ("gerne", True), ("mach das", True),
            ("mach es", True), ("klingt gut", True), ("einverstanden", True),
            ("yes", True), ("go", True), ("los", True), ("mach", True),
            ("ja danke", True), ("ja, mach das bitte", True),
            ("danke", False), ("super", False), ("👍", False), ("", False),
            ("nein", False), ("nicht", False), ("doch nicht", False),
            ("lieber nicht", False), ("no", False), ("ja?", False),
            ("mach das nicht", False), ("ja nein", False),
            ("ja, aber nicht am Dienstag", False),
        ):  # fmt: skip
            with self.subTest(text=text):
                self.assertEqual(gate.is_bare_affirmation(text), expected)


class WriteCapTests(unittest.TestCase):
    def test_cap_is_25_and_counts_allowed_writes(self):
        self.assertEqual(gate.WRITE_CAP, 25)
        authority = _authority("Schieb den Lauf auf Mittwoch")
        state = gate.TurnGateState()
        for _ in range(gate.WRITE_CAP):
            self.assertTrue(
                gate.check_write("stage_training_plan", authority, state=state).allowed
            )
        self.assertEqual(state.writes_count, 25)
        decision = gate.check_write("stage_training_plan", authority, state=state)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "cap_exceeded")
        self.assertEqual(state.writes_count, 25)

    def test_denied_calls_do_not_count(self):
        authority = _authority("danke")
        state = gate.TurnGateState()
        gate.check_write("delete_competition", authority, state=state)
        gate.check_write("sync_competitions", authority, state=state)
        self.assertEqual((state.writes_count, state.records_count), (0, 0))


class OpenAIClassifierTests(unittest.TestCase):
    def _classifier(self, response, calls):
        def create_response(payload):
            calls.append(payload)
            return response

        return gate.build_openai_impact_classifier(
            create_response, model="test-model", reasoning_effort="low"
        )

    def test_payload_uses_strict_schema_without_remote_domain(self):
        calls = []
        response = {
            "output_text": json.dumps(
                {
                    "requests": [
                        {"domain": "profile", "delete": True, "bulk": False},
                        {"domain": "undo", "delete": False, "bulk": False},
                    ]
                }
            )
        }
        classify = self._classifier(response, calls)
        self.assertEqual(
            classify("Lösch mein Rad", "Okay", ""),
            gate.ImpactVerdict(
                frozenset({"profile", "undo"}), delete=frozenset({"profile"})
            ),
        )
        (payload,) = calls
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["reasoning"], {"effort": "low"})
        self.assertIs(payload["store"], False)
        self.assertNotIn("tools", payload)
        fmt = payload["text"]["format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertEqual(fmt["name"], "write_impact")
        self.assertIs(fmt["strict"], True)
        schema = fmt["schema"]
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["required"], ["requests"])
        items = schema["properties"]["requests"]["items"]
        self.assertIs(items["additionalProperties"], False)
        self.assertEqual(items["required"], ["domain", "delete", "bulk"])
        self.assertEqual(
            set(items["properties"]["domain"]["enum"]),
            gate.DOMAINS - {"remote_intervals"},
        )
        self.assertIn("data", payload["instructions"])
        self.assertIn("explicitly", payload["instructions"])
        self.assertEqual(
            json.loads(payload["input"]),
            {"athlete_message": "Lösch mein Rad", "previous_assistant_message": "Okay"},
        )

    def test_original_request_is_sent_only_when_present(self):
        calls = []
        classify = self._classifier({"output_text": "{}"}, calls)
        classify("ja", "Welches?", "Lösch das Rennen")
        self.assertEqual(
            json.loads(calls[0]["input"])["original_athlete_request"],
            "Lösch das Rennen",
        )

    def test_reasoning_is_omitted_without_effort(self):
        calls = []
        classify = gate.build_openai_impact_classifier(
            lambda payload: calls.append(payload) or {"output_text": "{}"},
            model="m",
        )
        classify("x", "y", "")
        self.assertNotIn("reasoning", calls[0])

    def test_output_items_are_parsed(self):
        text = '{"requests":[{"domain":"planning","delete":false,"bulk":true}]}'
        response = {
            "output": [
                {"type": "reasoning", "summary": []},
                {"type": "message", "content": [{"type": "output_text", "text": text}]},
            ]
        }
        self.assertEqual(
            self._classifier(response, [])("x", "", ""),
            gate.ImpactVerdict(frozenset({"planning"}), bulk=frozenset({"planning"})),
        )

    def test_invalid_output_confirms_nothing(self):
        for response in (
            {},
            None,
            "text",
            {"output_text": "not json"},
            {"output_text": "[]"},
            {"output_text": '{"requests":"profile"}'},
            {"output_text": '{"domains":["profile"],"delete":true,"bulk":true}'},
            {
                "output_text": '{"requests":[{"domain":"remote_intervals",'
                '"delete":true},{"domain":"admin"},{"domain":["profile"]},3]}'
            },
        ):
            with self.subTest(response=response):
                self.assertEqual(
                    self._classifier(response, [])("x", "", ""), gate.NO_IMPACT
                )
        flags = {
            "output_text": '{"requests":[{"domain":"profile","delete":"yes","bulk":1}]}'
        }
        self.assertEqual(
            self._classifier(flags, [])("x", "", ""),
            gate.ImpactVerdict(frozenset({"profile"})),
        )

    def test_transport_error_fails_closed_through_the_gate(self):
        def broken(_payload):
            raise OSError("network down")

        classify = gate.build_openai_impact_classifier(broken, model="m")
        decision = _check("delete_competition", "Lösch das", classifier=classify)
        self.assertFalse(decision.allowed)

    def test_input_is_bounded(self):
        calls = []
        classify = self._classifier({"output_text": "{}"}, calls)
        classify("a" * 10000, "b" * 10000, "c" * 10000)
        sent = json.loads(calls[0]["input"])
        self.assertLessEqual(len(sent["athlete_message"]), 2000)
        self.assertLessEqual(len(sent["previous_assistant_message"]), 1200)
        self.assertLessEqual(len(sent["original_athlete_request"]), 2000)

    def test_end_to_end_through_the_gate(self):
        classify = self._classifier(
            {
                "output_text": '{"requests":[{"domain":"competition",'
                '"delete":true,"bulk":false}]}'
            },
            [],
        )
        decision = _check("delete_competition", "Lösch das Rennen", classifier=classify)
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.classifier_used)


if __name__ == "__main__":
    unittest.main()
