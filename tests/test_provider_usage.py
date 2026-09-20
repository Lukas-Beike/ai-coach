import json
import unittest
from datetime import date

from backend.providers.usage import daily_summary, recorded_usage, usage_counts


class ProviderUsageTests(unittest.TestCase):
    def test_daily_summary_decodes_valid_state_and_resets_stale_state(self):
        raw = json.dumps({
            "date": "2026-09-19",
            "requests": "2",
            "input_tokens": 3,
            "output_tokens": 4,
            "total_tokens": 7,
            "last_operation": "chat",
            "last_request_at": "2026-09-19T10:00:00Z",
            "ignored": "not returned",
        }).encode()
        summary = daily_summary(raw, today=date(2026, 9, 19), raw_status={"state": "ok"}, raw_rate_limits=[])
        self.assertEqual(summary["date"], "2026-09-19")
        self.assertEqual(summary["requests"], 2)
        self.assertEqual(summary["last_operation"], "chat")
        self.assertEqual(summary["status"], {"state": "ok"})
        self.assertEqual(summary["rate_limits"], {})
        self.assertEqual(
            daily_summary('{"date":"2026-09-18","requests":99}', today="2026-09-19"),
            {"date": "2026-09-19", "requests": 0, "input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "status": {}, "rate_limits": {}},
        )

    def test_usage_counts_supports_provider_wire_shapes_and_safe_fallbacks(self):
        self.assertEqual(
            usage_counts({"usage": {"prompt_tokens": "3", "completion_tokens": 4}}, provider="openai"),
            {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7},
        )
        self.assertEqual(
            usage_counts({"usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 2, "totalTokenCount": 9}}, provider="gemini"),
            {"input_tokens": 5, "output_tokens": 2, "total_tokens": 9},
        )
        self.assertEqual(
            usage_counts({"usage": {"input_tokens": "bad", "output_tokens": float("inf"), "total_tokens": -1}}, provider="openai"),
            {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
        )
        with self.assertRaises(ValueError):
            usage_counts({}, provider="OpenAI")

    def test_recorded_usage_is_non_mutating_and_returns_only_safe_delta(self):
        summary = {
            "date": "2026-09-19",
            "requests": 2,
            "input_tokens": 10,
            "output_tokens": 4,
            "total_tokens": 14,
            "status": {"state": "ok"},
            "rate_limits": {"remaining_tokens": "12"},
        }
        response = {"usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5, "secret": "not copied"}, "output_text": "private"}
        original_summary = json.loads(json.dumps(summary))
        original_response = json.loads(json.dumps(response))
        updated, delta = recorded_usage(summary, response, provider="openai", operation="chat", recorded_at="now")
        self.assertEqual(updated["requests"], 3)
        self.assertEqual(updated["input_tokens"], 13)
        self.assertEqual(updated["output_tokens"], 6)
        self.assertEqual(updated["total_tokens"], 19)
        self.assertEqual(updated["last_operation"], "chat")
        self.assertEqual(updated["last_request_at"], "now")
        self.assertEqual(delta, {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5})
        self.assertEqual(summary, original_summary)
        self.assertEqual(response, original_response)
        self.assertNotIn("secret", json.dumps(updated))
        self.assertNotIn("private", json.dumps(delta))


if __name__ == "__main__":
    unittest.main()
