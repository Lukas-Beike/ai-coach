import unittest

from backend.coach.conversation import (
    gemini_history_parts_without_raw_media,
    gemini_inline_media_from_history,
    trim_gemini_history,
)


class GeminiHistoryTests(unittest.TestCase):
    def test_trimming_preserves_complete_tool_exchange_boundary(self):
        history = [
            {"role": "user", "parts": [{"text": "Plan"}]},
            {"role": "model", "parts": [{"functionCall": {"name": "save", "args": {}}}]},
            {"role": "user", "parts": [{"functionResponse": {"name": "save", "response": {"ok": True}}}]},
            {"role": "model", "parts": [{"text": "Saved"}]},
        ]
        for index in range(29):
            history.extend([
                {"role": "user", "parts": [{"text": f"Question {index}"}]},
                {"role": "model", "parts": [{"text": f"Answer {index}"}]},
            ])

        trimmed = trim_gemini_history(history)

        self.assertEqual(len(trimmed), 58)
        self.assertEqual(trimmed[0]["parts"][0]["text"], "Question 0")
        self.assertFalse(any("functionResponse" in part for entry in trimmed for part in entry["parts"]))

    def test_retention_keeps_latest_limit_entries(self):
        history = [
            {"role": role, "parts": [{"text": f"{role} {index}"}]}
            for index in range(35)
            for role in ("user", "model")
        ]

        trimmed = trim_gemini_history(history)

        self.assertEqual(len(trimmed), 60)
        self.assertEqual(trimmed[0]["parts"][0]["text"], "user 5")
        self.assertEqual(trimmed[-1]["parts"][0]["text"], "model 34")

    def test_corrupt_suffix_without_user_exchange_is_discarded(self):
        history = [
            {"role": "user", "parts": [{"functionResponse": {"name": "save", "response": {}}}]},
            {"role": "model", "parts": [{"functionCall": {"name": "save", "args": {}}}]},
        ]
        self.assertEqual(trim_gemini_history(history), [])

    def test_invalid_roles_and_parts_do_not_create_boundaries(self):
        history = [
            None,
            {"role": "assistant", "parts": [{"text": "wrong role"}]},
            {"role": "user", "parts": "not a list"},
            {"role": "user", "parts": [None, "text", {"functionResponse": {}}]},
            {"role": "model", "parts": [{"text": "orphan model turn"}]},
        ]
        self.assertEqual(trim_gemini_history(history), [])

    def test_sanitizing_removes_inline_data_and_fit_raw_marker(self):
        parts = [
            {"text": "Keep this prompt"},
            {"inlineData": {"mimeType": "image/png", "data": "secret"}},
            {"text": '{"untrusted_fit_raw_base64":"secret"}'},
            {"text": '{"untrusted_attachment_name":"route.fit"}'},
            "invalid part",
        ]

        self.assertEqual(
            gemini_history_parts_without_raw_media(parts),
            [parts[0], parts[3]],
        )

    def test_inline_media_preserves_truthy_values_and_skips_missing_or_falsy_values(self):
        history = [{"role": "user", "parts": [
            {"inlineData": {"mimeType": "image/png", "data": "iVBORw0KGgo="}},
            {"inlineData": {"mimeType": 12, "data": [1, 2]}},
            {"inlineData": {"mimeType": "image/png", "data": "  "}},
            {"inlineData": {"mimeType": "image/png", "data": ""}},
            {"inlineData": {"mimeType": "", "data": "abc"}},
            {"inlineData": {"data": "abc"}},
            {"inlineData": {"mimeType": "image/png"}},
            None,
        ]}]

        self.assertEqual(
            gemini_inline_media_from_history(history),
            [
                {"mime": "image/png", "data": "iVBORw0KGgo="},
                {"mime": "12", "data": "[1, 2]"},
                {"mime": "image/png", "data": "  "},
            ],
        )


if __name__ == "__main__":
    unittest.main()
