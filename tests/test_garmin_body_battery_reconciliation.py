"""Daily Body Battery reconciliation of the regular Garmin sync (#1932).

Synthetic reports shaped after the range answer; temporary SQLite and fake
clients only, no Garmin account or token.
"""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from backend.db import garmin_store
from backend.db.manager import DatabaseManager
from backend.db.repositories import KeyValueRepository, SnapshotRepository
from backend.db.schema import initialize_schema
from backend.providers.garmin import GarminCollectionOptions, collect_garmin_data
from backend.sync.garmin import GarminPayloadService
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter
from backend.sync.state import SyncStateRepository

TODAY = date(2026, 9, 20)
NOW = "2026-09-20T12:00:00+00:00"


def _report(day: str, charged: int, drained: int, samples: int) -> dict[str, Any]:
    start = int(datetime.fromisoformat(f"{day}T03:00:00+00:00").timestamp() * 1000)
    return {
        "date": day,
        "charged": charged,
        "drained": drained,
        "bodyBatteryValuesArray": [
            [start + index * 180_000, 30 + index] for index in range(samples)
        ],
    }


def _external_call(_service: str, _source: str, call: Any, _details: Any) -> Any:
    return call()


class _RangeClient:
    """The range readers of one collection, without Body Battery."""

    def get_activities_by_date(self, start: str, end: str) -> list[Any]:
        return []

    def get_sleep_daily(self, start: str, end: str) -> list[Any]:
        return []

    def get_hrv_data_range(self, start: str, end: str) -> list[Any]:
        return []


class _Client(_RangeClient):
    """Body Battery answers per request."""

    def __init__(self, battery: Any = None) -> None:
        self.battery_calls: list[tuple[str, str]] = []
        self.battery = battery if battery is not None else []

    def get_body_battery(self, start: str, end: str) -> Any:
        self.battery_calls.append((start, end))
        if isinstance(self.battery, Exception):
            raise self.battery
        return self.battery


def _collect(
    client: _RangeClient,
    *,
    days: int = 7,
    capability_allowed: Any = None,
    failures: list[tuple[str, BaseException]] | None = None,
    successes: list[str] | None = None,
    warnings: list[str] | None = None,
    options: GarminCollectionOptions | None = None,
) -> dict[str, Any]:
    failures = [] if failures is None else failures
    successes = [] if successes is None else successes
    warnings = [] if warnings is None else warnings
    return collect_garmin_data(
        client,
        [(date(2026, 9, 19), TODAY)],
        start=date(2026, 9, 19),
        today=TODAY,
        synced_at=NOW,
        external_call=_external_call,
        redact=lambda _text: "redacted",
        warn=lambda source, _message, _error: warnings.append(source),
        capability_allowed=capability_allowed,
        capability_failure=lambda source, error: failures.append((source, error)),
        capability_success=successes.append,
        options=replace(
            options or GarminCollectionOptions(),
            include_daily_metrics=False,
            body_battery_reconcile_days=days,
        ),
    )


class CollectorTests(unittest.TestCase):
    def test_the_recent_week_is_read_once_and_marks_the_day(self) -> None:
        reports = [_report("2026-09-18", 40, 52, 3)]
        client = _Client(reports)
        successes: list[str] = []

        payload = _collect(client, successes=successes)

        self.assertEqual(client.battery_calls, [("2026-09-14", "2026-09-20")])
        self.assertEqual(payload["body_battery"], reports)
        self.assertEqual(
            payload["provider_sync"]["body_battery_reconciled_on"], "2026-09-20"
        )
        self.assertEqual(
            payload["provider_sync"]["pagination"]["body_battery"],
            {"windows": 1, "records": 1, "complete": True},
        )
        self.assertIn("body_battery", successes)
        self.assertEqual(payload["errors"], [])

    def test_the_span_includes_the_day_before_the_check_in_day(self) -> None:
        # Sleep that starts after midnight dates the morning read on the check-in
        # day, so the evening before is only re-read by the reconciliation.
        client = _Client([])

        _collect(client)

        ((first, last),) = client.battery_calls
        self.assertLessEqual(first, "2026-09-19")
        self.assertEqual(last, "2026-09-20")

    def test_a_longer_span_is_requested_in_at_most_31_days(self) -> None:
        client = _Client([])

        _collect(client, days=45)

        self.assertEqual(
            client.battery_calls,
            [("2026-08-07", "2026-09-06"), ("2026-09-07", "2026-09-20")],
        )

    def test_without_a_due_reconciliation_nothing_is_read_and_reports_stay(
        self,
    ) -> None:
        client = _Client([_report("2026-09-18", 40, 52, 3)])

        payload = _collect(client, days=0)

        self.assertEqual(client.battery_calls, [])
        self.assertNotIn("body_battery", payload)
        self.assertNotIn("body_battery_reconciled_on", payload["provider_sync"])
        # Not due is not stale: the stored reports and their freshness stay.
        self.assertIn("body_battery", payload["provider_sync"]["skipped_sources"])

    def test_only_a_recovery_read_of_the_current_day_reconciles(self) -> None:
        for name, options in (
            ("no recovery", GarminCollectionOptions(include_recovery=False)),
            (
                "no current metrics",
                GarminCollectionOptions(include_current_metrics=False),
            ),
        ):
            with self.subTest(name):
                client = _Client([_report("2026-09-18", 40, 52, 3)])

                payload = _collect(client, options=options)

                self.assertEqual(client.battery_calls, [])
                self.assertNotIn("body_battery", payload)
                self.assertNotIn("body_battery_reconciled_on", payload["provider_sync"])

    def test_a_failed_read_keeps_the_sync_complete_and_the_day_open(self) -> None:
        error = RuntimeError("private provider detail")
        client = _Client(error)
        failures: list[tuple[str, BaseException]] = []
        warnings: list[str] = []

        payload = _collect(client, failures=failures, warnings=warnings)

        self.assertEqual(failures, [("body_battery", error)])
        self.assertEqual(warnings, ["body_battery"])
        self.assertNotIn("body_battery", payload)
        self.assertEqual(payload["errors"], [])
        self.assertNotIn("body_battery", payload["provider_sync"]["pagination"])
        self.assertNotIn("body_battery_reconciled_on", payload["provider_sync"])
        # A failed read is not skipped: its stored reports show as stale.
        self.assertNotIn(
            "body_battery", payload["provider_sync"].get("skipped_sources", [])
        )

    def test_an_unreadable_answer_counts_as_a_failed_read(self) -> None:
        failures: list[tuple[str, BaseException]] = []

        payload = _collect(_Client({"unexpected": True}), failures=failures)

        self.assertEqual([source for source, _ in failures], ["body_battery"])
        self.assertNotIn("body_battery_reconciled_on", payload["provider_sync"])

    def test_a_paused_source_is_not_read(self) -> None:
        client = _Client([_report("2026-09-18", 40, 52, 3)])

        payload = _collect(
            client, capability_allowed=lambda source: source != "body_battery"
        )

        self.assertEqual(client.battery_calls, [])
        self.assertNotIn("body_battery_reconciled_on", payload["provider_sync"])

    def test_a_transport_without_body_battery_reads_nothing(self) -> None:
        payload = _collect(_RangeClient())

        self.assertNotIn("body_battery", payload)
        self.assertNotIn("body_battery_reconciled_on", payload["provider_sync"])


class StoredReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.database = DatabaseManager(
            Path(temporary.name) / "test.sqlite3", sqlite3, row_factory=sqlite3.Row
        )
        self.addCleanup(self.database.close)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.today = TODAY
        sync_state = SyncStateRepository(
            self.database, self.key_values, SnapshotRepository(), lambda: NOW
        )
        with self.database.unit_of_work() as db:
            initialize_schema(db)
        self.service = GarminPayloadService(
            self.database, self.key_values, sync_state, lambda: self.today
        )

    def sync(self, client: _Client, days: int = 7) -> dict[str, Any]:
        """Collect, prepare and store one regular sync, as the Garmin service does."""
        payload = self.service.prepare_remote(_collect(client, days=days))
        with self.database.unit_of_work() as db:
            GarminSnapshotWriter(self.key_values, lambda: UTC).write(db, payload)
        return payload

    def metric(self, day: str, metric: str) -> list[float]:
        with self.database.reader() as db:
            return [
                row["value"]
                for row in db.execute(
                    "SELECT value FROM observations WHERE provider = 'garmin' "
                    "AND observed_on = ? AND metric = ? AND state = 'active'",
                    (day, metric),
                )
            ]

    def counts(self) -> tuple[int, int]:
        with self.database.reader() as db:
            return (
                db.execute("SELECT COUNT(*) FROM provider_records").fetchone()[0],
                db.execute("SELECT COUNT(*) FROM observations").fetchone()[0],
            )

    def test_the_day_is_reconciled_once_and_a_new_day_again(self) -> None:
        self.assertTrue(self.service.body_battery_reconciliation_due())

        self.sync(_Client([_report("2026-09-19", 40, 52, 3)]))
        self.assertFalse(self.service.body_battery_reconciliation_due())

        # A later run of the same day that reads no Body Battery keeps the day.
        self.sync(_Client(), days=0)
        self.assertFalse(self.service.body_battery_reconciliation_due())

        self.today = date(2026, 9, 21)
        self.assertTrue(self.service.body_battery_reconciliation_due())

    def test_a_failed_read_leaves_the_day_due(self) -> None:
        self.sync(_Client(RuntimeError("rate limited")))

        self.assertTrue(self.service.body_battery_reconciliation_due())

    def test_an_unreadable_marker_makes_the_reconciliation_due(self) -> None:
        with self.database.unit_of_work() as db:
            GarminSnapshotWriter(self.key_values, lambda: UTC).write(
                db,
                {
                    "synced_at": NOW,
                    "provider_sync": {"body_battery_reconciled_on": "invalid"},
                },
            )

        self.assertTrue(self.service.body_battery_reconciliation_due())

    def test_a_day_whose_morning_read_failed_gets_its_report(self) -> None:
        self.assertEqual(self.metric("2026-09-18", "body_battery_charged"), [])

        self.sync(_Client([_report("2026-09-18", 41, 53, 3)]))

        with self.database.reader() as db:
            stored = garmin_store.read_item(db, "body_battery", "2026-09-18")
        self.assertEqual(stored, _report("2026-09-18", 41, 53, 3))
        self.assertEqual(self.metric("2026-09-18", "body_battery_charged"), [41.0])
        self.assertEqual(self.metric("2026-09-18", "body_battery_drained"), [53.0])

    def test_the_partial_morning_totals_are_replaced_by_the_complete_ones(
        self,
    ) -> None:
        # The check-in day's report as stored at about 05:00: a few hours only.
        partial = _report("2026-09-20", 3, 9, 2)
        with self.database.unit_of_work() as db:
            GarminSnapshotWriter(self.key_values, lambda: UTC).write_refresh(
                db,
                fetched_at="2026-09-20T05:00:00+00:00",
                sections={"body_battery": [partial]},
                view={},
                windows={},
                allowed=frozenset({"body_battery"}),
            )
        self.assertEqual(self.metric("2026-09-20", "body_battery_charged"), [3.0])

        self.today = date(2026, 9, 21)
        self.sync(_Client([_report("2026-09-20", 58, 71, 6)]))

        with self.database.reader() as db:
            stored = garmin_store.read_item(db, "body_battery", "2026-09-20")
        self.assertEqual(stored, _report("2026-09-20", 58, 71, 6))
        # One value per day: the later report replaces the partial one.
        self.assertEqual(self.metric("2026-09-20", "body_battery_charged"), [58.0])
        self.assertEqual(self.metric("2026-09-20", "body_battery_drained"), [71.0])

    def test_a_repeated_reconciliation_rewrites_nothing(self) -> None:
        reports = [_report("2026-09-18", 41, 53, 3), _report("2026-09-19", 44, 50, 4)]
        self.sync(_Client(reports))
        before = self.counts()

        self.sync(_Client(reports))

        self.assertEqual(self.counts(), before)
        self.assertEqual(self.metric("2026-09-19", "body_battery_charged"), [44.0])

    def test_a_sync_without_reconciliation_keeps_the_stored_reports_current(
        self,
    ) -> None:
        self.sync(_Client([_report("2026-09-18", 41, 53, 3)]))
        before = self.service.view(("body_battery",))

        self.sync(_Client(), days=0)

        after = self.service.view(("body_battery",))
        self.assertEqual(after["body_battery"], before["body_battery"])
        self.assertEqual(
            after["source_freshness"]["body_battery"]["freshness"],
            before["source_freshness"]["body_battery"]["freshness"],
        )
        self.assertEqual(
            after["source_freshness"]["body_battery"]["freshness"], "current"
        )


if __name__ == "__main__":
    unittest.main()
