"""Canonical analysis input reproduces the legacy Intervals.icu analysis."""

import copy
import dataclasses
import unittest
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.activities.detail_merge import (
    ChannelChoice,
    DetailCandidate,
    MergedStreams,
    SetChoice,
    merge_details,
)
from backend.canonical.activity_detail import (
    ActivityLap,
    ActivityLapSet,
    ActivityStreamSet,
)
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    Environment,
    LapKind,
    LapSource,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
    StreamChannel,
    StreamResolution,
)
from backend.db.activity_detail_store import StoredDetailSet
from backend.performance.analysis_input import analysis_input
from backend.performance.power_profile import power_profile, running_profile
from backend.performance.session_analysis import aerobic_analysis, interval_quality
from backend.providers.intervals_activity_detail_mapping import (
    map_intervals_activity_detail,
)
from backend.providers.intervals_activity_detail_projection import detailed_activity
from backend.providers.intervals_activity_fields import activity_detail_laps
from backend.providers.intervals_activity_mapping import intervals_analysis_sport
from backend.sync.activity_details import normalize_streams

RETRIEVED = datetime(2026, 10, 19, 8, 0, tzinfo=UTC)
STARTED = datetime(2026, 10, 19, 7, 0, tzinfo=UTC)
FETCHED = "2026-10-19T08:00:00+00:00"
TIME = tuple(float(second) for second in range(2701))
POWER = StreamChannel.POWER_W
HR = StreamChannel.HEART_RATE_BPM
SPEED = StreamChannel.SPEED_MPS
DISTANCE = StreamChannel.DISTANCE_M
MOVING = StreamChannel.MOVING
TIME_S = StreamChannel.TIME_S


def ride_payload() -> dict[str, Any]:
    return {
        "id": "i-ride",
        "type": "Ride",
        "name": "Synthetic ride",
        "start_date_local": "2026-10-19T07:00:00",
        "decoupling": 3.2,
        "icu_intervals": [
            {"start_time": 0, "end_time": 600, "name": "Block 1"},
            {"start_time": 900, "end_time": 1500, "name": "Block 2"},
            {"start_time": 1800, "end_time": 2400, "name": "Block 3"},
        ],
    }


def ride_streams() -> list[dict[str, Any]]:
    return [
        {"type": "time", "data": list(range(2701))},
        {"type": "watts", "data": [200 + index % 7 for index in range(2701)]},
        {"type": "heartrate", "data": [100 + index / 100 for index in range(2701)]},
        {
            "type": "moving",
            "data": [not 1500 <= index < 1560 for index in range(2701)],
        },
    ]


def run_payload() -> dict[str, Any]:
    return {"id": "i-run", "type": "Run", "name": "Synthetic run"}


def run_streams() -> list[dict[str, Any]]:
    return [
        {"type": "time", "data": list(range(2701))},
        {
            "type": "velocity_smooth",
            "data": [3.0 + (index % 5) / 100 for index in range(2701)],
        },
        {"type": "distance", "data": [index * 3.0 for index in range(2701)]},
        {"type": "heartrate", "data": [140 + index / 200 for index in range(2701)]},
        {"type": "moving", "data": [True] * 2701},
    ]


def record(
    sport: Sport,
    environment: Environment = Environment.OUTDOOR,
    *,
    label: str | None = "Intervals.icu",
) -> ActivityRecord:
    return ActivityRecord(
        activity_id="act-1",
        provenance=Provenance(
            provider=ProviderId.INTERVALS,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id="i-ride",
            recorded_by=RecordingOrigin.WAHOO,
            retrieved_at=RETRIEVED,
            label=label,
        ),
        sport=sport,
        environment=environment,
        started_at=STARTED,
        duration_s=2700.0,
        distance_m=2700.0,
        load=85.0,
        load_model=LoadModel.INTERVALS_TRAINING_LOAD,
        avg_hr=120.0,
        avg_power=200.0,
        name="Synthetic",
    )


def as_provider(activity: ActivityRecord, provider: ProviderId) -> ActivityRecord:
    """Return the same record attributed to another provider."""
    return dataclasses.replace(
        activity,
        provenance=dataclasses.replace(activity.provenance, provider=provider),
    )


def provenance(provider: ProviderId, label: str | None) -> Provenance:
    return Provenance(
        provider=provider,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=None,
        recorded_by=RecordingOrigin.WAHOO,
        retrieved_at=RETRIEVED,
        label=label,
    )


def candidate(
    provider: ProviderId,
    label: str | None,
    channels: Mapping[StreamChannel, tuple[float | None, ...]],
) -> DetailCandidate:
    detail = ActivityStreamSet(
        provider_activity_id=f"{provider.value}-1",
        provenance=provenance(provider, label),
        origin=ActivityDetailOrigin.FETCH,
        resolution=StreamResolution.FULL,
        channels={TIME_S: TIME, **channels},
    )
    return DetailCandidate(
        stored=StoredDetailSet(
            provider=provider.value,
            provider_activity_id=detail.provider_activity_id,
            activity_id="act-1",
            mapper_version=1,
            summary_sha256=None,
            fetched_at=FETCHED,
            detail=detail,
        ),
        started_at=STARTED,
        device_type=None,
    )


def merged(
    primary: DetailCandidate,
    choices: Mapping[StreamChannel, tuple[DetailCandidate, tuple[float | None, ...]]],
) -> MergedStreams:
    return MergedStreams(
        primary=primary,
        time_s=TIME,
        channels={
            channel: ChannelChoice(values=values, source=source, aligned=True)
            for channel, (source, values) in choices.items()
        },
        alternatives=(),
    )


def lap_choice(provider: ProviderId, started_at: datetime | None) -> SetChoice:
    """One 0-60 s lap of ``provider`` whose recording started at ``started_at``."""
    lap_set = ActivityLapSet(
        provider_activity_id=f"{provider.value}-1",
        provenance=provenance(provider, "Garmin"),
        origin=ActivityDetailOrigin.FETCH,
        lap_source=LapSource.DEVICE_LAPS,
        laps=(
            ActivityLap(
                index=0, kind=LapKind.LAP, start_offset_s=0.0, end_offset_s=60.0
            ),
        ),
    )
    return SetChoice(
        chosen=DetailCandidate(
            stored=StoredDetailSet(
                provider=provider.value,
                provider_activity_id=lap_set.provider_activity_id,
                activity_id="act-1",
                mapper_version=1,
                summary_sha256=None,
                fetched_at=FETCHED,
                detail=lap_set,
            ),
            started_at=started_at,
            device_type=None,
        ),
        alternatives=(),
    )


def from_intervals(
    payload: dict[str, Any], stream_list: list[dict[str, Any]]
) -> tuple[dict[str, Any], Any]:
    """Build the legacy dict as refresh does, and merge the mapped canonical sets."""
    streams = normalize_streams(stream_list)
    projected = detailed_activity({**payload, "laps": activity_detail_laps(payload)})
    projected["streams"] = streams
    # The sync path analyses the projection with its canonical sport.
    projected = {**projected, **intervals_analysis_sport(projected)}
    result = map_intervals_activity_detail(
        payload, streams, recorded_by=RecordingOrigin.WAHOO, retrieved_at=RETRIEVED
    )
    assert result.issues == ()
    candidates = [
        DetailCandidate(
            stored=StoredDetailSet(
                provider=ProviderId.INTERVALS.value,
                provider_activity_id=detail.provider_activity_id,
                activity_id="act-1",
                mapper_version=1,
                summary_sha256=None,
                fetched_at=FETCHED,
                detail=detail,
            ),
            started_at=STARTED,
            device_type=None,
        )
        for detail in result.records
    ]
    return projected, merge_details(candidates)


class GoldenParityTests(unittest.TestCase):
    def test_ride_analysis_matches_legacy_input(self) -> None:
        projected, merged = from_intervals(ride_payload(), ride_streams())
        adapted = analysis_input(
            record(Sport.RIDE),
            merged.streams,
            merged.laps,
            decoupling=projected.get("decoupling"),
        )
        targets = {
            "steps": [{"kind": "power", "target": "100%", "duration": 600}] * 3,
            "basis": {"ftp": 200},
        }
        self.assertEqual("Intervals.icu", adapted.source_label)
        legacy_aerobic = aerobic_analysis(projected)
        self.assertEqual("ok", legacy_aerobic["status"])
        self.assertEqual(
            legacy_aerobic,
            aerobic_analysis(adapted.activity, source_label=adapted.source_label),
        )
        legacy_power = power_profile(projected)
        self.assertEqual("ok", legacy_power["status"])
        self.assertEqual(
            legacy_power,
            power_profile(adapted.activity, source_label=adapted.source_label),
        )
        legacy_quality = interval_quality(projected, targets)
        self.assertEqual("ok", legacy_quality["status"])
        self.assertEqual(
            legacy_quality,
            interval_quality(
                adapted.activity, targets, source_label=adapted.source_label
            ),
        )

    def test_run_analysis_matches_legacy_input(self) -> None:
        # Intervals.icu "Run" activities map to an unknown environment.
        projected, merged = from_intervals(run_payload(), run_streams())
        adapted = analysis_input(
            record(Sport.RUN, Environment.UNKNOWN), merged.streams, merged.laps
        )
        legacy_running = running_profile(projected)
        self.assertEqual("ok", legacy_running["status"])
        self.assertEqual(
            legacy_running,
            running_profile(adapted.activity, source_label=adapted.source_label),
        )
        legacy_aerobic = aerobic_analysis(projected)
        self.assertEqual("ok", legacy_aerobic["status"])
        self.assertEqual(
            legacy_aerobic,
            aerobic_analysis(adapted.activity, source_label=adapted.source_label),
        )


class AnalysisInputMappingTests(unittest.TestCase):
    def test_activity_names_its_canonical_sport_and_environment(self) -> None:
        for sport, environment in (
            (Sport.RIDE, Environment.OUTDOOR),
            (Sport.RIDE, Environment.VIRTUAL),
            (Sport.RUN, Environment.UNKNOWN),
            (Sport.SWIM, Environment.OUTDOOR),
        ):
            with self.subTest(sport=sport, environment=environment):
                adapted = analysis_input(record(sport, environment), None, None)
                self.assertEqual(sport.value, adapted.activity["sport"])
                self.assertEqual(environment.value, adapted.activity["environment"])
                self.assertNotIn("type", adapted.activity)

    def test_intervals_outdoor_runs_are_trail_runs(self) -> None:
        adapted = analysis_input(record(Sport.RUN), None, None)
        self.assertTrue(adapted.activity["trail"])

    def test_other_providers_outdoor_runs_are_not_trail_runs(self) -> None:
        adapted = analysis_input(
            as_provider(record(Sport.RUN), ProviderId.WAHOO), None, None
        )
        self.assertFalse(adapted.activity["trail"])

    def test_moving_flags_map_to_booleans_and_gaps(self) -> None:
        source = candidate(
            ProviderId.INTERVALS, "Intervals.icu", {POWER: (200.0,) * len(TIME)}
        )
        values = (1.0, 0.0, None) + (1.0,) * (len(TIME) - 3)
        stream = merged(source, {MOVING: (source, values)})
        moving = analysis_input(record(Sport.RIDE), stream, None).activity["streams"][
            "moving"
        ]
        self.assertEqual([True, False, None], moving[:3])
        self.assertTrue(all(flag is True for flag in moving[3:]))

    def test_missing_channels_are_absent_and_lists_are_plain(self) -> None:
        source = candidate(
            ProviderId.INTERVALS, "Intervals.icu", {POWER: (200.0,) * len(TIME)}
        )
        stream = merged(source, {POWER: (source, (200.0,) * len(TIME))})
        adapted = analysis_input(record(Sport.RIDE), stream, None)
        self.assertEqual({"time", "watts"}, set(adapted.activity["streams"]))
        self.assertIsInstance(adapted.activity["streams"]["time"], list)
        self.assertIsInstance(adapted.activity["streams"]["watts"], list)

    def test_missing_streams_and_laps_are_empty(self) -> None:
        adapted = analysis_input(record(Sport.RIDE), None, None)
        self.assertEqual({}, adapted.activity["streams"])
        self.assertEqual([], adapted.activity["laps"])
        self.assertEqual("Intervals.icu", adapted.source_label)
        self.assertIsNone(adapted.activity["decoupling"])

    def test_laps_keep_offsets_in_lap_order(self) -> None:
        lap_set = ActivityLapSet(
            provider_activity_id="intervals-1",
            provenance=provenance(ProviderId.INTERVALS, "Intervals.icu"),
            origin=ActivityDetailOrigin.FETCH,
            lap_source=LapSource.PROVIDER_INTERVALS,
            laps=(
                ActivityLap(
                    index=0,
                    kind=LapKind.LAP,
                    start_offset_s=0.0,
                    end_offset_s=60.0,
                ),
                ActivityLap(
                    index=1,
                    kind=LapKind.LAP,
                    start_offset_s=60.0,
                    end_offset_s=130.0,
                ),
            ),
        )
        laps = SetChoice(
            chosen=DetailCandidate(
                stored=StoredDetailSet(
                    provider="intervals",
                    provider_activity_id="intervals-1",
                    activity_id="act-1",
                    mapper_version=1,
                    summary_sha256=None,
                    fetched_at=FETCHED,
                    detail=lap_set,
                ),
                started_at=STARTED,
                device_type=None,
            ),
            alternatives=(),
        )
        adapted = analysis_input(record(Sport.RIDE, label="Record"), None, laps)
        self.assertEqual(
            [
                {"start_time": 0.0, "end_time": 60.0},
                {"start_time": 60.0, "end_time": 130.0},
            ],
            adapted.activity["laps"],
        )
        self.assertEqual("Intervals.icu", adapted.label_for("laps"))
        self.assertEqual("Record", adapted.source_label)

    def test_laps_of_another_recording_move_to_the_primary_clock(self) -> None:
        primary = candidate(
            ProviderId.INTERVALS, "Intervals.icu", {POWER: (200.0,) * len(TIME)}
        )
        stream = merged(primary, {})
        later = lap_choice(ProviderId.GARMIN, STARTED + timedelta(seconds=30))
        adapted = analysis_input(record(Sport.RIDE), stream, later)
        self.assertEqual(
            [{"start_time": 30.0, "end_time": 90.0}], adapted.activity["laps"]
        )
        self.assertEqual("Garmin", adapted.label_for("laps"))

    def test_laps_without_a_start_time_are_dropped_when_unalignable(self) -> None:
        primary = candidate(
            ProviderId.INTERVALS, "Intervals.icu", {POWER: (200.0,) * len(TIME)}
        )
        stream = merged(primary, {})
        adapted = analysis_input(
            record(Sport.RIDE), stream, lap_choice(ProviderId.GARMIN, None)
        )
        self.assertEqual([], adapted.activity["laps"])
        self.assertNotIn("laps", adapted.channel_labels)

    def test_laps_of_the_primary_recording_keep_their_offsets(self) -> None:
        primary = candidate(ProviderId.GARMIN, "Garmin", {POWER: (200.0,) * len(TIME)})
        stream = merged(primary, {})
        adapted = analysis_input(
            record(Sport.RIDE), stream, lap_choice(ProviderId.GARMIN, None)
        )
        self.assertEqual(
            [{"start_time": 0.0, "end_time": 60.0}], adapted.activity["laps"]
        )

    def test_decoupling_is_passed_through(self) -> None:
        adapted = analysis_input(record(Sport.RIDE), None, None, decoupling=4.5)
        self.assertEqual(4.5, adapted.activity["decoupling"])


class SourceLabelTests(unittest.TestCase):
    def test_single_provider_label_comes_from_its_streams(self) -> None:
        source = candidate(
            ProviderId.INTERVALS, "Intervals.icu", {POWER: (200.0,) * len(TIME)}
        )
        stream = merged(source, {POWER: (source, (200.0,) * len(TIME))})
        adapted = analysis_input(record(Sport.RIDE, label="Ignored"), stream, None)
        self.assertEqual("Intervals.icu", adapted.source_label)

    def test_two_providers_are_joined_per_channel_in_channel_order(self) -> None:
        wahoo = candidate(ProviderId.WAHOO, "Wahoo", {POWER: (200.0,) * len(TIME)})
        garmin = candidate(ProviderId.GARMIN, "Garmin", {HR: (130.0,) * len(TIME)})
        stream = merged(
            wahoo,
            {
                POWER: (wahoo, (200.0,) * len(TIME)),
                HR: (garmin, (130.0,) * len(TIME)),
            },
        )
        adapted = analysis_input(record(Sport.RIDE), stream, None)
        self.assertEqual("Wahoo / Garmin", adapted.source_label)
        self.assertEqual(
            {"watts": "Wahoo", "heartrate": "Garmin"}, dict(adapted.channel_labels)
        )
        self.assertEqual("Wahoo", adapted.label_for("watts"))
        self.assertEqual("Garmin / Wahoo", adapted.label_for("heartrate", "watts"))
        self.assertEqual(
            "Wahoo / Garmin", adapted.label_for("velocity_smooth", "distance")
        )

    def test_repeated_provider_label_is_listed_once(self) -> None:
        garmin = candidate(
            ProviderId.GARMIN,
            "Garmin",
            {SPEED: (3.0,) * len(TIME), DISTANCE: (0.0,) * len(TIME)},
        )
        stream = merged(
            garmin,
            {
                SPEED: (garmin, (3.0,) * len(TIME)),
                DISTANCE: (garmin, (0.0,) * len(TIME)),
            },
        )
        adapted = analysis_input(record(Sport.RUN), stream, None)
        self.assertEqual("Garmin", adapted.source_label)

    def test_unlabelled_streams_are_named_by_their_provider(self) -> None:
        wahoo = candidate(ProviderId.WAHOO, None, {POWER: (200.0,) * len(TIME)})
        stream = merged(wahoo, {POWER: (wahoo, (200.0,) * len(TIME))})
        adapted = analysis_input(record(Sport.RIDE), stream, None)
        self.assertEqual(ProviderId.WAHOO.value, adapted.source_label)

    def test_without_stream_labels_the_record_label_is_used(self) -> None:
        self.assertEqual(
            "Intervals.icu",
            analysis_input(record(Sport.RIDE), None, None).source_label,
        )
        self.assertEqual(
            "Fallback label",
            analysis_input(
                record(Sport.RIDE, label="Fallback label"), None, None
            ).source_label,
        )

    def test_custom_label_reaches_the_analysis_source_strings(self) -> None:
        _, merged_detail = from_intervals(ride_payload(), ride_streams())
        adapted = analysis_input(record(Sport.RIDE), merged_detail.streams, None)
        result = aerobic_analysis(adapted.activity, source_label="Wahoo")
        self.assertEqual("derived from Wahoo original streams", result["source"])
        self.assertEqual("Intervals.icu", result["provider_decoupling"]["source"])


class NonMutationTests(unittest.TestCase):
    def test_legacy_and_adapter_inputs_are_not_mutated(self) -> None:
        projected, merged_detail = from_intervals(ride_payload(), ride_streams())
        legacy_before = copy.deepcopy(projected)
        channels_before = {
            channel: choice.values
            for channel, choice in merged_detail.streams.channels.items()
        }
        time_before = merged_detail.streams.time_s
        analysis_input(record(Sport.RIDE), merged_detail.streams, merged_detail.laps)
        aerobic_analysis(projected)
        power_profile(projected)
        self.assertEqual(legacy_before, projected)
        self.assertEqual(
            channels_before,
            {
                channel: choice.values
                for channel, choice in merged_detail.streams.channels.items()
            },
        )
        self.assertEqual(time_before, merged_detail.streams.time_s)

    def test_adapter_output_does_not_share_storage_with_merged_streams(self) -> None:
        source = candidate(
            ProviderId.INTERVALS, "Intervals.icu", {POWER: (200.0,) * len(TIME)}
        )
        stream = merged(source, {POWER: (source, (200.0,) * len(TIME))})
        adapted = analysis_input(record(Sport.RIDE), stream, None)
        adapted.activity["streams"]["watts"].append(0.0)
        self.assertEqual(len(TIME), len(stream.channels[POWER].values))


if __name__ == "__main__":
    unittest.main()
