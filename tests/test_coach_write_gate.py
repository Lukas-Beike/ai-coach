"""Coach write gate: a high-recall veto, never a grant of authority."""

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


def _authority(text, previous="", message_id=7, pending_origin=None):
    return gate.build_turn_authority(message_id, text, previous, pending_origin)


def _check(tool, text, previous="", **kwargs):
    authority = _authority(text, previous)
    return gate.check_write(
        tool,
        authority,
        current_text=text,
        previous_assistant_text=previous,
        **kwargs,
    )


class _Classifier:
    def __init__(self, result=frozenset(), error=None):
        self.result = result
        self.error = error
        self.calls = []

    def __call__(self, current_text, previous_assistant_text):
        self.calls.append((current_text, previous_assistant_text))
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
        self.assertEqual(gate.normalize("übernimm"), "uebernimm")


class StemDomainTests(unittest.TestCase):
    PASSING = (
        ("Schieb den Dienstag-Lauf auf Mittwoch", "planning", "planning"),
        ("Mach die lange Einheit am Sonntag kürzer", "planning", "planning"),
        ("Verschiebe das Intervalltraining auf Freitag", "planning", "planning"),
        ("Streich bitte das Schwimmen morgen", "planning", "planning"),
        ("Ersetz den Ruhetag durch eine lockere Einheit", "planning", "planning"),
        ("Plane nächste Woche zwei Radtouren mehr ein", "planning", "planning"),
        ("loesch den Lauf morgen", "planning", "planning"),
        ("Passt, übernimm die Änderungen", "planning", "planning"),
        ("Speichere das als Vorlage", "planning", "manage_training_templates"),
        ("Speichere das als Vorlage", "nutrition", "save_nutrition_template"),
        ("Pass den Trainingsplan an mein Wochenende an", "planning", "planning"),
        ("Ich bin krank", "checkin", "save_checkin"),
        ("Heute schlecht geschlafen", "checkin", "save_checkin"),
        ("Meine HRV war heute Nacht niedrig, Ruhepuls 52", "checkin", "save_checkin"),
        ("Ich fühle mich erkältet, leichtes Fieber", "checkin", "save_checkin"),
        ("Das Training war ein RPE 8", "checkin", "save_activity_feedback"),
        ("Heute fühle ich mich nicht fit.", "checkin", "save_checkin"),
        ("Meine Tagesform ist mies, total schlapp", "checkin", "save_checkin"),
        ("Trag den Halbmarathon in Berlin am 12.4. ein", "competition", "save_competition"),
        ("Meld mich für den Triathlon in Roth an", "competition", "save_competition"),
        ("Das Rennen am 3. Mai streichst du", "competition", "delete_competition"),
        ("Ich wiege jetzt 72 kg", "profile", "update_profile"),
        ("Meine FTP ist 250", "profile", "update_profile"),
        ("Ich habe nur noch 6 Stunden pro Woche Zeit", "profile", "update_profile"),
        ("Mein Ziel ist Sub-3 im Marathon", "profile", "update_profile"),
        ("Neue Schuhe, bitte eintragen", "profile", "save_equipment"),
        ("Frühstück waren 2 Eier", "nutrition", "save_nutrition_entry"),
        ("Zum Mittagessen gab es Nudeln mit Tomatensoße", "nutrition", "save_nutrition_entry"),
        ("Ich habe 600 kcal gegessen", "nutrition", "save_nutrition_entry"),
        ("Neues Produkt: Haferriegel, 120 kcal", "nutrition", "save_nutrition_product"),
        ("Mach das rückgängig", "undo", "undo_training_change"),
        ("Mach das ruckgangig", "undo", "undo_training_change"),
        ("Nimm die letzte Änderung bitte zurück", "undo", None),
        ("Synchronisier den Plan mit Intervals", "remote_intervals", "start_intervals_plan_sync"),
        ("Sync die Wettkämpfe zu Intervals.icu", "remote_intervals", "sync_competitions"),
        ("Übertrag die Ernährung in den Intervals Kalender", "remote_intervals", "sync_nutrition"),
        ("Lösche die Dublette bei Intervals", "remote_intervals", "delete_duplicate_intervals_activity"),
        ("Please move tomorrow's run to Friday", "planning", "stage_training_plan"),
        ("I weigh 72 kg now", "profile", "update_profile"),
        ("I slept badly", "checkin", "save_checkin"),
        ("I feel exhausted today", "checkin", "save_checkin"),
        ("Please undo that", "undo", "undo_training_change"),
    )  # fmt: skip

    def test_expected_domain_is_found(self):
        for text, domain, _tool in self.PASSING:
            with self.subTest(text=text, domain=domain):
                self.assertIn(domain, gate.stem_domains(text))

    def test_write_tools_pass_for_matching_text(self):
        for text, domain, tool in self.PASSING:
            if tool is None:
                continue
            with self.subTest(text=text, tool=tool):
                if tool in gate.TOOL_DOMAIN:
                    self.assertEqual(gate.TOOL_DOMAIN[tool], domain)
                    decision = _check(tool, text)
                    self.assertTrue(decision.allowed, decision)
                    self.assertEqual(decision.reason, "ok")
                    self.assertFalse(decision.classifier_used)

    def test_no_domain_for_chitchat(self):
        for text in ("danke", "super", "👍", "cool", "nice", "Danke dir!", ""):
            with self.subTest(text=text):
                self.assertEqual(gate.stem_domains(text), frozenset())

    def test_word_start_stems_do_not_match_mid_word(self):
        self.assertNotIn("planning", gate.stem_domains("Das ist ein Parade-Beispiel"))
        self.assertNotIn("nutrition", gate.stem_domains("Ich habe es vergessen"))
        self.assertNotIn("profile", gate.stem_domains("Das ist ein Zugriff"))

    def test_intervals_service_does_not_imply_interval_training(self):
        self.assertEqual(gate.stem_domains("intervals"), {"remote_intervals"})


class NegationAndQuestionTests(unittest.TestCase):
    def test_negated_sync_request_grants_no_remote_write(self):
        for text in (
            "Do not sync anything to Intervals",
            "Synchronisier nichts mit Intervals",
            "Bitte nicht zu Intervals hochladen",
            "Don't upload it to Intervals",
            "Lade das doch nicht zu Intervals hoch",
            "Synchronisier den Plan doch nicht",
        ):
            with self.subTest(text=text):
                self.assertNotIn("remote_intervals", gate.requested_domains(text))
                decision = _check(
                    "start_intervals_plan_sync", text, classifier=_Classifier()
                )
                self.assertFalse(decision.allowed)

    def test_information_question_grants_no_domain(self):
        for question in (
            "How can I sync my plan to Intervals?",
            "Wie kann ich meinen Plan zu Intervals synchronisieren?",
        ):
            with self.subTest(text=question):
                self.assertEqual(gate.requested_domains(question), frozenset())
        text = "Wie sieht mein Trainingsplan aus?"
        self.assertEqual(gate.requested_domains(text), frozenset())
        decision = _check("stage_training_plan", text, classifier=_Classifier())
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.classifier_used)

    def test_requests_and_unnegated_clauses_still_grant(self):
        for text, domain in (
            ("Kannst du meinen Plan für nächste Woche anpassen?", "planning"),
            ("Was würdest du an meinem Plan anpassen?", "planning"),
            ("How could you adjust my plan?", "planning"),
            ("Ich kann Dienstag nicht, verschieb den Lauf auf Mittwoch", "planning"),
            ("Nicht zu Intervals hochladen, aber den Plan anpassen", "planning"),
            ("Ach, doch nicht", "undo"),
            ("Ich habe nicht gut geschlafen", "checkin"),
            ("Kein Frühstück heute, nur Kaffee", "nutrition"),
        ):
            with self.subTest(text=text):
                self.assertIn(domain, gate.requested_domains(text))
        self.assertNotIn(
            "remote_intervals",
            gate.requested_domains(
                "Nicht zu Intervals hochladen, aber den Plan anpassen"
            ),
        )

    def test_negated_domain_is_left_to_the_classifier(self):
        text = "Ändere den Plan nicht zu stark, nur die Dauer"
        self.assertNotIn("planning", gate.requested_domains(text))
        decision = _check(
            "stage_training_plan", text, classifier=_Classifier({"planning"})
        )
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.classifier_used)


class DenyWithoutFootingTests(unittest.TestCase):
    def test_thanks_and_praise_deny_every_write(self):
        for text in ("danke", "super", "👍", "top", "cool"):
            for tool in gate.TOOL_DOMAIN:
                with self.subTest(text=text, tool=tool):
                    decision = _check(tool, text)
                    self.assertFalse(decision.allowed)
                    self.assertEqual(decision.reason, "domain_not_requested")
                    self.assertFalse(decision.classifier_used)

    def test_generic_save_needs_clarification(self):
        for text in (
            "speicher das",
            "Speichere das bitte",
            "Trag das ein",
            "Notier dir das",
            "Merk dir das",
            "save this",
        ):
            with self.subTest(text=text):
                authority = _authority(text)
                self.assertTrue(authority.generic_save_without_domain)
                decision = gate.check_write(
                    "save_checkin", authority, current_text=text
                )
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.reason, "generic_save_needs_clarification")

    def test_save_verb_with_domain_is_not_generic(self):
        for text in ("Speichere mein Gewicht: 72 kg", "Trag den Marathon ein"):
            with self.subTest(text=text):
                self.assertFalse(_authority(text).generic_save_without_domain)

    def test_wrong_domain_is_denied(self):
        for tool, text in (
            ("update_profile", "Schieb den Lauf auf Mittwoch"),
            ("save_competition", "Ich bin krank"),
            ("save_nutrition_entry", "Meine FTP ist 250"),
            ("save_checkin", "Trag den Marathon ein"),
            ("undo_training_change", "Ich wiege 72 kg"),
        ):
            with self.subTest(tool=tool):
                decision = _check(tool, text)
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.reason, "domain_not_requested")
                self.assertEqual(decision.domain, gate.TOOL_DOMAIN[tool])

    def test_remote_flags_require_a_named_sync_request(self):
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


class ContinuationTests(unittest.TestCase):
    def test_affirmation_inherits_preceding_assistant_domains(self):
        previous = "Soll ich die Einheit am Dienstag kürzen?"
        for reply in ("ja", "Ja!", "jo", "ok", "Okay", "passt", "gerne", "mach das",
                      "Mach es", "klingt gut", "einverstanden", "yes", "go", "los",
                      "mach", "Ja, bitte"):  # fmt: skip
            with self.subTest(reply=reply):
                authority = _authority(reply, previous)
                self.assertIn("planning", authority.domains)
                self.assertTrue(
                    gate.check_write(
                        "apply_training_patch", authority, current_text=reply
                    ).allowed
                )

    def test_affirmation_after_unrelated_assistant_text_grants_nothing(self):
        authority = _authority("ja", "Schön, dass es dir gut geht!")
        self.assertEqual(authority.domains, frozenset())
        self.assertFalse(
            gate.check_write(
                "apply_training_patch", authority, current_text="ja"
            ).allowed
        )

    def test_negations_never_inherit(self):
        previous = "Soll ich die Einheit am Dienstag kürzen?"
        for reply in ("nein", "doch nicht", "lieber nicht", "nicht jetzt", "no",
                      "ja, lieber nicht", "ja?", "Nein danke", "stopp"):  # fmt: skip
            with self.subTest(reply=reply):
                authority = _authority(reply, previous)
                self.assertNotIn("planning", authority.domains)
                self.assertFalse(gate.is_bare_affirmation(reply))

    def test_long_or_non_affirming_replies_do_not_inherit(self):
        previous = "Soll ich die Einheit am Dienstag kürzen?"
        for reply in (
            "danke",
            "super",
            "Wie lange dauert das?",
            "ja ich glaube schon dass das gut ist",
        ):
            with self.subTest(reply=reply):
                self.assertNotIn("planning", _authority(reply, previous).domains)

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

    def test_pending_origin_merges_for_explicit_retry(self):
        origin = gate.PendingOrigin(3, frozenset({"competition"}))
        authority = _authority("versuch es nochmal", "", pending_origin=origin)
        self.assertEqual(authority.allowed_message_ids, {3, 7})
        self.assertIn("competition", authority.domains)
        self.assertEqual(_authority("hallo").allowed_message_ids, {7})

    def test_answer_to_a_clarification_inherits_the_negated_checkin(self):
        # "nicht" refuses only plan and sync changes, not a check-in statement.
        origin_domains = gate.requested_domains("Heute fühle ich mich nicht fit.")
        self.assertEqual(origin_domains, {"checkin"})
        authority = _authority(
            "Ziemlich schwer.",
            "Wie fühlen sich deine Beine an?",
            pending_origin=gate.PendingOrigin(3, origin_domains),
        )
        decision = gate.check_write(
            "save_checkin", authority, current_text="Ziemlich schwer."
        )
        self.assertTrue(decision.allowed, decision)
        self.assertFalse(
            gate.check_write(
                "stage_training_plan", authority, current_text="Ziemlich schwer."
            ).allowed
        )

    def test_authority_is_frozen(self):
        authority = _authority("ja", "Einheit kürzen?")
        with self.assertRaises(FrozenInstanceError):
            authority.domains = frozenset()
        self.assertFalse(authority.classifier_used)


class ApprovalTests(unittest.TestCase):
    def test_approval_table(self):
        for text, expected in (
            ("ja, übernehmen", True), ("Passt, übernimm die Änderungen", True),
            ("ok", True), ("Okay, freigeben", True), ("bestätigt", True),
            ("anwenden bitte", True), ("einverstanden", True), ("mach", True),
            ("Ja, das passt so", True), ("uebernimm das", True),
            ("danke", False), ("super", False), ("top", False), ("cool", False),
            ("👍", False), ("nice", False), ("Danke, super!", False),
            ("ja?", False), ("Soll ich ja sagen?", False),
            ("nein", False), ("nicht übernehmen", False),
            ("ja, aber nicht die Dienstag-Einheit", False),
            ("doch nicht", False), ("", False),
        ):  # fmt: skip
            with self.subTest(text=text):
                self.assertEqual(gate.is_approval(text), expected)


class ClassifierFallbackTests(unittest.TestCase):
    TEXT = "Ich spiele neuerdings Gitarre"  # no stem in any domain

    def test_not_called_when_stems_hit(self):
        classifier = _Classifier(frozenset({"profile"}))
        decision = _check(
            "save_checkin", "Heute schlecht geschlafen", classifier=classifier
        )
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.classifier_used)
        self.assertEqual(classifier.calls, [])

    def test_not_called_for_ungated_or_unknown_tools(self):
        classifier = _Classifier(frozenset({"profile"}))
        _check("brand_new_write_tool", self.TEXT, classifier=classifier)
        _check("start_provider_refresh", self.TEXT, classifier=classifier)
        self.assertEqual(classifier.calls, [])

    def test_used_on_stem_miss_and_sees_only_typed_and_assistant_text(self):
        classifier = _Classifier(frozenset({"profile"}))
        previous = "Verstanden."
        decision = _check("update_profile", self.TEXT, previous, classifier=classifier)
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.classifier_used)
        self.assertEqual(classifier.calls, [(self.TEXT, previous)])

    def test_classifier_must_contain_the_tools_domain(self):
        classifier = _Classifier(frozenset({"nutrition"}))
        decision = _check("update_profile", self.TEXT, classifier=classifier)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "domain_not_requested")
        self.assertTrue(decision.classifier_used)

    def test_result_is_cached_per_turn_without_mutating_authority(self):
        classifier = _Classifier(frozenset({"profile", "planning"}))
        authority = _authority(self.TEXT)
        state = gate.TurnGateState()
        for tool in ("update_profile", "apply_training_patch", "save_checkin"):
            gate.check_write(
                tool,
                authority,
                state=state,
                classifier=classifier,
                current_text=self.TEXT,
            )
        self.assertEqual(len(classifier.calls), 1)
        self.assertTrue(state.classifier_used)
        self.assertEqual(state.classifier_domains, {"profile", "planning"})
        self.assertEqual(authority.domains, frozenset())
        self.assertFalse(authority.classifier_used)

    def test_a_new_turn_state_calls_the_classifier_again(self):
        classifier = _Classifier(frozenset({"profile"}))
        _check("update_profile", self.TEXT, classifier=classifier)
        _check("update_profile", self.TEXT, classifier=classifier)
        self.assertEqual(len(classifier.calls), 2)

    def test_failures_and_invalid_output_fail_closed(self):
        for label, classifier in (
            ("error", _Classifier(error=RuntimeError("boom"))),
            ("timeout", _Classifier(error=TimeoutError())),
            ("string", _Classifier("profile")),
            ("none", _Classifier(None)),
            ("dict", _Classifier({"domains": ["profile"]})),
            ("unknown", _Classifier(frozenset({"admin", 5}))),
        ):
            with self.subTest(label=label):
                decision = _check("update_profile", self.TEXT, classifier=classifier)
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.reason, "domain_not_requested")

    def test_failure_is_cached_and_not_retried(self):
        classifier = _Classifier(error=RuntimeError("boom"))
        authority = _authority(self.TEXT)
        state = gate.TurnGateState()
        for _ in range(3):
            gate.check_write(
                "update_profile",
                authority,
                state=state,
                classifier=classifier,
                current_text=self.TEXT,
            )
        self.assertEqual(len(classifier.calls), 1)

    def test_remote_intervals_is_never_granted_by_the_classifier(self):
        classifier = _Classifier(frozenset(gate.DOMAINS))
        text = "Schieb den Lauf auf Mittwoch"
        for tool in (
            "start_intervals_plan_sync",
            "sync_competitions",
            "sync_nutrition",
            "resolve_training_sync_conflict",
            "delete_duplicate_intervals_activity",
        ):
            with self.subTest(tool=tool):
                decision = _check(tool, text, classifier=classifier)
                self.assertFalse(decision.allowed)
                self.assertEqual(decision.reason, "domain_not_requested")
        flagged = _check(
            "apply_training_patch",
            text,
            classifier=classifier,
            arguments={"_request": {"remote_write": True}},
        )
        self.assertFalse(flagged.allowed)
        self.assertEqual(classifier.calls, [])

    def test_remote_filtered_from_classifier_output(self):
        classifier = _Classifier(frozenset({"remote_intervals", "profile"}))
        state = gate.TurnGateState()
        gate.check_write(
            "update_profile",
            _authority(self.TEXT),
            state=state,
            classifier=classifier,
            current_text=self.TEXT,
        )
        self.assertEqual(state.classifier_domains, {"profile"})

    def test_generic_save_with_classifier_resolves_or_asks(self):
        text = "speicher das"
        previous = "Dein Frühstück: 2 Eier und Brot."
        authority = _authority(text, previous)
        self.assertTrue(authority.generic_save_without_domain)
        allowed = gate.check_write(
            "save_nutrition_entry",
            authority,
            classifier=_Classifier(frozenset({"nutrition"})),
            current_text=text,
            previous_assistant_text=previous,
        )
        self.assertTrue(allowed.allowed)
        denied = gate.check_write(
            "save_nutrition_entry",
            authority,
            classifier=_Classifier(frozenset()),
            current_text=text,
            previous_assistant_text=previous,
        )
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason, "generic_save_needs_clarification")


class WriteCapTests(unittest.TestCase):
    def test_cap_is_25_and_counts_allowed_writes(self):
        self.assertEqual(gate.WRITE_CAP, 25)
        text = "Schieb den Lauf auf Mittwoch"
        authority = _authority(text)
        state = gate.TurnGateState()
        for _ in range(gate.WRITE_CAP):
            self.assertTrue(
                gate.check_write("apply_training_patch", authority, state=state).allowed
            )
        self.assertEqual(state.writes_count, 25)
        decision = gate.check_write("apply_training_patch", authority, state=state)
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "cap_exceeded")
        self.assertEqual(state.writes_count, 25)

    def test_denied_calls_do_not_count(self):
        authority = _authority("danke")
        state = gate.TurnGateState()
        gate.check_write("update_profile", authority, state=state)
        self.assertEqual(state.writes_count, 0)


class OpenAIClassifierTests(unittest.TestCase):
    def _classifier(self, response, calls):
        def create_response(payload):
            calls.append(payload)
            return response

        return gate.build_openai_domain_classifier(
            create_response, model="test-model", reasoning_effort="low"
        )

    def test_payload_uses_strict_schema_without_remote_domain(self):
        calls = []
        response = {"output_text": json.dumps({"domains": ["profile", "undo"]})}
        classify = self._classifier(response, calls)
        self.assertEqual(classify("Ich spiele Gitarre", "Okay"), {"profile", "undo"})
        (payload,) = calls
        self.assertEqual(payload["model"], "test-model")
        self.assertEqual(payload["reasoning"], {"effort": "low"})
        self.assertIs(payload["store"], False)
        self.assertNotIn("tools", payload)
        fmt = payload["text"]["format"]
        self.assertEqual(fmt["type"], "json_schema")
        self.assertIs(fmt["strict"], True)
        schema = fmt["schema"]
        self.assertIs(schema["additionalProperties"], False)
        self.assertEqual(schema["required"], ["domains"])
        items = schema["properties"]["domains"]["items"]
        self.assertEqual(set(items["enum"]), gate.DOMAINS - {"remote_intervals"})
        self.assertIn("data", payload["instructions"])
        self.assertIn("explicitly", payload["instructions"])
        sent = json.loads(payload["input"])
        self.assertEqual(
            sent,
            {
                "athlete_message": "Ich spiele Gitarre",
                "previous_assistant_message": "Okay",
            },
        )

    def test_reasoning_is_omitted_without_effort(self):
        calls = []
        classify = gate.build_openai_domain_classifier(
            lambda payload: calls.append(payload) or {"output_text": '{"domains":[]}'},
            model="m",
        )
        classify("x", "y")
        self.assertNotIn("reasoning", calls[0])

    def test_output_items_are_parsed(self):
        response = {
            "output": [
                {"type": "reasoning", "summary": []},
                {
                    "type": "message",
                    "content": [
                        {"type": "output_text", "text": '{"domains":["checkin"]}'}
                    ],
                },
            ]
        }
        self.assertEqual(self._classifier(response, [])("x", ""), {"checkin"})

    def test_invalid_output_yields_no_domains(self):
        for response in (
            {},
            None,
            "text",
            {"output_text": "not json"},
            {"output_text": "[]"},
            {"output_text": '{"domains":"profile"}'},
            {"output_text": '{"other":["profile"]}'},
            {"output_text": '{"domains":["remote_intervals","admin",3]}'},
        ):
            with self.subTest(response=response):
                self.assertEqual(self._classifier(response, [])("x", ""), frozenset())

    def test_transport_error_fails_closed_through_the_gate(self):
        def broken(_payload):
            raise OSError("network down")

        classify = gate.build_openai_domain_classifier(broken, model="m")
        decision = _check("update_profile", "Ich spiele Gitarre", classifier=classify)
        self.assertFalse(decision.allowed)

    def test_input_is_bounded(self):
        calls = []
        classify = self._classifier({"output_text": '{"domains":[]}'}, calls)
        classify("a" * 10000, "b" * 10000)
        sent = json.loads(calls[0]["input"])
        self.assertLessEqual(len(sent["athlete_message"]), 2000)
        self.assertLessEqual(len(sent["previous_assistant_message"]), 1200)

    def test_end_to_end_through_the_gate(self):
        classify = self._classifier({"output_text": '{"domains":["profile"]}'}, [])
        decision = _check("update_profile", "Ich spiele Gitarre", classifier=classify)
        self.assertTrue(decision.allowed)
        self.assertTrue(decision.classifier_used)


if __name__ == "__main__":
    unittest.main()
