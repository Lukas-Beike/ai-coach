"""Synthetic input sets for the method cards M1-M4: complete, incomplete, contradictory.

Each set asserts a defined outcome: a value, no value with a status or reason, or an
exclusion. M4 has no method yet, so it asserts input-level facts. Gaps are
pinned: the assertion states today's behaviour and names the owning issue, so closing
the gap fails the test and forces an update. All data is synthetic, in temporary
storage, with no provider call. Detailed behaviour lives in test_personal_recovery,
test_performance_canonical_recovery, test_power_profile,
test_activity_detail_merge, test_activity_detail_store and test_session_linking.
"""

from __future__ import annotations

import json
import math
import unittest
from datetime import UTC, date, datetime, timedelta
from functools import partial
from typing import Any, ClassVar

import test_session_linking as linking
from canonical_recovery_support import (
    RecordingReader,
    mapped_personal_recovery,
    mapped_recovery_inputs,
    recovery_inputs,
    recovery_observation,
)

from backend.activities.activity_reference import ActivityReferences
from backend.activities.activity_summary import activity_summaries
from backend.activities.detail_merge import DetailCandidate, merge_details
from backend.activities.feedback import ActivityFeedbackService
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
from backend.db import canonical_store
from backend.db.activity_detail_store import (
    StoredDetailSet,
    detail_sets_for,
    detail_sets_for_session,
    replace_detail_set,
)
from backend.db.repositories import ActivityFeedbackRepository
from backend.db.schema import CURRENT_DATABASE_SCHEMA
from backend.errors import AppError
from backend.performance.canonical_recovery import (
    RECOVERY_KINDS,
    read_recovery_inputs,
)
from backend.performance.mean_max_curve import SessionCurveReader
from backend.performance.personal_recovery import personal_recovery
from backend.performance.power_profile import power_profile
from backend.performance.session_rpe_load import feedback_by_session, session_rpe_load
from backend.providers.canonical_plans import ACTIVITY_RECORD_KIND
from backend.sync.canonical_table_reader import CanonicalTableReader

INTERVALS = ProviderId.INTERVALS.value
GARMIN = ProviderId.GARMIN.value
TODAY = date(2026, 10, 2)
CP_W = 250.0
W_PRIME_J = 18_000.0
EFFORT_S = (180, 420, 720)
RECOVERY_S = 1800


class _NoActivityRows:
    def activity_rows(
        self,
        db: Any,
        *,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> tuple[dict[str, Any], ...]:
        return ()


class M1SessionRpeInputs(linking.LinkingCase):
    """Elapsed duration and local session RPE for one canonical session."""

    def _record(self, provider: str, provider_activity_id: str) -> dict[str, Any]:
        with self.manager.reader() as db:
            row = db.execute(
                "SELECT recorded_by, duration_s, moving_duration_s, details "
                "FROM activity_records WHERE provider = ? AND provider_activity_id = ?",
                (provider, provider_activity_id),
            ).fetchone()
        return dict(row)

    def _feedback(self) -> ActivityFeedbackService:
        return ActivityFeedbackService(
            self.manager,
            ActivityFeedbackRepository(lambda: linking.SECOND.isoformat()),
            _NoActivityRows(),
            references=ActivityReferences(self.manager),
        )

    def _stored_feedback(self, activity_id: str) -> list[dict[str, Any]]:
        """Rows stored under ``activity_id``, not the session feedback it shows."""
        with self.manager.reader() as db:
            rows = ActivityFeedbackRepository(lambda: "").all(db)
        return [row for row in rows if row["activity_id"] == activity_id]

    def _ingest_ride(self, **intervals_fields: Any) -> None:
        self._ingest_intervals(
            [
                linking.intervals_ride(
                    moving_time=3300,
                    elapsed_time=3600,
                    device_name="Garmin Edge 530",
                    **intervals_fields,
                )
            ],
            linking.FIRST,
        )
        self._ingest_garmin(
            [linking.garmin_ride(duration=3600.0, movingDuration=3300.0)],
            linking.SECOND,
        )

    def test_complete(self) -> None:
        self._ingest_ride()
        sessions = self._sessions()
        survivor, alias = sessions[linking.INTERVALS_ID], sessions[linking.GARMIN_ID]
        self.assertEqual(
            sorted(row["state"] for row in sessions.values()), ["active", "duplicate"]
        )
        self.assertEqual(alias["merged_into"], survivor["activity_id"])

        intervals = self._record(INTERVALS, linking.INTERVALS_ID)
        garmin = self._record(GARMIN, linking.GARMIN_ID)
        self.assertEqual(
            (
                intervals["duration_s"],
                intervals["moving_duration_s"],
                canonical_store.activity_elapsed_duration(intervals["details"]),
            ),
            (3300.0, 3300.0, 3600.0),
            msg="#1445: Intervals keeps its elapsed time in the one elapsed field; "
            "the Intervals.icu mapper (v6) also maps moving_time to moving_duration_s",
        )
        self.assertEqual(
            (
                garmin["duration_s"],
                garmin["moving_duration_s"],
                canonical_store.activity_elapsed_duration(garmin["details"]),
            ),
            (3600.0, 3300.0, 3600.0),
            msg="#1445: Garmin stores its elapsed duration in the one elapsed field",
        )
        self.assertEqual(
            (intervals["recorded_by"], garmin["recorded_by"]),
            (RecordingOrigin.GARMIN.value, RecordingOrigin.GARMIN.value),
        )
        self.assertEqual(
            canonical_store.activity_device_type(intervals["details"]).value,  # type: ignore[union-attr]
            "bike_computer",
        )
        self.assertIsNone(canonical_store.activity_device_type(garmin["details"]))

        saved = self._feedback().save(alias["activity_id"], {"session_rpe": 5})
        self.assertEqual(
            saved["activity_feedback"]["activity_id"], linking.INTERVALS_ID
        )
        self.assertEqual(
            self._stored_feedback(linking.INTERVALS_ID)[0]["session_rpe"], 5
        )
        self.assertEqual(self._stored_feedback(linking.GARMIN_ID), [])
        self.assertEqual(self._stored_feedback(alias["activity_id"]), [])

    def test_incomplete(self) -> None:
        workout = linking.wahoo_workout()
        workout["workout_summary"]["duration_total_accum"] = "3900"
        self._ingest_wahoo([workout], linking.FIRST)
        record = self._record(ProviderId.WAHOO.value, linking.WAHOO_ID)
        self.assertEqual(
            (record["duration_s"], record["moving_duration_s"]), (3600.0, 3600.0)
        )
        self.assertEqual(
            canonical_store.activity_elapsed_duration(record["details"]),
            3900.0,
            msg="#1445: the Wahoo total survives next to the active duration",
        )
        local_id = self._sessions()[linking.WAHOO_ID]["activity_id"]
        self.assertEqual(self._stored_feedback(linking.WAHOO_ID), [])
        self.assertEqual(self._stored_feedback(local_id), [])

        reference = ActivityReferences(self.manager).resolve_reference(local_id)
        self.assertEqual(
            (reference.activity_id, reference.provider),
            (local_id, None),
            msg="#1423: a Wahoo-only session keeps its local id as the feedback key, "
            "which is its canonical session",
        )

        service = self._feedback()
        service.save(linking.WAHOO_ID, {"session_rpe": 0})
        self.assertEqual(self._stored_feedback(linking.WAHOO_ID)[0]["session_rpe"], 0)
        for invalid in (-1, 10.5, math.nan):
            with self.subTest(rpe=invalid), self.assertRaises(AppError):
                service.save(linking.WAHOO_ID, {"session_rpe": invalid})

    def test_contradictory(self) -> None:
        self._ingest_ride(icu_rpe=7)
        self._feedback().save(linking.INTERVALS_ID, {"session_rpe": 5})
        self._ingest_intervals(
            [
                linking.intervals_ride(
                    moving_time=3300,
                    elapsed_time=3600,
                    device_name="Garmin Edge 530",
                    icu_rpe=7,
                )
            ],
            linking.THIRD,
        )
        self.assertEqual(
            self._stored_feedback(linking.INTERVALS_ID)[0]["session_rpe"], 5
        )
        with self.manager.reader() as db:
            payloads = canonical_store.active_activity_payload_texts(
                db, provider=INTERVALS, record_kind=ACTIVITY_RECORD_KIND
            )
            columns = [
                row["name"] for row in db.execute("PRAGMA table_info(activity_records)")
            ]
        self.assertEqual([json.loads(text)["icu_rpe"] for text in payloads], [7])
        self.assertEqual(
            [name for name in columns if "rpe" in name],
            [],
            msg="the provider RPE lives in the record details, not in a column",
        )
        intervals = self._record(INTERVALS, linking.INTERVALS_ID)
        self.assertEqual(
            json.loads(intervals["details"])["rpe"],
            7,
            msg="#1446: the canonical record keeps icu_rpe with its provenance",
        )
        with self.manager.reader() as db:
            summaries = activity_summaries(
                CanonicalTableReader().activity_sessions(db), linking.ZONE
            )
        result = session_rpe_load(
            summaries,
            feedback_by_session(
                summaries,
                partial(self._feedback().for_activity_ids, sessions_only=True),
            ),
            start=date(2026, 9, 10),
            end=date(2026, 9, 10),
            timezone="Europe/Berlin",
        )
        (session,) = result["sessions"]
        self.assertEqual(
            (session["value"], session["rpe"], session["rpe_source"]),
            (300.0, 5, "athlete_feedback"),
            msg="#1427/D3: the local rating wins over icu_rpe, never averaged",
        )


def _wellness(nights: int, *, shift: int = 0, **latest: Any) -> list[dict[str, Any]]:
    """One Intervals.icu row per day: the latest day plus ``nights`` earlier days."""
    rows: list[dict[str, Any]] = []
    for index in range(nights + 1):
        row: dict[str, Any] = {
            "id": (TODAY - timedelta(days=shift + index)).isoformat(),
            "hrv": 40 + index % 5,
            "restingHR": 50 + index % 3,
        }
        rows.append(row)
    rows[0].update(latest)
    return rows


def _baseline(
    result: dict[str, Any], metric: str, provider: str, measurement: str | None = None
) -> dict[str, Any]:
    matches = [
        item
        for item in result["baselines"]
        if (item["metric"], item["source_provider"]) == (metric, provider)
        and measurement in (None, item["measurement"])
    ]
    if len(matches) != 1:
        raise AssertionError(f"expected one {metric} baseline, got {matches}")
    return matches[0]


class M2HrvRestingHrInputs(unittest.TestCase):
    """Personal quartiles of Intervals.icu and Garmin HRV and resting HR."""

    def test_complete(self) -> None:
        result = mapped_personal_recovery(
            _wellness(28, hrv=60, restingHR=40), {}, {}, TODAY
        )
        hrv = _baseline(result, "hrv", INTERVALS, "RMSSD")
        resting = _baseline(result, "resting_hr", INTERVALS)
        self.assertEqual(
            (hrv["status"], hrv["nights"], hrv["position"]), ("ok", 28, "above")
        )
        self.assertEqual(
            (resting["status"], resting["nights"], resting["position"]),
            ("ok", 28, "below"),
        )
        self.assertNotIn("reason", hrv)

    def test_incomplete(self) -> None:
        short = mapped_personal_recovery(_wellness(13), {}, {}, TODAY)
        stale = mapped_personal_recovery(_wellness(30, shift=3), {}, {}, TODAY)
        for result, reason in (
            (short, "Mindestens 14 frühere passende Nächte erforderlich."),
            (stale, "Messung veraltet."),
        ):
            for metric in ("hrv", "resting_hr"):
                with self.subTest(reason=reason, metric=metric):
                    baseline = _baseline(result, metric, INTERVALS)
                    self.assertEqual(baseline["status"], "insufficient_data")
                    self.assertEqual(baseline["reason"], reason)
                    self.assertNotIn("position", baseline)
        self.assertEqual(_baseline(short, "hrv", INTERVALS)["nights"], 13)

        implausible = mapped_personal_recovery(
            [{"id": TODAY.isoformat(), "hrv": 0, "restingHR": 19}], {}, {}, TODAY
        )
        self.assertEqual(implausible["baselines"], [])

    def test_contradictory(self) -> None:
        wellness = _wellness(28, hrv=60, hrvSDNN=45)
        garmin = {
            "hrv": [
                {"calendarDate": row["id"], "lastNightAvg": 30 + index % 4}
                for index, row in enumerate(wellness)
            ]
        }
        result = mapped_personal_recovery(wellness, garmin, {}, TODAY)
        rmssd = _baseline(result, "hrv", INTERVALS, "RMSSD")
        sdnn = _baseline(result, "hrv", INTERVALS, "SDNN")
        garmin_hrv = _baseline(result, "hrv", GARMIN)
        self.assertEqual(
            (rmssd["value"], sdnn["value"], garmin_hrv["value"]), (60.0, 45.0, 30.0)
        )
        self.assertEqual([item["status"] for item in (rmssd, garmin_hrv)], ["ok", "ok"])
        self.assertEqual(sdnn["status"], "insufficient_data")
        self.assertEqual(
            len([item for item in result["baselines"] if item["metric"] == "hrv"]), 3
        )

    def test_canonical_resting_hr_is_the_primary_input(self) -> None:
        wellness = _wellness(28, restingHR=45)
        mapped = mapped_recovery_inputs(None, wellness)
        observations = [
            observation
            for kind in RECOVERY_KINDS
            for observation in mapped.of(kind)
            if not (
                observation.kind is MetricKind.RESTING_HR
                and observation.observed_on == TODAY
            )
        ]
        observations.append(
            recovery_observation(
                MetricKind.RESTING_HR, 47.0, TODAY.isoformat(), ProviderId.INTERVALS
            )
        )
        canonical = recovery_inputs(observations, latest_wellness_day=TODAY)

        served = personal_recovery({}, TODAY, canonical=canonical)

        # The raw row says 45; the canonical observation (47) is the input (#1411).
        self.assertEqual(_baseline(served, "resting_hr", INTERVALS)["value"], 47.0)

    def test_canonical_hrv_is_read_per_provider(self) -> None:
        observation = recovery_observation(
            MetricKind.HRV_RMSSD, 99.0, TODAY.isoformat(), ProviderId.GARMIN
        )
        reader = RecordingReader({MetricKind.HRV_RMSSD: [observation]})

        inputs = read_recovery_inputs(
            reader, None, as_of=TODAY, latest_wellness_day=None
        )
        # A source without stored sleep periods leaves the regularity on raw rows.
        self.assertIsNone(inputs.sleep_periods)
        served = personal_recovery({}, TODAY, canonical=inputs)

        self.assertIn(MetricKind.HRV_RMSSD, [call[0] for call in reader.calls])
        self.assertIn(MetricKind.HRV_SDNN, [call[0] for call in reader.calls])
        self.assertEqual(_baseline(served, "hrv", GARMIN)["value"], 99.0)


def _night(
    offset: int, hours: float = 8.0, *, onset: tuple[int, int] = (21, 30)
) -> dict[str, Any]:
    """Garmin sleep record waking 05:30 UTC ``offset`` days before today."""
    day = TODAY - timedelta(days=offset)
    end = datetime(day.year, day.month, day.day, 5, 30, tzinfo=UTC)
    previous = day - timedelta(days=1)
    start = datetime(previous.year, previous.month, previous.day, *onset, tzinfo=UTC)
    return {
        "calendarDate": day.isoformat(),
        "sleepStartTimestampGMT": int(start.timestamp() * 1000),
        "sleepEndTimestampGMT": int(end.timestamp() * 1000),
        "sleepTimeSeconds": int(hours * 3600),
    }


class M3SleepInputs(unittest.TestCase):
    """Sleep duration, goal shortfall and the timing deviation."""

    profile: ClassVar[dict[str, str]] = {
        "sleep_target_hours": "8",
        "timezone": "UTC",
    }

    def test_complete(self) -> None:
        hours = [7.0, 6.5, 8.0, 9.0, 5.0, 7.5, 6.0]
        wellness = [
            {
                "id": (TODAY - timedelta(days=index)).isoformat(),
                "sleepSecs": hour * 3600,
            }
            for index, hour in enumerate(hours)
        ]
        garmin = {"sleep": [_night(offset) for offset in range(29)]}
        result = mapped_personal_recovery(wellness, garmin, self.profile, TODAY)
        deficit = next(
            item
            for item in result["sleep_deficits"]
            if item["source"] == "Intervals.icu"
        )
        self.assertEqual(
            (deficit["known_nights"], deficit["deficit_hours"], deficit["status"]),
            (7, 8.0, "ok"),
        )
        series = result["regularity"]["series"][0]
        self.assertEqual(
            (series["status"], series["coverage"]["baseline_nights"]), ("ok", 28)
        )
        self.assertEqual(series["baseline"]["onset_median_minutes_local"], 1290)
        self.assertEqual(series["points"][-1]["onset_deviation_minutes"], 0.0)

    def test_incomplete(self) -> None:
        wellness = [
            {"id": (TODAY - timedelta(days=index)).isoformat(), "sleepSecs": 7 * 3600}
            for index in range(5)
        ]
        no_goal = mapped_personal_recovery(wellness, {}, {}, TODAY)
        self.assertEqual(
            (no_goal["sleep_deficits"], no_goal["sleep_target_hours"]), ([], None)
        )
        partial = mapped_personal_recovery(wellness, {}, self.profile, TODAY)[
            "sleep_deficits"
        ][0]
        self.assertEqual(
            (partial["known_nights"], partial["deficit_hours"], partial["status"]),
            (5, 5.0, "partial"),
        )
        empty = mapped_personal_recovery([], {}, self.profile, TODAY)["regularity"]
        self.assertEqual((empty["status"], empty["series"]), ("insufficient_data", []))

        garmin = {"sleep": [_night(offset) for offset in range(13, 0, -1)]}
        garmin["sleep"].append(_night(0, onset=(22, 45)))
        regularity = mapped_personal_recovery([], garmin, self.profile, TODAY)[
            "regularity"
        ]
        series = regularity["series"][0]
        self.assertEqual(
            (series["status"], series["coverage"]["baseline_nights"]),
            ("insufficient_data", 13),
        )
        self.assertEqual(
            series["reason"],
            "Mindestens 14 frühere datierte Schlafintervalle erforderlich.",
        )
        # #1429 (v2): below 14 earlier intervals no median and no deviation.
        self.assertEqual(
            [None] * 14,
            [point["onset_deviation_minutes"] for point in series["points"]],
        )
        self.assertIsNone(series["baseline"]["onset_median_minutes_local"])
        self.assertIsNone(series["baseline"]["wake_deviation_median_minutes"])

    def test_contradictory(self) -> None:
        wellness = [
            {"id": TODAY.isoformat(), "sleepSecs": 7 * 3600},
            {"id": (TODAY - timedelta(days=1)).isoformat(), "sleepSecs": 25 * 3600},
        ]
        garmin = {"sleep": [_night(0, hours=6.0)]}
        deficits = mapped_personal_recovery(wellness, garmin, self.profile, TODAY)[
            "sleep_deficits"
        ]
        by_source = {item["source"]: item for item in deficits}
        self.assertEqual(sorted(by_source), ["Garmin Connect", "Intervals.icu"])
        self.assertEqual(
            (
                by_source["Intervals.icu"]["deficit_hours"],
                by_source["Intervals.icu"]["known_nights"],
            ),
            (1.0, 1),
        )
        self.assertEqual(by_source["Garmin Connect"]["deficit_hours"], 2.0)

        too_long = _night(0)
        too_long["sleepStartTimestampGMT"] -= 20 * 3600 * 1000
        regularity = mapped_personal_recovery(
            [], {"sleep": [too_long]}, self.profile, TODAY
        )
        self.assertEqual(regularity["regularity"]["series"], [])

    def test_sleep_duration_and_timing_are_canonical_inputs(self) -> None:
        observation = recovery_observation(
            MetricKind.SLEEP_DURATION, 28_800.0, TODAY.isoformat(), ProviderId.GARMIN
        )
        reader = RecordingReader({MetricKind.SLEEP_DURATION: [observation]})
        inputs = read_recovery_inputs(
            reader, None, as_of=TODAY, latest_wellness_day=None
        )
        # Since #1411 sleep duration is a canonical input of the baselines.
        self.assertIn(MetricKind.SLEEP_DURATION, [call[0] for call in reader.calls])
        served = personal_recovery({}, TODAY, canonical=inputs)
        self.assertEqual(_baseline(served, "sleep", GARMIN)["value"], 8.0)
        timing = [
            kind.name
            for kind in MetricKind
            if "SLEEP" in kind.name
            and any(word in kind.name for word in ("START", "END", "ONSET", "WAKE"))
        ]
        self.assertEqual(
            timing,
            [],
            msg="#1419: sleep start and end are canonical sleep periods, not metric kinds",
        )
        sleep_storage = [
            f"{table}.{column}"
            for table, columns in CURRENT_DATABASE_SCHEMA.items()
            for column in {table, *columns}
            if "sleep" in column.lower()
        ]
        self.assertEqual(
            sleep_storage,
            ["sleep_periods.sleep_periods"],
            msg="#1419: canonical sleep periods are stored (schema v15); "
            "sleep-timing-variability-v2 reads them",
        )
        series = mapped_personal_recovery(
            [], {"sleep": [_night(0)]}, self.profile, TODAY
        )["regularity"]["series"][0]
        self.assertTrue(series["method"].startswith("sleepStartTimestampGMT/"))


def _effort_watts() -> tuple[list[float], list[tuple[int, int]]]:
    """1 Hz watts of a CP 250 W / W' 18 kJ rider's 3, 7 and 12 min efforts."""
    watts: list[float] = []
    spans: list[tuple[int, int]] = []
    for index, duration in enumerate(EFFORT_S):
        if index:
            watts += [100.0] * RECOVERY_S
        spans.append((len(watts), duration))
        watts += [CP_W + W_PRIME_J / duration] * duration
    return watts + [100.0], spans


class M4BestEffortInputs(linking.LinkingCase):
    """Power streams as input of a future critical power fit."""

    def _stream(
        self,
        provider: ProviderId,
        activity_id: str,
        time_s: list[float],
        watts: list[float],
        resolution: StreamResolution,
    ) -> ActivityStreamSet:
        return ActivityStreamSet(
            provider_activity_id=activity_id,
            provenance=Provenance(
                provider=provider,
                source_kind=SourceKind.PROVIDER_REPORTED,
                source_record_id=None,
                recorded_by=RecordingOrigin.GARMIN,
                retrieved_at=linking.SECOND,
                label=None,
            ),
            origin=ActivityDetailOrigin.FETCH,
            resolution=resolution,
            channels={
                StreamChannel.TIME_S: tuple(time_s),
                StreamChannel.POWER_W: tuple(watts),
            },
        )

    def _store(self, detail: ActivityStreamSet) -> StoredDetailSet:
        provider = detail.provenance.provider
        assert provider is not None
        with self.manager.unit_of_work() as db:
            replace_detail_set(
                db,
                detail,
                mapper_version=1,
                summary_sha256=None,
                now=linking.SECOND.isoformat(),
            )
            return detail_sets_for(db, provider.value, detail.provider_activity_id)[0]

    def _full_intervals(self) -> tuple[StoredDetailSet, list[tuple[int, int]]]:
        watts, spans = _effort_watts()
        detail = self._stream(
            ProviderId.INTERVALS,
            linking.INTERVALS_ID,
            [float(second) for second in range(len(watts))],
            watts,
            StreamResolution.FULL,
        )
        return self._store(detail), spans

    def _garmin_downsampled(self) -> StoredDetailSet:
        time_s = [float(second) for second in range(0, 1301, 5)]
        return self._store(
            self._stream(
                ProviderId.GARMIN,
                linking.GARMIN_ID,
                time_s,
                [250.0] * len(time_s),
                StreamResolution.DOWNSAMPLED,
            )
        )

    def test_complete(self) -> None:
        self._ingest_intervals([linking.intervals_ride()], linking.FIRST)
        stored, spans = self._full_intervals()
        detail = stored.detail
        assert isinstance(detail, ActivityStreamSet)
        self.assertEqual(detail.resolution, StreamResolution.FULL)
        watts = detail.channels[StreamChannel.POWER_W]
        for start, duration in spans:
            window = [
                value for value in watts[start : start + duration] if value is not None
            ]
            self.assertEqual(len(window), duration)
            self.assertAlmostEqual(
                math.fsum(window), CP_W * duration + W_PRIME_J, places=6
            )
        self.assertAlmostEqual(watts[spans[1][0]] or 0.0, 292.857142857, places=9)
        self.assertEqual((watts[spans[0][0]], watts[spans[2][0]]), (350.0, 275.0))

        profile = power_profile(
            {
                "sport": "ride",
                "streams": {
                    "time": list(detail.channels[StreamChannel.TIME_S]),
                    "watts": list(watts),
                },
            }
        )
        best = {
            point["duration_seconds"]: point["watts"]
            for point in profile["duration_curve"]
        }
        self.assertEqual(
            [best[duration] for duration in EFFORT_S], [350.0, 292.86, 275.0]
        )

    def test_incomplete(self) -> None:
        self._ingest_garmin([linking.garmin_ride()], linking.FIRST)
        stored = self._garmin_downsampled()
        assert isinstance(stored.detail, ActivityStreamSet)
        self.assertEqual(stored.detail.resolution, StreamResolution.DOWNSAMPLED)

        session = self._sessions()[linking.GARMIN_ID]["activity_id"]
        with self.manager.reader() as db:
            curves = SessionCurveReader(
                CanonicalTableReader().session_activities
            ).curves(db, [session], {})
        # A downsampled stream never enters the mean-maximal curve.
        self.assertEqual(curves, {})
        empty = power_profile({"sport": "ride", "streams": {}})
        self.assertEqual(
            (empty["status"], empty["reason"], empty["duration_curve"]),
            ("insufficient_data", "Vollständige Rad-Leistungsmessreihe fehlt.", []),
        )

    def test_contradictory(self) -> None:
        self._ingest_intervals([linking.intervals_ride()], linking.FIRST)
        self._ingest_garmin([linking.garmin_ride()], linking.SECOND)
        full, _ = self._full_intervals()
        downsampled = self._garmin_downsampled()
        survivor = self._sessions()[linking.INTERVALS_ID]["activity_id"]
        with self.manager.reader() as db:
            stored = detail_sets_for_session(db, survivor)
        self.assertEqual(
            {
                item.provider: item.detail.resolution
                for item in stored
                if isinstance(item.detail, ActivityStreamSet)
            },
            {INTERVALS: StreamResolution.FULL, GARMIN: StreamResolution.DOWNSAMPLED},
        )
        started_at = datetime(2026, 9, 10, 5, 0, tzinfo=UTC)
        merged = merge_details(
            DetailCandidate(item, started_at, None) for item in reversed(stored)
        )
        assert merged.streams is not None
        self.assertEqual(merged.streams.primary.stored.provider, INTERVALS)
        self.assertEqual(
            [item.stored.provider for item in merged.streams.alternatives], [GARMIN]
        )
        choice = merged.streams.channels[StreamChannel.POWER_W]
        self.assertEqual(choice.source.stored.provider, INTERVALS)
        assert isinstance(full.detail, ActivityStreamSet)
        self.assertEqual(choice.values, full.detail.channels[StreamChannel.POWER_W])
        self.assertNotEqual(downsampled.provider, choice.source.stored.provider)


if __name__ == "__main__":
    unittest.main()
