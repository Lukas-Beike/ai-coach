"""Wahoo FIT detail import: storage, skips, retries, caps, budget and leaks.

The download is a fake that never touches the network; every URL is the
placeholder. Stored sets come from the real canonical tables of the sync fixture.
"""

from __future__ import annotations

import json
import threading
import unittest
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.canonical.vocabulary import RecordingOrigin, SourceKind
from backend.db.activity_detail_store import detail_sets_for
from backend.db.canonical_store import active_provider_record_hash
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND
from backend.providers.fit_activity_detail_mapping import MAPPER_VERSION
from backend.providers.wahoo_client import WahooWorkoutFetch
from backend.providers.wahoo_fit_download import WahooFitUnavailable
from backend.sync.wahoo_activity_details import (
    DETAIL_IMPORT_BUDGET_SECONDS,
    MAX_DETAIL_ATTEMPTS,
    STATE_KEY,
    WahooActivityDetailImport,
)
from tests.test_fit_file import UINT8, UINT16, UINT32, FitBuilder
from tests.wahoo_sync_fixture import WahooSyncCase, workout

URL = "https://cdn.wahooligan.com/w.fit?sig=placeholder"
LEAK_MARKERS = ("sig=placeholder", "w.fit", "cdn.wahooligan.com")
BASE = datetime(2026, 10, 1, 6, 0, tzinfo=UTC)
RECORD_FIELDS = [(253, UINT32), (3, UINT8), (5, UINT32), (7, UINT16)]
LAP_FIELDS = [(2, UINT32), (7, UINT32)]


def starts(index: int) -> str:
    """Workouts three hours apart so that none overlaps another in ingest."""
    return (BASE + timedelta(hours=3 * index)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def fit_bytes(records: int = 3, *, laps: int = 0) -> bytes:
    builder = FitBuilder().define(0, 20, RECORD_FIELDS)
    for index in range(records):
        builder.data(
            0, {253: 1000 + index, 3: 120 + index, 5: 100 * index, 7: 200 + index}
        )
    if laps:
        builder.define(1, 19, LAP_FIELDS)
        for index in range(laps):
            builder.data(1, {2: 1000 + index, 7: 1000})
    return builder.build()


def with_url(number: int, index: int = 0, **summary: Any) -> dict[str, Any]:
    """A workout row whose summary carries the placeholder download link."""
    return workout(number, starts(index), summary={"file": {"url": URL}, **summary})


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now


class FakeDownload:
    """Returns FIT bytes or raises a queued failure; each call advances the clock."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.data = fit_bytes()
        self.failure: BaseException | None = None
        self.cost = 0.0
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        self.clock.now += self.cost
        if self.failure is not None:
            raise self.failure
        return self.data


class WahooActivityDetailTests(WahooSyncCase):
    def setUp(self) -> None:
        super().setUp()
        self.clock = FakeClock()
        self.download = FakeDownload(self.clock)
        self.importer = WahooActivityDetailImport(
            database_manager=lambda: self.database,
            database_lock=threading.RLock(),
            key_values=self.key_values,
            download=self.download,
            monotonic=self.clock.monotonic,
            logger=self.logger,
        )

    def sync(self, *rows: dict[str, Any]) -> list[dict[str, Any]]:
        """Run the real sync so the workouts have active activity records."""
        self.source.fetch = WahooWorkoutFetch(tuple(rows))
        self.assertEqual("ok", self.service.sync()["status"])
        return list(rows)

    def run_import(self, rows: list[Any]) -> dict[str, Any]:
        return self.importer.import_details(rows, retrieved_at=self.now)

    def stored_sets(self, workout_id: str = "1") -> list[Any]:
        with self.database.reader() as db:
            return detail_sets_for(db, "wahoo", workout_id)

    def state(self) -> dict[str, Any]:
        return json.loads(self._value(STATE_KEY) or "{}")

    def test_stores_detail_with_wahoo_provenance_and_summary_hash(self) -> None:
        rows = self.sync(with_url(1))

        result = self.run_import(rows)

        self.assertEqual(
            {"status": "ok", "stored": 1, "failed": 0, "skipped": 0, "empty": 0},
            result,
        )
        self.assertEqual(1, len(self.download.urls))
        sets = self.stored_sets()
        self.assertTrue(sets)
        with self.database.reader() as db:
            expected = active_provider_record_hash(
                db, "wahoo", ACTIVITY_RECORD_KIND, "1"
            )
        for item in sets:
            self.assertEqual("wahoo", item.provider)
            self.assertEqual(MAPPER_VERSION, item.mapper_version)
            self.assertEqual(expected, item.summary_sha256)
        provenance = self.rows(
            "SELECT DISTINCT source_kind, recorded_by FROM activity_detail_sets "
            "WHERE provider = 'wahoo'"
        )
        self.assertEqual(
            [
                {
                    "source_kind": SourceKind.DEVICE_MEASURED.value,
                    "recorded_by": RecordingOrigin.WAHOO.value,
                }
            ],
            provenance,
        )
        self.assertEqual({}, self.state())

    def test_second_run_skips_detail_already_stored_for_the_same_summary(self) -> None:
        rows = self.sync(with_url(1))
        self.run_import(rows)

        result = self.run_import(rows)

        self.assertEqual(0, result["stored"])
        self.assertEqual(1, result["skipped"])
        self.assertEqual(1, len(self.download.urls))

    def test_changed_summary_downloads_again_and_replaces_the_stored_hash(self) -> None:
        rows = self.sync(with_url(1))
        self.run_import(rows)
        with self.database.reader() as db:
            old = active_provider_record_hash(db, "wahoo", ACTIVITY_RECORD_KIND, "1")

        rows = self.sync(with_url(1, heart_rate_avg="150"))
        result = self.run_import(rows)

        self.assertEqual(1, result["stored"])
        self.assertEqual(2, len(self.download.urls))
        with self.database.reader() as db:
            new = active_provider_record_hash(db, "wahoo", ACTIVITY_RECORD_KIND, "1")
        self.assertNotEqual(old, new)
        self.assertEqual({new}, {item.summary_sha256 for item in self.stored_sets()})

    def test_a_stale_set_of_a_missing_kind_does_not_download_again(self) -> None:
        self.download.data = fit_bytes(laps=2)
        rows = self.sync(with_url(1))
        self.run_import(rows)
        self.assertEqual(2, len(self.stored_sets()))

        # The new file has no laps, so the lap set keeps the old summary hash.
        self.download.data = fit_bytes()
        rows = self.sync(with_url(1, heart_rate_avg="150"))
        self.assertEqual(1, self.run_import(rows)["stored"])
        result = self.run_import(rows)

        self.assertEqual(1, result["skipped"])
        self.assertEqual(2, len(self.download.urls))

    def test_failed_downloads_stop_after_the_maximum_attempts(self) -> None:
        rows = self.sync(with_url(1))
        self.download.failure = WahooFitUnavailable("unavailable")

        for _ in range(MAX_DETAIL_ATTEMPTS):
            self.assertEqual(1, self.run_import(rows)["failed"])
        result = self.run_import(rows)

        self.assertEqual(1, result["skipped"])
        self.assertEqual(0, result["failed"])
        self.assertEqual(MAX_DETAIL_ATTEMPTS, len(self.download.urls))
        self.assertEqual(MAX_DETAIL_ATTEMPTS, self.state()["1"]["attempts"])
        self.assertFalse(self.state()["1"]["empty"])
        self.assertEqual([], self.stored_sets())

    def test_rate_limit_stops_the_run_without_counting_an_attempt(self) -> None:
        rows = self.sync(with_url(1), with_url(2, index=1))
        self.download.failure = WahooFitUnavailable("rate_limited")

        result = self.run_import(rows)

        self.assertEqual("rate_limited", result["status"])
        self.assertEqual(0, result["failed"])
        self.assertEqual(1, len(self.download.urls))
        self.assertEqual({}, self.state())

        self.download.failure = None
        result = self.run_import(rows)

        self.assertEqual("ok", result["status"])
        self.assertEqual(2, result["stored"])

    def test_empty_file_is_marked_and_not_downloaded_again(self) -> None:
        self.download.data = FitBuilder().build()
        rows = self.sync(with_url(1))

        result = self.run_import(rows)

        self.assertEqual(1, result["empty"])
        self.assertEqual(0, result["stored"])
        self.assertTrue(self.state()["1"]["empty"])
        self.assertEqual(1, len(self.download.urls))

        result = self.run_import(rows)

        self.assertEqual(1, result["skipped"])
        self.assertEqual(1, len(self.download.urls))

    def test_unreadable_bytes_count_as_failed_and_are_retried(self) -> None:
        self.download.data = b"not a fit file at all"
        rows = self.sync(with_url(1))

        result = self.run_import(rows)

        self.assertEqual(1, result["failed"])
        self.assertEqual(0, result["empty"])
        self.assertEqual(1, self.state()["1"]["attempts"])
        self.assertFalse(self.state()["1"]["empty"])
        self.assertEqual([], self.stored_sets())

    def test_at_most_ten_downloads_run_per_sync(self) -> None:
        rows = self.sync(
            *(with_url(number, index=number - 1) for number in range(1, 13))
        )

        first = self.run_import(rows)
        downloads_after_first = len(self.download.urls)
        second = self.run_import(rows)

        self.assertEqual("ok", first["status"])
        self.assertEqual(10, first["stored"])
        self.assertEqual(10, downloads_after_first)
        self.assertEqual(2, second["stored"])
        self.assertEqual(10, second["skipped"])
        self.assertEqual(12, len(self.download.urls))

    def test_time_budget_stops_the_run_before_the_next_download(self) -> None:
        self.download.cost = 60.0
        rows = self.sync(with_url(1), with_url(2, index=1), with_url(3, index=2))

        result = self.run_import(rows)

        self.assertEqual("budget", result["status"])
        self.assertEqual(2, result["stored"])
        self.assertEqual(2, len(self.download.urls))
        self.assertEqual([], self.stored_sets("3"))
        self.assertGreaterEqual(self.clock.now, DETAIL_IMPORT_BUDGET_SECONDS)

    def test_rows_without_link_or_active_record_are_skipped(self) -> None:
        rows = self.sync(workout(1, starts(0)), with_url(2, index=1))
        unsynced = with_url(9, index=5)

        result = self.run_import([*rows, unsynced])

        self.assertEqual(1, result["stored"])
        self.assertEqual(2, result["skipped"])
        self.assertEqual(1, len(self.download.urls))

    def test_duplicate_rows_are_downloaded_once(self) -> None:
        rows = self.sync(with_url(1))

        result = self.run_import([rows[0], rows[0]])

        self.assertEqual(1, result["stored"])
        self.assertEqual(1, result["skipped"])
        self.assertEqual(1, len(self.download.urls))

    def test_state_is_pruned_to_the_current_workouts(self) -> None:
        rows = self.sync(with_url(1))
        self.download.failure = WahooFitUnavailable("unavailable")
        self.run_import(rows)
        self.assertIn("1", self.state())

        self.run_import([])

        self.assertEqual({}, self.state())

    def test_malformed_stored_state_is_ignored(self) -> None:
        rows = self.sync(with_url(1))
        with self.database.unit_of_work() as db:
            self.key_values.set(db, STATE_KEY, "not json")

        result = self.run_import(rows)

        self.assertEqual(1, result["stored"])

    def test_naive_retrieved_at_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.importer.import_details([], retrieved_at=datetime(2026, 10, 1))  # noqa: DTZ001 - naive value under test

    def test_download_link_is_absent_from_storage_and_logs(self) -> None:
        rows = self.sync(with_url(1), with_url(2, index=1))
        self.download.failure = WahooFitUnavailable("unavailable")
        self.run_import(rows)
        self.download.failure = None
        self.run_import(rows)

        tables = [
            row["name"]
            for row in self.rows("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
        self.assertTrue(tables)
        for table in tables:
            for row in self.rows(f'SELECT * FROM "{table}"'):
                for value in row.values():
                    text = (
                        value.decode("latin-1")
                        if isinstance(value, bytes)
                        else str(value)
                    )
                    for marker in LEAK_MARKERS:
                        self.assertNotIn(marker, text, table)
        for call in self.logger.mock_calls:
            for marker in LEAK_MARKERS:
                self.assertNotIn(marker, repr(call))


if __name__ == "__main__":
    unittest.main()
