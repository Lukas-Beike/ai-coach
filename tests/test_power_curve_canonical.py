"""The Intervals.icu power curve through the canonical tables (schema v17).

The stored ``cycling_power_profile`` envelope is mapped to canonical power curve
points at ingest and by the backfill; the analysis chart reads them through the
canonical ports and shows the same envelope the snapshot read showed. Temporary
SQLite files, synthetic values, no provider access.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from backend.athlete.local_date import LocalDate
from backend.canonical.domain_records import PowerCurvePoint
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
from backend.providers.intervals_power_curve_mapping import map_intervals_power_curve
from backend.runtime.ports import PowerCurveReader
from backend.sync.canonical_backfill import CanonicalBackfill
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


def chart(points: tuple[PowerCurvePoint, ...]) -> Any:
    inputs = CanonicalPerformanceInputs(
        wellness_day=None, ctl=None, atl=None, power_curve=points
    )
    return analysis_history(None, {}, TODAY, canonical=inputs)["cycling_power_profile"]


def curve_point(**overrides: Any) -> PowerCurvePoint:
    values: dict[str, Any] = {
        "duration_s": 60,
        "watts": 450.0,
        "observed_on": date(2026, 10, 1),
        "provider_activity_id": "i1",
        "window_start": date(2026, 7, 1),
        "window_end": TODAY,
        "fetch_status": "ok",
        "provenance": Provenance(
            provider=ProviderId.INTERVALS,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=POWER_CURVE_RECORD_ID,
            recorded_by=RecordingOrigin.UNKNOWN,
            retrieved_at=FETCHED,
            label=POWER_CURVE_LABEL,
        ),
    }
    values.update(overrides)
    return PowerCurvePoint(**values)


class PowerCurveRecordTests(unittest.TestCase):
    def test_invalid_points_are_rejected(self) -> None:
        for overrides, error in (
            ({"duration_s": 0}, ValueError),
            ({"duration_s": True}, TypeError),
            ({"watts": -1}, ValueError),
            ({"watts": 6000}, ValueError),
            ({"observed_on": date(2026, 6, 30)}, ValueError),
            ({"window_end": date(2026, 6, 1)}, ValueError),
            ({"fetch_status": "Failed"}, ValueError),
            ({"fetch_status": None}, TypeError),
        ):
            with self.subTest(overrides=overrides), self.assertRaises(error):
                curve_point(**overrides)

    def test_points_need_a_provider_source(self) -> None:
        with self.assertRaises(ValueError):
            curve_point(
                provenance=Provenance(
                    provider=ProviderId.INTERVALS,
                    source_kind=SourceKind.PROVIDER_REPORTED,
                    source_record_id=None,
                    recorded_by=RecordingOrigin.UNKNOWN,
                    retrieved_at=FETCHED,
                    label=None,
                )
            )


class PowerCurveMappingTests(unittest.TestCase):
    def mapped(self, envelope: Any) -> tuple[PowerCurvePoint, ...]:
        return map_intervals_power_curve(
            envelope,
            source_record_id=POWER_CURVE_RECORD_ID,
            fetched_at=FETCHED,
            zone=ZONE,
        )

    def test_every_ok_point_keeps_its_values_window_and_fetch(self) -> None:
        points = self.mapped(ENVELOPE)
        self.assertEqual([p.duration_s for p in points], [5, 60, 300, 1200, 3600])
        first = points[0]
        self.assertEqual(first.watts, 910.0)
        self.assertEqual(first.observed_on, date(2026, 10, 1))
        self.assertEqual(first.provider_activity_id, "i501")
        self.assertEqual(
            (first.window_start, first.window_end), (date(2026, 7, 1), TODAY)
        )
        self.assertEqual(first.fetch_status, "ok")
        self.assertEqual(
            first.provenance.retrieved_at,
            datetime.fromisoformat(ENVELOPE["synced_at"]),
        )
        self.assertEqual(first.provenance.label, POWER_CURVE_LABEL)
        self.assertIsNone(points[3].provider_activity_id)

    def test_unusable_points_and_envelopes_map_to_nothing(self) -> None:
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
        points = self.mapped(envelope)
        self.assertEqual([(p.duration_s, p.watts) for p in points], [(60, 451.0)])
        self.assertEqual(points[0].provenance.retrieved_at, FETCHED)
        broken_envelopes: tuple[Any, ...] = (
            None,
            [],
            {"status": "failed"},
            {**ENVELOPE, "start": "x"},
            {**ENVELOPE, "points": None},
            {**ENVELOPE, "status": None},
        )
        for broken in broken_envelopes:
            with self.subTest(envelope=broken):
                self.assertEqual(self.mapped(broken), ())


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

    def points(self) -> tuple[PowerCurvePoint, ...]:
        return CanonicalTableReader().power_curve(self.db)


class PowerCurveIngestTests(IngestFixture):
    def test_the_chart_shows_the_snapshot_curve_after_ingest(self) -> None:
        self.ingest(snapshot())
        raw = self.db.execute(
            "SELECT payload FROM provider_records WHERE record_kind = ?",
            (POWER_CURVE_RECORD_KIND,),
        ).fetchone()
        self.assertEqual(json.loads(raw["payload"]), ENVELOPE)
        shown = chart(self.points())
        self.assertEqual(shown, legacy_chart(snapshot(), CHART_START, TODAY))
        self.assertEqual(
            [p["duration_seconds"] for p in shown["points"]], [5, 60, 1200, 3600]
        )
        self.assertIsInstance(shown["points"][0]["watts"], int)

    def test_a_failed_fetch_keeps_the_points_and_shows_the_failure(self) -> None:
        self.ingest(snapshot())
        failed = snapshot({**ENVELOPE, "status": "failed"})
        self.ingest(failed, partial=True)
        shown = chart(self.points())
        self.assertEqual(shown["status"], "failed")
        self.assertEqual(shown, legacy_chart(failed, CHART_START, TODAY))

    def test_a_sync_without_a_curve_keeps_it_and_a_new_curve_replaces_it(
        self,
    ) -> None:
        self.ingest(snapshot())
        self.ingest(snapshot(None), partial=True)
        self.ingest(snapshot({}))
        self.assertEqual(len(self.points()), 5)
        smaller = {**ENVELOPE, "points": [point(5, 920, "2026-10-18", "i9")]}
        self.ingest(snapshot(smaller))
        self.assertEqual([(p.duration_s, p.watts) for p in self.points()], [(5, 920.0)])
        self.assertEqual(
            chart(self.points()), legacy_chart(snapshot(smaller), CHART_START, TODAY)
        )
        retired = self.db.execute(
            "SELECT COUNT(*) AS n FROM power_curve_points WHERE state = 'retired'"
        ).fetchone()
        self.assertEqual(retired["n"], 4)

    def test_no_stored_curve_shows_no_points(self) -> None:
        self.assertEqual(chart(()), legacy_chart(None, CHART_START, TODAY))
        self.assertEqual(
            analysis_history(None, {}, TODAY, canonical=EMPTY_PERFORMANCE_INPUTS)[
                "cycling_power_profile"
            ],
            {"points": []},
        )

    def test_reprojection_of_the_raw_record_emits_the_same_points(self) -> None:
        self.ingest(snapshot())
        row = self.db.execute(
            "SELECT * FROM provider_records WHERE record_kind = ?",
            (POWER_CURVE_RECORD_KIND,),
        ).fetchone()
        plan = reprojection_plan(dict(row), zone=ZONE)
        assert plan is not None
        self.assertEqual(plan.domain_batches[0].power_curve, self.points())

    def test_the_export_reads_every_row(self) -> None:
        self.ingest(snapshot())
        rows = self.db.execute("SELECT * FROM power_curve_points").fetchall()
        self.assertEqual(len(rows), 5)
        self.assertEqual(
            len(canonical_domain_store.active_power_curve_rows(self.db)), 5
        )


class PowerCurveReadStateTests(IngestFixture):
    def selector(self) -> CanonicalReadSelector:
        return CanonicalReadSelector(
            table=CanonicalTableReader(),
            reprojecting_table=CanonicalTableReader(),
            key_values=KeyValueRepository(lambda: NOW),
            zone=lambda _db: ZONE,
            compact_only=lambda _db: False,
        )

    def test_nothing_is_read_before_the_first_completed_backfill(self) -> None:
        self.ingest(snapshot())
        pending = PENDING_READER
        assert isinstance(pending, PowerCurveReader)
        self.assertEqual(pending.power_curve(self.db), ())
        selector = self.selector()
        self.assertIs(selector.reader_for(self.db), PENDING_READER)
        inputs = read_performance_inputs(
            selector, self.db, activity_reader=selector, as_of=TODAY
        )
        assert inputs is not None
        self.assertEqual(inputs.power_curve, ())
        self.assertEqual(chart(inputs.power_curve), {"points": []})

    def test_the_backfill_projects_a_stored_snapshot_and_reads_follow(self) -> None:
        manager = DatabaseManager(
            self.root / "backfill.db", sqlite3, row_factory=row_factory
        )
        self.addCleanup(manager.close)
        key_values = KeyValueRepository(lambda: NOW)
        with manager.unit_of_work() as db:
            initialize_schema(db)
            db.execute(
                "INSERT INTO snapshots(payload, created_at, synced_at, "
                "recent_activity_count) VALUES (?, ?, ?, 0)",
                (json.dumps(snapshot()), NOW, NOW),
            )
        backfill = CanonicalBackfill(
            key_values=key_values, zone_provider=lambda: ZONE, clock=lambda: NOW
        )
        for _ in range(100):
            with manager.unit_of_work() as db:
                if backfill.run_batch(db).done:
                    break
        selector = CanonicalReadSelector(
            table=CanonicalTableReader(),
            reprojecting_table=CanonicalTableReader(),
            key_values=key_values,
            zone=lambda _db: ZONE,
            compact_only=lambda _db: False,
        )
        with manager.reader() as db:
            inputs = read_performance_inputs(
                selector, db, activity_reader=selector, as_of=TODAY
            )
        assert inputs is not None
        self.assertEqual(
            chart(inputs.power_curve), legacy_chart(snapshot(), CHART_START, TODAY)
        )


if __name__ == "__main__":
    unittest.main()
