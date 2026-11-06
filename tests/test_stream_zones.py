"""Time in zone derived from a session's streams with the athlete's zones (#1724)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime

from backend.activities.detail_contract import activity_detail_contract
from backend.activities.detail_merge import DetailCandidate, merge_details
from backend.activities.stream_zones import with_stream_zones
from backend.activities.zone_settings import ZoneSettings
from backend.canonical.activity_detail import (
    ActivityStreamSet,
    ZoneBucket,
    ZoneDistribution,
)
from backend.canonical.records import ActivityRecord, Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    Environment,
    LoadModel,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
    StreamChannel,
    StreamResolution,
    ZoneBoundarySource,
    ZoneMetric,
)
from backend.db.activity_detail_store import StoredDetailSet

STARTED = datetime(2026, 11, 3, 10, 0, tzinfo=UTC)
PROVENANCE = Provenance(
    provider=ProviderId.GARMIN,
    source_kind=SourceKind.PROVIDER_REPORTED,
    source_record_id="g1",
    recorded_by=RecordingOrigin.GARMIN,
    retrieved_at=STARTED,
    label="Garmin Connect",
)
# LTHR 160 bpm with the default limits: Z1 <= 108.8, Z2 <= 132.8, Z3 <= 150.4,
# Z4 <= 168, Z5 <= 192, Z6 <= 240, Z7 above.
SETTINGS = ZoneSettings(lthr=160.0, ftp=250.0)


def _with(settings: ZoneSettings):
    return lambda: settings


def _candidate(detail: ActivityStreamSet | ZoneDistribution) -> DetailCandidate:
    return DetailCandidate(
        stored=StoredDetailSet(
            provider="garmin",
            provider_activity_id="g1",
            activity_id="act_1",
            mapper_version=3,
            summary_sha256=None,
            fetched_at=STARTED.isoformat(),
            detail=detail,
        ),
        started_at=STARTED,
        device_type=None,
    )


def _streams(
    time_s: tuple[float, ...], **channels: tuple[float | None, ...]
) -> DetailCandidate:
    return _candidate(
        ActivityStreamSet(
            provider_activity_id="g1",
            provenance=PROVENANCE,
            origin=ActivityDetailOrigin.FETCH,
            resolution=StreamResolution.FULL,
            channels={
                StreamChannel.TIME_S: time_s,
                **{StreamChannel(key): values for key, values in channels.items()},
            },
        )
    )


def _seconds(zones: ZoneDistribution) -> list[float]:
    return [bucket.seconds for bucket in zones.buckets]


def _zones(merged: object, metric: ZoneMetric) -> ZoneDistribution:
    detail = merged.zones[metric].chosen.stored.detail  # type: ignore[attr-defined]
    assert isinstance(detail, ZoneDistribution)
    return detail


SECONDS = tuple(float(second) for second in range(11))
HEART_RATE = (100.0,) * 4 + (140.0,) * 4 + (170.0,) * 2 + (170.0,)


class StreamZoneTests(unittest.TestCase):
    def test_heart_rate_seconds_follow_the_local_zones(self) -> None:
        merged = with_stream_zones(
            merge_details([_streams(SECONDS, heart_rate_bpm=HEART_RATE)]),
            _with(SETTINGS),
        )

        zones = _zones(merged, ZoneMetric.HEART_RATE)
        # Each sample counts the second until the next one; the last counts nothing.
        self.assertEqual([4.0, 0.0, 4.0, 0.0, 2.0, 0.0, 0.0], _seconds(zones))
        self.assertIs(ZoneBoundarySource.PROFILE, zones.boundary_source)
        self.assertIs(SourceKind.DERIVED, zones.provenance.source_kind)
        self.assertEqual(
            (None, 108.8), (zones.buckets[0].lower, zones.buckets[0].upper)
        )
        self.assertEqual(
            (240.0, None), (zones.buckets[6].lower, zones.buckets[6].upper)
        )

    def test_power_uses_the_ftp(self) -> None:
        merged = with_stream_zones(
            merge_details([_streams((0.0, 1.0, 2.0), power_w=(200.0, 300.0, 0.0))]),
            _with(SETTINGS),
        )

        # 200 W = 80 % FTP (Z3), 300 W = 120 % (Z5).
        self.assertEqual(
            [0.0, 0.0, 1.0, 0.0, 1.0, 0.0, 0.0],
            _seconds(_zones(merged, ZoneMetric.POWER)),
        )

    def test_coasting_counts_in_the_lowest_power_zone(self) -> None:
        merged = with_stream_zones(
            merge_details(
                [_streams((0.0, 1.0, 2.0, 3.0), power_w=(0.0, 0.0, 200.0, 0.0))]
            ),
            _with(SETTINGS),
        )

        self.assertEqual(
            [2.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0],
            _seconds(_zones(merged, ZoneMetric.POWER)),
        )

    def test_a_high_threshold_leaves_bounds_beyond_the_range_open(self) -> None:
        # LTHR 175: 150 % is 262.5 bpm, above the 250 bpm boundary range.
        merged = with_stream_zones(
            merge_details([_streams(SECONDS, heart_rate_bpm=HEART_RATE)]),
            _with(ZoneSettings(lthr=175.0)),
        )

        buckets = _zones(merged, ZoneMetric.HEART_RATE).buckets
        self.assertEqual((210.0, None), (buckets[5].lower, buckets[5].upper))
        self.assertEqual((None, None), (buckets[6].lower, buckets[6].upper))

    def test_settings_are_not_read_without_a_stream_to_derive(self) -> None:
        def unexpected() -> ZoneSettings:
            raise AssertionError("settings read")

        merged = merge_details([_streams(SECONDS, cadence_rpm=(80.0,) * 11)])

        self.assertIs(merged, with_stream_zones(merged, unexpected))

    def test_a_pause_counts_nothing(self) -> None:
        merged = with_stream_zones(
            merge_details(
                [
                    _streams(
                        (0.0, 1.0, 2.0, 3.0, 300.0, 301.0),
                        heart_rate_bpm=(100.0, 100.0, 100.0, 100.0, 100.0, 100.0),
                    )
                ]
            ),
            _with(SETTINGS),
        )

        self.assertEqual(4.0, sum(_seconds(_zones(merged, ZoneMetric.HEART_RATE))))

    def test_a_provider_distribution_is_kept(self) -> None:
        provider = ZoneDistribution(
            provider_activity_id="g1",
            provenance=PROVENANCE,
            origin=ActivityDetailOrigin.FETCH,
            metric=ZoneMetric.HEART_RATE,
            boundary_source=ZoneBoundarySource.PROVIDER_REPORTED,
            buckets=(ZoneBucket(index=1, seconds=10.0),),
        )

        merged = with_stream_zones(
            merge_details(
                [_streams(SECONDS, heart_rate_bpm=HEART_RATE), _candidate(provider)]
            ),
            _with(SETTINGS),
        )

        self.assertIs(provider, _zones(merged, ZoneMetric.HEART_RATE))

    def test_no_threshold_or_no_stream_gives_no_distribution(self) -> None:
        merged = merge_details([_streams(SECONDS, heart_rate_bpm=HEART_RATE)])

        self.assertEqual(
            {}, dict(with_stream_zones(merged, _with(ZoneSettings())).zones)
        )
        self.assertNotIn(
            ZoneMetric.POWER, with_stream_zones(merged, _with(SETTINGS)).zones
        )

    def test_the_document_labels_the_zones_as_derived(self) -> None:
        record = ActivityRecord(
            activity_id="g1",
            provenance=PROVENANCE,
            sport=Sport.RUN,
            environment=Environment.OUTDOOR,
            started_at=STARTED,
            duration_s=10.0,
            distance_m=None,
            load=None,
            load_model=LoadModel.UNKNOWN,
            avg_hr=None,
            avg_power=None,
            name=None,
        )
        merged = with_stream_zones(
            merge_details([_streams(SECONDS, heart_rate_bpm=HEART_RATE)]),
            _with(SETTINGS),
        )

        doc = activity_detail_contract(
            "act_1", [record], merged, [], analysis=None, refreshable=frozenset()
        )

        source = doc["zones"]["heart_rate"]["source"]
        self.assertEqual(
            ("derived", "Zoneneinstellungen"), (source["kind"], source["label"])
        )
        self.assertEqual("profile", doc["zones"]["heart_rate"]["boundary_source"])


if __name__ == "__main__":
    unittest.main()
