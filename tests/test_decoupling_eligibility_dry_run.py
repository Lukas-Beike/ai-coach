"""The decoupling eligibility (#1773, #2779): gates, candidate rules, aggregate-only report.

The dry run on a database copy and the diagnostics section share one core.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import sqlite3
import tempfile
import unittest
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from unittest import mock

from backend.canonical.activity_detail import ActivityStreamSet
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    StreamChannel,
    StreamResolution,
)
from backend.db import DatabaseManager
from backend.db.activity_detail_store import replace_detail_set
from backend.db.repositories import KeyValueRepository
from backend.performance import decoupling_eligibility as eligibility
from backend.performance.mean_max_curve import SessionCurveReader
from backend.sync.canonical_table_reader import CanonicalTableReader
from backend.sync.session_metrics import analysis_activity
from scripts import decoupling_eligibility_dry_run as dry_run
from tests.canonical_detail_support import NOW, add_session_record, open_manager

TODAY = date(2026, 10, 1)
HEART = 140.0


def _times(seconds: int) -> tuple[float, ...]:
    return tuple(float(second) for second in range(seconds + 1))


def _power(seconds: int, level: Callable[[int], float]) -> dict[StreamChannel, Any]:
    time = _times(seconds)
    return {
        StreamChannel.TIME_S: time,
        StreamChannel.POWER_W: tuple(level(int(second)) for second in time),
        StreamChannel.HEART_RATE_BPM: tuple(HEART for _ in time),
    }


def _steady(second: int) -> float:
    return 200.0


def _alternating(second: int) -> float:
    # 10 s at 100 W, 10 s at 300 W: 1 s CV 0.5, 60 s means exactly 200 W.
    return 100.0 if second // 10 % 2 == 0 else 300.0


def _cool_down(second: int) -> float:
    return 100.0 if second > 2400 else 200.0


def _stepped(second: int) -> float:
    return 200.0 if second < 1800 else 250.0


def _store(
    manager: DatabaseManager, provider_activity_id: str, channels: Mapping[Any, Any]
) -> None:
    with manager.unit_of_work() as db:
        replace_detail_set(
            db,
            ActivityStreamSet(
                provider_activity_id=provider_activity_id,
                provenance=Provenance(
                    provider=ProviderId.GARMIN,
                    source_kind=SourceKind.PROVIDER_REPORTED,
                    source_record_id=None,
                    recorded_by=RecordingOrigin.GARMIN,
                    retrieved_at=datetime(2026, 10, 18, 8, 0, tzinfo=UTC),
                    label="Garmin Connect",
                ),
                origin=ActivityDetailOrigin.FETCH,
                resolution=StreamResolution.FULL,
                channels=dict(channels),
            ),
            mapper_version=1,
            summary_sha256=None,
            now=NOW,
        )


def _add(
    manager: DatabaseManager,
    name: str,
    channels: Mapping[Any, Any] | None,
    sport: str = "ride",
) -> None:
    add_session_record(manager, ProviderId.GARMIN, name, f"act_{name}", sport=sport)
    if channels is not None:
        _store(manager, name, channels)


def _seed(manager: DatabaseManager) -> None:
    _add(manager, "steady", _power(3000, _steady))
    _add(manager, "alternating", _power(3000, _alternating))
    _add(manager, "cooldown", _power(3000, _cool_down))
    _add(manager, "stepped", _power(3000, _stepped))
    _add(manager, "short", _power(1200, _steady))
    _add(manager, "nostreams", None)
    time = _times(3000)
    _add(
        manager,
        "road",
        {
            StreamChannel.TIME_S: time,
            StreamChannel.SPEED_MPS: tuple(3.0 for _ in time),
            StreamChannel.HEART_RATE_BPM: tuple(HEART for _ in time),
        },
        sport="run",
    )
    with manager.unit_of_work() as db:  # The window reads the stored local date.
        db.execute("UPDATE activity_records SET local_date = '2026-09-10'")


class DryRunTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "intervals-coach.db"
        manager = open_manager(directory.name, self.path.name)
        _seed(manager)
        manager.close()

    def _run(self, **options: Any) -> dict[str, Any]:
        return dry_run.dry_run(
            self.path, "", backend=sqlite3, configure=None, today=TODAY, **options
        )

    def test_gates_and_rules_count_known_cases(self) -> None:
        digest = hashlib.sha256(self.path.read_bytes()).hexdigest()
        report = self._run()

        self.assertEqual(hashlib.sha256(self.path.read_bytes()).hexdigest(), digest)
        self.assertTrue(report["rolled_back"])
        self.assertEqual(
            sorted(report["groups"]),
            ["ride/indoor", "ride/outdoor", "run/indoor", "run/outdoor"],
        )
        ride = report["groups"]["ride/outdoor"]
        self.assertEqual((ride["sessions"], ride["without_streams"]), (6, 1))
        counts = ride["counts"]
        # Independent expectations: steady 200 W passes everything; the 10 s
        # alternation fails the 1 s CV (100/200 = 0.5) but not rolling means or VI;
        # the cool-down fails halves; the step halves differ by 25 %.
        self.assertEqual(counts["evaluated"], 5)
        self.assertEqual(counts["fail_short"], 1)
        self.assertEqual(counts["past_coverage"], 4)
        self.assertEqual(counts["fail_variable_output_current_rule"], 2)
        self.assertEqual(counts["fail_halves_differ"], 1)
        self.assertEqual(counts["pass_cv_1s_15"], 1)
        self.assertEqual(counts["pass_cv_30s_15"], 2)
        self.assertEqual(counts["pass_cv_60s_15"], 2)
        self.assertEqual(counts["pass_vi_30s_105"], 2)
        self.assertEqual(counts["pass_vi_30s_110"], 2)
        self.assertEqual(counts["trim_pass_cv_1s_15"], 2)
        self.assertEqual(counts["trim_pass_cv_30s_15"], 3)
        self.assertEqual(counts["production_mismatch"], 0)

    def test_distribution_is_rounded_quartiles_of_the_worst_half(self) -> None:
        ride = self._run()["groups"]["ride/outdoor"]["max_half_distribution"]
        one_second = ride["cv_1s"]
        # Worst-half CV of steady 0, cool-down 50/150, alternation 0.5, step 0.
        self.assertEqual(one_second["n"], 4)
        self.assertEqual(one_second["p50"], 0.167)
        self.assertEqual(one_second["p75"], 0.375)
        self.assertLess(ride["cv_60s"]["p50"], 0.05)
        self.assertIn("vi_30s", ride)

    def test_runs_report_no_ride_only_measures_and_unknown_terrain(self) -> None:
        run = self._run()["groups"]["run/outdoor"]
        self.assertEqual(run["counts"]["fail_terrain_unknown"], 1)
        self.assertEqual(run["counts"]["production_mismatch"], 0)
        self.assertNotIn("pass_vi_30s_105", run["counts"])
        self.assertNotIn("vi_30s", run["max_half_distribution"])

    def test_window_excludes_older_sessions_and_report_is_aggregate_only(self) -> None:
        report = self._run(days=10)
        for group in report["groups"].values():
            self.assertEqual(group["sessions"], 0)
        text = json.dumps(self._run())
        for content in ("act_", "steady", "alternating", "2026-", "Garmin"):
            self.assertNotIn(content, text)

    def test_cli_requires_the_password_from_the_environment(self) -> None:
        with (
            mock.patch.dict("os.environ", {"APP_PASSWORD": ""}),
            mock.patch("sys.stderr"),
        ):
            self.assertEqual(dry_run.main(["copy.db"]), 2)


class DiagnosticsSectionTests(unittest.TestCase):
    """The diagnostics section builds the dry-run report off the request path (#2779)."""

    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "intervals-coach.db"
        self.manager = open_manager(directory.name, self.path.name)
        self.addCleanup(self.manager.close)
        _seed(self.manager)
        self.builds: list[Callable[[], None]] = []
        self.pauses: list[tuple[float, int]] = []
        self.snapshots_open = 0
        ticks = itertools.count(0.0, 0.25)
        reader = CanonicalTableReader()
        manager = mock.Mock(read_snapshot=self._read_snapshot)
        self.section = eligibility.DecouplingEligibility(
            lambda: manager,
            reader.activity_sessions,
            analysis_activity,
            KeyValueRepository(lambda: ""),
            lambda: TODAY,
            SessionCurveReader(reader.session_activities, spawn=self.builds.append),
            pause=lambda seconds: self.pauses.append((seconds, self.snapshots_open)),
            clock=lambda: next(ticks),
        ).section

    def _read_snapshot(self) -> Any:
        snapshot = self.manager.read_snapshot()
        test = self

        class Counted:
            def __enter__(self) -> Any:
                test.snapshots_open += 1
                return snapshot.__enter__()

            def __exit__(self, *exc: object) -> None:
                test.snapshots_open -= 1
                snapshot.__exit__(*exc)

        return Counted()

    def test_section_equals_the_dry_run_report_and_paces_each_session(self) -> None:
        self.assertEqual(self.section(), {"status": "pending"})
        self.assertEqual(len(self.builds), 1)
        self.assertEqual(self.section(), {"status": "pending"})  # one build at a time
        self.builds.pop()()
        # One session per read snapshot, then a pause as long as its own work,
        # outside the snapshot: the six streamed sessions of the fixture.
        self.assertEqual(self.pauses, [(0.25, 0)] * 6)

        section = self.section()
        self.assertEqual(self.builds, [])  # unchanged sessions build nothing
        script = dry_run.dry_run(
            self.path, "", backend=sqlite3, configure=None, today=TODAY
        )
        self.assertEqual(
            (section.pop("status"), section.pop("current")), ("ready", True)
        )
        self.assertEqual(
            section, {k: v for k, v in script.items() if k != "rolled_back"}
        )

    def test_new_session_rebuilds_in_background_and_a_failure_reports_failed(
        self,
    ) -> None:
        self.section()
        self.builds.pop()()
        _add(self.manager, "later", _power(3000, _steady))
        with self.manager.unit_of_work() as db:
            db.execute("UPDATE activity_records SET local_date = '2026-09-10'")
        stale = self.section()
        self.assertEqual((stale["status"], stale["current"]), ("ready", False))
        with (
            mock.patch.object(eligibility, "evaluate", side_effect=ValueError),
            self.assertLogs("intervals_coach", "ERROR"),
        ):
            self.builds.pop()()
        self.assertEqual(self.section(), {"status": "failed"})

    def test_section_holds_counts_only(self) -> None:
        self.section()
        self.builds.pop()()
        section = self.section()
        text = json.dumps(section)
        for content in ("act_", "steady", "alternating", "2026-", "Garmin"):
            self.assertNotIn(content, text)

        def leaves(value: Any) -> list[Any]:
            if isinstance(value, dict):
                return [leaf for item in value.values() for leaf in leaves(item)]
            return [value]

        # Numbers, flags and the state word; no other text.
        for leaf in leaves(section):
            self.assertTrue(leaf in (None, "ready") or isinstance(leaf, int | float))


class MeasureTests(unittest.TestCase):
    def test_rolling_cv_and_variability_index_of_known_series(self) -> None:
        samples: Sequence[eligibility.Sample] = [
            (float(second), 1.0, 100.0 if second // 10 % 2 == 0 else 300.0)
            for second in range(1200)
        ]
        half = eligibility._half(samples, power=True)
        one_second, one_minute = half.cv[1], half.cv[60]
        assert one_second is not None and one_minute is not None
        self.assertAlmostEqual(one_second, 0.5)
        self.assertAlmostEqual(one_minute, 0.0, places=6)
        assert half.vi is not None
        self.assertGreater(half.vi, 1.0)
        self.assertLess(half.vi, 1.05)
        self.assertIsNone(eligibility._half(samples, power=False).vi)


if __name__ == "__main__":
    unittest.main()
