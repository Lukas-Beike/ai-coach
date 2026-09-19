import unittest

from backend.providers.http import (
    error_detail,
    json_request_parts,
    multipart_form_data,
    read_bounded_response,
    read_error_body,
    request_body,
)


class ProviderHTTPTests(unittest.TestCase):
    def test_request_body_requires_exactly_one_body_source(self):
        self.assertEqual(request_body({"ü": "ja"}, None), b'{"\\u00fc": "ja"}')
        self.assertEqual(request_body(None, b"raw"), b"raw")
        self.assertIsNone(request_body(None, None))
        with self.assertRaises(ValueError):
            request_body({}, b"raw")

    def test_json_request_parts_builds_safe_request_and_context(self):
        request, parsed_url, headers, context = json_request_parts(
            "post",
            "https://example.test/api/v1/resource?id=secret&blank=",
            payload={"name": "synthetic"},
            headers={"X-Test": "yes"},
            timeout=12,
            service="synthetic",
            content_type="application/custom+json",
            app_version="1.2.3",
            operation_context={"operation_id": "op-1", "trigger": "test", "phase": "wire"},
        )
        self.assertEqual(request.data, b'{"name": "synthetic"}')
        self.assertEqual(parsed_url.netloc, "example.test")
        self.assertEqual(headers["Accept"], "application/json")
        self.assertEqual(headers["User-Agent"], "IntervalsCoach/1.2.3")
        self.assertEqual(headers["Content-Type"], "application/custom+json")
        self.assertEqual(context["service"], "synthetic")
        self.assertEqual(context["method"], "POST")
        self.assertEqual(context["query_keys"], ["blank", "id"])
        self.assertEqual(context["request_bytes"], len(request.data))
        self.assertEqual(
            {key: context[key] for key in ("operation_id", "trigger", "phase")},
            {"operation_id": "op-1", "trigger": "test", "phase": "wire"},
        )
        self.assertNotIn("secret", context.values())

    def test_json_request_parts_does_not_add_content_type_without_body(self):
        _, _, headers, context = json_request_parts(
            "get",
            "https://example.test/resource",
            content_type="application/custom+json",
            app_version="1.2.3",
        )
        self.assertNotIn("Content-Type", headers)
        self.assertEqual(context["request_bytes"], 0)

    def test_json_request_parts_derives_phase_when_context_omits_it(self):
        _, _, _, context = json_request_parts(
            "post",
            "https://example.test/api/v1/resource",
            raw_body=b"raw",
            app_version="1.2.3",
            operation_context={"operation_id": "op-1", "trigger": "test"},
        )
        self.assertEqual(context["phase"], "resource")

    def test_read_error_body_bounds_and_closes_sized_response(self):
        class Response:
            def __init__(self):
                self.closed = False
                self.read_size = None

            def read(self, size):
                self.read_size = size
                return b"012345"

            def close(self):
                self.closed = True

        response = Response()
        self.assertEqual(read_error_body(response, 3), b"0123")
        self.assertEqual(response.read_size, 4)
        self.assertTrue(response.closed)

    def test_read_error_body_bounds_fakes_without_read_size_and_closes(self):
        class Response:
            def __init__(self):
                self.closed = False

            def read(self):
                return b"012345"

            def close(self):
                self.closed = True

        response = Response()
        self.assertEqual(read_error_body(response, 3), b"0123")
        self.assertTrue(response.closed)

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
