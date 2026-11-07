"""Local session metrics (card M8): EF, VI, work and decoupling, stored per session."""

from __future__ import annotations

import tempfile
import unittest
from datetime import UTC, datetime
from typing import Any

from backend.activities.activity_summary import activity_summaries
from backend.canonical.activity_detail import ActivityStreamSet
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    StreamChannel,
    StreamResolution,
)
from backend.db.activity_detail_store import replace_detail_set
from backend.db.repositories import KeyValueRepository
from backend.performance.canonical_detail import CanonicalDetailReader
from backend.performance.session_metrics import (
    metrics_fingerprint,
    session_metrics,
)
from backend.performance.session_metrics_reads import (
    stored_session_metrics,
    with_session_metrics,
)
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.session_metrics import SessionMetricsStage, summarize_session_metrics
from tests.canonical_detail_support import NOW, ZONE, add_session_record, open_manager

FINGERPRINT = "0" * 64
# 50 minutes at 1 s: steady 200 W, HR 140 bpm in the first half after the
# warm-up and 145 bpm in the second.
SECONDS = 3000
TIME = tuple(float(second) for second in range(SECONDS + 1))
WATTS = tuple(200.0 for _ in TIME)
MIDPOINT = (600 + SECONDS) / 2
HEART = tuple(140.0 if second < MIDPOINT else 145.0 for second in TIME)


def _ride(**values: Any) -> dict[str, Any]:
    return {"id": "act_1", "sport": "ride", **values}


class SessionMetricsTests(unittest.TestCase):
    def test_ride_ef_and_vi_from_the_summary(self) -> None:
        result = session_metrics(
            _ride(normalized_power=230.0, avg_power=210.0, avg_hr=142.0),
            None,
            FINGERPRINT,
        )
        self.assertAlmostEqual(result.values[MetricKind.EFFICIENCY_FACTOR], 230 / 142)
        self.assertEqual(
            result.details[MetricKind.EFFICIENCY_FACTOR],
            {"basis": "normalized_power", "unit": "W/bpm"},
        )
        self.assertAlmostEqual(result.values[MetricKind.VARIABILITY_INDEX], 230 / 210)
        self.assertNotIn(MetricKind.MECHANICAL_WORK, result.values)
        self.assertNotIn(MetricKind.AEROBIC_DECOUPLING, result.values)

    def test_run_ef_uses_grade_adjusted_then_average_speed(self) -> None:
        gap = session_metrics(
            {
                "sport": "run",
                "avg_hr": 150.0,
                "grade_adjusted_speed_mps": 3.0,
                "avg_speed_mps": 2.8,
                "normalized_power": 300.0,
            },
            None,
            FINGERPRINT,
        )
        self.assertAlmostEqual(gap.values[MetricKind.EFFICIENCY_FACTOR], 1.2)
        self.assertEqual(
            gap.details[MetricKind.EFFICIENCY_FACTOR]["basis"], "grade_adjusted_speed"
        )
        self.assertNotIn(MetricKind.VARIABILITY_INDEX, gap.values)
        flat = session_metrics(
            {"sport": "run", "avg_hr": 150.0, "avg_speed_mps": 2.5}, None, FINGERPRINT
        )
        self.assertAlmostEqual(flat.values[MetricKind.EFFICIENCY_FACTOR], 1.0)
        self.assertEqual(
            flat.details[MetricKind.EFFICIENCY_FACTOR]["basis"], "average_speed"
        )

    def test_other_sports_and_missing_inputs_give_nothing(self) -> None:
        self.assertEqual(
            {},
            session_metrics(
                {"sport": "strength", "avg_hr": 120.0}, None, FINGERPRINT
            ).values,
        )
        self.assertEqual(
            {},
            session_metrics(
                _ride(normalized_power=230.0, avg_hr=10.0), None, FINGERPRINT
            ).values,
        )
        implausible = session_metrics(
            _ride(normalized_power=230.0, avg_power=20.0), None, FINGERPRINT
        )
        self.assertNotIn(MetricKind.VARIABILITY_INDEX, implausible.values)

    def test_work_prefers_the_device_total_then_the_power_stream(self) -> None:
        device = session_metrics(_ride(energy_kj=900.0), None, FINGERPRINT)
        self.assertEqual(device.values[MetricKind.MECHANICAL_WORK], 900.0)
        activity = {"sport": "ride", "streams": {"time": TIME, "watts": WATTS}}
        stream = session_metrics(
            _ride(moving_duration_s=float(SECONDS)), activity, FINGERPRINT
        )
        self.assertAlmostEqual(stream.values[MetricKind.MECHANICAL_WORK], 600.0)
        self.assertEqual(
            stream.details[MetricKind.MECHANICAL_WORK],
            {"basis": "power_stream", "coverage": 1.0},
        )

    def test_work_needs_power_coverage(self) -> None:
        # A 20-second gap every 20 seconds leaves half the moving time uncovered.
        times = tuple(float(second) for second in range(0, SECONDS, 20))
        activity = {
            "sport": "ride",
            "streams": {"time": times, "watts": tuple(200.0 for _ in times)},
        }
        result = session_metrics(
            _ride(moving_duration_s=float(SECONDS)), activity, FINGERPRINT
        )
        self.assertNotIn(MetricKind.MECHANICAL_WORK, result.values)

    def test_decoupling_is_the_session_analysis_drift(self) -> None:
        activity = {
            "sport": "ride",
            "streams": {"time": TIME, "watts": WATTS, "heartrate": HEART},
        }
        result = session_metrics(_ride(), activity, FINGERPRINT)
        expected = 100 * (200 / 140 - 200 / 145) / (200 / 140)
        self.assertAlmostEqual(
            result.values[MetricKind.AEROBIC_DECOUPLING], expected, places=1
        )
        self.assertEqual(
            result.details[MetricKind.AEROBIC_DECOUPLING]["sensor"], "watts"
        )

    def test_fingerprint_follows_inputs(self) -> None:
        base = metrics_fingerprint(_ride(started_at=NOW), ["a"], [["garmin", "g1"]])
        self.assertEqual(
            base, metrics_fingerprint(_ride(started_at=NOW), ["a"], [["garmin", "g1"]])
        )
        for other in (
            metrics_fingerprint(
                _ride(started_at=NOW, avg_hr=140.0), ["a"], [["garmin", "g1"]]
            ),
            metrics_fingerprint(_ride(started_at=NOW), ["b"], [["garmin", "g1"]]),
            metrics_fingerprint(_ride(started_at=NOW), ["a"], [["wahoo", "w1"]]),
        ):
            self.assertNotEqual(base, other)


def _store_streams(
    db: Any, provider_activity_id: str, *, provider: ProviderId = ProviderId.GARMIN
) -> None:
    replace_detail_set(
        db,
        ActivityStreamSet(
            provider_activity_id=provider_activity_id,
            provenance=Provenance(
                provider=provider,
                source_kind=SourceKind.PROVIDER_REPORTED,
                source_record_id=None,
                recorded_by=RecordingOrigin.GARMIN,
                retrieved_at=datetime(2026, 10, 18, 8, 0, tzinfo=UTC),
                label="Garmin Connect",
            ),
            origin=ActivityDetailOrigin.FETCH,
            resolution=StreamResolution.FULL,
            channels={
                StreamChannel.TIME_S: TIME,
                StreamChannel.POWER_W: WATTS,
                StreamChannel.HEART_RATE_BPM: HEART,
            },
        ),
        mapper_version=1,
        summary_sha256=None,
        now=NOW,
    )


class SessionMetricsStageTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.stage = SessionMetricsStage(
            key_values=self.key_values,
            zone_provider=lambda: ZONE,
            clock=lambda: NOW,
            batch_size=1,
        )
        add_session_record(
            self.manager,
            ProviderId.GARMIN,
            "g1",
            "act_g1",
            normalized_power=210.0,
            avg_power=200.0,
            avg_hr=142.0,
            moving_duration_s=float(SECONDS),
        )

    def _run(self) -> dict[str, Any]:
        with self.manager.unit_of_work() as db:
            self.stage.run_batch(db)
            return summarize_session_metrics(self.key_values, db)

    def _served(self) -> dict[str, Any]:
        with self.manager.reader() as db:
            summaries = activity_summaries(
                CanonicalTableReader().activity_sessions(db), ZONE
            )
            (summary,) = with_session_metrics(summaries, stored_session_metrics(db))
            return summary

    def test_summary_values_without_streams(self) -> None:
        state = self._run()
        self.assertEqual(state["status"], "complete")
        summary = self._served()
        self.assertAlmostEqual(summary["efficiency_factor"], round(210 / 142, 4))
        self.assertEqual(summary["efficiency_factor_unit"], "W/bpm")
        self.assertAlmostEqual(summary["variability_index"], 1.05)
        self.assertNotIn("decoupling_pct", summary)
        self.assertEqual(summary["sources"]["efficiency_factor"], "derived")

    def test_streams_add_work_and_decoupling_and_unchanged_passes_write_nothing(
        self,
    ) -> None:
        self._run()
        with self.manager.unit_of_work() as db:
            _store_streams(db, "g1")
        state = self._run()
        self.assertEqual(state["counts"]["computed"], 1)
        summary = self._served()
        self.assertAlmostEqual(summary["work_kj"], 600.0)
        self.assertGreater(summary["decoupling_pct"], 3.0)
        again = self._run()
        self.assertEqual(again["counts"]["computed"], 0)
        self.assertEqual(again["counts"]["written"], 0)
        self.assertEqual(again["counts"]["retired"], 0)

    def test_detail_document_shows_the_local_values(self) -> None:
        with self.manager.unit_of_work() as db:
            _store_streams(db, "g1")
        self._run()
        reader = CanonicalDetailReader(
            CanonicalTableReader().session_activities, refreshable=frozenset
        )
        with self.manager.reader() as db:
            document = reader.read(db, "act_g1")
        assert document is not None
        metrics = document["metrics"]
        self.assertEqual(metrics["efficiency_factor"]["unit"], "W/bpm")
        self.assertEqual(metrics["work_kj"]["source"]["kind"], "derived")
        self.assertEqual(metrics["work_kj"]["basis"], "power_stream")
        self.assertIn("decoupling_pct", metrics)

    def test_batches_resume_and_gone_sessions_retire(self) -> None:
        add_session_record(
            self.manager,
            ProviderId.WAHOO,
            "w1",
            "act_w1",
            recorded_by="wahoo",
            normalized_power=220.0,
            avg_hr=150.0,
        )
        first = self._run()
        self.assertEqual(first["status"], "running")
        self.assertEqual(first["counts"]["pending"], 1)
        self.assertEqual(self._run()["status"], "complete")
        with self.manager.unit_of_work() as db:
            db.execute(
                "UPDATE activity_sessions SET state = 'deleted' WHERE activity_id = ?",
                ("act_w1",),
            )
        state = self._run()
        self.assertEqual(state["counts"]["retired"], 1)  # its EF row
        with self.manager.reader() as db:
            self.assertEqual(set(stored_session_metrics(db)), {"act_g1"})

    def test_intervals_streams_are_not_read(self) -> None:
        # Athlete decision 2026-11-07 (#1685): only Garmin, Wahoo and local data.
        add_session_record(self.manager, ProviderId.INTERVALS, "i1", "act_g1")
        with self.manager.unit_of_work() as db:
            _store_streams(db, "i1", provider=ProviderId.INTERVALS)
        self._run()
        summary = self._served()
        self.assertNotIn("work_kj", summary)
        self.assertNotIn("decoupling_pct", summary)

    def test_session_without_values_is_not_recomputed(self) -> None:
        add_session_record(self.manager, ProviderId.GARMIN, "g2", "act_g2", sport="run")
        self._run()
        self._run()
        state = self._run()
        self.assertEqual(state["counts"]["computed"], 0)
        self.assertEqual(state["counts"]["values"], {})


if __name__ == "__main__":
    unittest.main()
