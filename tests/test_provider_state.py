import json
import unittest
from datetime import date

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

    def test_empty_summaries_are_daily_for_both_providers(self):
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
        self.assertEqual(
            self.service.summary("gemini"),
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
            (self.service.record_usage, ("gemini ", {}, "chat")),
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

        self.service.record_status(
            "gemini",
            state="error",
            reason="http_error",
            message="Fehler",
            provider_error_code="rate_limit_exceeded",
        )
        self.assertNotIn("provider_error_code", json.loads(self.repository.values["gemini_status"]))

    def test_success_uses_german_provider_message(self):
        self.service.record_success("openai")
        self.service.record_success("gemini")
        self.assertEqual(json.loads(self.repository.values["openai_status"])["message"], "OpenAI ist verfügbar.")
        self.assertEqual(json.loads(self.repository.values["gemini_status"])["message"], "Gemini ist verfügbar.")

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

    def test_usage_accumulates_atomically_and_logs_only_operation_and_counts(self):
        first = self.service.record_usage(
            "openai",
            {"usage": {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5}, "secret": "private"},
            "chat",
        )
        second = self.service.record_usage(
            "openai",
            {"usage": {"input_tokens": 4, "output_tokens": 1, "total_tokens": 5}},
            "stream",
        )
        self.assertEqual(first, {"input_tokens": 3, "output_tokens": 2, "total_tokens": 5})
        self.assertEqual(second, {"input_tokens": 4, "output_tokens": 1, "total_tokens": 5})
        self.assertEqual(self.service.summary("openai")["requests"], 2)
        self.assertEqual(self.service.summary("openai")["total_tokens"], 10)
        self.service.record_usage(
            "gemini",
            {
                "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 2},
                "secret": "gemini-private-payload",
            },
            "generate_content",
        )
        self.assertEqual(len(self.logger.calls), 2)
        self.assertNotIn("private", json.dumps(self.logger.calls))
        self.assertEqual(self.logger.calls[0][0], "OpenAI usage recorded")
        self.assertEqual(self.logger.calls[0][1]["extra"]["event"], "openai_usage")
        self.assertEqual(self.logger.calls[-1][1]["extra"]["context"], {
            "operation": "stream",
            "input_tokens": 4,
            "output_tokens": 1,
            "total_tokens": 5,
        })

    def test_every_operation_acquires_lock_before_transaction(self):
        self.service.summary("openai")
        self.assertLess(self.events.index("lock-enter"), self.events.index("uow-enter"))
        self.assertLess(self.events.index("uow-enter"), self.events.index("get:openai_usage"))
        self.assertEqual(self.events[-2:], ["uow-exit", "lock-exit"])


if __name__ == "__main__":
    unittest.main()
