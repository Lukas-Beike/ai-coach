from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.config import Config
from backend.diagnostics.logs import RecentLogEntriesService
from backend.observability import Redactor


def _redactor() -> Redactor:
    config = Config(
        port=8090,
        openai_api_key="sk-test-secret-value",
        openai_base_url="https://api.openai.com/v1",
        openai_model="gpt-6-luna",
        gemini_api_key="",
        gemini_model="gemini-test",
        ai_provider="openai",
        intervals_api_key="",
        intervals_athlete_id="",
        garmin_email="",
        garmin_password="",
        garmin_tokenstore="",
        garmin_fixture_path="",
        calendar_ical_url="",
        app_password="",
        secure_cookies=False,
        data_retention_days=30,
    )
    return Redactor(lambda: config)


class RecentLogEntriesServiceTests(unittest.TestCase):
    def test_missing_file_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            service = RecentLogEntriesService(
                Path(directory) / "missing.log", _redactor(), lambda: "fixed-time"
            )

            self.assertEqual(service.list(), [])

    def test_list_tails_lines_falls_back_for_invalid_json_and_sanitizes_values(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "app.log"
            log_path.write_text(
                "ignored line\n"
                + json.dumps({"message": "failed sk-test-secret-value", "context": {"ok": True}})
                + "\n"
                + "broken sk-test-secret-value\n",
                encoding="utf-8",
            )
            service = RecentLogEntriesService(log_path, _redactor(), lambda: "fixed-time")

            entries = service.list(2)

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["message"], "failed [REDACTED]")
        self.assertEqual(entries[0]["context"], {"ok": True})
        self.assertEqual(
            entries[1],
            {
                "level": "UNKNOWN",
                "event": "unparsed_log",
                "message": "broken [REDACTED]",
            },
        )

    def test_oserror_uses_injected_clock_and_redacts_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            log_path = Path(directory) / "app.log"
            log_path.write_text("{}\n", encoding="utf-8")
            service = RecentLogEntriesService(log_path, _redactor(), lambda: "fixed-time")
            with patch.object(Path, "read_text", side_effect=OSError("sk-test-secret-value")):
                entries = service.list()

        self.assertEqual(
            entries,
            [{
                "timestamp": "fixed-time",
                "level": "ERROR",
                "event": "log_read_failed",
                "message": "[REDACTED]",
            }],
        )


if __name__ == "__main__":
    unittest.main()
