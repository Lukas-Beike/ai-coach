import json
import unittest
from datetime import date

from backend.errors import AppError
from backend.providers.state import ProviderStateService


class _Lock:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("lock-enter")
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.events.append("lock-exit")
        return False


class _UnitOfWork:
    def __init__(self, events):
        self.events = events

    def __enter__(self):
        self.events.append("uow-enter")
        return object()

    def __exit__(self, exc_type, exc_value, traceback):
        self.events.append("uow-exit")
        return False


class _Manager:
    def __init__(self, events):
        self.events = events

    def unit_of_work(self):
        return _UnitOfWork(self.events)


class _Repository:
    def __init__(self, events):
        self.events = events
        self.values = {}

    def get(self, db, key):
        self.events.append(f"get:{key}")
        return self.values.get(key)

    def set(self, db, key, value):
        self.events.append(f"set:{key}")
        self.values[key] = value


class _Logger:
    def __init__(self):
        self.calls = []

    def info(self, message, **kwargs):
        self.calls.append((message, kwargs))


class ProviderStateServiceTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.repository = _Repository(self.events)
        self.logger = _Logger()
        self.service = ProviderStateService(
            _Manager(self.events),
            self.repository,
            _Lock(self.events),
            lambda: "2026-09-19T10:00:00Z",
            lambda: date(2026, 9, 19),
            self.logger,
        )

    def test_empty_openai_summary_is_daily(self):
        self.assertEqual(
            self.service.summary("openai"),
            {
                "date": "2026-09-19",
                "requests": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "status": {},
                "rate_limits": {},
            },
        )

    def test_provider_is_exactly_validated(self):
        for method, args in (
            (self.service.summary, ("OpenAI",)),
            (self.service.record_success, ("other",)),
            (self.service.record_usage, ("unsupported ", {}, "chat")),
        ):
            with self.assertRaises(ValueError):
                method(*args)

    def test_status_is_normalized_and_provider_code_is_allowlisted(self):
        self.service.record_status(
            "openai",
            state="error with payload",
            reason=" provider_timeout ",
            message="x" * 400,
            http_status="503",
            provider_error_code="rate_limit_exceeded",
        )
        status = json.loads(self.repository.values["openai_status"])
        self.assertEqual(status["state"], "unknown")
        self.assertEqual(status["reason"], "provider_timeout")
        self.assertEqual(len(status["message"]), 300)
        self.assertEqual(status["http_status"], 503)
        self.assertEqual(status["provider_error_code"], "rate_limit_exceeded")

    def test_success_uses_german_provider_message(self):
        self.service.record_success("openai")
        self.assertEqual(
            json.loads(self.repository.values["openai_status"])["message"],
            "OpenAI ist verfügbar.",
        )
        self.assertEqual(
            json.loads(self.repository.values["openai_status"])["message"],
            "OpenAI ist verfügbar.",
        )

    def test_rate_limits_are_allowlisted(self):
        self.service.record_rate_limits(
            {
                "x-ratelimit-remaining-requests": "19",
                "x-ratelimit-reset-tokens": "30s",
                "x-request-id": "private",
            }
        )
        snapshot = json.loads(self.repository.values["openai_rate_limits"])
        self.assertEqual(snapshot["remaining_requests"], "19")
        self.assertEqual(snapshot["reset_tokens"], "30s")
        self.assertNotIn("private", json.dumps(snapshot))

    def test_openai_response_validation_persists_safe_failure_and_maps_app_error(self):
        with self.assertRaises(AppError) as raised:
            self.service.validate_openai_response(
                "/responses",
                {
                    "error": {
                        "code": "server_error",
                        "message": "private provider content",
                    }
                },
            )

        self.assertEqual(raised.exception.reason, "response_error")
        self.assertEqual(raised.exception.provider_error_code, "server_error")
        self.assertNotIn("private provider content", str(raised.exception))
        status = json.loads(self.repository.values["openai_status"])
        self.assertEqual(status["reason"], "response_error")
        self.assertEqual(status["provider_error_code"], "server_error")
        self.assertNotIn("private provider content", json.dumps(status))

    def test_openai_terminal_error_codes_use_production_allowlist_and_actionable_reasons(
        self,
    ):
        cases = (
            ("conversation_locked", "conversation_locked"),
            ("conversation_lock_timeout", "conversation_locked"),
            ("concurrent_request", "conversation_locked"),
            ("conversation_state_invalid", "conversation_state_invalid"),
            ("conversation_not_found", "conversation_state_invalid"),
            ("invalid_conversation", "conversation_state_invalid"),
            ("invalid_function_call_output", "conversation_state_invalid"),
            ("invalid_organization", "authentication_or_permission"),
        )
        for code, reason in cases:
            with self.subTest(code=code):
                with self.assertRaises(AppError) as raised:
                    self.service.validate_openai_response(
                        "/responses",
                        {
                            "status": "failed",
                            "error": {
                                "code": code,
                                "message": "private provider content",
                            },
                        },
                    )
                self.assertEqual(raised.exception.reason, reason)
                self.assertEqual(raised.exception.provider_error_code, code)
                self.assertNotIn("private provider content", str(raised.exception))
                status = json.loads(self.repository.values["openai_status"])
                self.assertEqual(status["reason"], reason)
                self.assertEqual(status["provider_error_code"], code)
                self.assertNotIn("private provider content", json.dumps(status))

    def test_openai_response_validation_drops_untrusted_code_and_keeps_invalid_shape_out_of_state(
        self,
    ):
        with self.assertRaises(AppError) as raised:
            self.service.validate_openai_response(
                "/responses",
                {
                    "error": {
                        "code": "private_code",
                        "message": "private provider content",
                    }
                },
            )
        self.assertEqual(raised.exception.reason, "response_error")
        self.assertFalse(hasattr(raised.exception, "provider_error_code"))
        self.assertNotIn(
            "provider_error_code", json.loads(self.repository.values["openai_status"])
        )

        self.repository.values.pop("openai_status")
        with self.assertRaises(AppError) as invalid:
            self.service.validate_openai_response("/responses", None)
        self.assertEqual(invalid.exception.reason, "invalid_response")
        self.assertNotIn("openai_status", self.repository.values)

    def test_openai_response_validation_surfaces_and_persists_billing_failure(self):
        with self.assertRaises(AppError) as raised:
            self.service.validate_openai_response(
                "/responses",
                {
                    "status": "failed",
                    "error": {
                        "code": "credit_balance_exhausted",
                        "message": "private provider content",
                    },
                },
            )
        message = "Das OpenAI-Guthaben ist aufgebraucht. Bitte im OpenAI-Billing Guthaben hinzufügen."
        self.assertEqual(raised.exception.reason, "credit_balance_exhausted")
        self.assertEqual(raised.exception.message, message)
        self.assertEqual(
            raised.exception.provider_error_code, "credit_balance_exhausted"
        )
        self.assertEqual(raised.exception.status, 502)
        status = json.loads(self.repository.values["openai_status"])
        self.assertEqual(status["reason"], "credit_balance_exhausted")
        self.assertEqual(status["provider_error_code"], "credit_balance_exhausted")
        self.assertEqual(status["message"], message)
        self.assertNotIn("private provider content", json.dumps(status))

    def test_openai_response_validation_returns_valid_result_unchanged(self):
        result = {"id": "response-test", "status": "completed"}
        self.assertIs(
            self.service.validate_openai_response("/responses", result), result
        )

    def test_usage_accumulates_atomically_and_logs_only_operation_and_counts(self):
        first = self.service.record_usage(
            "openai",
            {
                "usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5},
                "secret": "private",
            },
            "chat",
        )
        second = self.service.record_usage(
            "openai",
            {"usage": {"input_tokens": 4, "output_tokens": 1, "total_tokens": 5}},
            "stream",
        )
        self.assertEqual(
            first, {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}
        )
        self.assertEqual(
            second, {"input_tokens": 4, "output_tokens": 1, "total_tokens": 5}
        )
        self.assertEqual(self.service.summary("openai")["requests"], 2)
        self.assertEqual(self.service.summary("openai")["total_tokens"], 10)
        self.assertEqual(len(self.logger.calls), 2)
        self.assertNotIn("private", json.dumps(self.logger.calls))
        self.assertEqual(self.logger.calls[0][0], "OpenAI usage recorded")
        self.assertEqual(self.logger.calls[0][1]["extra"]["event"], "openai_usage")
        self.assertEqual(
            self.logger.calls[-1][1]["extra"]["context"],
            {
                "operation": "stream",
                "input_tokens": 4,
                "output_tokens": 1,
                "total_tokens": 5,
            },
        )

    def test_every_operation_acquires_lock_before_transaction(self):
        self.service.summary("openai")
        self.assertLess(self.events.index("lock-enter"), self.events.index("uow-enter"))
        self.assertLess(
            self.events.index("uow-enter"), self.events.index("get:openai_usage")
        )
        self.assertEqual(self.events[-2:], ["uow-exit", "lock-exit"])


if __name__ == "__main__":
    unittest.main()
