import json
import unittest

from backend.coach.intent import intent_request_payload, parse_intent_response


class CoachIntentContractTests(unittest.TestCase):
    def test_schema_request_contains_only_local_refs_and_allowed_targets(self):
        payload = intent_request_payload("Jetzt speichern", [{"id": "artifact-1"}], ["local"])
        self.assertEqual(payload["tools"], [])
        self.assertEqual(payload["tool_choice"], "none")
        self.assertEqual(json.loads(payload["input"]), {
            "message": "Jetzt speichern",
            "artifact_refs": [{"id": "artifact-1"}],
            "allowed_targets": ["local"],
        })
        self.assertNotIn("provider", payload["instructions"])

    def test_parse_intent_accepts_valid_local_action(self):
        result = parse_intent_response({"output_text": json.dumps({
            "intent": "local_action",
            "operation": "stage_training_plan",
            "target_system": "local",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": ["local_plan"],
        })})
        self.assertEqual(result["operation"], "stage_training_plan")
        self.assertEqual(result["target_system"], "local")

    def test_parse_intent_rejects_advice_with_mutating_operation(self):
        with self.assertRaises(ValueError):
            parse_intent_response({"output_text": json.dumps({
                "intent": "advice",
                "operation": "commit_training_plan",
                "target_system": "local",
                "artifact_id": None,
                "ambiguities": [],
                "authorization_scope": [],
            })})

    def test_parse_intent_accepts_explicit_competition_sync_operation(self):
        result = parse_intent_response({"output_text": json.dumps({
            "intent": "remote_sync",
            "operation": "sync_competitions",
            "target_system": "intervals",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": ["local_competitions"],
            "follow_up_operations": [],
        })})
        self.assertEqual(result["operation"], "sync_competitions")
        self.assertEqual(result["target_system"], "intervals")

    def test_parse_intent_accepts_training_plan_update_operation(self):
        result = parse_intent_response({"output_text": json.dumps({
            "intent": "local_action",
            "operation": "update_training_plan",
            "target_system": "local",
            "artifact_id": None,
            "ambiguities": [],
            "authorization_scope": ["training_plan:plan-1"],
            "follow_up_operations": [],
        })})
        self.assertEqual(result["operation"], "update_training_plan")

    def test_contract_supports_checkins_feedback_and_direct_plan_commit(self):
        payload = intent_request_payload("Plane meine Woche", [], ["local"])
        self.assertIn("save_checkin", payload["instructions"])
        self.assertIn("save_activity_feedback", payload["instructions"])
        self.assertIn("commit_training_plan in follow_up_operations", payload["instructions"])
        for operation, scope in (("save_checkin", "local_checkin"), ("save_activity_feedback", "activity_feedback")):
            result = parse_intent_response({"output_text": json.dumps({
                "intent": "local_action",
                "operation": operation,
                "target_system": "local",
                "artifact_id": None,
                "ambiguities": [],
                "authorization_scope": [scope],
                "follow_up_operations": [],
            })})
            self.assertEqual(result["operation"], operation)


if __name__ == "__main__":
    unittest.main()
