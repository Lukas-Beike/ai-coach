"""Backfill batches read through the Personal API alone, with one cached token."""

from __future__ import annotations

import io
import unittest
from contextlib import nullcontext
from datetime import date
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch
from urllib.parse import urlparse

from backend.providers.garmin_personal import TOKEN_PATH, GarminTransportClient
from backend.sync.garmin_service import GarminRemoteReader

KEY = "synthetic-personal-key"
FIT = b"\x0e\x10\x00\x00\x00\x00\x00\x00.FIT" + b"\x00" * 8
NOW = "2026-11-09T08:00:00+00:00"


class _Response(io.BytesIO):
    status = 200


class FakeApi:
    """The token and file endpoints; counts the key exchanges."""

    def __init__(self) -> None:
        self.token_exchanges = 0

    def __call__(self, request: Any, timeout: float) -> _Response:
        if urlparse(request.full_url).path == TOKEN_PATH:
            self.token_exchanges += 1
            return _Response(b'"header.token.signature"')
        return _Response(FIT)


def make_reader(key: str = KEY) -> GarminRemoteReader:
    """A reader with a Personal key and stored SDK tokens, as in production."""
    config = SimpleNamespace(
        garmin_personal_api_key=key,
        garmin_email="",
        garmin_password="",
        garmin_tokenstore="",
    )
    factory = Mock()
    factory.available.return_value = True
    tokens = Mock()
    tokens.connected.return_value = True
    tokens.disconnected.return_value = False
    tokens.login_argument.return_value = '{"stored": "tokens"}'
    reader = GarminRemoteReader(
        cast(Any, config),
        factory,
        Mock(),
        Mock(),
        lambda value: value,
        Mock(),
        lambda: NOW,
        lambda: date(2026, 11, 9),
        date(2020, 1, 1),
        90,
        -1,
        garmin_tokens=tokens,
    )
    cast(Mock, reader._state_service).personal_key_rejected.return_value = False
    return reader


def refuse_sdk_login() -> Any:
    return patch(
        "backend.sync.garmin_service.garmin_adapter.authenticate_client",
        side_effect=AssertionError("the SDK must not log in"),
    )


class PersonalOnlyBatchTests(unittest.TestCase):
    def assert_personal_only(self, reader: GarminRemoteReader, collector: Mock) -> None:
        client = collector.call_args.args[0]
        self.assertIsInstance(client, GarminTransportClient)
        self.assertIsNone(client.sdk)
        self.assertIsNotNone(client.personal)
        cast(Mock, reader._state_service).record_sdk_skipped.assert_not_called()
        cast(Mock, reader._garmin_tokens).write_back.assert_not_called()

    def test_file_batches_make_no_sdk_login(self) -> None:
        reader = make_reader()
        with (
            refuse_sdk_login(),
            patch("backend.sync.garmin_service.collect_activity_fit_files") as collect,
        ):
            reader.fetch_activity_files(
                ["11"], lambda _id, _data: None, lambda _id: None, nullcontext
            )

        self.assert_personal_only(reader, collect)

    def test_rating_batches_make_no_sdk_login(self) -> None:
        reader = make_reader()
        with (
            refuse_sdk_login(),
            patch("backend.sync.garmin_service.collect_activity_ratings") as collect,
        ):
            reader.fetch_activity_ratings(
                [("11", "")], lambda _row: None, lambda _id: None, nullcontext
            )

        self.assert_personal_only(reader, collect)

    def test_wellness_batches_make_no_sdk_login(self) -> None:
        reader = make_reader()
        with (
            refuse_sdk_login(),
            patch("backend.sync.garmin_service.collect_wellness_history") as collect,
        ):
            reader.fetch_wellness_history(
                date(2026, 11, 1), date(2026, 11, 7), needs_night=lambda _day: True
            )

        self.assert_personal_only(reader, collect)

    def test_a_sync_with_stored_sdk_tokens_still_logs_the_sdk_in(self) -> None:
        reader = make_reader()
        with patch(
            "backend.sync.garmin_service.garmin_adapter.authenticate_client",
            return_value=(Mock(), None),
        ) as login:
            client, _ = reader._authenticated_client(Mock())

        login.assert_called_once()
        self.assertIsNotNone(client.sdk)


class TokenReuseTests(unittest.TestCase):
    def fetch_one_file(self, reader: GarminRemoteReader) -> None:
        files: dict[str, bytes | None] = {}
        reader.fetch_activity_files(
            ["11"], files.__setitem__, lambda _id: None, nullcontext
        )
        self.assertEqual({"11": FIT}, files)

    def test_two_personal_only_jobs_exchange_the_key_once(self) -> None:
        api = FakeApi()
        reader = make_reader()
        with refuse_sdk_login(), patch("backend.providers.http.urlopen", api):
            self.fetch_one_file(reader)
            self.fetch_one_file(reader)

        self.assertEqual(1, api.token_exchanges)

    def test_a_changed_key_builds_a_new_client(self) -> None:
        api = FakeApi()
        reader = make_reader()
        with refuse_sdk_login(), patch("backend.providers.http.urlopen", api):
            self.fetch_one_file(reader)
            cast(Any, reader._config).garmin_personal_api_key = "another-key"
            self.fetch_one_file(reader)

        self.assertEqual(2, api.token_exchanges)

    def test_the_cached_client_reports_key_results_to_the_state(self) -> None:
        api = FakeApi()
        reader = make_reader()
        with refuse_sdk_login(), patch("backend.providers.http.urlopen", api):
            self.fetch_one_file(reader)

        state = cast(Mock, reader._state_service)
        state.record_personal_key_result.assert_called_once_with(True)


if __name__ == "__main__":
    unittest.main()
