import base64
import unittest
from unittest.mock import patch

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

    def test_oversize_cursor_is_rejected_before_decoding(self):
        # A valid cursor that only exceeds the 4096-character bound.
        long_value = encode_page_cursor("1" * 5000)
        self.assertGreater(len(long_value), 4096)
        with patch("backend.pagination.json.loads") as loads:
            self.assertIsNone(decode_page_cursor(long_value))
        loads.assert_not_called()
        self.assertEqual(decode_page_cursor(encode_page_cursor("1" * 300)), "1" * 300)

    def test_largest_server_issued_cursors_round_trip(self):
        # 200-character names of 4-byte characters (the worst case) in the
        # planning and library cursor shapes, with a UUID-sized id.
        name = "🚴" * 200
        local_id = "0123456789abcdef0123456789abcdef"
        planning = {
            "revision": 123456789,
            "include_inactive": True,
            "today": "2026-11-10",
            "key": ["2026-11-10", name, local_id],
        }
        library = ["running", name, local_id]
        for value in (planning, library):
            cursor = encode_page_cursor(value)
            self.assertGreater(len(cursor), 512)
            self.assertEqual(decode_page_cursor(cursor), value)

    def test_cursor_decoding_survives_recursion_errors(self):
        cursor = base64.urlsafe_b64encode(b"[" * 380).decode().rstrip("=")
        self.assertLessEqual(len(cursor), 4096)
        with patch("backend.pagination.json.loads", side_effect=RecursionError):
            self.assertIsNone(decode_page_cursor(cursor))

    def test_page_limit_uses_default_and_bounds(self):
        self.assertEqual(api_page_limit(None, 10, 20), 10)
        self.assertEqual(api_page_limit("bad", 10, 20), 10)
        self.assertEqual(api_page_limit(0, 10, 20), 1)
        self.assertEqual(api_page_limit(100, 10, 20), 20)


if __name__ == "__main__":
    unittest.main()
