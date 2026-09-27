"""Tests for external-calendar composition."""

import logging
import unittest
from datetime import date
from unittest.mock import Mock

from backend.sync.external_calendar_assembly import (
    ExternalCalendarAssembly,
    ExternalCalendarSyncOwners,
    ExternalCalendarSyncRuntime,
)


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
        ExternalCalendarAssembly(dependencies=ExternalCalendarAssembly.Inputs(
            owners=ExternalCalendarSyncOwners(
                config=callbacks["config"],
                database_manager=callbacks["database_manager"],
                key_values=Mock(),
                daily_markers=callbacks["daily_markers"],
                adaptive_preview_service=callbacks["adaptive_preview_service"],
                event_buffer=Mock(),
            ),
            runtime=ExternalCalendarSyncRuntime(
                operation_observer=callbacks["operation_observer"],
                logger=logging.getLogger("test.external.calendar.assembly"),
                redact_text=Mock(),
                athlete_clock=callbacks["athlete_clock"],
                local_date=callbacks["local_date"],
                utc_now=callbacks["utc_now"],
                app_version="test",
                sync_lock=callbacks["sync_lock"],
            ),
        ))

        for callback in callbacks.values():
            callback.assert_not_called()


if __name__ == "__main__":
    unittest.main()
