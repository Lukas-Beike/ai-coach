import unittest

from backend.providers.openai import response_failure_reason, response_text


class OpenAIProviderTests(unittest.TestCase):
    def test_response_failure_reason_is_pure(self):
        self.assertEqual(response_failure_reason("/responses", None), "invalid_response")
        self.assertEqual(response_failure_reason("/responses", {"status": "failed"}), "response_failed")
        self.assertEqual(response_failure_reason("/responses", {"status": "mystery"}), "invalid_response_status")
        self.assertEqual(response_failure_reason("/models", {"status": "mystery"}), None)

    def test_response_text_supports_direct_and_nested_output(self):
        self.assertEqual(response_text({"output_text": "  hello  "}), "hello")
        self.assertEqual(response_text({"output": [{"type": "message", "content": [
            {"type": "output_text", "text": "hello"},
            {"type": "refusal", "refusal": "no"},
        ]}]}), "hello\nThe coach declined to answer: no")
        self.assertEqual(response_text({"output": [{"type": "message", "content": [
            {"type": "output_text", "text": {"secret": "must not display"}},
        ]}]}), "")


if __name__ == "__main__":
    unittest.main()
