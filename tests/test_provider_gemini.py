import json
import unittest

from backend.providers.gemini import error_details, function_tools, response_text


class GeminiProviderErrorTests(unittest.TestCase):
    def assert_reason(self, status, body=b"{}", reason="http_error", message=None):
        details = error_details(status, body, updated_at="2026-09-19T10:11:12+00:00")
        self.assertEqual(details["reason"], reason)
        self.assertEqual(details["http_status"], status)
        self.assertEqual(details["updated_at"], "2026-09-19T10:11:12+00:00")
        self.assertEqual(details["state"], "error")
        if message is not None:
            self.assertEqual(details["message"], message)
        return details

    def test_status_classes_use_stable_reasons_and_messages(self):
        self.assert_reason(
            401,
            reason="authentication_or_permission",
            message="Der Gemini-Zugang wurde abgelehnt. Bitte API-Schlüssel und Berechtigungen prüfen.",
        )
        self.assert_reason(
            403,
            reason="authentication_or_permission",
            message="Der Gemini-Zugang wurde abgelehnt. Bitte API-Schlüssel und Berechtigungen prüfen.",
        )
        self.assert_reason(
            404,
            reason="not_found",
            message="Das konfigurierte Gemini-Modell oder der angeforderte Dienst wurde nicht gefunden.",
        )
        self.assert_reason(
            503,
            reason="provider_unavailable",
            message="Gemini ist vorübergehend nicht verfügbar. Bitte später erneut versuchen.",
        )
        self.assert_reason(
            400,
            reason="http_error",
            message="Gemini konnte die Anfrage nicht verarbeiten (HTTP 400).",
        )

    def test_permission_and_unauthenticated_detail_markers_classify_authentication(self):
        for marker in ("permissionDenied", "UNAUTHENTICATED"):
            body = json.dumps({"error": {"details": [{"reason": marker}]}}).encode()
            self.assert_reason(400, body, reason="authentication_or_permission")

    def test_quota_markers_in_status_reason_and_type_classify_quota(self):
        for error in (
            {"status": "RESOURCE_EXHAUSTED", "details": [{"reason": "quotaExceeded"}]},
            {"details": [{"reason": "quotaExceeded"}]},
            {"details": [{"@type": "type.googleapis.com/google.rpc.QuotaFailure"}]},
        ):
            body = json.dumps({"error": error}).encode()
            self.assert_reason(429, body, reason="insufficient_quota")

    def test_non_quota_429_is_rate_limit(self):
        self.assert_reason(429, b'{"error":{"message":"provider text"}}', reason="rate_limit_exceeded")

    def test_malformed_json_and_foreign_shapes_are_safe(self):
        for body in (
            b"not-json",
            b"",
            b"[]",
            b'{"error": "not-an-object"}',
            b'{"error": {"details": [null, "text", {"reason": ["quota"]}]}}',
        ):
            details = self.assert_reason(400, body)
            self.assertEqual(set(details), {"state", "reason", "message", "http_status", "updated_at"})

    def test_provider_text_never_reaches_result(self):
        secret = "provider-secret-do-not-return"
        body = json.dumps({
            "error": {
                "status": "INVALID_ARGUMENT",
                "message": secret,
                "details": [{"reason": "INVALID_ARGUMENT", "message": secret}],
            }
        }).encode()
        result = self.assert_reason(400, body)
        self.assertNotIn(secret, json.dumps(result, ensure_ascii=False))


class GeminiProviderAdapterTests(unittest.TestCase):
    def test_response_text_keeps_visible_text_only(self):
        result = {"candidates": [{"content": {"parts": [{"text": "Hallo"}, {"functionCall": {"name": "x"}}]}}]}
        self.assertEqual(response_text(result), "Hallo")

    def test_function_tools_translates_functions_and_ignores_invalid_entries(self):
        tools = function_tools([
            {"type": "function", "name": "save", "parameters": {"type": "object"}},
            {"type": "text"},
        ])
        self.assertEqual(tools[0]["functionDeclarations"][0]["name"], "save")
        self.assertEqual(function_tools([]), [])


if __name__ == "__main__":
    unittest.main()
