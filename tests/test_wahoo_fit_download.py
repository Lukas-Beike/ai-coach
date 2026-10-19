"""Read-only Wahoo FIT download: URL trust, request shape, reasons and leaks.

Every test uses a fake opener and a placeholder URL; no network is used.
"""

from __future__ import annotations

import io
import unittest
from email.message import Message
from unittest import mock
from urllib.error import HTTPError, URLError

from backend.providers import wahoo_fit_download as download
from backend.providers.wahoo_fit_download import (
    WAHOO_FIT_REASONS,
    WahooFitUnavailable,
    download_wahoo_fit,
    wahoo_fit_url,
)

URL = "https://cdn.wahooligan.com/w.fit?sig=placeholder"
FORBIDDEN_TEXT = ("sig=placeholder", "w.fit", "cdn.wahooligan.com")


class FakeResponse:
    def __init__(
        self, body: bytes = b"fit-bytes", *, read_error: BaseException | None = None
    ) -> None:
        self.body = body
        self.read_error = read_error
        self.closed = 0

    def read(self, size: int = -1) -> bytes:
        if self.read_error is not None:
            raise self.read_error
        return self.body if size is None or size < 0 else self.body[:size]

    def close(self) -> None:
        self.closed += 1


class WahooFitUrlTests(unittest.TestCase):
    def test_summary_file_url_is_returned_only_when_it_is_text(self) -> None:
        self.assertEqual(URL, wahoo_fit_url({"file": {"url": URL}}))
        self.assertIsNone(wahoo_fit_url({"file": {}}))
        self.assertIsNone(wahoo_fit_url({"file": {"url": 5}}))
        self.assertIsNone(wahoo_fit_url({}))
        self.assertIsNone(wahoo_fit_url(None))
        self.assertIsNone(wahoo_fit_url("file"))


class WahooFitDownloadTests(unittest.TestCase):
    def assert_no_url_text(self, error: BaseException) -> None:
        text = " ".join([str(error), repr(error), *map(str, error.args)])
        for part in FORBIDDEN_TEXT:
            self.assertNotIn(part, text)
        self.assertIsNone(error.__cause__)
        self.assertIsNone(error.__context__)

    def test_trusted_host_is_accepted_in_any_case_with_trailing_dot(self) -> None:
        response = FakeResponse()
        opener = mock.Mock(return_value=response)
        url = "https://CDN.WAHOOLIGAN.COM./w.fit?sig=placeholder"

        self.assertEqual(b"fit-bytes", download_wahoo_fit(url, opener=opener))
        opener.assert_called_once()

    def test_untrusted_urls_never_reach_the_opener(self) -> None:
        untrusted = [
            "http://cdn.wahooligan.com/w.fit?sig=placeholder",
            "ftp://cdn.wahooligan.com/w.fit?sig=placeholder",
            "https://evil.example.com/w.fit?sig=placeholder",
            "https://cdn.wahooligan.com.evil.example.com/w.fit?sig=placeholder",
            "https://cdn.wahooligan.com:8443/w.fit?sig=placeholder",
            "https://user@cdn.wahooligan.com/w.fit?sig=placeholder",
            "https://cdn.wahooligan.com/w.fit?sig=placeholder#fragment",
            "https://cdn.wahooligan.com/w.fit?sig=pl\r\nX-Injected: 1",
            "https://cdn.wahooligan.com/w .fit?sig=placeholder",
            " https://cdn.wahooligan.com/w.fit?sig=placeholder",
            "",
        ]
        for url in untrusted:
            with self.subTest(url=url[:12]):
                opener = mock.Mock(return_value=FakeResponse())
                with self.assertRaises(WahooFitUnavailable) as caught:
                    download_wahoo_fit(url, opener=opener)
                self.assertEqual("untrusted_url", caught.exception.reason)
                opener.assert_not_called()
                self.assert_no_url_text(caught.exception)

    def test_non_text_url_is_untrusted(self) -> None:
        opener = mock.Mock(return_value=FakeResponse())
        with self.assertRaises(WahooFitUnavailable) as caught:
            download_wahoo_fit(None, opener=opener)  # type: ignore[arg-type]
        self.assertEqual("untrusted_url", caught.exception.reason)
        opener.assert_not_called()

    def test_request_is_a_plain_get_with_only_accept_and_user_agent(self) -> None:
        response = FakeResponse()
        opener = mock.Mock(return_value=response)

        download_wahoo_fit(URL, opener=opener)

        request, timeout = opener.call_args.args
        self.assertEqual(URL, request.full_url)
        self.assertEqual("GET", request.get_method())
        self.assertIsNone(request.data)
        header_names = {name.casefold() for name in request.headers}
        self.assertLessEqual(header_names, {"accept", "user-agent"})
        self.assertNotIn("authorization", header_names)
        self.assertEqual(download.FIT_DOWNLOAD_TIMEOUT_SECONDS, timeout)

    def test_successful_response_is_closed_once(self) -> None:
        response = FakeResponse(b"abc")
        self.assertEqual(
            b"abc", download_wahoo_fit(URL, opener=mock.Mock(return_value=response))
        )
        self.assertEqual(1, response.closed)

    def test_http_statuses_map_to_reasons_without_leaking_the_url(self) -> None:
        cases = {
            429: "rate_limited",
            403: "rejected",
            404: "rejected",
            500: "unavailable",
            503: "unavailable",
        }
        for status, reason in cases.items():
            with self.subTest(status=status):
                error = HTTPError(
                    URL, status, "Status text", Message(), io.BytesIO(b"")
                )
                with self.assertRaises(WahooFitUnavailable) as caught:
                    download_wahoo_fit(URL, opener=mock.Mock(side_effect=error))
                self.assertEqual(reason, caught.exception.reason)
                self.assertIn(reason, WAHOO_FIT_REASONS)
                self.assert_no_url_text(caught.exception)

    def test_transport_failures_map_to_unavailable(self) -> None:
        failures = [URLError(URL), TimeoutError(URL), OSError(URL)]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                with self.assertRaises(WahooFitUnavailable) as caught:
                    download_wahoo_fit(URL, opener=mock.Mock(side_effect=failure))
                self.assertEqual("unavailable", caught.exception.reason)
                self.assert_no_url_text(caught.exception)

    def test_read_failure_maps_to_unavailable_and_closes_the_response(self) -> None:
        response = FakeResponse(read_error=TimeoutError(URL))
        with self.assertRaises(WahooFitUnavailable) as caught:
            download_wahoo_fit(URL, opener=mock.Mock(return_value=response))
        self.assertEqual("unavailable", caught.exception.reason)
        self.assertEqual(1, response.closed)
        self.assert_no_url_text(caught.exception)

    def test_oversized_body_maps_to_too_large_and_closes_the_response(self) -> None:
        response = FakeResponse(b"0123456789")
        with (
            mock.patch.object(download, "MAX_WAHOO_FIT_BYTES", 4),
            self.assertRaises(WahooFitUnavailable) as caught,
        ):
            download_wahoo_fit(URL, opener=mock.Mock(return_value=response))
        self.assertEqual("too_large", caught.exception.reason)
        self.assertEqual(1, response.closed)
        self.assert_no_url_text(caught.exception)

    def test_size_limit_is_the_documented_sixteen_mebibytes(self) -> None:
        self.assertEqual(16 * 1024 * 1024, download.MAX_WAHOO_FIT_BYTES)
        self.assertEqual(30, download.FIT_DOWNLOAD_TIMEOUT_SECONDS)
        self.assertEqual({"cdn.wahooligan.com"}, set(download.WAHOO_FIT_HOSTS))


if __name__ == "__main__":
    unittest.main()
