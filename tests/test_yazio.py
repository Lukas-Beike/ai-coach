"""Yazio client with synthetic fixtures and mocked HTTP; no real account."""

from __future__ import annotations

import http.client
import io
import json
import threading
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock
from urllib.error import HTTPError

from backend.config import load_config
from backend.errors import AppError
from backend.nutrition.food_database import FoodDatabaseService
from backend.providers.yazio import (
    CLIENT_ID,
    CLIENT_SECRET,
    YazioClient,
    project_product,
)

PRODUCT_ID = "11111111-2222-3333-4444-555555555555"
OTHER_ID = "66666666-7777-8888-9999-000000000000"
SECRETS = ("synthetic@example.test", "pw-synthetic")


def config(**changes):
    base = load_config(Path("."), Path("data"), {"APP_PASSWORD": "x" * 12})
    values = {
        "yazio_email": SECRETS[0],
        "yazio_password": SECRETS[1],
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


class YazioConnectionTests(unittest.TestCase):
    def test_passive_status_check_and_credential_change(self):
        holder = {"config": config()}
        script = Script(tokens=[token()])
        client = YazioClient(lambda: holder["config"], opener=script)
        self.assertEqual(client.connection_status()["status"], "unchecked")
        self.assertEqual(script.requests, [])
        result = client.check_connection()
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["checked_at"])
        self.assertEqual(len(script.requests), 1)
        self.assertEqual(client.connection_status(), result)
        holder["config"] = config(yazio_password="replacement")
        self.assertEqual(client.connection_status()["status"], "unchecked")
        holder["config"] = config(yazio_password="")
        self.assertEqual(client.check_connection()["status"], "not_configured")
        self.assertEqual(len(script.requests), 1)

    def test_check_uses_password_grant_and_restart_is_unchecked(self):
        current = config()
        script = Script(tokens=[token(), token(access_token="new")])
        client = YazioClient(lambda: current, opener=script)
        self.assertEqual(client.check_connection()["status"], "success")
        self.assertEqual(client.check_connection()["status"], "success")
        self.assertEqual(len(script.requests), 2)
        self.assertEqual(script.bodies()[1]["grant_type"], "password")
        self.assertEqual(
            YazioClient(lambda: current, opener=script).connection_status()["status"],
            "unchecked",
        )

    def test_transient_check_failures_preserve_tokens_for_lookup(self):
        for failed in (failure(500), failure(429), {}):
            with self.subTest(failure=failed):
                current = config()
                script = Script(tokens=[token(), failed], api=[[hit()]])
                client = YazioClient(
                    lambda current=current: current, opener=script, clock=lambda: 100
                )
                self.assertEqual(client.check_connection()["status"], "success")
                result = client.check_connection()
                self.assertIn(result["status"], ("unavailable", "rate_limited"))
                self.assertEqual(client._access_token, "access-1")
                self.assertEqual(client._refresh_token, "refresh-1")
                self.assertEqual(client._expires_at, 3700)
                if result["status"] != "rate_limited":
                    self.assertEqual(len(client.search("skyr")), 1)
                    self.assertEqual(len(script.bodies()), 2)

    def test_password_rejection_does_not_succeed_with_retained_refresh(self):
        current = config()
        script = Script(tokens=[token(), failure(401)])
        client = YazioClient(lambda: current, opener=script, clock=lambda: 100)
        self.assertEqual(client.check_connection()["status"], "success")
        self.assertEqual(client.check_connection()["status"], "auth_failed")
        self.assertEqual(client.check_connection()["status"], "auth_failed")
        self.assertEqual(
            [body["grant_type"] for body in script.bodies()], ["password", "password"]
        )

    def test_rejected_check_preserves_previous_token_for_lookup(self):
        for code in (400, 401, 403):
            with self.subTest(code=code):
                current = config()
                script = Script(tokens=[token(), failure(code)], api=[[hit()]])
                client = YazioClient(
                    lambda current=current: current, opener=script, clock=lambda: 100
                )
                self.assertEqual(client.check_connection()["status"], "success")
                self.assertEqual(client.check_connection()["status"], "auth_failed")
                self.assertEqual(client.check_connection()["status"], "auth_failed")
                self.assertEqual(len(client.search("skyr")), 1)
                self.assertEqual(
                    script.requests[-1].get_header("Authorization"), "Bearer access-1"
                )
                self.assertEqual(len(script.bodies()), 2)

    def test_rejected_inflight_check_does_not_restore_replaced_identity(self):
        holder = {"config": config()}
        entered, release = threading.Event(), threading.Event()
        script = Script(tokens=[token()])

        def opener(request, timeout):
            if not script.requests:
                return script(request, timeout)
            entered.set()
            self.assertTrue(release.wait(5))
            raise failure(401)

        client = YazioClient(lambda: holder["config"], opener=opener)
        self.assertEqual(client.check_connection()["status"], "success")
        results = []
        thread = threading.Thread(
            target=lambda: results.append(client.check_connection())
        )
        thread.start()
        self.assertTrue(entered.wait(5))
        holder["config"] = config(yazio_password="replacement")
        self.assertEqual(client.connection_status()["status"], "unchecked")
        holder["config"] = config()
        self.assertEqual(client.connection_status()["status"], "unchecked")
        release.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(results[0]["status"], "unchecked")
        self.assertEqual((client._access_token, client._refresh_token), ("", ""))

    def test_rejected_check_preserves_token_after_unrelated_config_change(self):
        holder = {"config": config()}
        script = Script(tokens=[token()], api=[[hit()]])

        def opener(request, timeout):
            if not script.requests:
                return script(request, timeout)
            if request.full_url.endswith("/oauth/token"):
                holder["config"] = config(yazio_country="FR")
                raise failure(401)
            return script(request, timeout)

        client = YazioClient(lambda: holder["config"], opener=opener, clock=lambda: 100)
        self.assertEqual(client.check_connection()["status"], "success")
        self.assertEqual(client.check_connection()["status"], "auth_failed")
        self.assertEqual(len(client.search("skyr")), 1)
        self.assertEqual(
            script.requests[-1].get_header("Authorization"), "Bearer access-1"
        )

    def _run_successful_inflight_check(self, mutate):
        holder = {"config": config()}
        entered, release = threading.Event(), threading.Event()

        def opener(request, timeout):
            entered.set()
            self.assertTrue(release.wait(5))
            return reply(token())

        client = YazioClient(lambda: holder["config"], opener=opener)
        results = []
        thread = threading.Thread(
            target=lambda: results.append(client.check_connection())
        )
        thread.start()
        self.assertTrue(entered.wait(5))
        mutate(holder, client)
        release.set()
        thread.join(5)
        self.assertFalse(thread.is_alive())
        return client, results[0]

    def test_successful_inflight_check_cannot_restore_an_old_generation(self):
        def mutate(holder, client):
            holder["config"] = config(yazio_password="replacement")
            client.connection_status()
            holder["config"] = config()
            client.connection_status()

        client, result = self._run_successful_inflight_check(mutate)
        self.assertEqual(result["status"], "unchecked")
        self.assertEqual((client._access_token, client._refresh_token), ("", ""))

    def test_changed_then_restored_credentials_invalidate_previous_result(self):
        holder = {"config": config()}
        client = YazioClient(lambda: holder["config"], opener=Script(tokens=[token()]))
        self.assertEqual(client.check_connection()["status"], "success")
        holder["config"] = config(yazio_password="replacement")
        holder["config"] = config(yazio_credential_generation=2)
        self.assertEqual(client.connection_status()["status"], "unchecked")

    def test_unrelated_provider_credentials_preserve_check_status(self):
        holder = {"config": config()}
        client = YazioClient(lambda: holder["config"], opener=Script(tokens=[token()]))
        result = client.check_connection()
        holder["config"] = config(openai_api_key="other-synthetic-key")
        self.assertEqual(client.connection_status(), result)

    def test_rejection_and_backoff_are_safe(self):
        current = config()
        script = Script(tokens=[failure(401)])
        client = YazioClient(lambda: current, opener=script, clock=lambda: 100)
        self.assertEqual(client.check_connection()["status"], "auth_failed")
        self.assertEqual(client.check_connection()["status"], "auth_failed")
        self.assertEqual(len(script.requests), 1)
        self.assertTrue(
            all(secret not in str(client.connection_status()) for secret in SECRETS)
        )

    def test_inflight_result_is_discarded_after_credential_replacement(self):
        client, result = self._run_successful_inflight_check(
            lambda holder, client: holder.update(
                config=config(yazio_password="replacement")
            )
        )
        self.assertEqual(result["status"], "unchecked")
        self.assertEqual(client.connection_status()["status"], "unchecked")


class YazioProjectionTests(unittest.TestCase):
    def test_per_unit_values_become_per_100_with_source(self):
        food = project_product(hit())
        self.assertEqual(food["id"], "yazio:" + PRODUCT_ID)
        self.assertEqual(food["source"], "Yazio")
        self.assertEqual(food["basis_unit"], "g")
        self.assertEqual(
            food["per_100"],
            {
                "kcal": 63.0,
                "carbs_g": 4.0,
                "protein_g": 11.0,
                "fat_g": 0.2,
                "sugar_g": None,
                "fiber_g": None,
                "salt_g": None,
            },
        )

    def test_additional_nutrients_are_scaled_and_invalid_values_remain_unknown(self):
        food = project_product(
            hit(
                nutrients={
                    "energy.energy": 0.63,
                    "nutrient.sugar": 0.04,
                    "nutrient.dietaryfiber": 0,
                    "nutrient.salt": -1,
                }
            )
        )
        self.assertEqual(food["per_100"]["sugar_g"], 4)
        self.assertEqual(food["per_100"]["fiber_g"], 0)
        self.assertIsNone(food["per_100"]["salt_g"])

    def test_unknown_unit_and_missing_values_stay_unknown(self):
        food = project_product(hit(base_unit="piece", nutrients={"energy.energy": 0.5}))
        self.assertIsNone(food["basis_unit"])
        self.assertEqual(food["per_100"]["kcal"], 50.0)
        self.assertIsNone(food["per_100"]["protein_g"])
        self.assertIsNone(project_product(hit(nutrients={})))

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
        self.assertIsNone(food)

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
        self.assertEqual(login["client_id"], CLIENT_ID)
        self.assertEqual(login["client_secret"], CLIENT_SECRET)
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

    def test_recognized_version_block_is_safe_and_distinct(self):
        blocked = HTTPError(
            "https://yzapi.yazio.com/",
            403,
            "forbidden",
            {},
            io.BytesIO(b'{"error":"version_blocked","detail":"synthetic-secret"}'),
        )
        client = self.client(Script(tokens=[token()], api=[blocked]))
        with self.assertRaises(AppError) as raised:
            client.search("Skyr")
        self.assertEqual(raised.exception.reason, "food_database_version_blocked")
        self.assertNotIn("synthetic-secret", raised.exception.message)

    def test_truncated_forbidden_response_is_sanitized(self):
        class BrokenBody(io.BytesIO):
            def read(self, size=-1):
                raise http.client.IncompleteRead(b"synthetic-secret")

        blocked = HTTPError(
            "https://yzapi.yazio.com/", 403, "forbidden", {}, BrokenBody()
        )
        client = self.client(Script(tokens=[token()], api=[blocked]))
        with self.assertRaises(AppError) as raised:
            client.search("Skyr")
        self.assertEqual(raised.exception.reason, "food_database_unavailable")
        self.assertNotIn("synthetic-secret", raised.exception.message)

        blocked = HTTPError(
            "https://yzapi.yazio.com/", 403, "forbidden", {}, BrokenBody()
        )
        client = self.client(Script(tokens=[token()], api=[blocked]))
        off = Mock()
        off.search.return_value = []
        result = FoodDatabaseService(off=off, yazio=client).lookup(
            {"query": "Haferflocken"}
        )
        self.assertTrue(result["foods"])
        self.assertIn("Onlinequelle", result["notice"])

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
        self.assertEqual(raised.exception.reason, "not_configured")
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

    def test_a_missing_candidate_does_not_hide_the_next_one(self):
        detail = hit(eans=["4000000000001"])
        script = Script(
            tokens=[token()],
            api=[[hit(), hit(product_id=OTHER_ID)], failure(404), detail],
        )
        found = self.client(script).barcode("4000000000001")
        self.assertEqual(found["id"], "yazio:" + OTHER_ID)

    def test_country_is_configurable_and_validated(self):
        script = Script(tokens=[token()], api=[[], []])
        client = self.client(script, yazio_country="at")
        client.search("a")
        self.assertIn("countries=AT", script.requests[1].full_url)
        client = self.client(Script(tokens=[token()], api=[[]]), yazio_country="bad!")
        script = client._opener
        client.search("a")
        self.assertIn("countries=DE", script.requests[1].full_url)

    def test_a_cache_hit_is_not_blocked_by_a_slow_request(self):
        import threading

        release, started = threading.Event(), threading.Event()
        script = Script(tokens=[token()], api=[[hit()], [hit()]])
        original = script.__call__

        def slow(request, timeout):
            if "Skyr+zwei" in request.full_url:
                started.set()
                release.wait(5)
            return original(request, timeout)

        client = YazioClient(
            lambda: config(), opener=slow, clock=Mock(return_value=0.0)
        )
        client.search("Skyr")
        worker = threading.Thread(target=client.search, args=("Skyr zwei",))
        worker.start()
        self.assertTrue(started.wait(5))
        self.assertEqual(len(client.search("Skyr")), 1)
        release.set()
        worker.join(5)

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
