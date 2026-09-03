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


if __name__ == "__main__":
    unittest.main()
