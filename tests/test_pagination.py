import unittest

from backend.http_api.pagination import (
    api_page_limit,
    decode_page_cursor,
    encode_page_cursor,
)


class PaginationTests(unittest.TestCase):
    def test_cursor_round_trip_preserves_unicode_and_structure(self):
        value = {"name": "Laufen 🚴", "key": ["2026-09-20", "a", "id"]}

        self.assertEqual(decode_page_cursor(encode_page_cursor(value)), value)

    def test_invalid_or_empty_cursor_decodes_to_none(self):
        self.assertIsNone(decode_page_cursor(None))
        self.assertIsNone(decode_page_cursor("not-a-cursor"))

    def test_page_limit_uses_default_and_bounds(self):
        self.assertEqual(api_page_limit(None, 10, 20), 10)
        self.assertEqual(api_page_limit("bad", 10, 20), 10)
        self.assertEqual(api_page_limit(0, 10, 20), 1)
        self.assertEqual(api_page_limit(100, 10, 20), 20)


if __name__ == "__main__":
    unittest.main()
