"""Tests for external-calendar composition."""

import logging
import unittest
from datetime import date
from unittest.mock import Mock

from backend.sync.external_calendar_assembly import ExternalCalendarAssembly


class ExternalCalendarAssemblyTests(unittest.TestCase):
    def test_assembly_construction_does_not_resolve_runtime_dependencies(self):
        callbacks = {
            "config": Mock(),
            "database_manager": Mock(),
            "daily_markers": Mock(),
            "operation_observer": Mock(),
            "adaptive_preview_service": Mock(),
            "athlete_clock": Mock(),
            "local_date": Mock(return_value=date(2026, 9, 26)),
            "utc_now": Mock(),
            "sync_lock": Mock(),
        }
        ExternalCalendarAssembly(
            **callbacks,
            key_values=Mock(),
            event_buffer=Mock(),
            logger=logging.getLogger("test.external.calendar.assembly"),
            redact_text=Mock(),
            app_version="test",
        )

        for callback in callbacks.values():
            callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
