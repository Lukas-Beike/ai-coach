"""``activity_detail.v1`` contract: metric priority, sources, streams, laps and zones."""

import json
import unittest
from datetime import UTC, datetime, timedelta
from typing import Any

from backend.activities.detail_contract import (
    ACTIVITY_DETAIL_CONTRACT,
    activity_detail_contract,
    measured_order,
)
from backend.activities.detail_merge import (
    DetailCandidate,
    merge_details,
)
from backend.canonical.activity_detail import (
    LAP_METRIC_FIELDS,
    ActivityDetailSet,
    ActivityLap,
    ActivityLapSet,
    ActivityStreamSet,
    ZoneBucket,
    ZoneDistribution,
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
    ZoneBoundarySource,
    ZoneMetric,
)
from backend.db.activity_detail_store import StoredDetailSet

RETRIEVED = datetime(2026, 10, 19, 8, 0, tzinfo=UTC)
STARTED = datetime(2026, 10, 19, 7, 0, tzinfo=UTC)
FETCHED = "2026-10-19T08:00:00+00:00"
TIME = tuple(float(second) for second in range(2701))
HR = StreamChannel.HEART_RATE_BPM
POWER = StreamChannel.POWER_W
REFRESHABLE = frozenset({ProviderId.INTERVALS})
INTERVALS = ProviderId.INTERVALS
GARMIN = ProviderId.GARMIN
WAHOO = ProviderId.WAHOO


def record(
    provider: ProviderId,
    provider_activity_id: str,
    *,
    recorded_by: RecordingOrigin = RecordingOrigin.WAHOO,
    label: str | None = None,
    **fields: Any,
) -> ActivityRecord:
    values: dict[str, Any] = {
        "distance_m": None,
        "load": None,
        "load_model": LoadModel.UNKNOWN,
        "avg_hr": None,
        "avg_power": None,
        "name": "Synthetic ride",
        "duration_s": 2700.0,
    }
    values.update(fields)
    return ActivityRecord(
        activity_id=provider_activity_id,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=None,
            recorded_by=recorded_by,
            retrieved_at=RETRIEVED,
            label=label,
        ),
        sport=Sport.RIDE,
        environment=Environment.OUTDOOR,
        started_at=STARTED,
        **values,
    )


def provenance(
    provider: ProviderId, recorded_by: RecordingOrigin, label: str | None
) -> Provenance:
    return Provenance(
        provider=provider,
        source_kind=SourceKind.PROVIDER_REPORTED,
        source_record_id=None,
        recorded_by=recorded_by,
        retrieved_at=RETRIEVED,
        label=label,
    )


def stream_set(
    provider: ProviderId,
    provider_activity_id: str,
    channels: dict[StreamChannel, tuple[float | None, ...]],
    *,
    recorded_by: RecordingOrigin = RecordingOrigin.WAHOO,
    label: str | None = None,
) -> ActivityStreamSet:
    return ActivityStreamSet(
        provider_activity_id=provider_activity_id,
        provenance=provenance(provider, recorded_by, label),
        origin=ActivityDetailOrigin.FETCH,
        resolution=StreamResolution.FULL,
        channels={StreamChannel.TIME_S: TIME, **channels},
    )


def lap_set(
    provider: ProviderId,
    provider_activity_id: str,
    lap_source: LapSource,
    count: int,
    *,
    recorded_by: RecordingOrigin = RecordingOrigin.WAHOO,
    label: str | None = None,
) -> ActivityLapSet:
    return ActivityLapSet(
        provider_activity_id=provider_activity_id,
        provenance=provenance(provider, recorded_by, label),
        origin=ActivityDetailOrigin.FETCH,
        lap_source=lap_source,
        laps=tuple(
            ActivityLap(
                index=index,
                kind=LapKind.LAP,
                start_offset_s=index * 600.0,
                end_offset_s=(index + 1) * 600.0,
            )
            for index in range(count)
        ),
    )


def zone_set(
    provider: ProviderId,
    provider_activity_id: str,
    *,
    bounded: bool,
    recorded_by: RecordingOrigin = RecordingOrigin.WAHOO,
    label: str | None = None,
) -> ZoneDistribution:
    lower, upper = (100.0, 140.0) if bounded else (None, None)
    return ZoneDistribution(
        provider_activity_id=provider_activity_id,
        provenance=provenance(provider, recorded_by, label),
        origin=ActivityDetailOrigin.FETCH,
        metric=ZoneMetric.HEART_RATE,
        boundary_source=(
            ZoneBoundarySource.PROVIDER_REPORTED
            if bounded
            else ZoneBoundarySource.UNKNOWN
        ),
        buckets=(
            ZoneBucket(index=1, seconds=600.0, lower=lower, upper=upper, label="Z1"),
            ZoneBucket(index=2, seconds=300.0, lower=lower, upper=upper, label="Z2"),
        ),
    )


def candidate(
    detail: ActivityDetailSet,
    *,
    fetched: str = FETCHED,
    started_at: datetime | None = STARTED,
) -> DetailCandidate:
    provider = detail.provenance.provider
    assert provider is not None
    return DetailCandidate(
        stored=StoredDetailSet(
            provider=provider.value,
            provider_activity_id=detail.provider_activity_id,
            activity_id="act_1",
            mapper_version=1,
            summary_sha256=None,
            fetched_at=fetched,
            detail=detail,
        ),
        started_at=started_at,
        device_type=None,
    )


def build(
    records: list[ActivityRecord],
    candidates: list[DetailCandidate] | tuple[()] = (),
    *,
    analysis: dict[str, Any] | None = None,
    refreshable: frozenset[ProviderId] = REFRESHABLE,
) -> dict[str, Any]:
    return activity_detail_contract(
        "act_1",
        records,
        merge_details(candidates),
        [item.stored for item in candidates],
        analysis=analysis,
        refreshable=refreshable,
    )


def heart_rate_values(offset: int = 0) -> tuple[float, ...]:
    return tuple(float(100 + (index + offset) % 50) for index in range(len(TIME)))


class DocumentShapeTests(unittest.TestCase):
    def test_document_has_the_contract_sections(self) -> None:
        doc = build([record(INTERVALS, "i-ride-99", label="Intervals.icu")])

        self.assertEqual(ACTIVITY_DETAIL_CONTRACT, doc["contract"])
        self.assertEqual("activity_detail.v1", doc["contract"])
        self.assertEqual(
            {
                "contract",
                "session",
                "metrics",
                "streams",
                "laps",
                "zones",
                "analysis",
                "detail_data",
            },
            set(doc),
        )
        self.assertEqual(
            {
                "activity_id": "act_1",
                "sport": "ride",
                "environment": "outdoor",
                "started_at": STARTED.isoformat(),
                "name": "Synthetic ride",
                "device_type": None,
            },
            doc["session"],
        )

    def test_records_are_required(self) -> None:
        with self.assertRaises(ValueError):
            build([])

    def test_analysis_is_passed_through_unchanged(self) -> None:
        analysis = {"aerobic": {"status": "ok"}}

        self.assertEqual(
            analysis,
            build([record(INTERVALS, "i-ride-99")], analysis=analysis)["analysis"],
        )
        self.assertIsNone(build([record(INTERVALS, "i-ride-99")])["analysis"])

    def test_document_serialises_strictly_and_leaks_no_provider_identifiers(
        self,
    ) -> None:
        records = [
            record(INTERVALS, "i-ride-99", label="Intervals.icu", avg_hr=120.0),
            record(WAHOO, "w-ride-99", label="Wahoo", avg_power=200.0),
        ]
        doc = build(
            records,
            [
                candidate(
                    stream_set(
                        INTERVALS,
                        "i-ride-99",
                        {HR: heart_rate_values(), POWER: (200.0,) * len(TIME)},
                        label="Intervals.icu",
                    )
                ),
                candidate(lap_set(WAHOO, "w-ride-99", LapSource.DEVICE_LAPS, 2)),
            ],
        )

        text = json.dumps(doc, allow_nan=False)

        for leaked in (
            "i-ride-99",
            "w-ride-99",
            "icu_",
            "velocity_smooth",
            "source_record_id",
        ):
            self.assertNotIn(leaked, text)


class MetricTests(unittest.TestCase):
    def test_recorders_own_copy_provides_the_measured_value_and_others_are_alternatives(
        self,
    ) -> None:
        intervals = record(INTERVALS, "i-ride-99", label="Intervals.icu", avg_hr=120.0)
        wahoo = record(WAHOO, "w-ride-99", label="Wahoo", avg_hr=130.0)

        metric = build([intervals, wahoo])["metrics"]["avg_hr"]

        self.assertEqual(130.0, metric["value"])
        self.assertEqual("bpm", metric["unit"])
        self.assertEqual(
            {"provider": "wahoo", "label": "Wahoo", "kind": "measured"},
            metric["source"],
        )
        self.assertEqual(
            [
                {
                    "value": 120.0,
                    "source": {
                        "provider": "intervals",
                        "label": "Intervals.icu",
                        "kind": "measured",
                    },
                }
            ],
            metric["alternatives"],
        )

    def test_measured_order_puts_the_recorders_own_copy_first(self) -> None:
        intervals = record(INTERVALS, "i-ride-99")
        wahoo = record(WAHOO, "w-ride-99")

        self.assertEqual(
            ["w-ride-99", "i-ride-99"],
            [item.activity_id for item in measured_order([intervals, wahoo])],
        )

    def test_absent_measured_values_are_omitted(self) -> None:
        metrics = build([record(INTERVALS, "i-ride-99")])["metrics"]

        self.assertIn("duration_s", metrics)
        self.assertNotIn("avg_hr", metrics)
        self.assertNotIn("max_power_w", metrics)
        self.assertNotIn("distance_m", metrics)

    def test_missing_average_is_filled_from_the_stream_mean_and_labelled_derived(
        self,
    ) -> None:
        values = heart_rate_values()
        doc = build(
            [record(INTERVALS, "i-ride-99", label="Intervals.icu")],
            [
                candidate(
                    stream_set(
                        INTERVALS, "i-ride-99", {HR: values}, label="Intervals.icu"
                    )
                )
            ],
        )

        metric = doc["metrics"]["avg_hr"]

        self.assertAlmostEqual(sum(values) / len(values), metric["value"])
        self.assertEqual("bpm", metric["unit"])
        self.assertEqual(
            {"provider": "intervals", "label": "Intervals.icu", "kind": "derived"},
            metric["source"],
        )
        self.assertEqual([], metric["alternatives"])

    def test_derived_metrics_name_their_source_and_load_model(self) -> None:
        doc = build(
            [
                record(
                    INTERVALS,
                    "i-ride-99",
                    label="Intervals.icu",
                    load=85.0,
                    load_model=LoadModel.INTERVALS_TRAINING_LOAD,
                    normalized_power=210.0,
                )
            ]
        )

        self.assertEqual(
            {
                "value": 85.0,
                "unit": None,
                "source": {
                    "provider": "intervals",
                    "label": "Intervals.icu",
                    "kind": "derived",
                },
                "alternatives": [],
                "model": "intervals_training_load",
            },
            doc["metrics"]["load"],
        )
        normalized = doc["metrics"]["normalized_power"]
        self.assertEqual(210.0, normalized["value"])
        self.assertEqual("W", normalized["unit"])
        self.assertEqual("derived", normalized["source"]["kind"])

    def test_load_is_omitted_without_a_value(self) -> None:
        self.assertNotIn("load", build([record(INTERVALS, "i-ride-99")])["metrics"])


class StreamTests(unittest.TestCase):
    def test_streams_are_downsampled_with_aligned_equal_length_channels(self) -> None:
        doc = build(
            [record(INTERVALS, "i-ride-99", label="Intervals.icu")],
            [
                candidate(
                    stream_set(
                        INTERVALS,
                        "i-ride-99",
                        {HR: heart_rate_values(), POWER: (200.0,) * len(TIME)},
                        label="Intervals.icu",
                    )
                )
            ],
        )

        streams = doc["streams"]
        time_s = streams["time_s"]
        self.assertLessEqual(len(time_s), 2000)
        self.assertEqual(0.0, time_s[0])
        self.assertEqual(2700.0, time_s[-1])
        self.assertEqual({HR.value, POWER.value}, set(streams["channels"]))
        for channel in streams["channels"].values():
            self.assertEqual(len(time_s), len(channel["values"]))
            # Only channels shifted in from another provider's clock are "aligned".
            self.assertFalse(channel["aligned"])
            self.assertEqual("measured", channel["source"]["kind"])
            self.assertEqual("intervals", channel["source"]["provider"])

    def test_streams_are_absent_without_stream_sets(self) -> None:
        self.assertIsNone(build([record(INTERVALS, "i-ride-99")])["streams"])


class LapAndZoneTests(unittest.TestCase):
    def lap_offsets(self, started_at: datetime | None) -> dict[str, Any]:
        """Intervals streams with one-lap Garmin laps recorded from ``started_at``."""
        doc = build(
            [
                record(INTERVALS, "i-ride-99", label="Intervals.icu"),
                record(GARMIN, "g-ride-99", recorded_by=RecordingOrigin.GARMIN),
            ],
            [
                candidate(
                    stream_set(INTERVALS, "i-ride-99", {HR: heart_rate_values()})
                ),
                candidate(
                    lap_set(
                        GARMIN,
                        "g-ride-99",
                        LapSource.DEVICE_LAPS,
                        1,
                        recorded_by=RecordingOrigin.GARMIN,
                    ),
                    started_at=started_at,
                ),
            ],
        )
        laps: dict[str, Any] = doc["laps"]
        return laps

    def test_laps_of_another_recording_move_to_the_stream_clock(self) -> None:
        laps = self.lap_offsets(STARTED + timedelta(seconds=30))
        self.assertTrue(laps["on_stream_clock"])
        first = laps["laps"][0]
        self.assertEqual(
            (30.0, 630.0), (first["start_offset_s"], first["end_offset_s"])
        )

    def test_unalignable_laps_keep_their_own_clock(self) -> None:
        laps = self.lap_offsets(None)
        self.assertFalse(laps["on_stream_clock"])
        first = laps["laps"][0]
        self.assertEqual((0.0, 600.0), (first["start_offset_s"], first["end_offset_s"]))

    def test_laps_use_the_preferred_source_and_list_the_others(self) -> None:
        doc = build(
            [
                record(INTERVALS, "i-ride-99", label="Intervals.icu"),
                record(
                    GARMIN,
                    "g-ride-99",
                    recorded_by=RecordingOrigin.GARMIN,
                    label="Garmin",
                ),
            ],
            [
                candidate(
                    lap_set(
                        INTERVALS,
                        "i-ride-99",
                        LapSource.PROVIDER_INTERVALS,
                        3,
                        label="Intervals.icu",
                    )
                ),
                candidate(
                    lap_set(
                        GARMIN,
                        "g-ride-99",
                        LapSource.DEVICE_LAPS,
                        5,
                        recorded_by=RecordingOrigin.GARMIN,
                        label="Garmin",
                    )
                ),
            ],
        )

        laps = doc["laps"]
        self.assertFalse(laps["on_stream_clock"])
        self.assertEqual("provider_intervals", laps["lap_source"])
        self.assertEqual("intervals", laps["source"]["provider"])
        self.assertEqual(3, len(laps["laps"]))
        first = laps["laps"][0]
        self.assertEqual(
            {"index", "kind", "start_offset_s", "end_offset_s", "name"}
            | set(LAP_METRIC_FIELDS),
            set(first),
        )
        self.assertEqual(
            ("lap", 0.0, 600.0),
            (first["kind"], first["start_offset_s"], first["end_offset_s"]),
        )
        self.assertEqual(
            [
                {
                    "lap_source": "device_laps",
                    "source": {
                        "provider": "garmin",
                        "label": "Garmin",
                        "kind": "measured",
                    },
                    "count": 5,
                }
            ],
            laps["alternatives"],
        )

    def test_zones_name_their_boundary_source_and_list_the_others(self) -> None:
        doc = build(
            [
                record(INTERVALS, "i-ride-99", label="Intervals.icu"),
                record(
                    GARMIN,
                    "g-ride-99",
                    recorded_by=RecordingOrigin.GARMIN,
                    label="Garmin",
                ),
            ],
            [
                candidate(
                    zone_set(
                        INTERVALS, "i-ride-99", bounded=True, label="Intervals.icu"
                    )
                ),
                candidate(
                    zone_set(
                        GARMIN,
                        "g-ride-99",
                        bounded=False,
                        recorded_by=RecordingOrigin.GARMIN,
                        label="Garmin",
                    )
                ),
            ],
        )

        zone = doc["zones"]["heart_rate"]
        self.assertEqual("provider_reported", zone["boundary_source"])
        self.assertEqual("intervals", zone["source"]["provider"])
        self.assertEqual(
            {
                "index": 1,
                "seconds": 600.0,
                "lower": 100.0,
                "upper": 140.0,
                "label": "Z1",
            },
            zone["buckets"][0],
        )
        self.assertEqual(
            [{"provider": "garmin", "label": "Garmin", "kind": "measured"}],
            zone["alternatives"],
        )


class ProviderTests(unittest.TestCase):
    def test_every_provider_is_listed_in_rank_order_with_its_sets(self) -> None:
        doc = build(
            [
                record(WAHOO, "w-ride-99", label="Wahoo"),
                record(INTERVALS, "i-ride-99", label="Intervals.icu"),
            ],
            [
                candidate(
                    stream_set(
                        INTERVALS,
                        "i-ride-99",
                        {HR: heart_rate_values()},
                        label="Intervals.icu",
                    )
                )
            ],
        )

        self.assertEqual(
            [
                {
                    "provider": "intervals",
                    "label": "Intervals.icu",
                    "kinds": ["streams"],
                    "fetched_at": FETCHED,
                    "refreshable": True,
                },
                {
                    "provider": "wahoo",
                    "label": "Wahoo",
                    "kinds": [],
                    "fetched_at": None,
                    "refreshable": False,
                },
            ],
            doc["detail_data"]["providers"],
        )

    def test_newest_aware_fetch_time_wins_and_naive_times_are_ignored(self) -> None:
        doc = build(
            [record(INTERVALS, "i-ride-99", label="Intervals.icu")],
            [
                candidate(
                    stream_set(INTERVALS, "i-ride-99", {HR: heart_rate_values()}),
                    fetched="2026-10-19T08:00:00+00:00",
                ),
                candidate(
                    lap_set(INTERVALS, "i-ride-99", LapSource.PROVIDER_INTERVALS, 2),
                    fetched="2026-10-19T10:00:00+00:00",
                ),
                candidate(
                    zone_set(INTERVALS, "i-ride-99", bounded=True),
                    fetched="2026-10-20T00:00:00",
                ),
            ],
        )

        provider = doc["detail_data"]["providers"][0]
        self.assertEqual("2026-10-19T10:00:00+00:00", provider["fetched_at"])
        self.assertEqual(["heart_rate_zones", "laps", "streams"], provider["kinds"])

    def test_refreshable_flag_follows_the_refreshable_providers(self) -> None:
        doc = build(
            [record(INTERVALS, "i-ride-99"), record(WAHOO, "w-ride-99")],
            refreshable=frozenset({WAHOO}),
        )

        flags = {
            item["provider"]: item["refreshable"]
            for item in doc["detail_data"]["providers"]
        }
        self.assertEqual({"intervals": False, "wahoo": True}, flags)


if __name__ == "__main__":
    unittest.main()
