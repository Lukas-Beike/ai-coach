import unittest
from datetime import date

from backend.sync.intervals_state import (
    calendar_window,
    connection_state,
    decode_pagination,
    public_state,
)


class IntervalsStateTests(unittest.TestCase):
    def test_connection_state_priority_and_all_states(self):
        self.assertEqual(
            connection_state(False, True, "error", "sync", "library"), "not_configured"
        )
        self.assertEqual(
            connection_state(True, True, "error", "sync", "library"), "syncing"
        )
        self.assertEqual(
            connection_state(True, False, "error", "sync", "library"), "error"
        )
        self.assertEqual(connection_state(True, False, None, "sync", None), "connected")
        self.assertEqual(
            connection_state(True, False, None, None, "library"), "connected"
        )
        self.assertEqual(connection_state(True, False, None, None, None), "configured")

    def test_decode_pagination_accepts_json_and_dict(self):
        expected = {"activities": {"complete": True}}
        self.assertEqual(
            decode_pagination('{"activities":{"complete":true}}'), expected
        )
        self.assertIs(decode_pagination(expected), expected)

    def test_decode_pagination_returns_empty_for_malformed_or_non_dict_values(self):
        for value in ("{broken", "[]", "null", None, 42):
            with self.subTest(value=value):
                self.assertEqual(decode_pagination(value), {})

    def test_calendar_window_returns_snapshot_window_unchanged(self):
        window = {"start": "2026-01-02", "end": "2026-02-03", "extra": "kept"}
        snapshot = {"provider_sync": {"calendar_window": window}}
        result = calendar_window(
            snapshot, today=date(2026, 3, 4), history_days=10, future_days=20
        )
        self.assertIs(result, window)

    def test_calendar_window_falls_back_for_malformed_snapshots(self):
        expected = {"start": "2026-03-04", "end": "2026-04-13"}
        for snapshot in (
            None,
            [],
            {"provider_sync": []},
            {"provider_sync": {"calendar_window": []}},
        ):
            with self.subTest(snapshot=snapshot):
                self.assertEqual(
                    calendar_window(
                        snapshot,
                        today=date(2026, 3, 14),
                        history_days=10,
                        future_days=30,
                    ),
                    expected,
                )

    def test_public_state_matches_payload_and_prefers_sync_error(self):
        library_state = {"pending": 2, "failed": 1}
        window = {"start": "2026-03-01", "end": "2026-04-01"}
        pagination = {"activities": {"complete": False}}
        result = public_state(
            configured=True,
            running=False,
            status="idle",
            last_sync_at="2026-03-14T07:00:00+00:00",
            last_sync_error="sync failed",
            last_library_sync_at="2026-03-13T08:00:00+00:00",
            last_library_sync_error="library failed",
            pagination_value=pagination,
            snapshot={"provider_sync": {"calendar_window": window}},
            library_sync_state=library_state,
            today=date(2026, 3, 14),
            history_days=90,
            future_days=30,
        )
        self.assertEqual(
            result,
            {
                "configured": True,
                "state": "error",
                "running": False,
                "status": "idle",
                "last_sync_at": "2026-03-14T07:00:00+00:00",
                "last_error": "sync failed",
                "pagination": pagination,
                "calendar_window": window,
                "library_sync": {
                    "last_sync_at": "2026-03-13T08:00:00+00:00",
                    "last_error": "library failed",
                    "state": library_state,
                },
            },
        )


if __name__ == "__main__":
    unittest.main()
