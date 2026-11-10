"""Yazio, Open Food Facts and Wahoo FIT requests are observed without leaking URLs."""

from __future__ import annotations

import io
import json
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

from backend.errors import AppError
from backend.providers.observed_opener import observed_opener
from backend.providers.open_food_facts import OpenFoodFactsClient
from backend.providers.wahoo_fit_download import (
    WahooFitUnavailable,
    download_wahoo_fit,
)
from backend.providers.yazio import YazioClient
from backend.sync.wahoo_sync_assembly import WahooSyncAssembly
from tests.test_yazio import config

SIGNED = "https://cdn.wahooligan.com/private/fake-signed-path/w.fit?Signature=fake-sig"


def observe(service, inner, *, include_path=True):
    logger, capture = Mock(), Mock()
    opener = observed_opener(
        service,
        logger=logger,
        diagnostic_capture=capture,
        operation_context=lambda: {"operation_id": "op1", "trigger": "manual"},
        include_path=include_path,
        opener=inner,
    )
    return opener, logger, capture


def events(capture):
    return {call.args[0]: call.args[1] for call in capture.capture.call_args_list}


class ObservedOpenerTests(unittest.TestCase):
    def test_a_failure_is_recorded_with_its_class_and_raised_unchanged(self):
        error = HTTPError("https://x.invalid/", 503, "fake-body-secret", {}, None)
        self.addCleanup(error.close)
        inner = Mock(side_effect=error)
        opener, logger, capture = observe("yazio", inner)
        request = Mock(full_url="https://yzapi.invalid/v1/products/search?q=fake")
        request.get_method.return_value = "GET"

        with self.assertRaises(HTTPError) as raised:
            opener(request, 10)

        self.assertIs(raised.exception, error)
        failed = events(capture)["external_http_failed"]
        self.assertEqual(failed["exception_type"], "HTTPError")
        self.assertEqual(failed["error"]["status"], 503)
        self.assertEqual(failed["host"], "yzapi.invalid")
        self.assertEqual(failed["trigger"], "manual")
        self.assertEqual(
            logger.warning.call_args.kwargs["extra"]["event"], "external_request_failed"
        )
        serialized = json.dumps(
            [events(capture), logger.mock_calls[-1].kwargs], default=str
        )
        for private in ("fake-body-secret", "q=fake"):
            self.assertNotIn(private, serialized)

    def test_a_success_records_start_and_status(self):
        response = io.BytesIO(b"{}")
        response.status = 200
        opener, _logger, capture = observe(
            "open_food_facts", Mock(return_value=response)
        )
        request = Mock(full_url="https://world.invalid/api/v3/product/12345678")
        request.get_method.return_value = "GET"

        self.assertIs(opener(request, 10), response)

        recorded = events(capture)
        self.assertEqual(
            set(recorded), {"external_http_started", "external_http_completed"}
        )
        self.assertEqual(recorded["external_http_completed"]["status"], 200)
        self.assertNotIn("12345678", json.dumps(recorded))


class ObservedClientsTests(unittest.TestCase):
    def test_a_yazio_failure_is_captured_and_still_classified_by_the_client(self):
        opener, _logger, capture = observe(
            "yazio", Mock(side_effect=URLError("fake-network-secret"))
        )
        client = YazioClient(lambda: config(), opener=opener)

        result = client.check_connection()

        self.assertEqual(result["status"], "unavailable")
        failed = events(capture)["external_http_failed"]
        self.assertEqual(failed["service"], "yazio")
        self.assertEqual(failed["exception_type"], "URLError")
        self.assertNotIn("fake-network-secret", json.dumps(events(capture)))

    def test_an_open_food_facts_failure_is_captured_and_still_classified(self):
        opener, _logger, capture = observe(
            "open_food_facts", Mock(side_effect=URLError("down"))
        )
        client = OpenFoodFactsClient(opener=opener)

        with self.assertRaises(AppError) as raised:
            client.product("12345678")

        self.assertEqual(raised.exception.reason, "food_database_unavailable")
        failed = events(capture)["external_http_failed"]
        self.assertEqual(failed["service"], "open_food_facts")
        self.assertEqual(failed["exception_type"], "URLError")

    def test_a_wahoo_fit_failure_is_captured_without_the_signed_url(self):
        error = HTTPError(SIGNED, 403, "fake-body-secret", {}, None)
        self.addCleanup(error.close)
        opener, logger, capture = observe(
            "wahoo", Mock(side_effect=error), include_path=False
        )

        with self.assertRaises(WahooFitUnavailable) as raised:
            download_wahoo_fit(SIGNED, opener=opener)

        self.assertEqual(raised.exception.reason, "rejected")
        failed = events(capture)["external_http_failed"]
        self.assertEqual(failed["exception_type"], "HTTPError")
        self.assertEqual(failed["error"]["status"], 403)
        self.assertNotIn("path", failed)
        serialized = json.dumps([events(capture), logger.mock_calls], default=str)
        for private in ("fake-signed-path", "fake-sig", "fake-body-secret"):
            self.assertNotIn(private, serialized)

    def test_the_wahoo_assembly_downloads_through_the_observed_opener(self):
        opener, _logger, capture = observe(
            "wahoo", Mock(side_effect=URLError("down")), include_path=False
        )
        assembly = WahooSyncAssembly(Mock(fit_opener=lambda: opener))

        with self.assertRaises(WahooFitUnavailable):
            assembly.fit_download()(SIGNED)

        self.assertIn("external_http_failed", events(capture))


if __name__ == "__main__":
    unittest.main()
