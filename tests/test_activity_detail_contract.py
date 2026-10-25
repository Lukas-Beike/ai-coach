"""``activity_detail.v1`` contract: metric priority, sources, streams, laps and zones."""

import json
import unittest
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from backend.activities.detail_contract import (
    ACTIVITY_DETAIL_CONTRACT,
    ProviderStatus,
    activity_detail_contract,
    measured_order,
)
from backend.activities.detail_merge import (
    DetailCandidate,
    merge_details,
)
from backend.activities.detail_summary_metrics import intervals_summary_metrics
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
    **extras: Any,
) -> dict[str, Any]:
    return activity_detail_contract(
        "act_1",
        records,
        merge_details(candidates),
        [item.stored for item in candidates],
        analysis=analysis,
        refreshable=refreshable,
        **extras,
    )


def _sources(value: Any) -> Any:
    """Yield every ``source`` object of a document, at any depth."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key == "source" and isinstance(item, dict):
                yield item
            else:
                yield from _sources(item)
    elif isinstance(value, list):
        for item in value:
            yield from _sources(item)


def heart_rate_values(offset: int = 0) -> tuple[float, ...]:
    return tuple(float(100 + (index + offset) % 50) for index in range(len(TIME)))


class DocumentShapeTests(unittest.TestCase):
    def test_session_local_start_is_the_athlete_wall_time(self) -> None:
        doc = build(
            [record(INTERVALS, "i-ride-99", label="Intervals.icu")],
            zone=ZoneInfo("Europe/Berlin"),
        )

        self.assertEqual("2026-10-19T07:00:00+00:00", doc["session"]["started_at"])
        self.assertEqual("2026-10-19T09:00:00", doc["session"]["started_at_local"])

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
                "started_at_local": "2026-10-19T07:00:00",
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
            {
                "provider": "wahoo",
                "label": "Wahoo",
                "kind": "measured",
                "recorded_by": "wahoo",
            },
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
                        "recorded_by": "wahoo",
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

    def test_every_source_names_the_recorder_and_unknown_is_explicit(self) -> None:
        intervals = record(
            INTERVALS,
            "i-ride-99",
            recorded_by=RecordingOrigin.UNKNOWN,
            label="Intervals.icu",
            avg_hr=120.0,
            load=85.0,
            load_model=LoadModel.INTERVALS_TRAINING_LOAD,
        )
        garmin = record(
            GARMIN,
            "g-ride-99",
            recorded_by=RecordingOrigin.GARMIN,
            label="Garmin",
            avg_hr=130.0,
        )
        doc = build(
            [intervals, garmin],
            [
                candidate(
                    stream_set(
                        INTERVALS,
                        "i-ride-99",
                        {HR: heart_rate_values()},
                        recorded_by=RecordingOrigin.UNKNOWN,
                        label="Intervals.icu",
                    )
                ),
                candidate(
                    zone_set(
                        GARMIN,
                        "g-ride-99",
                        bounded=True,
                        recorded_by=RecordingOrigin.GARMIN,
                        label="Garmin",
                    )
                ),
            ],
            summary_metrics=intervals_summary_metrics(
                {"average_speed": 8.5}, recorded_by=RecordingOrigin.UNKNOWN
            ),
        )

        sources = list(_sources(doc))
        self.assertGreater(len(sources), 5)
        for source in sources:
            self.assertEqual({"provider", "label", "kind", "recorded_by"}, set(source))
        self.assertEqual("garmin", doc["metrics"]["avg_hr"]["source"]["recorded_by"])
        self.assertEqual(
            "unknown",
            doc["metrics"]["avg_hr"]["alternatives"][0]["source"]["recorded_by"],
        )
        self.assertEqual("unknown", doc["metrics"]["load"]["source"]["recorded_by"])
        self.assertEqual(
            "unknown", doc["metrics"]["avg_speed_mps"]["source"]["recorded_by"]
        )
        self.assertEqual("unknown", doc["streams"]["source"]["recorded_by"])
        self.assertEqual("garmin", doc["zones"]["heart_rate"]["source"]["recorded_by"])

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
            {
                "provider": "intervals",
                "label": "Intervals.icu",
                "kind": "derived",
                "recorded_by": "wahoo",
            },
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
                    "recorded_by": "wahoo",
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
                        "recorded_by": "garmin",
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
            [
                {
                    "provider": "garmin",
                    "label": "Garmin",
                    "kind": "measured",
                    "recorded_by": "garmin",
                }
            ],
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


class StatusTests(unittest.TestCase):
    def test_status_adds_stale_load_error_and_coverage_per_provider(self) -> None:
        values: list[float | None] = list(heart_rate_values())
        values[3] = None
        error = {"message": "boom", "observed_at": FETCHED}
        doc = build(
            [record(INTERVALS, "i-ride-99"), record(WAHOO, "w-ride-99")],
            [
                candidate(
                    stream_set(
                        INTERVALS, "i-ride-99", {HR: tuple(values)}, label="Intervals"
                    )
                )
            ],
            status={INTERVALS: ProviderStatus(stale=True, load_error=error)},
        )

        intervals, wahoo = doc["detail_data"]["providers"]
        self.assertTrue(intervals["stale"])
        self.assertEqual(error, intervals["load_error"])
        self.assertEqual(
            {HR.value: {"points": 2701, "valid_points": 2700}}, intervals["coverage"]
        )
        self.assertEqual(
            (False, None, {}),
            (wahoo["stale"], wahoo["load_error"], wahoo["coverage"]),
        )

    def test_provider_entries_are_unchanged_without_status(self) -> None:
        doc = build([record(INTERVALS, "i-ride-99")])

        self.assertNotIn("stale", doc["detail_data"]["providers"][0])

    def test_display_sampled_follows_the_downsampling_cap(self) -> None:
        records = [record(INTERVALS, "i-ride-99")]
        long_set = candidate(
            stream_set(INTERVALS, "i-ride-99", {HR: heart_rate_values()})
        )
        short = tuple(float(i) for i in range(2000))
        short_set = candidate(
            ActivityStreamSet(
                provider_activity_id="i-ride-99",
                provenance=provenance(INTERVALS, RecordingOrigin.WAHOO, None),
                origin=ActivityDetailOrigin.FETCH,
                resolution=StreamResolution.FULL,
                channels={StreamChannel.TIME_S: short, HR: (100.0,) * len(short)},
            )
        )

        self.assertTrue(build(records, [long_set])["detail_data"]["display_sampled"])
        self.assertFalse(build(records, [short_set])["detail_data"]["display_sampled"])
        self.assertFalse(build(records)["detail_data"]["display_sampled"])


class EnvelopeTests(unittest.TestCase):
    def test_envelope_blocks_become_top_level_keys(self) -> None:
        envelope = {
            "activity_feedback": {"rpe": 6},
            "equipment": [{"id": "bike"}],
            "activity_validation": {"status": "ok"},
            "ignored": 1,
        }

        doc = build([record(INTERVALS, "i-ride-99")], envelope=envelope)

        self.assertEqual(envelope["activity_feedback"], doc["activity_feedback"])
        self.assertEqual(envelope["equipment"], doc["equipment"])
        self.assertEqual(envelope["activity_validation"], doc["activity_validation"])
        self.assertNotIn("ignored", doc)

    def test_missing_envelope_blocks_are_none_and_absent_envelope_adds_nothing(
        self,
    ) -> None:
        doc = build([record(INTERVALS, "i-ride-99")], envelope={})

        self.assertEqual(
            (None, None, None),
            (doc["activity_feedback"], doc["equipment"], doc["activity_validation"]),
        )
        self.assertNotIn("activity_feedback", build([record(INTERVALS, "i-ride-99")]))


class SummaryMetricTests(unittest.TestCase):
    def test_summary_scalars_map_to_labelled_metrics(self) -> None:
        metrics = intervals_summary_metrics(
            {
                "average_speed": 8.5,
                "calories": 700,
                "decoupling": float("nan"),
                "feel": True,
                "icu_intensity": 0.8,
                "icu_weighted_avg_watts": 205,
                "average_cadence": 88,
                "total_elevation_gain": 310,
                "average_temp": "warm",
            },
            recorded_by=RecordingOrigin.GARMIN,
        )

        self.assertEqual(
            {
                "avg_speed_mps",
                "calories_kcal",
                "intensity",
                "normalized_power",
                "avg_cadence",
                "elevation_gain_m",
            },
            set(metrics),
        )
        self.assertEqual(
            {
                "value": 8.5,
                "unit": "m/s",
                "source": {
                    "provider": "intervals",
                    "label": "Intervals.icu",
                    "kind": "measured",
                    "recorded_by": "garmin",
                },
                "alternatives": [],
            },
            metrics["avg_speed_mps"],
        )
        self.assertEqual("derived", metrics["intensity"]["source"]["kind"])
        self.assertEqual(
            (205, "W", "derived"),
            (
                metrics["normalized_power"]["value"],
                metrics["normalized_power"]["unit"],
                metrics["normalized_power"]["source"]["kind"],
            ),
        )

    def test_summary_metrics_never_override_measured_values(self) -> None:
        extra = intervals_summary_metrics(
            {"average_speed": 8.5}, recorded_by=RecordingOrigin.UNKNOWN
        )
        extra["avg_hr"] = {"value": 1, "unit": "bpm", "source": {}, "alternatives": []}

        doc = build(
            [record(INTERVALS, "i-ride-99", label="Intervals.icu", avg_hr=120.0)],
            summary_metrics=extra,
        )

        self.assertEqual(120.0, doc["metrics"]["avg_hr"]["value"])
        self.assertEqual(8.5, doc["metrics"]["avg_speed_mps"]["value"])
        json.dumps(doc, allow_nan=False)


if __name__ == "__main__":
    unittest.main()
