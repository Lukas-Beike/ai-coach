"""Read-time choice between alternative provider detail sets (synthetic, no DB)."""

import unittest
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta

from backend.activities.detail_merge import (
    DetailCandidate,
    MergedDetail,
    merge_details,
    stream_average,
)
from backend.canonical.activity_detail import (
    ActivityDetailSet,
    ActivityLap,
    ActivityLapSet,
    ActivityStreamSet,
    ZoneBucket,
    ZoneDistribution,
)
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    DeviceType,
    LapKind,
    LapSource,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    StreamChannel,
    StreamResolution,
    ZoneBoundarySource,
    ZoneMetric,
)
from backend.db.activity_detail_store import StoredDetailSet

STARTED = datetime(2026, 10, 18, 7, 0, tzinfo=UTC)
FETCHED = "2026-10-18T08:00:00+00:00"
TIME_5 = (0.0, 1.0, 2.0, 3.0, 4.0)
POWER = StreamChannel.POWER_W
HR = StreamChannel.HEART_RATE_BPM
MOVING = StreamChannel.MOVING


def provenance(provider: ProviderId, recorded_by: RecordingOrigin) -> Provenance:
    return Provenance(
        provider=provider,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=None,
        recorded_by=recorded_by,
        retrieved_at=None,
        label=None,
    )


def streams(
    provider: ProviderId,
    recorded_by: RecordingOrigin,
    channels: Mapping[StreamChannel, Sequence[float | None]],
    *,
    time: Sequence[float] = TIME_5,
    resolution: StreamResolution = StreamResolution.FULL,
    activity: str | None = None,
) -> ActivityStreamSet:
    return ActivityStreamSet(
        provider_activity_id=activity or f"{provider.value}-activity",
        provenance=provenance(provider, recorded_by),
        origin=ActivityDetailOrigin.FETCH,
        resolution=resolution,
        channels={
            StreamChannel.TIME_S: tuple(time),
            **{channel: tuple(values) for channel, values in channels.items()},
        },
    )


def laps(
    provider: ProviderId,
    recorded_by: RecordingOrigin,
    source: LapSource,
    *,
    activity: str | None = None,
) -> ActivityLapSet:
    return ActivityLapSet(
        provider_activity_id=activity or f"{provider.value}-activity",
        provenance=provenance(provider, recorded_by),
        origin=ActivityDetailOrigin.FETCH,
        lap_source=source,
        laps=tuple(
            ActivityLap(
                index=index,
                kind=LapKind.LAP,
                start_offset_s=60.0 * index,
                end_offset_s=60.0 * (index + 1),
            )
            for index in range(2)
        ),
    )


def zones(
    provider: ProviderId,
    recorded_by: RecordingOrigin,
    metric: ZoneMetric,
    boundary: ZoneBoundarySource,
    *,
    bounded: bool,
) -> ZoneDistribution:
    return ZoneDistribution(
        provider_activity_id=f"{provider.value}-activity",
        provenance=provenance(provider, recorded_by),
        origin=ActivityDetailOrigin.FETCH,
        metric=metric,
        boundary_source=boundary,
        buckets=(
            ZoneBucket(
                index=1,
                seconds=600.0,
                lower=100.0 if bounded else None,
                upper=130.0 if bounded else None,
            ),
            ZoneBucket(
                index=2,
                seconds=300.0,
                lower=130.0 if bounded else None,
                upper=None,
            ),
        ),
    )


def candidate(
    detail: ActivityDetailSet,
    *,
    started_at: datetime | None = STARTED,
    device: DeviceType | None = None,
    fetched_at: str = FETCHED,
) -> DetailCandidate:
    provider = detail.provenance.provider
    assert provider is not None
    return DetailCandidate(
        stored=StoredDetailSet(
            provider=provider.value,
            provider_activity_id=detail.provider_activity_id,
            activity_id="session-1",
            mapper_version=1,
            summary_sha256=None,
            fetched_at=fetched_at,
            detail=detail,
        ),
        started_at=started_at,
        device_type=device,
    )


class PrimaryStreamChoiceTests(unittest.TestCase):
    def test_full_set_beats_downsampled_even_when_relayed(self) -> None:
        relayed_full = candidate(
            streams(
                ProviderId.INTERVALS,
                RecordingOrigin.GARMIN,
                {POWER: (200.0, 210.0, 220.0, 230.0, 240.0)},
            )
        )
        own_downsampled = candidate(
            streams(
                ProviderId.WAHOO,
                RecordingOrigin.WAHOO,
                {
                    POWER: (1.0, 2.0, 3.0, 4.0, 5.0),
                    HR: (120.0, 121.0, 122.0, 123.0, 124.0),
                },
                resolution=StreamResolution.DOWNSAMPLED,
            ),
            device=DeviceType.BIKE_COMPUTER,
        )
        merged = merge_details([own_downsampled, relayed_full])
        assert merged.streams is not None
        self.assertIs(merged.streams.primary, relayed_full)
        self.assertEqual(len(merged.streams.alternatives), 1)
        self.assertIs(merged.streams.alternatives[0], own_downsampled)

    def test_own_copy_beats_relay_at_equal_resolution(self) -> None:
        relay = candidate(
            streams(
                ProviderId.INTERVALS,
                RecordingOrigin.GARMIN,
                {POWER: (200.0, 200.0, 200.0, 200.0, 200.0)},
            )
        )
        own = candidate(
            streams(
                ProviderId.GARMIN,
                RecordingOrigin.GARMIN,
                {POWER: (150.0, 150.0, 150.0, 150.0, 150.0)},
            )
        )
        merged = merge_details([relay, own])
        assert merged.streams is not None
        self.assertIs(merged.streams.primary, own)

    def test_channel_count_precedes_tie_break_after_copy(self) -> None:
        # Garmin would win the provider tie-break, but Wahoo has more channels.
        garmin = candidate(
            streams(
                ProviderId.GARMIN,
                RecordingOrigin.GARMIN,
                {
                    POWER: (200.0, 200.0, 200.0, 200.0, 200.0),
                    StreamChannel.CADENCE_RPM: (None, None, None, None, None),
                },
            )
        )
        wahoo = candidate(
            streams(
                ProviderId.WAHOO,
                RecordingOrigin.WAHOO,
                {
                    POWER: (210.0, 210.0, 210.0, 210.0, 210.0),
                    HR: (130.0, 130.0, 130.0, 130.0, 130.0),
                },
            )
        )
        merged = merge_details([garmin, wahoo])
        assert merged.streams is not None
        self.assertIs(merged.streams.primary, wahoo)

    def test_tie_break_uses_provider_order_then_newest_fetch_then_id(self) -> None:
        values = {POWER: (200.0, 200.0, 200.0, 200.0, 200.0)}
        with self.subTest("provider order before fetch time and id"):
            intervals = candidate(
                streams(ProviderId.INTERVALS, RecordingOrigin.GARMIN, values),
                fetched_at="2026-10-17T08:00:00+00:00",
            )
            wahoo = candidate(
                streams(ProviderId.WAHOO, RecordingOrigin.GARMIN, values),
                fetched_at="2026-10-18T09:00:00+00:00",
            )
            merged = merge_details([wahoo, intervals])
            assert merged.streams is not None
            self.assertIs(merged.streams.primary, intervals)
        with self.subTest("newest fetch wins within one provider"):
            older = candidate(
                streams(
                    ProviderId.GARMIN, RecordingOrigin.GARMIN, values, activity="g-a"
                ),
                fetched_at="2026-10-17T08:00:00+00:00",
            )
            newer = candidate(
                streams(
                    ProviderId.GARMIN, RecordingOrigin.GARMIN, values, activity="g-z"
                ),
                fetched_at="2026-10-18T09:00:00+00:00",
            )
            merged = merge_details([older, newer])
            assert merged.streams is not None
            self.assertIs(merged.streams.primary, newer)
        with self.subTest("provider activity id breaks equal fetch times"):
            first = candidate(
                streams(
                    ProviderId.GARMIN, RecordingOrigin.GARMIN, values, activity="g-b"
                )
            )
            second = candidate(
                streams(
                    ProviderId.GARMIN, RecordingOrigin.GARMIN, values, activity="g-a"
                )
            )
            merged = merge_details([first, second])
            assert merged.streams is not None
            self.assertIs(merged.streams.primary, second)


class PerChannelChoiceTests(unittest.TestCase):
    def test_power_and_heart_rate_come_from_their_best_devices(self) -> None:
        time = (0.0, 1.0, 2.0)
        wahoo = candidate(
            streams(
                ProviderId.WAHOO,
                RecordingOrigin.WAHOO,
                {POWER: (250.0, 260.0, 270.0), HR: (130.0, 131.0, 132.0)},
                time=time,
            ),
            device=DeviceType.BIKE_COMPUTER,
        )
        garmin = candidate(
            streams(
                ProviderId.GARMIN,
                RecordingOrigin.GARMIN,
                {POWER: (200.0, 210.0, 220.0), HR: (140.0, 141.0, 142.0)},
                time=time,
            ),
            device=DeviceType.WATCH,
        )
        merged = merge_details([wahoo, garmin])
        assert merged.streams is not None
        self.assertIs(merged.streams.primary, garmin)
        power = merged.streams.channels[POWER]
        self.assertIs(power.source, wahoo)
        self.assertTrue(power.aligned)
        self.assertEqual(power.values, (250.0, 260.0, 270.0))
        heart_rate = merged.streams.channels[HR]
        self.assertIs(heart_rate.source, garmin)
        self.assertFalse(heart_rate.aligned)
        self.assertEqual(heart_rate.values, (140.0, 141.0, 142.0))

    def test_downsampled_set_never_beats_full_set_for_any_device(self) -> None:
        full_watch = candidate(
            streams(
                ProviderId.GARMIN,
                RecordingOrigin.GARMIN,
                {POWER: (200.0, 210.0, 220.0, 230.0, 240.0)},
            ),
            device=DeviceType.WATCH,
        )
        downsampled_meter = candidate(
            streams(
                ProviderId.WAHOO,
                RecordingOrigin.WAHOO,
                {POWER: (300.0, 310.0, 320.0, 330.0, 340.0)},
                resolution=StreamResolution.DOWNSAMPLED,
            ),
            device=DeviceType.POWER_METER,
        )
        merged = merge_details([downsampled_meter, full_watch])
        assert merged.streams is not None
        self.assertIs(merged.streams.primary, full_watch)
        self.assertIs(merged.streams.channels[POWER].source, full_watch)


class AlignmentTests(unittest.TestCase):
    def test_start_offset_with_coarser_sampling_uses_nearest_points(self) -> None:
        primary = candidate(
            streams(
                ProviderId.GARMIN,
                RecordingOrigin.GARMIN,
                {HR: tuple(140.0 + index for index in range(61))},
                time=tuple(float(index) for index in range(61)),
            ),
            device=DeviceType.WATCH,
        )
        # Starts 10 s later and samples every 2 s: sample i lies at 10 + 2 i.
        wahoo = candidate(
            streams(
                ProviderId.WAHOO,
                RecordingOrigin.WAHOO,
                {POWER: tuple(100.0 + index for index in range(26))},
                time=tuple(2.0 * index for index in range(26)),
            ),
            started_at=STARTED.replace(second=10),
            device=DeviceType.BIKE_COMPUTER,
        )
        merged = merge_details([wahoo, primary])
        assert merged.streams is not None
        self.assertIs(merged.streams.primary, primary)
        power = merged.streams.channels[POWER]
        self.assertIs(power.source, wahoo)
        self.assertTrue(power.aligned)
        self.assertEqual(len(power.values), 61)
        # Outside the 4 s tolerance (2 x 2 s) before the first sample: None.
        self.assertEqual(power.values[:6], (None,) * 6)
        self.assertEqual(power.values[6], 100.0)
        self.assertEqual(power.values[10], 100.0)
        # Ties between two samples pick the earlier one.
        self.assertEqual(power.values[11], 100.0)
        self.assertEqual(power.values[12], 101.0)
        self.assertEqual(power.values[13], 101.0)
        self.assertEqual(power.values[14], 102.0)
        self.assertEqual(power.values[60], 125.0)

    def test_overlap_below_threshold_falls_back_to_next_candidate(self) -> None:
        primary = candidate(
            streams(
                ProviderId.GARMIN,
                RecordingOrigin.GARMIN,
                {
                    HR: tuple(140.0 for _ in range(61)),
                    POWER: tuple(180.0 for _ in range(61)),
                },
                time=tuple(float(index) for index in range(61)),
            ),
            device=DeviceType.WATCH,
        )
        # Starts 50 s later: only 10 of 60 primary seconds overlap, so the
        # set is rejected for power.
        wahoo = candidate(
            streams(
                ProviderId.WAHOO,
                RecordingOrigin.WAHOO,
                {POWER: tuple(900.0 for _ in range(11))},
                time=tuple(float(index) for index in range(11)),
            ),
            started_at=STARTED + timedelta(seconds=50),
            device=DeviceType.BIKE_COMPUTER,
        )
        intervals = candidate(
            streams(
                ProviderId.INTERVALS,
                RecordingOrigin.GARMIN,
                {POWER: tuple(300.0 + index for index in range(61))},
                time=tuple(float(index) for index in range(61)),
            ),
            device=DeviceType.BIKE_COMPUTER,
        )
        merged = merge_details([wahoo, intervals, primary])
        assert merged.streams is not None
        self.assertIs(merged.streams.primary, primary)
        power = merged.streams.channels[POWER]
        self.assertIs(power.source, intervals)
        self.assertTrue(power.aligned)
        self.assertEqual(power.values[0], 300.0)
        self.assertEqual(power.values[60], 360.0)

        fallback = merge_details([wahoo, primary])
        assert fallback.streams is not None
        self.assertIs(fallback.streams.channels[POWER].source, primary)
        self.assertFalse(fallback.streams.channels[POWER].aligned)

    def test_missing_started_at_is_placeable_only_on_identical_axes(self) -> None:
        time = (0.0, 1.0, 2.0)
        with self.subTest("primary has a start, candidate does not"):
            primary = candidate(
                streams(
                    ProviderId.GARMIN,
                    RecordingOrigin.GARMIN,
                    {HR: (140.0, 141.0, 142.0)},
                    time=time,
                ),
            )
            wahoo = candidate(
                streams(
                    ProviderId.WAHOO,
                    RecordingOrigin.WAHOO,
                    {POWER: (250.0, 260.0, 270.0)},
                    time=time,
                ),
                started_at=None,
            )
            merged = merge_details([wahoo, primary])
            assert merged.streams is not None
            self.assertNotIn(POWER, merged.streams.channels)
        with self.subTest("candidate has a start, primary does not"):
            primary = candidate(
                streams(
                    ProviderId.GARMIN,
                    RecordingOrigin.GARMIN,
                    {HR: (140.0, 141.0, 142.0)},
                    time=time,
                ),
                started_at=None,
            )
            wahoo = candidate(
                streams(
                    ProviderId.WAHOO,
                    RecordingOrigin.WAHOO,
                    {POWER: (250.0, 260.0, 270.0)},
                    time=time,
                ),
            )
            merged = merge_details([wahoo, primary])
            assert merged.streams is not None
            self.assertNotIn(POWER, merged.streams.channels)
        with self.subTest("identical axes without starts are placeable"):
            primary = candidate(
                streams(
                    ProviderId.GARMIN,
                    RecordingOrigin.GARMIN,
                    {HR: (140.0, 141.0, 142.0)},
                    time=time,
                ),
                started_at=None,
            )
            wahoo = candidate(
                streams(
                    ProviderId.WAHOO,
                    RecordingOrigin.WAHOO,
                    {POWER: (250.0, 260.0, 270.0)},
                    time=time,
                ),
                started_at=None,
            )
            merged = merge_details([wahoo, primary])
            assert merged.streams is not None
            self.assertEqual(
                merged.streams.channels[POWER].values, (250.0, 260.0, 270.0)
            )
            self.assertTrue(merged.streams.channels[POWER].aligned)

    def test_channel_all_none_after_alignment_is_skipped(self) -> None:
        primary = candidate(
            streams(
                ProviderId.GARMIN,
                RecordingOrigin.GARMIN,
                {HR: tuple(140.0 for _ in range(61))},
                time=tuple(float(index) for index in range(61)),
            ),
            device=DeviceType.WATCH,
        )
        # Starts 30 s before the primary; only its first 11 samples carry power,
        # which lie before the primary start, so no primary second gets a value.
        wahoo = candidate(
            streams(
                ProviderId.WAHOO,
                RecordingOrigin.WAHOO,
                {POWER: tuple(150.0 if index <= 10 else None for index in range(101))},
                time=tuple(float(index) for index in range(101)),
            ),
            started_at=STARTED - timedelta(seconds=30),
            device=DeviceType.BIKE_COMPUTER,
        )
        merged = merge_details([wahoo, primary])
        assert merged.streams is not None
        self.assertNotIn(POWER, merged.streams.channels)
        self.assertIn(HR, merged.streams.channels)


class LapAndZoneChoiceTests(unittest.TestCase):
    def test_laps_prefer_provider_intervals_then_device_laps_then_splits(self) -> None:
        intervals = candidate(
            laps(
                ProviderId.INTERVALS,
                RecordingOrigin.GARMIN,
                LapSource.PROVIDER_INTERVALS,
            )
        )
        garmin = candidate(
            laps(ProviderId.GARMIN, RecordingOrigin.GARMIN, LapSource.DEVICE_LAPS)
        )
        wahoo = candidate(
            laps(ProviderId.WAHOO, RecordingOrigin.WAHOO, LapSource.SPLITS)
        )
        merged = merge_details([wahoo, garmin, intervals])
        assert merged.laps is not None
        self.assertIs(merged.laps.chosen, intervals)
        self.assertEqual(len(merged.laps.alternatives), 2)
        self.assertIs(merged.laps.alternatives[0], garmin)
        self.assertIs(merged.laps.alternatives[1], wahoo)

    def test_own_copy_breaks_lap_source_ties(self) -> None:
        relay = candidate(
            laps(ProviderId.INTERVALS, RecordingOrigin.GARMIN, LapSource.DEVICE_LAPS)
        )
        own = candidate(
            laps(ProviderId.GARMIN, RecordingOrigin.GARMIN, LapSource.DEVICE_LAPS)
        )
        merged = merge_details([relay, own])
        assert merged.laps is not None
        self.assertIs(merged.laps.chosen, own)
        self.assertIs(merged.laps.alternatives[0], relay)

    def test_zones_rank_bounded_sets_per_metric(self) -> None:
        hr_relay = candidate(
            zones(
                ProviderId.INTERVALS,
                RecordingOrigin.GARMIN,
                ZoneMetric.HEART_RATE,
                ZoneBoundarySource.UNKNOWN,
                bounded=False,
            )
        )
        hr_reported = candidate(
            zones(
                ProviderId.GARMIN,
                RecordingOrigin.GARMIN,
                ZoneMetric.HEART_RATE,
                ZoneBoundarySource.PROVIDER_REPORTED,
                bounded=False,
            )
        )
        power_bounded = candidate(
            zones(
                ProviderId.WAHOO,
                RecordingOrigin.WAHOO,
                ZoneMetric.POWER,
                ZoneBoundarySource.UNKNOWN,
                bounded=True,
            )
        )
        power_unbounded = candidate(
            zones(
                ProviderId.INTERVALS,
                RecordingOrigin.GARMIN,
                ZoneMetric.POWER,
                ZoneBoundarySource.UNKNOWN,
                bounded=False,
            )
        )
        merged = merge_details([hr_relay, power_unbounded, hr_reported, power_bounded])
        heart = merged.zones[ZoneMetric.HEART_RATE]
        self.assertIs(heart.chosen, hr_reported)
        self.assertIs(heart.alternatives[0], hr_relay)
        power = merged.zones[ZoneMetric.POWER]
        self.assertIs(power.chosen, power_bounded)
        self.assertIs(power.alternatives[0], power_unbounded)

    def test_zone_tie_break_prefers_intervals_and_absent_metrics_are_omitted(
        self,
    ) -> None:
        relay = candidate(
            zones(
                ProviderId.INTERVALS,
                RecordingOrigin.GARMIN,
                ZoneMetric.HEART_RATE,
                ZoneBoundarySource.UNKNOWN,
                bounded=True,
            )
        )
        reported = candidate(
            zones(
                ProviderId.GARMIN,
                RecordingOrigin.GARMIN,
                ZoneMetric.HEART_RATE,
                ZoneBoundarySource.PROVIDER_REPORTED,
                bounded=True,
            )
        )
        merged = merge_details([reported, relay])
        self.assertIs(merged.zones[ZoneMetric.HEART_RATE].chosen, relay)
        self.assertNotIn(ZoneMetric.POWER, merged.zones)


class StreamAverageTests(unittest.TestCase):
    def test_average_excludes_non_moving_and_missing_moving_points(self) -> None:
        merged = merge_details(
            [
                candidate(
                    streams(
                        ProviderId.GARMIN,
                        RecordingOrigin.GARMIN,
                        {
                            POWER: (100.0, 0.0, None, 200.0, 300.0),
                            MOVING: (1.0, 1.0, 1.0, 0.0, None),
                        },
                    ),
                    device=DeviceType.WATCH,
                )
            ]
        )
        assert merged.streams is not None
        # Kept: 100 and 0 (zero counts). Dropped: a gap, a paused point, and a
        # point whose moving state is missing.
        self.assertEqual(stream_average(merged.streams, POWER), 50.0)

    def test_average_without_moving_counts_zeros_and_skips_gaps(self) -> None:
        merged = merge_details(
            [
                candidate(
                    streams(
                        ProviderId.GARMIN,
                        RecordingOrigin.GARMIN,
                        {POWER: (100.0, 0.0, None, 200.0, 300.0)},
                    ),
                    device=DeviceType.WATCH,
                )
            ]
        )
        assert merged.streams is not None
        self.assertEqual(stream_average(merged.streams, POWER), 150.0)
        self.assertIsNone(stream_average(merged.streams, HR))

    def test_average_is_none_without_values_and_rejects_time_and_moving(self) -> None:
        merged = merge_details(
            [
                candidate(
                    streams(
                        ProviderId.GARMIN,
                        RecordingOrigin.GARMIN,
                        {
                            POWER: (5.0, 6.0, 7.0, 8.0, 9.0),
                            MOVING: (0.0, 0.0, 0.0, 0.0, 0.0),
                        },
                    ),
                    device=DeviceType.WATCH,
                )
            ]
        )
        assert merged.streams is not None
        self.assertIsNone(stream_average(merged.streams, POWER))
        with self.assertRaises(ValueError):
            stream_average(merged.streams, StreamChannel.TIME_S)
        with self.assertRaises(ValueError):
            stream_average(merged.streams, MOVING)


class MergeContractTests(unittest.TestCase):
    def test_candidates_may_be_a_single_pass_iterator(self) -> None:
        stream_set = candidate(
            streams(ProviderId.GARMIN, RecordingOrigin.GARMIN, {HR: (140.0,) * 5})
        )
        lap_set = candidate(
            laps(ProviderId.GARMIN, RecordingOrigin.GARMIN, LapSource.DEVICE_LAPS)
        )
        zone_set = candidate(
            zones(
                ProviderId.GARMIN,
                RecordingOrigin.GARMIN,
                ZoneMetric.HEART_RATE,
                ZoneBoundarySource.PROVIDER_REPORTED,
                bounded=True,
            )
        )
        merged = merge_details(item for item in (stream_set, lap_set, zone_set))
        assert merged.streams is not None
        assert merged.laps is not None
        self.assertIs(merged.streams.primary, stream_set)
        self.assertIs(merged.laps.chosen, lap_set)
        self.assertIs(merged.zones[ZoneMetric.HEART_RATE].chosen, zone_set)

    def test_empty_input_yields_no_detail(self) -> None:
        merged = merge_details([])
        self.assertEqual(merged, MergedDetail(None, None, {}))
        self.assertEqual(dict(merged.zones), {})

    def test_mixed_kinds_are_partitioned_and_inputs_are_not_mutated(self) -> None:
        primary = candidate(
            streams(
                ProviderId.GARMIN,
                RecordingOrigin.GARMIN,
                {HR: (140.0, 141.0, 142.0)},
                time=(0.0, 1.0, 2.0),
            ),
            device=DeviceType.WATCH,
        )
        wahoo = candidate(
            streams(
                ProviderId.WAHOO,
                RecordingOrigin.WAHOO,
                {POWER: (250.0, 260.0, 270.0)},
                time=(0.0, 1.0, 2.0),
            ),
            device=DeviceType.BIKE_COMPUTER,
        )
        lap_set = candidate(
            laps(ProviderId.GARMIN, RecordingOrigin.GARMIN, LapSource.DEVICE_LAPS)
        )
        zone_set = candidate(
            zones(
                ProviderId.GARMIN,
                RecordingOrigin.GARMIN,
                ZoneMetric.HEART_RATE,
                ZoneBoundarySource.PROVIDER_REPORTED,
                bounded=True,
            )
        )
        candidates = [wahoo, lap_set, primary, zone_set]
        before = [
            (item.stored, item.started_at, item.device_type) for item in candidates
        ]
        channels_before = {
            id(item): dict(item.stored.detail.channels)
            for item in candidates
            if isinstance(item.stored.detail, ActivityStreamSet)
        }

        merged = merge_details(candidates)

        assert merged.streams is not None
        self.assertIs(merged.streams.primary, primary)
        self.assertIsNotNone(merged.laps)
        self.assertIn(ZoneMetric.HEART_RATE, merged.zones)
        self.assertNotIn(StreamChannel.TIME_S, merged.streams.channels)
        self.assertEqual(
            before,
            [(item.stored, item.started_at, item.device_type) for item in candidates],
        )
        for item in candidates:
            if isinstance(item.stored.detail, ActivityStreamSet):
                self.assertEqual(
                    dict(item.stored.detail.channels), channels_before[id(item)]
                )


if __name__ == "__main__":
    unittest.main()
