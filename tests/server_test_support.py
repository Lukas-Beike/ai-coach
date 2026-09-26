"""Safe shared application setup for server integration tests."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.performance import context as performance_context
from backend.performance import garmin_metrics as performance_garmin_metrics
from support import create_test_session, reset_application_state

# Give the application deterministic, fake configuration before importing it.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="intervals-coach-test-")
os.environ.update({
    "AI_PROVIDER": "openai",
    "GEMINI_API_KEY": "",
    "GEMINI_BASE_URL": "https://generativelanguage.googleapis.com/v1beta",
    "GEMINI_MODEL": "gemini-3.8-flash",
    "OPENAI_API_KEY": "test-openai-key",
    "OPENAI_BASE_URL": "https://api.openai.com/v1",
    "OPENAI_MODEL": "gpt-6-luna",
    "INTERVALS_API_KEY": "test-intervals-key",
    "INTERVALS_ATHLETE_ID": "0",
    "GARMIN_EMAIL": "test-garmin@example.invalid",
    "GARMIN_PASSWORD": "test-garmin-password",
    "GARMINTOKENS": os.path.join(os.environ["DATA_DIR"], "garmin_tokens"),
    "GARMIN_FIXTURE_PATH": os.path.join(os.environ["DATA_DIR"], "missing-garmin-fixture.json"),
    "CALENDAR_ICAL_URL": "https://calendar.example.invalid/feed.ics",
    "APP_PASSWORD": "test-password-123",
    "DATA_RETENTION_DAYS": "-1",
    "PORT": "8090",
    "COOKIE_SECURE": "false",
})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
_original_read_text = Path.read_text
def _isolated_read_text(path, *args, **kwargs):
    if path.name == ".env":
        return ""
    return _original_read_text(path, *args, **kwargs)
with patch.object(Path, "read_text", _isolated_read_text):
    import server

server.CONFIG = replace(
    server.CONFIG,
    garmin_email="",
    garmin_password="",
    garmin_fixture_path="",
    calendar_ical_url="",
    secure_cookies=False,
)
_BASE_LOGGER_LEVEL = server.LOGGER.level
_BASE_LOGGER_PROPAGATE = server.LOGGER.propagate
_BASE_LOGGER_DISABLED = server.LOGGER.disabled

def _transcribe_via_http_route(audio: bytes, content_type: str) -> dict[str, str]:
    from types import SimpleNamespace
    from unittest.mock import Mock

    handler = SimpleNamespace(
        headers={"Content-Type": content_type},
        read_audio_body=Mock(return_value=audio),
        send_json=Mock(),
    )
    if not server.TRANSCRIBE_POST_ROUTES.handle(handler, "/api/transcribe"):
        raise AssertionError("transcription route was not handled")
    return handler.send_json.call_args.args[1]

def _garmin_metrics(snapshot):
    return performance_garmin_metrics.garmin_performance_metrics(
        snapshot, server.ATHLETE_CLOCK.now().date()
    )

def _current_performance_context(snapshot=None):
    effective_snapshot = snapshot if snapshot is not None else server.sync_state_repository().latest_snapshot()
    return performance_context.current_performance_context(
        effective_snapshot,
        server.garmin_payload_service().snapshot(),
        server.profile_service().get(),
        server.ATHLETE_CLOCK.now().date(),
    )

class ServerTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._original_config = server.CONFIG
        cls._original_data_dir = server.DATA_DIR
        cls._original_db_path = server.DB_PATH
        cls._original_log_path = server.LOG_PATH
        server.CONFIG = replace(server.CONFIG, app_password="")
        cls._template_dir = Path(tempfile.mkdtemp(prefix="intervals-coach-test-template-"))
        cls._class_data_dir = Path(tempfile.mkdtemp(prefix="intervals-coach-test-class-"))
        server.DATA_DIR = cls._template_dir
        server.DB_PATH = cls._template_dir / "intervals-coach.db"
        server.LOG_PATH = cls._template_dir / "intervals-coach.log"
        server.initialise_database()
        class_db_path = cls._class_data_dir / "intervals-coach.db"
        shutil.copy2(server.DB_PATH, class_db_path)
        server.DATA_DIR = cls._class_data_dir
        server.DB_PATH = class_db_path
        server.LOG_PATH = cls._class_data_dir / "intervals-coach.log"
        server.initialise_database()
        for handler in list(server.LOGGER.handlers):
            server.LOGGER.removeHandler(handler)
            handler.close()
        server.observability.configure_logging(
            server.LOGGER, server.DATA_DIR, server.LOG_PATH, server.REDACTOR
        )
        cls.addClassCleanup(cls._restore_test_config)

    @classmethod
    def _restore_test_config(cls):
        server.DATABASE_MANAGER_CACHE.reset()
        server.CONFIG = cls._original_config
        server.DATA_DIR = cls._original_data_dir
        server.DB_PATH = cls._original_db_path
        server.LOG_PATH = cls._original_log_path
        for handler in list(server.LOGGER.handlers):
            server.LOGGER.removeHandler(handler)
            handler.close()
        server.LOGGER.setLevel(_BASE_LOGGER_LEVEL)
        server.LOGGER.propagate = _BASE_LOGGER_PROPAGATE
        server.LOGGER.disabled = _BASE_LOGGER_DISABLED
        shutil.rmtree(cls._template_dir, ignore_errors=True)
        shutil.rmtree(cls._class_data_dir, ignore_errors=True)

    def setUp(self):
        reset_application_state(server)

    @staticmethod
    def history_preview(change_id, session_csrf_hash="session-csrf-hash"):
        preview = server.history_undo_service().preview(change_id)
        proposal = server.coach_proposal_creation_service().create(
            preview.pop("proposal"), session_csrf_hash
        )
        return {**preview, "proposed_action": proposal["proposed_action"]}
