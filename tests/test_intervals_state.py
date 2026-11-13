import unittest
from typing import Any

from backend.sync.intervals_state import connection_state, public_state


class IntervalsStateTests(unittest.TestCase):
    def test_connection_state_follows_configuration_run_error_and_push(self) -> None:
        self.assertEqual("not_configured", connection_state(False, True, "x", "t"))
        self.assertEqual("syncing", connection_state(True, True, "x", "t"))
        self.assertEqual("error", connection_state(True, False, "x", "t"))
        self.assertEqual("connected", connection_state(True, False, None, "t"))
        self.assertEqual("configured", connection_state(True, False, None, None))

    def test_a_plan_export_connects_and_a_newer_failed_one_is_an_error(self) -> None:
        ok, failed = "2026-05-02T08:00:00+00:00", "2026-05-03T08:00:00+00:00"

        def state(
            ok_at: str | None = None,
            failed_at: str | None = None,
            library_at: str | None = None,
        ) -> dict[str, Any]:
            return public_state(
                configured=True,
                running=False,
                last_library_sync_at=library_at,
                last_library_sync_error=None,
                library_sync_state={},
                last_job_ok_at=ok_at,
                last_job_failed_at=failed_at,
            )

        exported = state(ok_at=ok)
        self.assertEqual("connected", exported["state"])
        self.assertEqual(ok, exported["last_used_at"])
        self.assertIsNone(exported["library_sync"]["last_sync_at"])
        self.assertEqual("error", state(ok_at=ok, failed_at=failed)["state"])
        # A success after the failure wins, whichever export it came from.
        self.assertEqual(
            "connected",
            state(failed_at=failed, library_at="2026-05-04T08:00:00+00:00")["state"],
        )
        self.assertEqual("error", state(failed_at=failed)["state"])
        self.assertEqual("configured", state()["state"])

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
