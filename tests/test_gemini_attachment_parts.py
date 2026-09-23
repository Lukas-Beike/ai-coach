import json
import unittest

from backend.coach.attachments import gemini_history_parts, gemini_selected_raw_attachments


class GeminiAttachmentPartsTests(unittest.TestCase):
    def test_raw_selection_obeys_budget_and_prefers_newest(self):
        messages = [
            [{"type": "image", "data": "aa", "mime": "image/png"}],
            [{"type": "image", "data": "bbb", "mime": "image/png"}],
        ]

        self.assertEqual(gemini_selected_raw_attachments(messages, max_inline_bytes=3), {(1, 0)})
        self.assertEqual(gemini_selected_raw_attachments(messages, max_inline_bytes=5), {(0, 0), (1, 0)})
        self.assertEqual(gemini_selected_raw_attachments(messages, max_inline_bytes=2), {(0, 0)})

    def test_invalid_attachments_are_ignored_and_empty_content_has_no_parts(self):
        invalid = [None, "image", {}, {"type": "video", "data": "x"}]
        self.assertEqual(gemini_selected_raw_attachments([invalid]), set())
        self.assertEqual(gemini_history_parts({"content": "  \n"}, invalid, 0, set()), [])
        self.assertEqual(gemini_history_parts({"content": " hello "}, invalid, 0, set()), [{"text": "hello"}])
        self.assertEqual(gemini_history_parts(
            {"content": "hello"}, [{"type": "image", "data": ""}], 0, set()
        ), [{"text": "hello"}, {"text": json.dumps({"untrusted_attachment_name": None, "raw_image_omitted": True})}])

    def test_gpx_fit_summaries_are_untrusted_and_omitted_raw_files_are_marked(self):
        attachments = [
            {"type": "gpx", "name": "route.gpx", "mime": "application/gpx+xml", "data": "gpx",
             "summary": {"note": "provider data"}},
            {"type": "fit", "name": "ride.fit", "mime": "application/octet-stream", "data": "fit",
             "summary": {"note": "provider data"}},
        ]
        parts = gemini_history_parts({"content": "Review these"}, attachments, 4, set())

        self.assertEqual(parts[0], {"text": "Review these"})
        summaries = [json.loads(parts[index]["text"]) for index in (1, 3)]
        self.assertEqual(summaries, [
            {"untrusted_attachment_name": "route.gpx", "untrusted_gpx": {"note": "provider data"}},
            {"untrusted_attachment_name": "ride.fit", "untrusted_fit": {"note": "provider data"}},
        ])
        markers = [json.loads(parts[index]["text"]) for index in (2, 4)]
        self.assertEqual(markers, [
            {"untrusted_attachment_name": "route.gpx", "raw_file_omitted": True},
            {"untrusted_attachment_name": "ride.fit", "raw_file_omitted": True},
        ])
        self.assertFalse(any("inlineData" in part for part in parts))

    def test_selected_image_is_inlined_and_content_is_trimmed_to_6000(self):
        image = {"type": "image", "name": "chart.png", "mime": "image/png", "data": "encoded"}
        parts = gemini_history_parts({"content": "x" * 6001}, [image], 2, {(2, 0)})

        self.assertEqual(parts[0]["text"], "x" * 6000)
        self.assertEqual(parts[1], {"inlineData": {"mimeType": "image/png", "data": "encoded"}})


if __name__ == "__main__":
    unittest.main()
