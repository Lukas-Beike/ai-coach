import unittest

from backend.providers.http import (
    error_detail,
    multipart_form_data,
    read_bounded_response,
)


class ProviderHTTPTests(unittest.TestCase):
    def test_multipart_form_data_has_deterministic_exact_wire_bytes(self):
        body, content_type = multipart_form_data(
            [("model", "gpt-transcribe"), ("languages[]", "de")],
            "file",
            "voice.webm",
            "audio/webm",
            b"\x00\xffaudio\r\n",
            boundary_token="test-boundary",
        )
        boundary = b"----IntervalsCoachtest-boundary"
        expected = (
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="model"\r\n\r\n'
            b"gpt-transcribe\r\n"
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="languages[]"\r\n\r\n'
            b"de\r\n"
            b"--" + boundary + b"\r\n"
            b'Content-Disposition: form-data; name="file"; filename="voice.webm"\r\n'
            b"Content-Type: audio/webm\r\n\r\n"
            b"\x00\xffaudio\r\n"
            b"\r\n--" + boundary + b"--\r\n"
        )
        self.assertEqual(body, expected)
        self.assertEqual(content_type, "multipart/form-data; boundary=----IntervalsCoachtest-boundary")

    def test_multipart_form_data_default_boundary_has_expected_prefix_and_hex_token(self):
        body, content_type = multipart_form_data([], "file", "voice.mp3", "audio/mpeg", b"audio")
        self.assertRegex(content_type, r"^multipart/form-data; boundary=----IntervalsCoach[0-9a-f]{32}$")
        boundary = content_type.split("=", 1)[1].encode("ascii")
        self.assertTrue(body.startswith(b"--" + boundary + b"\r\n"))
        self.assertTrue(body.endswith(b"\r\n--" + boundary + b"--\r\n"))

    def test_read_bounded_response_rejects_oversized_body(self):
        class Response:
            def read(self, size):
                return b"1234"

        with self.assertRaises(ValueError):
            read_bounded_response(Response(), 3)

    def test_error_detail_is_redacted_and_bounded(self):
        raw = b'{"error":{"message":"authorization: bearer secret-token"}}'
        self.assertEqual(error_detail(raw), "authorization: [REDACTED]")
        self.assertEqual(error_detail(b'{"error":"Invalid workout type"}'), "Invalid workout type")
        self.assertEqual(error_detail(b'{"error":{},"message":"top-level detail"}'), "top-level detail")


if __name__ == "__main__":
    unittest.main()
