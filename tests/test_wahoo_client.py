"""Wahoo read transport with a mocked HTTP callable: paging, refresh, failures."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from backend.errors import AppError
from backend.providers.wahoo_client import (
    MAX_WORKOUT_PAGES,
    WORKOUTS_PER_PAGE,
    WahooClient,
    WahooReconnectRequiredError,
    WahooRetryableError,
)

ACCESS = "access-token-SENTINEL"
REFRESHED = "refreshed-token-SENTINEL"
SINCE = datetime(2026, 10, 1, tzinfo=UTC)


def workout(number: int, *, days: float = 5.0) -> dict[str, Any]:
    started = SINCE + timedelta(days=days) - timedelta(minutes=number)
    return {"id": number, "starts": started.isoformat(), "workout_type_id": 0}


def page_of(count: int, *, first: int = 1, days: float = 5.0) -> dict[str, Any]:
    return {"workouts": [workout(first + index, days=days) for index in range(count)]}


def upstream(status: int, retry_after: int | None = None) -> AppError:
    return AppError(
        502,
        "Upstream failed",
        reason="upstream_rejected",
        upstream_status=status,
        retry_after_seconds=retry_after,
    )


class ClientCase(unittest.TestCase):
    def setUp(self) -> None:
        self.request = Mock()
        self.refresh = Mock(return_value=REFRESHED)
        self.invalidate = Mock()
        self.client = WahooClient(
            request=self.request,
            access_token=lambda: ACCESS,
            refresh_access_token=self.refresh,
            invalidate_access_token=self.invalidate,
        )

    def assertSecretFree(self, error: BaseException) -> None:
        text = f"{error!s} {error!r} {vars(error)!r}"
        for secret in (ACCESS, REFRESHED):
            self.assertNotIn(secret, text)

    def query(self, call: Any) -> dict[str, list[str]]:
        return parse_qs(urlsplit(call.args[1]).query)


class ListWorkoutsTests(ClientCase):
    def test_walks_pages_until_a_short_page(self) -> None:
        self.request.side_effect = [
            page_of(WORKOUTS_PER_PAGE),
            page_of(2, first=WORKOUTS_PER_PAGE + 1),
        ]

        fetch = self.client.list_workouts(since=SINCE)

        self.assertEqual(WORKOUTS_PER_PAGE + 2, len(fetch.workouts))
        self.assertFalse(fetch.truncated)
        self.assertEqual(0, fetch.skipped)
        pages = [self.query(call)["page"] for call in self.request.call_args_list]
        self.assertEqual([["1"], ["2"]], pages)
        first = self.request.call_args_list[0]
        self.assertEqual("GET", first.args[0])
        self.assertEqual({"Authorization": f"Bearer {ACCESS}"}, first.kwargs["headers"])

    def test_a_smaller_applied_page_size_does_not_end_the_walk(self) -> None:
        first = {**page_of(30), "per_page": 30}
        second = {**page_of(2, first=31), "per_page": 30}
        self.request.side_effect = [first, second]

        fetch = self.client.list_workouts(since=SINCE)

        self.assertEqual(32, len(fetch.workouts))
        self.assertEqual(2, self.request.call_count)

    def test_stops_at_the_first_page_that_reaches_past_the_window(self) -> None:
        old = page_of(WORKOUTS_PER_PAGE, days=-3.0)
        self.request.side_effect = [old, page_of(1)]

        fetch = self.client.list_workouts(since=SINCE)

        self.assertEqual((), fetch.workouts)
        self.assertEqual(1, self.request.call_count)

    def test_until_filters_later_workouts(self) -> None:
        self.request.side_effect = [page_of(3)]

        fetch = self.client.list_workouts(since=SINCE, until=SINCE + timedelta(days=1))

        self.assertEqual((), fetch.workouts)

    def test_truncates_at_the_page_limit(self) -> None:
        self.request.side_effect = [
            page_of(WORKOUTS_PER_PAGE, first=1 + index * WORKOUTS_PER_PAGE)
            for index in range(MAX_WORKOUT_PAGES)
        ]

        fetch = self.client.list_workouts(since=SINCE)

        self.assertTrue(fetch.truncated)
        self.assertEqual(MAX_WORKOUT_PAGES, self.request.call_count)
        self.assertEqual(MAX_WORKOUT_PAGES * WORKOUTS_PER_PAGE, len(fetch.workouts))

    def test_naive_window_start_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.client.list_workouts(since=datetime(2026, 10, 1))  # noqa: DTZ001 - naive on purpose
        self.request.assert_not_called()

    def test_non_object_rows_are_counted_and_unparseable_starts_are_kept(self) -> None:
        self.request.side_effect = [
            {"workouts": ["text", 7, workout(1), {"id": 2, "starts": "garbage"}]}
        ]

        fetch = self.client.list_workouts(since=SINCE)

        self.assertEqual(2, fetch.skipped)
        self.assertEqual([1, 2], [row["id"] for row in fetch.workouts])

    def test_malformed_payloads_raise_a_content_free_error(self) -> None:
        payloads: tuple[object, ...] = (
            None,
            [],
            "text",
            {"workouts": {}},
            {"other": []},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                self.request.reset_mock()
                self.request.side_effect = [payload]
                with self.assertRaises(AppError) as raised:
                    self.client.list_workouts(since=SINCE)
                self.assertEqual("wahoo_invalid_response", raised.exception.reason)
                self.assertEqual(502, raised.exception.status)

    def test_oversized_response_error_passes_through_without_content(self) -> None:
        self.request.side_effect = AppError(
            502, "Die Antwort ist zu groß.", reason="response_too_large"
        )

        with self.assertRaises(AppError) as raised:
            self.client.list_workouts(since=SINCE)

        self.assertEqual("response_too_large", raised.exception.reason)
        self.assertEqual("Die Antwort ist zu groß.", raised.exception.message)


class TokenRefreshTests(ClientCase):
    def test_a_401_refreshes_once_and_retries_with_the_new_token(self) -> None:
        self.request.side_effect = [upstream(401), page_of(1)]

        fetch = self.client.list_workouts(since=SINCE)

        self.assertEqual(1, len(fetch.workouts))
        self.refresh.assert_called_once_with(ACCESS)
        headers = [call.kwargs["headers"] for call in self.request.call_args_list]
        self.assertEqual(
            [
                {"Authorization": f"Bearer {ACCESS}"},
                {"Authorization": f"Bearer {REFRESHED}"},
            ],
            headers,
        )

    def test_a_second_401_requires_reconnecting(self) -> None:
        self.request.side_effect = [upstream(401), upstream(401)]

        with self.assertRaises(WahooReconnectRequiredError) as raised:
            self.client.list_workouts(since=SINCE)

        self.assertEqual(409, raised.exception.status)
        self.assertEqual("wahoo_reconnect_required", raised.exception.reason)
        self.assertEqual(1, self.refresh.call_count)
        self.invalidate.assert_called_once_with(REFRESHED)
        self.assertSecretFree(raised.exception)

    def test_a_rejected_refresh_surfaces_the_connection_error(self) -> None:
        self.refresh.side_effect = WahooReconnectRequiredError()
        self.request.side_effect = [upstream(401)]

        with self.assertRaises(WahooReconnectRequiredError):
            self.client.list_workouts(since=SINCE)

        self.assertEqual(1, self.request.call_count)

    def test_a_server_error_after_the_refresh_is_retryable(self) -> None:
        self.request.side_effect = [upstream(401), upstream(502)]

        with self.assertRaises(WahooRetryableError):
            self.client.list_workouts(since=SINCE)


class FailureTests(ClientCase):
    def test_rate_limit_is_retryable_with_the_retry_after_hint(self) -> None:
        self.request.side_effect = upstream(429, retry_after=17)

        with self.assertRaises(WahooRetryableError) as raised:
            self.client.list_workouts(since=SINCE)

        error = raised.exception
        self.assertEqual(429, error.status)
        self.assertEqual("wahoo_rate_limited", error.reason)
        self.assertEqual(17, error.retry_after_seconds)
        self.assertSecretFree(error)
        self.refresh.assert_not_called()

    def test_timeouts_and_server_errors_are_retryable(self) -> None:
        for status in (408, 500, 502, 503, 504):
            with self.subTest(status=status):
                self.request.side_effect = upstream(status)
                with self.assertRaises(WahooRetryableError) as raised:
                    self.client.list_workouts(since=SINCE)
                self.assertEqual(503, raised.exception.status)
                self.assertEqual("wahoo_unavailable", raised.exception.reason)
                self.assertEqual(status, raised.exception.upstream_status)

    def test_other_rejections_are_content_free_and_not_retried(self) -> None:
        for status in (400, 403, 404):
            with self.subTest(status=status):
                self.request.side_effect = upstream(status)
                with self.assertRaises(AppError) as raised:
                    self.client.list_workouts(since=SINCE)
                self.assertNotIsInstance(raised.exception, WahooRetryableError)
                self.assertEqual("wahoo_request_rejected", raised.exception.reason)
                self.assertNotIn("Upstream failed", raised.exception.message)
                self.assertSecretFree(raised.exception)

    def test_no_log_records_are_emitted_and_no_token_is_in_the_url(self) -> None:
        self.request.side_effect = [upstream(401), page_of(1)]

        with self.assertNoLogs(level="DEBUG"):
            self.client.list_workouts(since=SINCE)

        for call in self.request.call_args_list:
            self.assertNotIn(ACCESS, call.args[1])
            self.assertNotIn(REFRESHED, call.args[1])


class SingleReadTests(ClientCase):
    def test_workout_summary_and_user_read_one_object(self) -> None:
        self.request.side_effect = [{"id": 9}, {"id": 3}]

        self.assertEqual({"id": 9}, self.client.workout_summary(9))
        self.assertEqual({"id": 3}, self.client.user())

        urls = [call.args[1] for call in self.request.call_args_list]
        self.assertTrue(urls[0].endswith("/v1/workouts/9/workout_summary"))
        self.assertTrue(urls[1].endswith("/v1/user"))

    def test_invalid_workout_ids_never_reach_the_transport(self) -> None:
        for value in (0, -1, True, "1", 2**63):
            with (
                self.subTest(value=value),
                self.assertRaises(ValueError),
            ):
                self.client.workout_summary(value)  # type: ignore[arg-type]
        self.request.assert_not_called()

    def test_a_non_object_response_is_invalid(self) -> None:
        self.request.side_effect = [[], "text"]

        with self.assertRaises(AppError):
            self.client.workout_summary(9)
        with self.assertRaises(AppError):
            self.client.user()

    def test_power_zones_reads_the_zone_rows_as_a_tuple(self) -> None:
        rows = [{"id": 1, "workout_type_family_id": 0, "ftp": 250}]
        self.request.side_effect = [rows]

        self.assertEqual(tuple(rows), self.client.power_zones())

        url = self.request.call_args.args[1]
        self.assertTrue(url.endswith("/v1/power_zones"))

    def test_power_zones_rejects_a_non_list_or_non_object_rows(self) -> None:
        self.request.side_effect = [{"id": 1}, [{"id": 1}, "text"]]

        for _ in range(2):
            with self.assertRaises(AppError) as context:
                self.client.power_zones()
            self.assertEqual("wahoo_invalid_response", context.exception.reason)


if __name__ == "__main__":
    unittest.main()
