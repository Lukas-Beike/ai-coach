import unittest
from typing import Any

from backend.sync.intervals_state import connection_state, public_state


class IntervalsStateTests(unittest.TestCase):
    def test_connection_state_follows_configuration_run_error_and_push(self) -> None:
        used = "2026-05-02T08:00:00+00:00"
        self.assertEqual("not_configured", connection_state(False, True, "x", used))
        self.assertEqual("syncing", connection_state(True, True, "x", used))
        self.assertEqual("error", connection_state(True, False, "x", None))
        self.assertEqual("connected", connection_state(True, False, None, used))
        self.assertEqual("configured", connection_state(True, False, None, None))

    def test_a_plan_export_connects_and_a_newer_failed_one_is_an_error(self) -> None:
        old, ok = "2026-01-02T08:00:00+00:00", "2026-05-02T08:00:00+00:00"
        failed = "2026-05-03T08:00:00+00:00"

        def state(
            ok_at: str | None = None,
            failed_at: str | None = None,
            library_at: str | None = None,
            error: str | None = None,
        ) -> dict[str, Any]:
            return public_state(
                configured=True,
                running=False,
                last_library_sync_at=library_at,
                last_library_sync_error=error,
                library_sync_state={},
                last_output_ok_at=ok_at,
                last_output_failed_at=failed_at,
            )

        exported = state(ok_at=ok)
        self.assertEqual("connected", exported["state"])
        self.assertEqual(ok, exported["last_used_at"])
        self.assertIsNone(exported["library_sync"]["last_sync_at"])
        # A success stays connected however long ago it was.
        self.assertEqual("connected", state(ok_at="2020-01-01T00:00:00+00:00")["state"])
        self.assertEqual("error", state(ok_at=ok, failed_at=failed)["state"])
        # A success after the failure wins, whichever export it came from.
        self.assertEqual(
            "connected",
            state(failed_at=failed, library_at="2026-05-04T08:00:00+00:00")["state"],
        )
        self.assertEqual(
            "connected",
            state(ok_at="2026-05-04T08:00:00+00:00", failed_at=failed)["state"],
        )
        self.assertEqual("error", state(failed_at=failed)["state"])
        self.assertEqual("configured", state()["state"])
        # The library error has no time: a later success outranks it, no success does not.
        self.assertEqual(
            "connected", state(ok_at=ok, library_at=old, error="alt")["state"]
        )
        self.assertEqual("error", state(error="alt")["state"])
        self.assertEqual("alt", state(error="alt")["last_error"])
        self.assertEqual(ok, state(ok_at=ok, library_at=old)["last_used_at"])

    def test_an_unreadable_or_naive_stamp_never_breaks_the_state(self) -> None:
        def state(ok_at: str | None, failed_at: str | None = None) -> dict[str, Any]:
            return public_state(
                configured=True,
                running=False,
                last_library_sync_at=None,
                last_library_sync_error=None,
                library_sync_state={},
                last_output_ok_at=ok_at,
                last_output_failed_at=failed_at,
            )

        for bad in ("kaputt", "", "2026-13-45", "12:00"):
            with self.subTest(stamp=bad):
                self.assertEqual("configured", state(bad)["state"])
                self.assertIsNone(state(bad)["last_used_at"])
                self.assertEqual(
                    "connected", state("2026-05-02T08:00:00Z", bad)["state"]
                )
        # A naive stamp is UTC and compares with an aware one.
        self.assertEqual(
            "error", state("2026-05-02T08:00:00", "2026-05-02T09:00:00+00:00")["state"]
        )
        self.assertEqual(
            "connected",
            state("2026-05-02T10:00:00", "2026-05-02T09:00:00+00:00")["state"],
        )

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
