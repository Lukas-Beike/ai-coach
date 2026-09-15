import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import backend
from backend.config import Config
from backend.errors import AppError
from backend.observability import (
    DiagnosticCapture,
    JsonLogFormatter,
    Redactor,
    configure_logging,
    diagnostic_capture_response,
    diagnostic_response_shape,
    external_result_context,
    safe_diagnostic_context,
    safe_diagnostic_error,
    safe_provider_path,
    safe_url_netloc,
)


def _config(**updates: str) -> Config:
    values = {
        "port": 8090,
        "openai_api_key": "synthetic-openai-value",
        "openai_base_url": "https://api.openai.com/v1",
        "openai_model": "test-model",
        "gemini_api_key": "synthetic-gemini-value",
        "gemini_model": "test-model",
        "ai_provider": "",
        "intervals_api_key": "synthetic-intervals-value",
        "intervals_athlete_id": "synthetic-athlete",
        "garmin_email": "synthetic@example.invalid",
        "garmin_password": "synthetic-garmin-password",
        "garmin_tokenstore": "synthetic-tokenstore",
        "garmin_fixture_path": "synthetic-fixture.json",
        "calendar_ical_url": "https://calendar-user:calendar-password@calendar.example.invalid/feed?token=synthetic-calendar-token",
        "app_password": "synthetic-app-password",
        "secure_cookies": False,
        "data_retention_days": -1,
    }
    values.update(updates)
    return Config(**values)


class _KeyValueStore:
    def __init__(self):
        self.values: dict[str, str] = {}
        self.lock = threading.Lock()

    def get(self, key: str) -> str | None:
        with self.lock:
            return self.values.get(key)

    def set(self, key: str, value: str) -> None:
        with self.lock:
            self.values[key] = value


class _Clock:
    def __init__(self, value: datetime):
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class ObservabilityTests(unittest.TestCase):
    def test_redacts_nested_values_and_secret_variants(self):
        current = _config()
        redactor = Redactor(lambda: current)
        encoded = "synthetic%40example.invalid"
        value = {
            "plain": "synthetic-openai-value",
            "nested": ["synthetic-intervals-value", ("synthetic@example.invalid", encoded)],
            "number": 3,
            "none": None,
            "other": object(),
        }

        sanitized = redactor.sanitize_log_value(value)

        self.assertEqual(sanitized["number"], 3)
        self.assertIsNone(sanitized["none"])
        self.assertIsInstance(sanitized["nested"], list)
        self.assertNotIn("synthetic-openai-value", json.dumps(sanitized))
        self.assertNotIn("synthetic-intervals-value", json.dumps(sanitized))
        self.assertNotIn("synthetic@example.invalid", json.dumps(sanitized))
        self.assertNotIn("synthetic-garmin-password", json.dumps(sanitized))
        self.assertNotIn("%40", json.dumps(sanitized))

    def test_redacts_url_credentials_query_and_unguessable_path(self):
        redactor = Redactor(_config)
        text = (
            "https://url-user:url-password@example.invalid/api/v1/activities/"
            "AbCdEf0123456789AbCdEf0123456789?token=synthetic-token&visible=ok"
        )

        redacted = redactor.redact_text(text)

        self.assertNotIn("url-user", redacted)
        self.assertNotIn("url-password", redacted)
        self.assertIn("https://example.invalid/api/v1/activities/[REDACTED_PATH]", redacted)
        self.assertIn("token=%5BREDACTED%5D", redacted)
        self.assertIn("visible=ok", redacted)

    def test_redacts_calendar_url_and_dynamic_configuration(self):
        configs = [_config(calendar_ical_url="https://first.example.invalid/calendar?secret=one"),
                   _config(calendar_ical_url="https://second.example.invalid/calendar?secret=two")]
        redactor = Redactor(lambda: configs[0])

        first = redactor.redact_text("configured https://first.example.invalid/calendar?secret=one")
        self.assertEqual(redactor.safe_calendar_url(), "https://first.example.invalid/redacted")
        self.assertNotIn("secret=one", first)

        configs[0] = configs[1]
        second = redactor.redact_text("configured https://second.example.invalid/calendar?secret=two")
        self.assertIn("https://second.example.invalid/redacted", second)
        self.assertNotIn("secret=two", second)

    def test_redacts_provider_key_patterns_and_authorization(self):
        redactor = Redactor(_config)
        text = "sk-SYNTHETICKEY123 AIzaSYNTHETICGEMINIKEY1234567890 authorization: Bearer synthetic-token"

        redacted = redactor.redact_text(text)

        self.assertNotIn("SYNTHETICKEY123", redacted)
        self.assertNotIn("SYNTHETICGEMINIKEY1234567890", redacted)
        self.assertIn("authorization: [REDACTED]", redacted)

    def test_formatter_redacts_traceback_and_context(self):
        redactor = Redactor(_config)
        formatter = JsonLogFormatter(redactor)
        logger = logging.getLogger("observability-formatter-test")
        try:
            try:
                raise RuntimeError("synthetic-openai-value")
            except RuntimeError:
                record = logger.makeRecord(
                    logger.name, logging.ERROR, __file__, 1, "failed", (), exc_info=sys.exc_info(),
                    extra={"event": "synthetic_event", "context": {"secret": "synthetic-garmin-password"}},
                )
                payload = json.loads(formatter.format(record))
        finally:
            logger.handlers.clear()

        self.assertEqual(payload["event"], "synthetic_event")
        self.assertNotIn("synthetic-openai-value", json.dumps(payload))
        self.assertNotIn("synthetic-garmin-password", json.dumps(payload))
        self.assertIn("[REDACTED]", payload["traceback"])

    def test_configure_logging_is_idempotent_and_writes_file_and_stream(self):
        logger = logging.getLogger("observability-configure-test")
        logger.handlers.clear()
        logger.propagate = True
        output = io.StringIO()
        redactor = Redactor(_config)
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "data"
            log_path = data_dir / "logs" / "coach.jsonl"
            try:
                configure_logging(logger, data_dir, log_path, redactor, stream=output)
                handlers = tuple(logger.handlers)
                configure_logging(logger, data_dir, log_path, redactor, stream=output)
                self.assertEqual(tuple(logger.handlers), handlers)
                self.assertEqual(len(logger.handlers), 2)
                self.assertFalse(logger.propagate)
                self.assertEqual(logger.level, logging.INFO)
                file_handler = next(handler for handler in logger.handlers if hasattr(handler, "maxBytes"))
                self.assertEqual(file_handler.maxBytes, 1_000_000)
                self.assertEqual(file_handler.backupCount, 3)

                logger.info("synthetic-openai-value", extra={"event": "test_event"})
                for handler in logger.handlers:
                    handler.flush()
                file_output = log_path.read_text(encoding="utf-8")
            finally:
                for handler in logger.handlers:
                    handler.close()
                logger.handlers.clear()

        self.assertNotIn("synthetic-openai-value", output.getvalue())
        self.assertNotIn("synthetic-openai-value", file_output)
        self.assertIn('"event":"test_event"', output.getvalue())

    def test_configure_logging_keeps_preinstalled_handlers_without_touching_paths(self):
        logger = logging.getLogger("observability-preinstalled-handler-test")
        logger.handlers.clear()
        foreign_handler = logging.StreamHandler(io.StringIO())
        logger.addHandler(foreign_handler)
        redactor = Redactor(_config)
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory) / "not-created-data"
            log_path = data_dir / "logs" / "not-created.jsonl"
            configure_logging(logger, data_dir, log_path, redactor, stream=io.StringIO())
            self.assertEqual(logger.handlers, [foreign_handler])
            self.assertFalse(data_dir.exists())
            self.assertFalse(log_path.exists())
        foreign_handler.close()
        logger.handlers.clear()

    def test_safe_provider_path_redacts_resource_ids(self):
        self.assertEqual(
            safe_provider_path("/api/v1/athlete/synthetic-athlete/activities/synthetic-activity"),
            "/api/v1/athlete/[REDACTED_PATH]/activities/[REDACTED_PATH]",
        )
        self.assertEqual(safe_provider_path("/api/v3/profile"), "/api/v3/profile")

    def test_safe_url_netloc_removes_userinfo_and_keeps_host_and_port(self):
        parsed = urlparse("https://synthetic-user:synthetic-password@example.invalid:8443/path")
        self.assertEqual(safe_url_netloc(parsed), "example.invalid:8443")

    def test_external_result_context_contains_shape_only(self):
        self.assertEqual(external_result_context(None), {"result_type": "null"})
        self.assertEqual(external_result_context({"secret": "synthetic-value"}), {"result_type": "object", "result_fields": 1})
        self.assertEqual(external_result_context((1, 2)), {"result_type": "array", "result_items": 2})
        self.assertEqual(external_result_context("synthetic-value"), {"result_type": "str"})

    def test_diagnostic_shapes_are_bounded_and_keep_only_structure(self):
        value = {"athlete_name": "Ada", "nested": [{"token": "hidden"}], "invalid key": "secret"}
        shape = diagnostic_response_shape(value)
        self.assertEqual(shape["field_count"], 3)
        self.assertEqual(shape["fields"], ["athlete_name", "nested", "[nonstandard]"])
        self.assertEqual(shape["sample"], {"type": "string", "length": 3})
        self.assertEqual(diagnostic_response_shape([{"token": "hidden"}])["item_shape"]["fields"], ["token"])
        self.assertEqual(diagnostic_response_shape({"nested": [{"token": "hidden"}]}, depth=1), {"type": "object", "field_count": 1, "fields": ["nested"]})
        self.assertEqual(diagnostic_capture_response("synthetic-response"), {"shape": {"type": "string", "length": 18}})

    def test_safe_diagnostic_context_and_error_never_retain_values_or_text(self):
        context = safe_diagnostic_context({"date": "2026-09-15", "secret": "synthetic-secret", "latest": True, 1: "ignored"})
        self.assertEqual(context, {"date": "2026-09-15", "latest": True})
        error = RuntimeError("synthetic exception text")
        error.status = 502
        error.reason = "provider_error"
        error.validation_reason = "invalid_request"
        error.provider_error_code = "server_error"
        safe = safe_diagnostic_error(error)
        self.assertEqual(safe, {"type": "RuntimeError", "status": 502, "reason": "provider_error", "validation_reason": "invalid_request", "provider_error_code": "server_error"})
        self.assertNotIn("synthetic", json.dumps(safe))
        error.provider_error_code = "synthetic-secret"
        error.reason = "not safe"
        self.assertNotIn("provider_error_code", safe_diagnostic_error(error))
        self.assertNotIn("reason", safe_diagnostic_error(error))

    def test_diagnostic_capture_requires_exact_bool_and_expires_state(self):
        store = _KeyValueStore()
        clock = _Clock(datetime(2026, 9, 15, 12, tzinfo=timezone.utc))
        capture = DiagnosticCapture(store.get, store.set, Redactor(_config), clock, duration_seconds=60, max_entries=2)
        with self.assertRaisesRegex(AppError, "Die Diagnoseaufzeichnung erwartet enabled=true oder enabled=false"):
            capture.set_enabled(1)
        self.assertFalse(capture.status()["active"])
        enabled = capture.set_enabled(True)
        self.assertTrue(enabled["active"])
        self.assertEqual(enabled["entries"], 0)
        capture.capture("synthetic-event", {"secret": "synthetic-openai-value", "shape": {"type": "string"}})
        self.assertEqual(capture.status()["entries"], 1)
        clock.value += timedelta(seconds=61)
        self.assertFalse(capture.status()["active"])
        self.assertEqual(store.get("diagnostic_capture_state"), "")
        self.assertEqual(capture.entries(), [{"timestamp": "2026-09-15T12:00:00+00:00", "event": "synthetic-event", "details": {"secret": "[REDACTED]", "shape": {"type": "string"}}}])

    def test_diagnostic_capture_rejects_naive_expiry_and_cleans_state(self):
        store = _KeyValueStore()
        clock = _Clock(datetime(2026, 9, 15, 12, tzinfo=timezone.utc))
        capture = DiagnosticCapture(store.get, store.set, Redactor(_config), clock)
        store.set("diagnostic_capture_state", '{"started_at":"2026-09-15T11:00:00","expires_at":"2026-09-15T13:00:00"}')
        self.assertFalse(capture.status()["active"])
        self.assertEqual(store.get("diagnostic_capture_state"), "")

    def test_diagnostic_capture_bounds_and_disable(self):
        store = _KeyValueStore()
        clock = _Clock(datetime(2026, 9, 15, 12, tzinfo=timezone.utc))
        capture = DiagnosticCapture(store.get, store.set, Redactor(_config), clock, max_entries=2)
        capture.set_enabled(True)
        for index in range(4):
            capture.capture("event", {"index": index, "token": "synthetic-openai-value"})
        entries = capture.entries()
        self.assertEqual(len(entries), 2)
        self.assertEqual([entry["details"]["index"] for entry in entries], [2, 3])
        self.assertTrue(all("synthetic-openai-value" not in json.dumps(entry) for entry in entries))
        capture.set_enabled(False)
        capture.capture("ignored", {"value": "not stored"})
        self.assertFalse(capture.status()["active"])
        self.assertEqual(len(capture.entries()), 2)

    def test_diagnostic_capture_concurrent_writes_do_not_lose_updates(self):
        store = _KeyValueStore()
        clock = _Clock(datetime(2026, 9, 15, 12, tzinfo=timezone.utc))
        capture = DiagnosticCapture(store.get, store.set, Redactor(_config), clock, max_entries=32)
        capture.set_enabled(True)
        barrier = threading.Barrier(8)

        def write(index: int) -> None:
            barrier.wait()
            capture.capture(f"event-{index}", {"index": index})

        threads = [threading.Thread(target=write, args=(index,)) for index in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        entries = capture.entries()
        self.assertEqual(len(entries), 8)
        self.assertEqual({entry["details"]["index"] for entry in entries}, set(range(8)))

    def test_observability_import_has_no_side_effect(self):
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(Path(backend.__file__).resolve().parent.parent)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-c", "import backend.observability; print('imported')"],
                cwd=directory,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(list(Path(directory).iterdir()), [])
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "imported")
        self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    unittest.main()
