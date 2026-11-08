import unittest

from backend.sync.intervals_state import (
    connection_state,
    latest_library_timestamp,
    public_state,
)


class IntervalsStateTests(unittest.TestCase):
    def test_latest_library_timestamp_picks_the_newest_text(self) -> None:
        self.assertEqual(
            "2026-05-02T08:00:00+00:00",
            latest_library_timestamp(
                "2026-05-01T08:00:00+00:00", None, "2026-05-02T08:00:00+00:00", ""
            ),
        )
        self.assertIsNone(latest_library_timestamp(None, ""))

    def test_connection_state_follows_configuration_run_error_and_push(self) -> None:
        self.assertEqual("not_configured", connection_state(False, True, "x", "t"))
        self.assertEqual("syncing", connection_state(True, True, "x", "t"))
        self.assertEqual("error", connection_state(True, False, "x", "t"))
        self.assertEqual("connected", connection_state(True, False, None, "t"))
        self.assertEqual("configured", connection_state(True, False, None, None))

    def test_public_state_carries_no_ingest_fields(self) -> None:
        state = public_state(
            configured=True,
            running=False,
            last_library_sync_at="2026-05-02T08:00:00+00:00",
            last_library_sync_error=None,
            library_sync_state={"pending": 0},
        )

        self.assertEqual("connected", state["state"])
        self.assertIsNone(state["last_error"])
        self.assertEqual(
            {
                "last_sync_at": "2026-05-02T08:00:00+00:00",
                "last_error": None,
                "state": {"pending": 0},
            },
            state["library_sync"],
        )
        for removed in ("status", "last_sync_at", "pagination", "calendar_window"):
            self.assertNotIn(removed, state)


if __name__ == "__main__":
    unittest.main()
