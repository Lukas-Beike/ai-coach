"""The one canonical session analysis per session (#1685), stored as version 3."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import patch

from backend.canonical.activity_detail import (
    ActivityLap,
    ActivityLapSet,
    ActivityStreamSet,
)
from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    LapKind,
    LapSource,
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
    StreamChannel,
    StreamResolution,
)
from backend.db import activity_detail_store, canonical_store
from backend.db.activity_detail_store import replace_detail_set, save_analysis
from backend.db.repositories import KeyValueRepository
from backend.performance import canonical_session_analysis
from backend.performance.canonical_detail import CanonicalDetailReader
from backend.performance.canonical_session_analysis import ANALYSIS_VERSION
from backend.performance.session_analysis_reads import (
    analysis_summaries,
    calendar_profiles,
)
from backend.performance.zone_time_reads import read_zone_times, with_zone_times
from backend.providers.garmin_health_mapping import MAPPER_VERSION
from backend.runtime.maintenance import MaintenanceGate
from backend.sync import session_analysis_stage
from backend.sync.canonical_backfill_assembly import build_canonical_backfill
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.session_analysis_stage import (
    SessionAnalysisStage,
    summarize_session_analysis,
)
from tests.canonical_detail_support import NOW, ZONE, add_session_record, open_manager

GARMIN = ProviderId.GARMIN
INTERVALS = ProviderId.INTERVALS
SECONDS = 3000
TIME = tuple(float(second) for second in range(SECONDS + 1))
WATTS = tuple(200.0 for _ in TIME)
HEART = tuple(140.0 for _ in TIME)
TARGETS = {"steps": [{"kind": "power", "target": "100%", "duration": 600}]}


def _provenance(provider: ProviderId) -> Provenance:
    return Provenance(
        provider=provider,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=None,
        recorded_by=RecordingOrigin.GARMIN,
        retrieved_at=datetime(2026, 10, 18, 8, 0, tzinfo=UTC),
        label=provider.value.title(),
    )


def _streams(
    db: Any,
    provider: ProviderId,
    provider_activity_id: str,
    *,
    watts: tuple[float, ...] = WATTS,
    summary_sha256: str | None = None,
) -> None:
    replace_detail_set(
        db,
        ActivityStreamSet(
            provider_activity_id=provider_activity_id,
            provenance=_provenance(provider),
            origin=ActivityDetailOrigin.FETCH,
            resolution=StreamResolution.FULL,
            channels={
                StreamChannel.TIME_S: TIME,
                StreamChannel.POWER_W: watts,
                StreamChannel.HEART_RATE_BPM: HEART,
            },
        ),
        mapper_version=1,
        summary_sha256=summary_sha256,
        now=NOW,
    )


def _laps(db: Any, provider: ProviderId, provider_activity_id: str) -> None:
    replace_detail_set(
        db,
        ActivityLapSet(
            provider_activity_id=provider_activity_id,
            provenance=_provenance(provider),
            origin=ActivityDetailOrigin.FETCH,
            lap_source=LapSource.DEVICE_LAPS,
            laps=(
                ActivityLap(
                    index=0, kind=LapKind.WORK, start_offset_s=0.0, end_offset_s=600.0
                ),
            ),
        ),
        mapper_version=1,
        summary_sha256=None,
        now=NOW,
    )


def _ftp(db: Any, provider: ProviderId, value: float) -> None:
    canonical_store.upsert_observation(
        db,
        Observation(
            kind=MetricKind.FTP,
            value=MetricValue(value, "W"),
            observed_on=date(2026, 9, 1),
            observed_at=None,
            provenance=Provenance(
                provider=provider,
                source_kind=SourceKind.PROVIDER_REPORTED,
                source_record_id=f"{provider.value}-ftp",
                recorded_by=RecordingOrigin.GARMIN,
                retrieved_at=datetime(2026, 9, 1, tzinfo=UTC),
                label=None,
            ),
            sport=Sport.RIDE,
        ),
        mapper_version=MAPPER_VERSION,
        now=NOW,
    )


class SessionAnalysisStageTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)
        self.key_values = KeyValueRepository(lambda: NOW)
        self.stage = SessionAnalysisStage(
            key_values=self.key_values, zone_provider=lambda: ZONE, clock=lambda: NOW
        )
        add_session_record(self.manager, GARMIN, "g1", "act_g1")

    def _run(self, stage: SessionAnalysisStage | None = None) -> dict[str, Any]:
        with self.manager.unit_of_work() as db:
            (stage or self.stage).run_batch(db)
            return summarize_session_analysis(self.key_values, db)

    def _write(self, *actions: Any) -> None:
        with self.manager.unit_of_work() as db:
            for action in actions:
                action(db)

    def _row(self, session_id: str) -> dict[str, Any] | None:
        with self.manager.reader() as db:
            return activity_detail_store.analysis_rows_for(db, [session_id]).get(
                session_id
            )

    def test_garmin_only_session_gets_a_stored_analysis_and_profile(self) -> None:
        self._write(lambda db: _streams(db, GARMIN, "g1"))

        state = self._run()

        self.assertEqual("complete", state["status"])
        row = self._row("act_g1")
        assert row is not None
        self.assertEqual(ANALYSIS_VERSION, row["analysis_version"])
        analysis = row["payload"]["session_analysis"]
        self.assertEqual("ok", analysis["aerobic"]["status"])
        self.assertEqual("Garmin Connect", row["payload"]["source"])
        self.assertIn("act_g1", calendar_profiles(self.manager))
        (summary,) = analysis_summaries(self.manager)
        self.assertEqual("act_g1", summary["session_id"])
        self.assertEqual(analysis["aerobic"], summary["aerobic"])

    def test_unchanged_inputs_write_nothing_and_a_new_set_recomputes(self) -> None:
        self._write(lambda db: _streams(db, GARMIN, "g1"))
        self._run()
        again = self._run()
        self.assertEqual(
            (0, 0), (again["counts"]["computed"], again["counts"]["written"])
        )

        # A restart with a new stage instance recomputes nothing either.
        restarted = SessionAnalysisStage(
            key_values=self.key_values, zone_provider=lambda: ZONE, clock=lambda: NOW
        )
        self.assertEqual(0, self._run(restarted)["counts"]["computed"])

        self._write(
            lambda db: _streams(db, GARMIN, "g1", watts=tuple(210.0 for _ in TIME))
        )
        changed = self._run()
        self.assertEqual(
            (1, 1), (changed["counts"]["computed"], changed["counts"]["written"])
        )

    def test_a_new_method_version_recomputes_the_stored_analysis(self) -> None:
        self._write(lambda db: _streams(db, GARMIN, "g1"))
        self._run()
        # The provider ranking changed with method version 2 (#1728).
        self.assertGreaterEqual(canonical_session_analysis.METHOD_VERSION, 2)

        with patch.object(
            canonical_session_analysis,
            "METHOD_VERSION",
            canonical_session_analysis.METHOD_VERSION + 1,
        ):
            changed = self._run()

        self.assertEqual(1, changed["counts"]["computed"])

    def test_detail_document_and_stored_analysis_agree(self) -> None:
        self._write(
            lambda db: _streams(db, GARMIN, "g1"), lambda db: _laps(db, GARMIN, "g1")
        )
        self._run()
        reader = CanonicalDetailReader(
            CanonicalTableReader().session_activities, refreshable=frozenset
        )
        with self.manager.reader() as db:
            document = reader.read(db, "act_g1")
        assert document is not None
        row = self._row("act_g1")
        assert row is not None
        self.assertEqual(
            json.loads(json.dumps(document["analysis"])),
            row["payload"]["session_analysis"],
        )

    def test_intervals_records_and_sets_are_never_read(self) -> None:
        add_session_record(self.manager, INTERVALS, "i9", "act_i9")
        add_session_record(self.manager, INTERVALS, "i1", "act_g1")
        self._write(
            lambda db: _streams(db, INTERVALS, "i9"),
            lambda db: _streams(db, INTERVALS, "i1", watts=tuple(300.0 for _ in TIME)),
            lambda db: _streams(db, GARMIN, "g1"),
        )

        self._run()

        self.assertIsNone(self._row("act_i9"))
        row = self._row("act_g1")
        assert row is not None
        power = row["payload"]["session_analysis"]["power_profile"]
        self.assertNotIn("Intervals", power["source"])
        before = row["input_sha256"]
        # Changing the Intervals.icu copy changes nothing.
        self._write(lambda db: _streams(db, INTERVALS, "i1"))
        self.assertEqual(0, self._run()["counts"]["computed"])
        row = self._row("act_g1")
        assert row is not None
        self.assertEqual(before, row["input_sha256"])

    def test_profile_uses_the_local_threshold_without_intervals(self) -> None:
        self._write(
            lambda db: _streams(db, GARMIN, "g1"),
            lambda db: _ftp(db, INTERVALS, 400.0),
            lambda db: _ftp(db, GARMIN, 200.0),
        )

        self._run()

        row = self._row("act_g1")
        assert row is not None
        segment = row["payload"]["calendar_profile"]["segments"][0]
        # 200 W at a Garmin FTP of 200 W is zone 4; 400 W would make it zone 1.
        self.assertEqual(4, segment["zone"])

    def test_report_zone_times_use_the_local_zones_of_the_day(self) -> None:
        self._write(
            lambda db: _streams(db, GARMIN, "g1"),
            lambda db: _ftp(db, INTERVALS, 400.0),
            lambda db: _ftp(db, GARMIN, 200.0),
        )

        self._run()

        row = self._row("act_g1")
        assert row is not None
        zones = row["payload"]["zone_times"]
        self.assertEqual("Zoneneinstellungen", zones["label"])
        power = {zone["id"]: zone["secs"] for zone in zones["power"]}
        # 200 W at the Garmin FTP of 200 W is Z4; the Intervals FTP is never read.
        self.assertEqual(float(SECONDS), power["Z4"])
        self.assertEqual(float(SECONDS), sum(power.values()))
        self.assertNotIn("heart_rate", zones)  # no threshold HR
        with self.manager.reader() as db:
            read = read_zone_times(db, ["act_g1"])
        summary = with_zone_times([{"id": "act_g1", "sport": "ride"}], read)[0]
        self.assertEqual(zones["power"], summary["power_zone_times"])
        self.assertEqual({"power_zone_times": "local"}, summary["zone_models"])
        self.assertEqual("Zoneneinstellungen", summary["sources"]["power_zone_times"])

    def test_a_new_threshold_recomputes_the_zone_times(self) -> None:
        self._write(
            lambda db: _streams(db, GARMIN, "g1"),
            lambda db: _ftp(db, GARMIN, 200.0),
        )
        self._run()

        self._write(lambda db: _ftp(db, GARMIN, 400.0))
        self.assertEqual(1, self._run()["counts"]["computed"])

        row = self._row("act_g1")
        assert row is not None
        power = {
            zone["id"]: zone["secs"] for zone in row["payload"]["zone_times"]["power"]
        }
        # 200 W is 50 % of 400 W: Z1.
        self.assertEqual(float(SECONDS), power["Z1"])

    def test_new_default_heart_rate_limits_recompute_the_zone_times(self) -> None:
        # #1773: a row stored under the former seven-zone default limits is stale.
        self._write(
            lambda db: _streams(db, GARMIN, "g1"),
            lambda db: _ftp(db, GARMIN, 200.0),
        )

        def seven_zones(zones: Any) -> Any:
            part = real_part(zones)
            if part is not None:
                part["hr_limits"] = [68, 83, 94, 105, 120, 150]
            return part

        real_part = session_analysis_stage.zone_settings_part
        with patch.object(session_analysis_stage, "zone_settings_part", seven_zones):
            self._run()
        self.assertEqual(1, self._run()["counts"]["computed"])
        self.assertEqual(0, self._run()["counts"]["computed"])

    def test_older_target_snapshots_carry_over_unchanged(self) -> None:
        self._write(
            lambda db: _streams(db, GARMIN, "g1"),
            lambda db: save_analysis(
                db,
                "act_g1",
                analysis_version=2,
                input_sha256="0" * 64,
                payload={"target_snapshot": TARGETS, "calendar_profile": {"x": 1}},
                now=NOW,
            ),
        )
        add_session_record(self.manager, INTERVALS, "i2", "act_i2")
        self._write(
            lambda db: save_analysis(
                db,
                "act_i2",
                analysis_version=2,
                input_sha256="0" * 64,
                payload={
                    "calendar_profile": {"x": 1},
                    "session_analysis": {"aerobic": {}},
                },
                now=NOW,
            )
        )

        self._run()

        row = self._row("act_g1")
        assert row is not None
        self.assertEqual(TARGETS, row["payload"]["target_snapshot"])
        # A row without Garmin, Wahoo or local details stays as it is, unread.
        untouched = self._row("act_i2")
        assert untouched is not None
        self.assertEqual(2, untouched["analysis_version"])
        self.assertNotIn("act_i2", calendar_profiles(self.manager))

    def test_settled_intervals_summary_hash_survives_a_recompute(self) -> None:
        # The hash only tells the Intervals.icu prefetch the copy was loaded.
        self._write(
            lambda db: _streams(db, GARMIN, "g1"),
            lambda db: save_analysis(
                db,
                "act_g1",
                analysis_version=2,
                input_sha256="0" * 64,
                payload={"summary_sha256": "b" * 64},
                now=NOW,
            ),
        )

        self._run()

        row = self._row("act_g1")
        assert row is not None
        self.assertEqual(ANALYSIS_VERSION, row["analysis_version"])
        self.assertEqual("b" * 64, row["payload"]["summary_sha256"])

    def test_snapshot_of_a_merged_session_carries_over(self) -> None:
        add_session_record(
            self.manager, INTERVALS, "i3", "act_i3", merged_into="act_g1"
        )
        self._write(
            lambda db: _streams(db, GARMIN, "g1"),
            lambda db: save_analysis(
                db,
                "act_i3",
                analysis_version=2,
                input_sha256="0" * 64,
                payload={"target_snapshot": TARGETS},
                now=NOW,
            ),
        )

        self._run()

        row = self._row("act_g1")
        assert row is not None
        self.assertEqual(TARGETS, row["payload"]["target_snapshot"])
        self.assertEqual(0, self._run()["counts"]["computed"])

    def test_stale_detail_withholds_the_analysis_everywhere(self) -> None:
        self._write(lambda db: _streams(db, GARMIN, "g1", summary_sha256="a" * 64))
        self._write(
            lambda db: db.execute(
                "INSERT INTO provider_records (provider, record_kind, source_record_id, "
                "payload, payload_hash, fetched_at, mapped_version, state, created_at, "
                "updated_at) VALUES ('garmin', 'activity', 'g1', '{}', ?, ?, 1, "
                "'active', ?, ?)",
                ("b" * 64, NOW, NOW, NOW),
            )
        )

        self._run()

        row = self._row("act_g1")
        assert row is not None
        self.assertTrue(row["payload"]["stale"])
        self.assertIsNone(row["payload"]["session_analysis"])
        self.assertEqual([], analysis_summaries(self.manager))
        self.assertEqual({}, calendar_profiles(self.manager))

    def test_lost_details_rewrite_the_row_without_an_analysis(self) -> None:
        self._write(lambda db: _streams(db, GARMIN, "g1"))
        self._run()
        self._write(
            lambda db: activity_detail_store.remove_detail_sets(
                db, "garmin", "g1", keep=()
            )
        )

        self._run()

        row = self._row("act_g1")
        assert row is not None
        self.assertIsNone(row["payload"]["session_analysis"])
        self.assertEqual({}, calendar_profiles(self.manager))

    def test_recent_session_freezes_its_matched_targets_once(self) -> None:
        planned = [
            {
                "id": "local-1",
                "date": "2026-09-10",
                "sport": "ride",
                "description": "- 2m 200w",
                "target": "POWER",
            }
        ]
        calls: list[int] = []

        def planned_units() -> list[dict[str, Any]]:
            calls.append(1)
            return planned

        def stage(clock: str) -> SessionAnalysisStage:
            return SessionAnalysisStage(
                key_values=self.key_values,
                zone_provider=lambda: ZONE,
                clock=lambda: clock,
                planned_units=planned_units,
            )

        self._write(lambda db: _streams(db, GARMIN, "g1"))
        # The session lies more than a week back: nothing is frozen.
        self._run(stage(NOW))
        row = self._row("act_g1")
        assert row is not None
        self.assertIsNone(row["payload"]["target_snapshot"])

        self._write(lambda db: _ftp(db, GARMIN, 250.0))
        recent = self._run(stage("2026-09-11T08:00:00+00:00"))

        self.assertEqual(1, recent["counts"]["outcomes"]["targets_frozen"])
        row = self._row("act_g1")
        assert row is not None
        targets = row["payload"]["target_snapshot"]
        self.assertEqual(120, targets["steps"][0]["duration"])
        self.assertEqual({"ftp": 250.0}, targets["basis"])
        # The frozen targets are part of the stored fingerprint.
        self.assertEqual(0, self._run(stage(NOW))["counts"]["computed"])

    def test_batches_resume_until_complete(self) -> None:
        add_session_record(self.manager, GARMIN, "g2", "act_g2")
        self._write(
            lambda db: _streams(db, GARMIN, "g1"),
            lambda db: _streams(db, GARMIN, "g2"),
        )
        stage = SessionAnalysisStage(
            key_values=self.key_values,
            zone_provider=lambda: ZONE,
            clock=lambda: NOW,
            batch_size=1,
        )

        first = self._run(stage)
        self.assertEqual(("running", 1), (first["status"], first["counts"]["pending"]))
        self.assertEqual("complete", self._run(stage)["status"])
        self.assertEqual(0, self._run(stage)["counts"]["computed"])


class StageOrderTests(unittest.TestCase):
    def test_analysis_runs_after_the_legacy_detail_copy(self) -> None:
        # The legacy copy writes the target snapshots the stage carries over.
        assembly = build_canonical_backfill(
            database=lambda: None,
            key_values=KeyValueRepository(lambda: NOW),
            zone_provider=lambda: ZONE,
            maintenance_gate=MaintenanceGate(),
            clock=lambda: NOW,
        )
        order = [stage.stage for stage in assembly.worker._followups]
        self.assertLess(
            order.index(assembly.detail_backfill.stage), order.index("session_analysis")
        )
        self.assertLess(
            order.index("session_analysis"),
            order.index(assembly.detail_retirement.stage),
        )


if __name__ == "__main__":
    unittest.main()
