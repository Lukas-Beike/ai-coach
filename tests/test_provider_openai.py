import json
import unittest

from backend.providers.openai import (
    error_details,
    error_diagnostic_details,
    rate_limit_snapshot,
    response_failure_reason,
    response_text,
    retry_after_seconds,
    safe_log_reason,
)


def body(error=None):
    return json.dumps({"error": error or {}}).encode()


class OpenAIProviderErrorTests(unittest.TestCase):
    def test_response_parsers_remain_pure(self):
        self.assertEqual(response_failure_reason("/responses", None), "invalid_response")
        self.assertEqual(response_failure_reason("/responses", {"status": "failed"}), "response_failed")
        self.assertEqual(response_failure_reason("/models", {"status": "unknown"}), None)
        self.assertEqual(response_text({"output_text": "  hello  "}), "hello")
        self.assertEqual(
            response_text({"output": [{"type": "message", "content": [{"type": "output_text", "text": "hi"}]}]}),
            "hi",
        )

    def test_retry_after_is_numeric_bounded_ceiled_and_non_negative(self):
        self.assertEqual(retry_after_seconds({"retry-after": "12.5"}), 13)
        self.assertEqual(retry_after_seconds({"retry-after": "0"}), 1)
        self.assertEqual(retry_after_seconds({"retry-after": "86400"}), 86400)
        self.assertEqual(retry_after_seconds({"retry-after": "86400.1"}), 86400)
        for value in ("-1", "nan", "inf", "not-a-delay", None):
            self.assertIsNone(retry_after_seconds({"retry-after": value}))
        self.assertIsNone(retry_after_seconds(None))

    def test_diagnostic_details_keep_only_safe_tokens_and_bounded_bytes(self):
        raw = body(
            {
                "code": "Invalid_Function_Call_Output",
                "type": "invalid_request_error",
                "param": "input[0]",
                "message": "secret provider detail must not leak",
            }
        )
        details = error_diagnostic_details(raw, {"x-request-id": "req_test_123"}, max_response_bytes=len(raw) - 1)
        self.assertEqual(details["error_code"], "invalid_function_call_output")
        self.assertEqual(details["error_type"], "invalid_request_error")
        self.assertEqual(details["parameter"], "input[0]")
        self.assertEqual(details["request_id"], "req_test_123")
        self.assertEqual(details["error_body_bytes"], len(raw))
        self.assertNotIn("secret", json.dumps(details))

    def test_diagnostic_details_reject_malformed_and_malicious_tokens(self):
        raw = body(
            {
                "code": "x" * 161,
                "type": "type with spaces",
                "param": "input/secret",
                "message": "private provider text",
            }
        )
        details = error_diagnostic_details(raw, {"x-request-id": "request/id"}, max_response_bytes=4)
        self.assertEqual(details, {"error_body_bytes": 5})
        self.assertEqual(error_diagnostic_details(b"not-json", max_response_bytes=10), {"error_body_bytes": 8})

    def test_error_classification_preserves_status_contracts(self):
        cases = (
            (401, {}, "authentication_or_permission"),
            (403, {}, "authentication_or_permission"),
            (404, {}, "not_found"),
            (500, {}, "provider_unavailable"),
            (400, {}, "http_error"),
            (429, {}, "rate_limit_exceeded"),
            (429, {"code": "model_not_found"}, "rate_limit_exceeded"),
        )
        for status, error, reason in cases:
            with self.subTest(status=status, error=error):
                details = error_details(status, body(error), updated_at="2026-09-19T10:00:00Z")
                self.assertEqual(details["reason"], reason)
                self.assertEqual(details["updated_at"], "2026-09-19T10:00:00Z")
                self.assertNotIn("message", details["message"])

    def test_billing_and_quota_are_classified_before_429(self):
        self.assertEqual(
            error_details(429, body({"code": "credit_balance_exhausted"}), updated_at="now")["reason"],
            "credit_balance_exhausted",
        )
        for code in ("organization_spend_limit_exceeded", "project_spend_limit_exceeded", "organization_usage_limit_exceeded"):
            self.assertEqual(error_details(429, body({"code": code}), updated_at="now")["reason"], code)
        self.assertEqual(
            error_details(429, body({"type": "insufficient_quota"}), updated_at="now")["reason"],
            "insufficient_quota",
        )

    def test_conversation_lock_and_invalid_state_are_distinct(self):
        locked = error_details(409, body({"code": "conversation_locked"}), updated_at="now")
        invalid = error_details(
            400,
            body(
                {
                    "code": "invalid_function_call_output",
                    "type": "invalid_request_error",
                    "param": "input[0]",
                    "message": "secret call details",
                }
            ),
            updated_at="now",
        )
        self.assertEqual(locked["reason"], "conversation_locked")
        self.assertEqual(invalid["reason"], "conversation_state_invalid")
        self.assertNotIn("secret", json.dumps(invalid))
        for provider_message in (
            "No tool output found for function call private",
            "Item private of type reasoning was provided without its required following item.",
        ):
            with self.subTest(provider_message=provider_message):
                self.assertEqual(
                    error_details(
                        400,
                        body({"type": "invalid_request_error", "param": "input", "message": provider_message}),
                        updated_at="now",
                    )["reason"],
                    "conversation_state_invalid",
                )
        unrelated = error_details(
            400,
            body(
                {
                    "type": "invalid_request_error",
                    "param": "input",
                    "message": "Input contains an unsupported content type.",
                }
            ),
            updated_at="now",
        )
        self.assertEqual(unrelated["reason"], "http_error")

    def test_error_details_attach_retry_after_and_never_provider_text(self):
        details = error_details(
            429,
            body({"message": "private provider message", "code": "rate_limit_exceeded"}),
            {"retry-after": "1.2"},
            updated_at="now",
        )
        self.assertEqual(details["retry_after_seconds"], 2)
        self.assertNotIn("private", json.dumps(details))

    def test_safe_log_reason_is_static_allowlist(self):
        self.assertEqual(safe_log_reason("project_spend_limit_exceeded"), "usage_limit_exceeded")
        self.assertEqual(safe_log_reason("usage_limit_exceeded"), "usage_limit_exceeded")
        self.assertEqual(safe_log_reason("provider_timeout"), "provider_timeout")
        self.assertEqual(safe_log_reason("provider-private-message"), "http_error")
        self.assertEqual(safe_log_reason(None), "http_error")
        self.assertEqual(safe_log_reason({"reason": "provider_timeout"}), "http_error")

    def test_rate_limit_snapshot_is_allowlisted_and_empty_is_none(self):
        self.assertIsNone(rate_limit_snapshot({}, updated_at="now"))
        snapshot = rate_limit_snapshot(
            {
                "x-ratelimit-remaining-requests": "19",
                "x-ratelimit-reset-tokens": "30s",
                "x-request-id": "must-not-be-copied",
                "untrusted": "must-not-be-copied",
                "x-ratelimit-limit-tokens": "",
            },
            updated_at="now",
        )
        self.assertEqual(
            snapshot,
            {"updated_at": "now", "remaining_requests": "19", "reset_tokens": "30s"},
        )


if __name__ == "__main__":
    unittest.main()
