import unittest

from backend import errors


class AppErrorTests(unittest.TestCase):
    def test_fields_and_exception_text_are_preserved(self):
        error = errors.AppError(418, "synthetic message", reason="synthetic_reason")

        self.assertIsInstance(error, Exception)
        self.assertEqual(str(error), "synthetic message")
        self.assertEqual(error.args, ("synthetic message",))
        self.assertEqual(error.status, 418)
        self.assertEqual(error.message, "synthetic message")
        self.assertEqual(error.reason, "synthetic_reason")

    def test_reason_defaults_to_none(self):
        self.assertIsNone(errors.AppError(500, "synthetic").reason)


class PublicStatusTests(unittest.TestCase):
    def test_authentication_or_permission_401_is_hidden_as_bad_gateway(self):
        self.assertEqual(errors.public_app_error_status(errors.AppError(401, "synthetic", reason="authentication_or_permission")), 502)

    def test_other_status_and_reasons_are_preserved(self):
        for status, reason in ((401, None), (401, "other"), (403, "authentication_or_permission"), (502, "authentication_or_permission")):
            with self.subTest(status=status, reason=reason):
                self.assertEqual(errors.public_app_error_status(errors.AppError(status, "synthetic", reason=reason)), status)


class ProviderErrorTests(unittest.TestCase):
    def test_network_category_uses_service_labels_and_reasons(self):
        expected = {
            "garmin": ("Garmin ist nicht erreichbar.", "provider_network_error"),
            "intervals": ("Intervals.icu ist nicht erreichbar.", "provider_network_error"),
            "openai": ("OpenAI ist nicht erreichbar.", "network_error"),
            "calendar": ("Der externe Kalender ist nicht erreichbar.", "provider_network_error"),
            "unknown": ("Der externe Dienst ist nicht erreichbar.", "provider_network_error"),
            None: ("Der externe Dienst ist nicht erreichbar.", "provider_network_error"),
        }
        for service, (message, reason) in expected.items():
            with self.subTest(service=service):
                error = errors.provider_error(service, "network")
                self.assertEqual((error.status, error.message, error.reason), (502, message, reason))

    def test_http_category_includes_only_truthy_optional_status(self):
        with_status = errors.provider_error("openai", "http", status=429)
        self.assertEqual(with_status.message, "OpenAI konnte die Anfrage nicht verarbeiten (HTTP 429).")
        self.assertEqual(with_status.reason, "http_error")
        self.assertEqual(with_status.status, 502)

        without_status = errors.provider_error("garmin", "http")
        self.assertEqual(without_status.message, "Garmin konnte die Anfrage nicht verarbeiten.")
        self.assertEqual(without_status.reason, "provider_http_error")
        self.assertEqual(errors.provider_error("garmin", "http", status=0).message, without_status.message)

    def test_client_category_is_default_for_unknown_categories(self):
        openai = errors.provider_error("OPENAI", "unexpected", status=503)
        other = errors.provider_error("not-a-provider", "unexpected")
        self.assertEqual((openai.message, openai.reason), ("Die Antwort von OpenAI konnte nicht verarbeitet werden.", "client_error"))
        self.assertEqual((other.message, other.reason), ("Die Antwort von Der externe Dienst konnte nicht verarbeitet werden.", "provider_client_error"))

    def test_provider_error_does_not_forward_provider_text(self):
        secret = "DO_NOT_EXPORT_PROVIDER_CONTENT"
        for category in ("network", "http", "client"):
            with self.subTest(category=category):
                error = errors.provider_error(secret, category, status=500)
                self.assertNotIn(secret, error.message)
                self.assertNotIn(secret, str(error))


class ErrorConstantTests(unittest.TestCase):
    def test_error_constants_match_existing_contract(self):
        expected = {
            "INTERVALS_API_KEY_ERROR": "INTERVALS_API_KEY ist nicht konfiguriert.",
            "OPENAI_API_KEY_ERROR": "OPENAI_API_KEY ist nicht konfiguriert.",
            "GEMINI_API_KEY_ERROR": "GEMINI_API_KEY ist nicht konfiguriert.",
            "NOT_FOUND_ERROR": "Nicht gefunden.",
            "INTERNAL_SERVER_ERROR": "Interner Serverfehler.",
            "COMPETITION_NOT_FOUND_ERROR": "Wettkampf nicht gefunden.",
            "COACH_ABORTED_ERROR": "Die Coach-Anfrage wurde abgebrochen.",
            "STRUCTURED_AUTHORIZATION_ERROR": "Die strukturierte Coach-Autorisierung erlaubt diesen Schritt nicht.",
            "INVALID_PLANNING_ID_ERROR": "Ungültige lokale Planungs-ID.",
            "CORRUPT_PLANNING_ERROR": "Die lokale Planung ist beschädigt.",
            "INVALID_LIBRARY_ID_ERROR": "Ungültige lokale Bibliothekseinheiten-ID.",
            "CORRUPT_LIBRARY_ERROR": "Die lokale Bibliothekseinheit ist beschädigt.",
            "INVALID_PLANNING_DATE_ERROR": "Das Planungsdatum muss das Format JJJJ-MM-TT haben.",
            "STALE_PLANNING_REVISION_ERROR": "Die lokale Planrevision ist inzwischen veraltet.",
            "UNSUPPORTED_BYDAY_ERROR": "BYDAY der Kalender-Wiederholung wird nicht unterstützt.",
            "PLANNED_CALENDAR_RECHECK_ERROR": "Die Planung wurde waehrend der Reparatur geaendert. Bitte erneut abgleichen.",
        }
        module = __import__("backend.errors", fromlist=list(expected))
        self.assertEqual({name: getattr(module, name) for name in expected}, expected)

    def test_disconnect_is_a_distinct_signal(self):
        self.assertTrue(issubclass(errors.ClientDisconnected, Exception))
        self.assertFalse(issubclass(errors.ClientDisconnected, errors.AppError))
        self.assertNotIsInstance(errors.ClientDisconnected(), errors.AppError)


if __name__ == "__main__":
    unittest.main()
