import unittest

from backend.providers.gemini import function_tools, response_text


class GeminiProviderTests(unittest.TestCase):
    def test_extracts_only_visible_candidate_text(self):
        result = {"candidates": [{"content": {"parts": [{"text": "Hallo"}, {"functionCall": {"name": "x"}}]}}]}
        self.assertEqual(response_text(result), "Hallo")

    def test_translates_function_tools_and_ignores_invalid_entries(self):
        tools = function_tools([{"type": "function", "name": "save", "parameters": {"type": "object"}}, {"type": "text"}])
        self.assertEqual(tools[0]["functionDeclarations"][0]["name"], "save")
        self.assertEqual(function_tools([]), [])


if __name__ == "__main__":
    unittest.main()
