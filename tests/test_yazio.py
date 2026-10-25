"""Yazio client with synthetic fixtures and mocked HTTP; no real account."""

from __future__ import annotations

import io
import json
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

from backend.config import load_config
from backend.errors import AppError
from backend.providers.yazio import YazioClient, project_product

PRODUCT_ID = "11111111-2222-3333-4444-555555555555"
OTHER_ID = "66666666-7777-8888-9999-000000000000"
SECRETS = ("synthetic@example.test", "pw-synthetic", "client-id-x", "client-secret-x")


def config(**changes):
    base = load_config(Path("."), Path("data"), {"APP_PASSWORD": "x" * 12})
    values = {
        "yazio_email": SECRETS[0],
        "yazio_password": SECRETS[1],
        "yazio_client_id": SECRETS[2],
        "yazio_client_secret": SECRETS[3],
        **changes,
    }
    return replace(base, **values)


def reply(payload):
    result = io.BytesIO(json.dumps(payload).encode())
    result.status = 200
    return result


def failure(code, headers=None):
    return HTTPError("https://yzapi.yazio.com/", code, SECRETS[1], headers or {}, None)


def hit(**changes):
    return {
        "product_id": PRODUCT_ID,
        "name": "Synthetic Skyr",
        "producer": "Synthetic Dairy",
        "base_unit": "g",
        "is_verified": True,
        "nutrients": {
            "energy.energy": 0.63,
            "nutrient.carb": 0.04,
            "nutrient.protein": 0.11,
            "nutrient.fat": 0.002,
        },
        **changes,
    }


def token(**changes):
    return {
        "access_token": "access-1",
        "refresh_token": "refresh-1",
        "expires_in": 3600,
        **changes,
    }


class Script:
    """Opener answering token and API calls from queues; records requests."""

    def __init__(self, *, tokens=(), api=()):
        self.tokens, self.api, self.requests = list(tokens), list(api), []

    def __call__(self, request, timeout):
        self.requests.append(request)
        queue = self.tokens if request.full_url.endswith("/oauth/token") else self.api
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return reply(item)

    def bodies(self):
        return [
            json.loads(r.data)
            for r in self.requests
            if r.full_url.endswith("/oauth/token")
        ]


class YazioProjectionTests(unittest.TestCase):
    def test_per_unit_values_become_per_100_with_source(self):
        food = project_product(hit())
        self.assertEqual(food["id"], "yazio:" + PRODUCT_ID)
        self.assertEqual(food["source"], "Yazio")
        self.assertEqual(food["basis_unit"], "g")
        self.assertEqual(
            food["per_100"],
            {"kcal": 63.0, "carbs_g": 4.0, "protein_g": 11.0, "fat_g": 0.2},
        )

    def test_unknown_unit_and_missing_values_stay_unknown(self):
        food = project_product(hit(base_unit="piece", nutrients={}))
        self.assertIsNone(food["basis_unit"])
        self.assertEqual(set(food["per_100"].values()), {None})

    def test_implausible_scale_is_dropped_instead_of_guessed(self):
        food = project_product(
            hit(
                nutrients={
                    "energy.energy": 250,
                    "nutrient.carb": 40,
                    "nutrient.protein": 10,
                    "nutrient.fat": 5,
                }
            )
        )
        self.assertEqual(set(food["per_100"].values()), {None})

    def test_unusable_records_are_dropped(self):
        for raw in (
            hit(name=""),
            hit(product_id="not-a-uuid"),
            hit(is_deleted=True),
            hit(is_private=True),
            "text",
            None,
        ):
            self.assertIsNone(project_product(raw))

    def test_servings_are_bounded_and_validated(self):
        food = project_product(
            hit(
                servings=[
                    {"serving": "Becher", "amount": 150},
                    {"serving": "", "amount": 5},
                    {"serving": "x", "amount": "bad"},
                ]
            )
        )
        self.assertEqual(food["servings"], [{"label": "Becher", "amount": 150.0}])


class YazioClientTests(unittest.TestCase):
    def client(self, script, *, clock=None, **changes):
        cfg = config(**changes)
        return YazioClient(
            lambda: cfg, opener=script, clock=clock or Mock(return_value=0.0)
        )

    def test_search_logs_in_once_and_caches(self):
        script = Script(tokens=[token()], api=[[hit()]])
        client = self.client(script)
        self.assertEqual(client.search("Skyr")[0]["id"], "yazio:" + PRODUCT_ID)
        client.search("Skyr")
        self.assertEqual(len(script.requests), 2)
        login = script.bodies()[0]
        self.assertEqual(login["grant_type"], "password")
        self.assertEqual(login["username"], SECRETS[0])
        search = script.requests[1]
        self.assertTrue(search.full_url.startswith("https://yzapi.yazio.com/v22/"))
        self.assertEqual(search.get_header("Authorization"), "Bearer access-1")
        self.assertIn("YAZIO", search.get_header("User-agent"))

    def test_expired_token_is_refreshed_then_login_is_the_fallback(self):
        clock = Mock(return_value=0.0)
        script = Script(
            tokens=[token(), token(access_token="access-2"), failure(400), token()],
            api=[[hit()], [hit()], [hit()]],
        )
        client = self.client(script, clock=clock)
        client.search("a")
        clock.return_value = 4000.0
        client.search("b")
        clock.return_value = 8000.0
        client.search("c")
        grants = [body["grant_type"] for body in script.bodies()]
        self.assertEqual(
            grants, ["password", "refresh_token", "refresh_token", "password"]
        )
        self.assertEqual(script.bodies()[1]["refresh_token"], "refresh-1")

    def test_rejected_login_pauses_further_attempts_without_leaking(self):
        clock = Mock(return_value=0.0)
        script = Script(tokens=[failure(400)])
        client = self.client(script, clock=clock)
        for _ in range(2):
            with self.assertRaises(AppError) as raised:
                client.search("Skyr")
            self.assertEqual(raised.exception.reason, "food_database_auth_failed")
            for secret in SECRETS:
                self.assertNotIn(secret, raised.exception.message)
        self.assertEqual(len(script.requests), 1)

    def test_changed_credentials_drop_tokens_and_the_login_pause(self):
        holder = {"config": config()}
        script = Script(tokens=[failure(401), token(access_token="access-2")], api=[[]])
        client = YazioClient(
            lambda: holder["config"], opener=script, clock=Mock(return_value=0.0)
        )
        with self.assertRaises(AppError):
            client.search("Skyr")
        holder["config"] = config(yazio_password="new-password")
        self.assertEqual(client.search("Skyr"), [])

    def test_rate_limit_backs_off_locally(self):
        clock = Mock(return_value=0.0)
        script = Script(
            tokens=[token()], api=[failure(429, {"Retry-After": "120"}), [hit()]]
        )
        client = self.client(script, clock=clock)
        with self.assertRaises(AppError) as raised:
            client.search("Skyr")
        self.assertEqual(raised.exception.status, 429)
        with self.assertRaises(AppError):
            client.search("Skyr two")
        self.assertEqual(len(script.requests), 2)
        clock.return_value = 121.0
        self.assertEqual(len(client.search("Skyr two")), 1)

    def test_per_minute_request_limit(self):
        script = Script(tokens=[token()], api=[[]] * 25)
        client = self.client(script)
        for index in range(19):
            client.search(f"Synthetic {index}")
        with self.assertRaises(AppError) as raised:
            client.search("Synthetic tenth")
        self.assertEqual(raised.exception.reason, "food_database_rate_limited")

    def test_token_rejected_by_the_api_is_renewed_once(self):
        script = Script(
            tokens=[token(), token(access_token="access-2")],
            api=[failure(401), [hit()]],
        )
        client = self.client(script)
        self.assertEqual(len(client.search("Skyr")), 1)
        self.assertEqual(
            script.requests[-1].get_header("Authorization"), "Bearer access-2"
        )

    def test_version_block_server_error_and_bad_shape_are_sanitized(self):
        for api, reason in (
            (failure(403), "food_database_unavailable"),
            (failure(500), "food_database_unavailable"),
            (OSError(SECRETS[1]), "food_database_unavailable"),
            ({"unexpected": True}, "food_database_invalid_response"),
        ):
            with self.subTest(reason=reason, api=type(api).__name__):
                client = self.client(Script(tokens=[token()], api=[api]))
                with self.assertRaises(AppError) as raised:
                    client.search("Skyr")
                self.assertEqual(raised.exception.reason, reason)
                for secret in (*SECRETS, "Skyr", "access-1"):
                    self.assertNotIn(secret, raised.exception.message)

    def test_failed_refresh_during_an_outage_keeps_the_token_and_does_not_log_in(self):
        clock = Mock(return_value=0.0)
        script = Script(tokens=[token(), failure(500)], api=[[hit()]])
        client = self.client(script, clock=clock)
        client.search("a")
        clock.return_value = 4000.0
        with self.assertRaises(AppError):
            client.search("b")
        self.assertEqual(
            [body["grant_type"] for body in script.bodies()],
            ["password", "refresh_token"],
        )

    def test_throttled_refresh_blocks_a_fallback_login(self):
        clock = Mock(return_value=0.0)
        script = Script(tokens=[token(), failure(429)], api=[[hit()]])
        client = self.client(script, clock=clock)
        client.search("a")
        clock.return_value = 4000.0
        for _ in range(2):
            with self.assertRaises(AppError) as raised:
                client.search("b")
            self.assertEqual(raised.exception.status, 429)
        self.assertEqual(len(script.bodies()), 2)

    def test_replaced_or_removed_credentials_drop_cached_results(self):
        holder = {"config": config()}
        script = Script(tokens=[token()], api=[[hit()]])
        client = YazioClient(
            lambda: holder["config"], opener=script, clock=Mock(return_value=0.0)
        )
        self.assertEqual(len(client.search("Skyr")), 1)
        holder["config"] = config(yazio_password="")
        with self.assertRaises(AppError) as raised:
            client.search("Skyr")
        self.assertEqual(raised.exception.reason, "food_database_not_configured")
        self.assertEqual(len(script.requests), 2)

    def test_throttled_login_reports_the_rate_limit_and_waits(self):
        clock = Mock(return_value=0.0)
        script = Script(tokens=[failure(429, {"Retry-After": "90"})])
        client = self.client(script, clock=clock)
        for _ in range(2):
            with self.assertRaises(AppError) as raised:
                client.search("Skyr")
            self.assertEqual(raised.exception.status, 429)
        self.assertEqual(len(script.requests), 1)

    def test_user_agent_can_be_overridden(self):
        script = Script(tokens=[token()], api=[[]])
        self.client(script, yazio_user_agent="Custom/1").search("Skyr")
        self.assertEqual(script.requests[1].get_header("User-agent"), "Custom/1")

    def test_product_detail_keeps_servings_and_barcode_requires_a_matching_ean(self):
        detail = hit(
            servings=[{"serving": "Becher", "amount": 150}], eans=["4000000000001"]
        )
        script = Script(tokens=[token()], api=[[hit()], detail, [hit()], detail])
        client = self.client(script)
        found = client.barcode("4000000000001")
        self.assertEqual(found["servings"][0]["label"], "Becher")
        self.assertIsNone(client.barcode("4000000000009"))
        with self.assertRaises(AppError):
            client.product("../etc")

    def test_unconfigured_client_reports_it(self):
        client = YazioClient(lambda: config(yazio_password=""))
        self.assertFalse(client.configured)


if __name__ == "__main__":
    unittest.main()
