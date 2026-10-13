"""Wahoo plan writes through a mocked HTTP callable: shape, refresh, secrecy."""

from __future__ import annotations

import base64
import json
from datetime import UTC, datetime
from urllib.parse import parse_qs

from backend.errors import AppError
from backend.providers.wahoo_client import WahooReconnectRequiredError
from tests.test_wahoo_client import ACCESS, REFRESHED, ClientCase, upstream

PLAN = {"header": {"name": "Tempo", "version": "1.0.0"}, "intervals": []}
STAMP = datetime(2026, 10, 13, 8, 0, tzinfo=UTC)


def form(call):
    return parse_qs(call.kwargs["raw_body"].decode("ascii"))


class PlanWriteTests(ClientCase):
    def test_create_posts_a_form_with_the_base64_plan_and_external_id(self) -> None:
        self.request.return_value = {"id": 42}

        saved = self.client.create_plan(
            PLAN,
            filename="a.json",
            external_id="coach-library-1",
            provider_updated_at=STAMP,
        )

        self.assertEqual({"id": 42}, saved)
        call = self.request.call_args
        self.assertEqual("POST", call.args[0])
        self.assertTrue(call.args[1].endswith("/v1/plans"))
        self.assertEqual({"Authorization": f"Bearer {ACCESS}"}, call.kwargs["headers"])
        self.assertEqual(
            "application/x-www-form-urlencoded", call.kwargs["content_type"]
        )
        fields = form(call)
        self.assertEqual(["a.json"], fields["plan[filename]"])
        self.assertEqual(["coach-library-1"], fields["plan[external_id]"])
        self.assertEqual(
            ["2026-10-13T08:00:00+00:00"], fields["plan[provider_updated_at]"]
        )
        prefix, encoded = fields["plan[file]"][0].split(",", 1)
        self.assertTrue(prefix.startswith("data:"))
        self.assertTrue(prefix.endswith(";base64"))
        self.assertEqual(PLAN, json.loads(base64.b64decode(encoded)))

    def test_update_puts_to_the_plan_without_an_external_id(self) -> None:
        self.request.return_value = {"id": 42}

        self.client.update_plan(42, PLAN, filename="a.json", provider_updated_at=STAMP)

        call = self.request.call_args
        self.assertEqual("PUT", call.args[0])
        self.assertTrue(call.args[1].endswith("/v1/plans/42"))
        self.assertNotIn("plan[external_id]", form(call))

    def test_delete_sends_no_body(self) -> None:
        self.request.return_value = {}

        self.client.delete_plan(42)

        call = self.request.call_args
        self.assertEqual("DELETE", call.args[0])
        self.assertTrue(call.args[1].endswith("/v1/plans/42"))
        self.assertNotIn("raw_body", call.kwargs)

    def test_a_401_refreshes_once_and_retries_with_the_new_token(self) -> None:
        self.request.side_effect = [upstream(401), {"id": 7}]

        saved = self.client.create_plan(
            PLAN, filename="a.json", external_id="x", provider_updated_at=STAMP
        )

        self.assertEqual({"id": 7}, saved)
        self.refresh.assert_called_once_with(ACCESS)
        retry = self.request.call_args_list[1]
        self.assertEqual(
            {"Authorization": f"Bearer {REFRESHED}"}, retry.kwargs["headers"]
        )
        self.assertEqual(form(self.request.call_args_list[0]), form(retry))
        self.invalidate.assert_not_called()

    def test_a_second_401_invalidates_and_requires_reconnect(self) -> None:
        self.request.side_effect = [upstream(401), upstream(401)]

        with self.assertRaises(WahooReconnectRequiredError) as caught:
            self.client.update_plan(
                1, PLAN, filename="a.json", provider_updated_at=STAMP
            )

        self.invalidate.assert_called_once_with(REFRESHED)
        self.assertSecretFree(caught.exception)
        self.assertEqual(2, self.request.call_count)

    def test_a_404_keeps_its_upstream_status_and_no_secret(self) -> None:
        self.request.side_effect = [upstream(404)]

        with self.assertRaises(AppError) as caught:
            self.client.update_plan(
                1, PLAN, filename="a.json", provider_updated_at=STAMP
            )

        self.assertEqual(404, caught.exception.upstream_status)
        self.assertSecretFree(caught.exception)
        self.refresh.assert_not_called()

    def test_naive_timestamps_are_rejected_before_any_request(self) -> None:
        with self.assertRaises(ValueError):
            self.client.create_plan(
                PLAN,
                filename="a.json",
                external_id="x",
                provider_updated_at=datetime(2026, 10, 13),  # noqa: DTZ001 - naive on purpose
            )

        self.request.assert_not_called()

    def test_list_plans_returns_the_array_and_rejects_other_shapes(self) -> None:
        self.request.return_value = [{"id": 1, "external_id": "x"}]
        self.assertEqual(({"id": 1, "external_id": "x"},), self.client.list_plans())

        self.request.return_value = {"plans": []}
        with self.assertRaises(AppError):
            self.client.list_plans()
