"""The Intervals.icu power curve through the canonical tables (schema v17).

The stored ``cycling_power_profile`` envelope is mapped to one canonical power
curve fetch and its points at ingest and by the backfill; the analysis chart
reads them through the canonical ports and shows the same envelope the snapshot
read showed. Temporary SQLite files, synthetic values, no provider access.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.athlete.local_date import LocalDate
from backend.canonical.domain_records import (
    EMPTY_POWER_CURVE,
    PowerCurve,
    PowerCurveFetch,
    PowerCurvePoint,
)
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import ProviderId, RecordingOrigin, SourceKind
from backend.db import DatabaseManager, canonical_domain_store, row_factory
from backend.db.repositories import KeyValueRepository
from backend.db.schema import initialize_schema
from backend.performance.canonical_inputs import (
    EMPTY_PERFORMANCE_INPUTS,
    CanonicalPerformanceInputs,
    read_performance_inputs,
)
from backend.performance.chart_history import analysis_history
from backend.providers.canonical_plans import (
    POWER_CURVE_RECORD_ID,
    POWER_CURVE_RECORD_KIND,
    reprojection_plan,
)
from backend.providers.intervals_power import POWER_CURVE_LABEL
from backend.providers.intervals_power_curve_mapping import (
    PowerCurveMapping,
    map_intervals_power_curve,
)
from backend.runtime.ports import PowerCurveReader
from backend.sync.canonical_backfill import CanonicalBackfill
from backend.sync.canonical_backfill import _ingest_work as backfill_ingest_work
from backend.sync.canonical_ingest import (
    ingest_intervals_partial_snapshot,
    ingest_intervals_snapshot,
)
from backend.sync.canonical_read_selector import PENDING_READER, CanonicalReadSelector
from backend.sync.canonical_table_reader import CanonicalTableReader

ZONE = ZoneInfo("Europe/Berlin")
TODAY = date(2026, 10, 20)
NOW = "2026-10-20T06:00:00+00:00"
FETCHED = datetime(2026, 10, 20, 6, 0, tzinfo=UTC)
CHART_START = TODAY - timedelta(days=89)


def point(duration: int, watts: Any, day: str, activity: str = "") -> dict[str, Any]:
    return {
        "duration_seconds": duration,
        "watts": watts,
        "date": day,
        "activity_id": activity,
        "source": POWER_CURVE_LABEL,
        "status": "ok",
    }


# The envelope IntervalsReader stores: one best effort before the chart window.
ENVELOPE: dict[str, Any] = {
    "status": "ok",
    "start": "2026-07-01",
    "end": TODAY.isoformat(),
    "synced_at": "2026-10-20T05:59:58.123456+00:00",
    "points": [
        point(5, 910, "2026-10-01", "i501"),
        point(60, 452.5, "2026-09-12", "i502"),
        point(300, 360, "2026-07-02", "i503"),
        point(1200, 301, "2026-07-23"),
        point(3600, 255, "2026-10-19", "i505"),
    ],
}


def snapshot(curve: Any = ENVELOPE, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "synced_at": NOW,
        "raw_provider_data": {"wellness": []},
        **extra,
    }
    if curve is not None:
        payload["cycling_power_profile"] = curve
    return payload


def legacy_chart(stored: dict[str, Any] | None, start: date, today: date) -> Any:
    """The chart's former read of the snapshot's power curve, kept for parity."""
    profile = (stored or {}).get("cycling_power_profile") or {}
    rows = profile.get("points")
    kept = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        try:
            day = LocalDate.parse(row.get("date")).to_date()
        except ValueError:
            continue
        if start <= day <= today:
            kept.append(row)
    return {**profile, "points": kept}


def chart(curve: PowerCurve) -> Any:
    inputs = CanonicalPerformanceInputs(
        wellness_day=None, ctl=None, atl=None, power_curve=curve
    )
    return analysis_history(None, {}, TODAY, canonical=inputs)["cycling_power_profile"]


def provenance(source_record_id: str | None = POWER_CURVE_RECORD_ID) -> Provenance:
    return Provenance(
        provider=ProviderId.INTERVALS,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=source_record_id,
        recorded_by=RecordingOrigin.UNKNOWN,
        retrieved_at=FETCHED,
        label=POWER_CURVE_LABEL,
    )


def curve_point(**overrides: Any) -> PowerCurvePoint:
    values: dict[str, Any] = {
        "duration_s": 60,
        "watts": 450.0,
        "observed_on": date(2026, 10, 1),
        "provider_activity_id": "i1",
        "provenance": provenance(),
    }
    values.update(overrides)
    return PowerCurvePoint(**values)


def curve_fetch(**overrides: Any) -> PowerCurveFetch:
    values: dict[str, Any] = {
        "fetch_status": "ok",
        "window_start": date(2026, 7, 1),
        "window_end": TODAY,
        "provenance": provenance(),
    }
    values.update(overrides)
    return PowerCurveFetch(**values)


class PowerCurveRecordTests(unittest.TestCase):
    def test_invalid_points_are_rejected(self) -> None:
        for overrides, error in (
            ({"duration_s": 0}, ValueError),
            ({"duration_s": True}, TypeError),
            ({"watts": -1}, ValueError),
            ({"watts": 6000}, ValueError),
            ({"provenance": provenance(None)}, ValueError),
        ):
            with self.subTest(overrides=overrides), self.assertRaises(error):
                curve_point(**overrides)

    def test_invalid_fetches_are_rejected(self) -> None:
        for overrides, error in (
            ({"fetch_status": "Failed"}, ValueError),
            ({"fetch_status": None}, TypeError),
            ({"window_end": None}, ValueError),
            ({"window_end": date(2026, 6, 1)}, ValueError),
            ({"provenance": provenance(None)}, ValueError),
        ):
            with self.subTest(overrides=overrides), self.assertRaises(error):
                curve_fetch(**overrides)
        self.assertIsNone(curve_fetch(window_start=None, window_end=None).window_end)


class PowerCurveMappingTests(unittest.TestCase):
    def mapped(self, envelope: Any) -> PowerCurveMapping:
        return map_intervals_power_curve(
            envelope,
            source_record_id=POWER_CURVE_RECORD_ID,
            fetched_at=FETCHED,
            zone=ZONE,
        )

    def test_the_fetch_is_mapped_once_and_every_point_keeps_its_values(self) -> None:
        mapped = self.mapped(ENVELOPE)
        synced = datetime.fromisoformat(ENVELOPE["synced_at"])
        self.assertEqual(
            mapped.fetch,
            curve_fetch(provenance=replace(provenance(), retrieved_at=synced)),
        )
        points = mapped.points
        assert points is not None
        self.assertEqual([p.duration_s for p in points], [5, 60, 300, 1200, 3600])
        first = points[0]
        self.assertEqual(first.watts, 910.0)
        self.assertEqual(first.observed_on, date(2026, 10, 1))
        self.assertEqual(first.provider_activity_id, "i501")
        self.assertEqual(first.provenance.retrieved_at, synced)
        self.assertEqual(first.provenance.label, POWER_CURVE_LABEL)
        self.assertIsNone(points[3].provider_activity_id)

    def test_unusable_points_are_left_out(self) -> None:
        envelope = {
            **ENVELOPE,
            "synced_at": None,
            "points": [
                {**point(5, 910, "2026-10-01"), "status": "estimated"},
                point(60, -5, "2026-10-01"),
                point(60, 400, "2026-06-01"),
                point(60, 450, "not a day"),
                point(60, 451, "2026-10-02"),
                point(60, 999, "2026-10-03"),
                "not a point",
            ],
        }
        mapped = self.mapped(envelope)
        assert mapped.fetch is not None and mapped.points is not None
        self.assertEqual(
            [(p.duration_s, p.watts) for p in mapped.points], [(60, 451.0)]
        )
        self.assertEqual(mapped.points[0].provenance.retrieved_at, FETCHED)
        self.assertIsNone(mapped.fetch.provenance.retrieved_at)

    def test_an_envelope_without_a_usable_curve_keeps_the_points(self) -> None:
        for envelope, window_start in (
            ({"status": "failed"}, None),
            ({**ENVELOPE, "start": "x"}, None),
            ({**ENVELOPE, "end": "2026-06-01"}, None),
            ({**ENVELOPE, "points": None}, date(2026, 7, 1)),
        ):
            with self.subTest(envelope=envelope):
                mapped = self.mapped(envelope)
                self.assertIsNone(mapped.points)
                assert mapped.fetch is not None
                self.assertEqual(mapped.fetch.fetch_status, envelope["status"])
                self.assertEqual(mapped.fetch.window_start, window_start)
        empty = {**ENVELOPE, "status": "insufficient_data", "points": []}
        self.assertEqual(self.mapped(empty).points, ())
        broken: tuple[Any, ...] = (None, [], {**ENVELOPE, "status": None})
        for envelope in broken:
            with self.subTest(envelope=envelope):
                self.assertEqual(self.mapped(envelope), PowerCurveMapping())


def stored_points(db: sqlite3.Connection) -> tuple[PowerCurvePoint, ...]:
    return CanonicalTableReader().power_curve(db).points


def active_point_count(db: sqlite3.Connection) -> int:
    row = db.execute(
        "SELECT COUNT(*) AS n FROM power_curve_points WHERE state = 'active'"
    ).fetchone()
    return int(row["n"])


class IngestFixture(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.db = sqlite3.connect(self.root / "curve.db")
        self.db.row_factory = row_factory
        self.addCleanup(self.db.close)
        initialize_schema(self.db)

    def ingest(self, stored: dict[str, Any], *, partial: bool = False) -> None:
        if partial:
            ingest_intervals_partial_snapshot(self.db, stored, zone=ZONE)
        else:
            ingest_intervals_snapshot(
                self.db,
                stored,
                zone=ZONE,
                activity_days=None,
                all_sync_days=365,
                earliest_date=date(2020, 1, 1),
            )
        self.db.commit()

    def curve(self) -> PowerCurve:
        return CanonicalTableReader().power_curve(self.db)


class PowerCurveIngestTests(IngestFixture):
    def test_the_chart_shows_the_snapshot_curve_after_ingest(self) -> None:
        self.ingest(snapshot())
        raw = self.db.execute(
            "SELECT payload FROM provider_records WHERE record_kind = ?",
            (POWER_CURVE_RECORD_KIND,),
        ).fetchone()
        self.assertEqual(json.loads(raw["payload"]), ENVELOPE)
        shown = chart(self.curve())
        self.assertEqual(shown, legacy_chart(snapshot(), CHART_START, TODAY))
        self.assertEqual(
            [p["duration_seconds"] for p in shown["points"]], [5, 60, 1200, 3600]
        )
        self.assertIsInstance(shown["points"][0]["watts"], int)
        self.assertEqual(len(self.curve().fetches), 1)

    def test_a_failed_fetch_keeps_the_points_and_shows_the_failure(self) -> None:
        self.ingest(snapshot())
        failed = snapshot({**ENVELOPE, "status": "failed"})
        self.ingest(failed, partial=True)
        shown = chart(self.curve())
        self.assertEqual(shown["status"], "failed")
        self.assertEqual(shown, legacy_chart(failed, CHART_START, TODAY))

    def test_a_failure_without_a_curve_keeps_the_points_and_records_it(self) -> None:
        self.ingest(snapshot())
        before = stored_points(self.db)
        self.ingest(snapshot({"status": "failed"}), partial=True)
        self.assertEqual(stored_points(self.db), before)
        self.assertEqual(active_point_count(self.db), 5)
        shown = chart(self.curve())
        self.assertEqual(shown["status"], "failed")
        self.assertNotIn("start", shown)
        self.assertEqual(
            shown["points"], legacy_chart(snapshot(), CHART_START, TODAY)["points"]
        )

    def test_a_status_without_points_is_shown(self) -> None:
        for envelope in (
            {"status": "failed"},
            {
                "status": "insufficient_data",
                "start": "2026-07-23",
                "end": TODAY.isoformat(),
                "synced_at": NOW,
                "points": [],
            },
        ):
            with self.subTest(envelope=envelope):
                self.setUp()
                stored = snapshot(envelope)
                self.ingest(stored)
                self.assertEqual(stored_points(self.db), ())
                shown = chart(self.curve())
                self.assertEqual(shown["status"], envelope["status"])
                self.assertEqual(shown, legacy_chart(stored, CHART_START, TODAY))

    def test_a_sync_without_a_curve_keeps_it_and_a_new_curve_replaces_it(
        self,
    ) -> None:
        self.ingest(snapshot())
        self.ingest(snapshot(None), partial=True)
        self.ingest(snapshot({}))
        self.assertEqual(len(stored_points(self.db)), 5)
        smaller = {**ENVELOPE, "points": [point(5, 920, "2026-10-18", "i9")]}
        self.ingest(snapshot(smaller))
        self.assertEqual(
            [(p.duration_s, p.watts) for p in stored_points(self.db)], [(5, 920.0)]
        )
        self.assertEqual(
            chart(self.curve()), legacy_chart(snapshot(smaller), CHART_START, TODAY)
        )
        self.assertEqual(active_point_count(self.db), 1)

    def test_no_stored_curve_shows_no_points(self) -> None:
        self.assertEqual(
            chart(EMPTY_POWER_CURVE), legacy_chart(None, CHART_START, TODAY)
        )
        self.assertEqual(
            analysis_history(None, {}, TODAY, canonical=EMPTY_PERFORMANCE_INPUTS)[
                "cycling_power_profile"
            ],
            {"points": []},
        )

    def test_reprojection_of_the_raw_record_emits_the_same_rows(self) -> None:
        self.ingest(snapshot())
        row = self.db.execute(
            "SELECT * FROM provider_records WHERE record_kind = ?",
            (POWER_CURVE_RECORD_KIND,),
        ).fetchone()
        plan = reprojection_plan(dict(row), zone=ZONE)
        assert plan is not None
        batch = plan.domain_batches[0]
        self.assertEqual(batch.power_curve, stored_points(self.db))
        self.assertEqual((batch.power_curve_fetch,), self.curve().fetches)

    def test_the_stored_rows_are_listed(self) -> None:
        self.ingest(snapshot())
        self.assertEqual(
            len(canonical_domain_store.active_power_curve_rows(self.db)), 5
        )
        self.assertEqual(
            len(canonical_domain_store.active_power_curve_fetch_rows(self.db)), 1
        )


class PowerCurveReadStateTests(IngestFixture):
    def selector(
        self, key_values: KeyValueRepository | None = None
    ) -> CanonicalReadSelector:
        return CanonicalReadSelector(
            table=CanonicalTableReader(),
            reprojecting_table=CanonicalTableReader(),
            key_values=key_values or KeyValueRepository(lambda: NOW),
            zone=lambda _db: ZONE,
            compact_only=lambda _db: False,
        )

    def test_nothing_is_read_before_the_first_completed_backfill(self) -> None:
        self.ingest(snapshot())
        pending = PENDING_READER
        assert isinstance(pending, PowerCurveReader)
        self.assertEqual(pending.power_curve(self.db), EMPTY_POWER_CURVE)
        selector = self.selector()
        self.assertIs(selector.reader_for(self.db), PENDING_READER)
        inputs = read_performance_inputs(
            selector,
            self.db,
            activity_reader=selector,
            as_of=TODAY,
            include_power_curve=True,
        )
        assert inputs is not None
        self.assertEqual(inputs.power_curve, EMPTY_POWER_CURVE)
        self.assertEqual(chart(inputs.power_curve), {"points": []})

    def test_the_curve_is_read_only_when_asked_and_without_other_inputs(
        self,
    ) -> None:
        self.ingest(snapshot())
        reader = CanonicalTableReader()
        self.assertIsNone(read_performance_inputs(reader, self.db, as_of=TODAY))
        inputs = read_performance_inputs(
            reader, self.db, as_of=TODAY, include_power_curve=True
        )
        assert inputs is not None
        self.assertEqual(inputs.power_curve, self.curve())
        self.assertEqual(
            chart(inputs.power_curve), legacy_chart(snapshot(), CHART_START, TODAY)
        )

    def backfilled(
        self, *snapshots: dict[str, Any]
    ) -> tuple[int, CanonicalPerformanceInputs | None]:
        manager = DatabaseManager(
            self.root / "backfill.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(manager.close)
        key_values = KeyValueRepository(lambda: NOW)
        with manager.unit_of_work() as db:
            initialize_schema(db)
            for stored in snapshots:
                db.execute(
                    "INSERT INTO snapshots(payload, created_at, synced_at, "
                    "recent_activity_count) VALUES (?, ?, ?, 0)",
                    (json.dumps(stored), NOW, NOW),
                )
        backfill = CanonicalBackfill(
            key_values=key_values, zone_provider=lambda: ZONE, clock=lambda: NOW
        )
        for _ in range(100):
            with manager.unit_of_work() as db:
                if backfill.run_batch(db).done:
                    break
        selector = self.selector(key_values)
        with manager.reader() as db:
            raw = db.execute(
                "SELECT COUNT(*) AS n FROM provider_records WHERE record_kind = ?",
                (POWER_CURVE_RECORD_KIND,),
            ).fetchone()
            return int(raw["n"]), read_performance_inputs(
                selector,
                db,
                activity_reader=selector,
                as_of=TODAY,
                include_power_curve=True,
            )

    def test_the_backfill_projects_a_stored_snapshot_and_reads_follow(self) -> None:
        raw, inputs = self.backfilled(snapshot())
        assert inputs is not None
        self.assertEqual(raw, 1)
        self.assertEqual(
            chart(inputs.power_curve), legacy_chart(snapshot(), CHART_START, TODAY)
        )

    def test_the_backfill_never_takes_an_older_snapshots_curve(self) -> None:
        for newest, raw_records in (
            (snapshot(None), 0),
            (snapshot({}), 0),
            (snapshot({"status": "Not a status"}), 1),
        ):
            with self.subTest(newest=newest.get("cycling_power_profile")):
                self.setUp()
                raw, inputs = self.backfilled(snapshot(), newest)
                assert inputs is not None
                self.assertEqual(raw, raw_records)
                self.assertEqual(inputs.power_curve, EMPTY_POWER_CURVE)

    def test_only_the_newest_snapshot_plans_its_curve(self) -> None:
        text = json.dumps(snapshot())
        self.assertEqual(backfill_ingest_work("snapshot", text, ZONE, False).items, ())
        self.assertEqual(
            len(backfill_ingest_work("snapshot", text, ZONE, True).items), 2
        )


if __name__ == "__main__":
    unittest.main()
