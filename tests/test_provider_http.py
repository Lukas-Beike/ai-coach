import unittest

from backend.providers.http import ProviderHTTPError, classify_provider_status, redact_provider_text


class ProviderHTTPTests(unittest.TestCase):
    def test_redacts_credentials_and_bounds_detail(self):
        detail = "Authorization: Bearer secret-token " + ("x" * 700)
        safe = redact_provider_text(detail)
        self.assertNotIn("secret-token", safe)
        self.assertLessEqual(len(safe), 500)

    def test_classifies_authentication_and_rate_limit_responses(self):
        self.assertEqual(classify_provider_status(401, "intervals").category, "authentication")
        self.assertEqual(classify_provider_status(429, "intervals").category, "rate_limited")
        self.assertEqual(classify_provider_status(503, "intervals").category, "http")

    def test_error_string_is_safe(self):
        error = ProviderHTTPError("intervals", "http", 400, "sk-secret-key")
        self.assertNotIn("sk-secret-key", str(error))


if __name__ == "__main__":
    unittest.main()
