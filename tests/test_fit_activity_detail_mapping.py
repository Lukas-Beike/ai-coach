"""Tests for the FIT activity detail mapper (origin FETCH).

Synthetic FIT files come from the struct-based builder in ``test_fit_file``;
no binary fixtures are read.
"""

import random
import struct
import unittest
from datetime import UTC, datetime
from unittest import mock

from backend.canonical.activity_detail import ActivityLapSet, ActivityStreamSet
from backend.canonical.mapping import IssueReason, MappingIssue, MappingResult
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    LapKind,
    LapSource,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    StreamChannel,
    StreamResolution,
)
from backend.providers import fit_activity_detail_mapping as mapper
from backend.providers.fit_activity_detail_mapping import (
    MAPPER_VERSION,
    map_fit_activity_detail,
)
from tests import test_fit_file as fit_builder

ENUM = fit_builder.ENUM
SINT8 = fit_builder.SINT8
UINT8 = fit_builder.UINT8
UINT16 = fit_builder.UINT16
UINT32 = fit_builder.UINT32

ID = "fit-42"
RETRIEVED = datetime(2026, 10, 19, 6, 0, tzinfo=UTC)
GARMIN = Provenance(
    provider=ProviderId.GARMIN,
    source_kind=SourceKind.PROVIDER_REPORTED,
    source_record_id=None,
    recorded_by=RecordingOrigin.GARMIN,
    retrieved_at=RETRIEVED,
    label=None,
)
RECORD_FIELDS = [
    (253, UINT32),
    (5, UINT32),
    (6, UINT16),
    (73, UINT32),
    (2, UINT16),
    (78, UINT32),
    (3, UINT8),
    (4, UINT8),
    (53, UINT8),
    (7, UINT16),
    (13, SINT8),
]
LAP_FIELDS = [
    (2, UINT32),
    (7, UINT32),
    (8, UINT32),
    (9, UINT32),
    (13, UINT16),
    (110, UINT32),
    (15, UINT8),
    (16, UINT8),
    (17, UINT8),
    (19, UINT16),
    (20, UINT16),
    (21, UINT16),
    (33, UINT16),
    (23, ENUM),
]
_RECORD_NAMES = {
    "distance": 5,
    "speed": 6,
    "enhanced_speed": 73,
    "altitude": 2,
    "enhanced_altitude": 78,
    "hr": 3,
    "cadence": 4,
    "fraction": 53,
    "power": 7,
    "temperature": 13,
}
_LAP_NAMES = {
    "start": 2,
    "elapsed": 7,
    "timer": 8,
    "distance": 9,
    "speed": 13,
    "enhanced_speed": 110,
    "avg_hr": 15,
    "max_hr": 16,
    "avg_cadence": 17,
    "avg_power": 19,
    "max_power": 20,
    "ascent": 21,
    "normalized_power": 33,
    "intensity": 23,
}


def _record(stamp, **raw):
    """One record row in raw FIT units; omitted fields are FIT invalid values."""
    row = {253: stamp}
    for name, value in raw.items():
        row[_RECORD_NAMES[name]] = value
    return row


def _lap(**raw):
    """One lap row in raw FIT units (times in milliseconds, distance in cm)."""
    return {_LAP_NAMES[name]: value for name, value in raw.items()}


def _fit(records=(), laps=()):
    builder = fit_builder.FitBuilder()
    if records:
        builder.define(0, 20, RECORD_FIELDS)
        for row in records:
            builder.data(0, row)
    if laps:
        builder.define(1, 19, LAP_FIELDS)
        for row in laps:
            builder.data(1, row)
    return builder.build()


def _map(data):
    return map_fit_activity_detail(data, provider_activity_id=ID, provenance=GARMIN)


def _only(result, cls):
    found = [record for record in result.records if isinstance(record, cls)]
    if len(found) != 1:
        raise AssertionError(f"expected one {cls.__name__}, got {len(found)}")
    return found[0]


def _channels(result):
    return dict(_only(result, ActivityStreamSet).channels)


def _issue(field, reason):
    return MappingIssue(ID, field, reason)


class FitActivityDetailMappingTests(unittest.TestCase):
    def test_mapper_version_is_one(self):
        self.assertEqual(MAPPER_VERSION, 1)

    def test_full_record_set_maps_every_channel_in_canonical_units(self):
        result = _map(
            _fit(
                records=[
                    _record(
                        1000,
                        distance=0,
                        speed=0,
                        altitude=3000,
                        hr=100,
                        cadence=80,
                        fraction=0,
                        power=200,
                        temperature=20,
                    ),
                    _record(
                        1001,
                        distance=250,
                        speed=2500,
                        altitude=3010,
                        hr=120,
                        cadence=81,
                        fraction=64,
                        power=250,
                        temperature=21,
                    ),
                    _record(
                        1002,
                        distance=500,
                        speed=2750,
                        altitude=3020,
                        hr=130,
                        cadence=82,
                        power=300,
                        temperature=22,
                    ),
                ]
            )
        )
        streams = _only(result, ActivityStreamSet)
        self.assertEqual(result.issues, ())
        self.assertEqual(streams.provider_activity_id, ID)
        self.assertEqual(streams.provenance, GARMIN)
        self.assertEqual(streams.origin, ActivityDetailOrigin.FETCH)
        self.assertEqual(streams.resolution, StreamResolution.FULL)
        self.assertEqual(
            dict(streams.channels),
            {
                StreamChannel.TIME_S: (0.0, 1.0, 2.0),
                StreamChannel.DISTANCE_M: (0.0, 2.5, 5.0),
                StreamChannel.SPEED_MPS: (0.0, 2.5, 2.75),
                StreamChannel.ALTITUDE_M: (100.0, 102.0, 104.0),
                StreamChannel.HEART_RATE_BPM: (100.0, 120.0, 130.0),
                StreamChannel.CADENCE_RPM: (80.0, 81.5, 82.0),
                StreamChannel.POWER_W: (200.0, 250.0, 300.0),
                StreamChannel.TEMPERATURE_C: (20.0, 21.0, 22.0),
            },
        )

    def test_enhanced_fields_win_per_record_and_fall_back_on_sentinel(self):
        result = _map(
            _fit(
                records=[
                    _record(1000, speed=9000, enhanced_speed=1500),
                    _record(1001, speed=2000, altitude=3010),
                    _record(1002, speed=2200, enhanced_speed=2300),
                ]
            )
        )
        channels = _channels(result)
        self.assertEqual(channels[StreamChannel.SPEED_MPS], (1.5, 2.0, 2.3))
        self.assertEqual(channels[StreamChannel.ALTITUDE_M], (None, 102.0, None))

    def test_enhanced_altitude_is_preferred_over_base_altitude(self):
        result = _map(
            _fit(
                records=[
                    _record(1000, altitude=3000, enhanced_altitude=3500, hr=100),
                    _record(1001, altitude=3010, enhanced_altitude=3520, hr=101),
                ]
            )
        )
        self.assertEqual(_channels(result)[StreamChannel.ALTITUDE_M], (200.0, 204.0))

    def test_fractional_cadence_adds_to_whole_cadence_when_present(self):
        result = _map(
            _fit(
                records=[
                    _record(1000, cadence=80, fraction=64),
                    _record(1001, cadence=80),
                    _record(1002, cadence=81, fraction=127),
                ]
            )
        )
        self.assertEqual(
            _channels(result)[StreamChannel.CADENCE_RPM],
            (80.5, 80.0, 81.9921875),
        )

    def test_duplicate_and_backwards_timestamps_are_skipped_with_one_issue(self):
        result = _map(
            _fit(
                records=[
                    _record(1000, hr=100),
                    _record(1001, hr=101),
                    _record(1001, hr=102),
                    _record(1000, hr=103),
                    _record(1002, hr=104),
                ]
            )
        )
        channels = _channels(result)
        self.assertEqual(channels[StreamChannel.TIME_S], (0.0, 1.0, 2.0))
        self.assertEqual(channels[StreamChannel.HEART_RATE_BPM], (100.0, 101.0, 104.0))
        self.assertEqual(
            result.issues, (_issue("timestamp", IssueReason.OUT_OF_RANGE),)
        )

    def test_records_without_timestamp_are_skipped_with_one_missing_issue(self):
        result = _map(
            _fit(
                records=[
                    _record(1000, hr=100),
                    {3: 110},
                    _record(1002, hr=120),
                    {3: 130},
                ]
            )
        )
        channels = _channels(result)
        self.assertEqual(channels[StreamChannel.TIME_S], (0.0, 2.0))
        self.assertEqual(channels[StreamChannel.HEART_RATE_BPM], (100.0, 120.0))
        self.assertEqual(result.issues, (_issue("timestamp", IssueReason.MISSING),))

    def test_out_of_range_points_become_gaps_with_one_issue_per_channel(self):
        result = _map(
            _fit(
                records=[
                    _record(1000, hr=120),
                    _record(1001, hr=10),
                    _record(1002, hr=5),
                ]
            )
        )
        self.assertEqual(
            _channels(result)[StreamChannel.HEART_RATE_BPM], (120.0, None, None)
        )
        self.assertEqual(
            result.issues,
            (_issue(StreamChannel.HEART_RATE_BPM.value, IssueReason.OUT_OF_RANGE),),
        )

    def test_channel_without_usable_points_is_dropped(self):
        result = _map(_fit(records=[_record(1000, hr=120), _record(1001, hr=121)]))
        self.assertEqual(
            set(_channels(result)), {StreamChannel.TIME_S, StreamChannel.HEART_RATE_BPM}
        )
        self.assertEqual(result.issues, ())

    def test_single_record_gives_no_stream_set(self):
        result = _map(_fit(records=[_record(1000, hr=120, power=200)]))
        self.assertEqual(result.records, ())
        self.assertEqual(result.issues, ())

    def test_field_with_mismatched_width_does_not_discard_the_records(self):
        # Field 200 is a uint16 declared three bytes wide, kept as bytes.
        definition = bytes(
            [0x40, 0, 0, 20, 0, 3, 253, 4, 0x86, 3, 1, 0x02, 200, 3, 0x84]
        )
        records = b"".join(
            bytes([0]) + struct.pack("<I", stamp) + bytes([hr, 1, 2, 3])
            for stamp, hr in ((1000, 100), (1001, 101))
        )
        builder = fit_builder.FitBuilder().raw(definition + records)
        result = _map(builder.build())
        self.assertEqual(result.issues, ())
        self.assertIn(StreamChannel.HEART_RATE_BPM, _channels(result))

    def test_record_only_file_gives_streams_and_no_laps(self):
        result = _map(_fit(records=[_record(1000, hr=100), _record(1001, hr=101)]))
        self.assertEqual(len(result.records), 1)
        self.assertIsInstance(result.records[0], ActivityStreamSet)

    def test_lap_only_file_gives_laps_with_first_lap_as_time_zero(self):
        result = _map(
            _fit(
                laps=[_lap(start=1000, elapsed=60000), _lap(start=1060, elapsed=30000)]
            )
        )
        self.assertEqual(len(result.records), 1)
        lap_set = _only(result, ActivityLapSet)
        self.assertEqual(lap_set.lap_source, LapSource.DEVICE_LAPS)
        self.assertEqual(lap_set.origin, ActivityDetailOrigin.FETCH)
        self.assertEqual(
            [(lap.start_offset_s, lap.end_offset_s) for lap in lap_set.laps],
            [(0.0, 60.0), (60.0, 90.0)],
        )
        self.assertEqual(result.issues, ())

    def test_lap_metrics_map_to_canonical_units_with_enhanced_speed(self):
        result = _map(
            _fit(
                laps=[
                    _lap(
                        start=1000,
                        elapsed=60000,
                        timer=58000,
                        distance=1000,
                        speed=3000,
                        enhanced_speed=3200,
                        avg_hr=150,
                        max_hr=170,
                        avg_cadence=90,
                        avg_power=200,
                        max_power=500,
                        ascent=12,
                        normalized_power=210,
                    )
                ]
            )
        )
        lap = _only(result, ActivityLapSet).laps[0]
        self.assertEqual(lap.moving_duration_s, 58.0)
        self.assertEqual(lap.distance_m, 10.0)
        self.assertEqual(lap.avg_speed_mps, 3.2)
        self.assertEqual(lap.avg_hr, 150.0)
        self.assertEqual(lap.max_hr, 170.0)
        self.assertEqual(lap.avg_cadence, 90.0)
        self.assertEqual(lap.avg_power, 200.0)
        self.assertEqual(lap.max_power, 500.0)
        self.assertEqual(lap.elevation_gain_m, 12.0)
        self.assertEqual(lap.normalized_power, 210.0)

    def test_lap_intensity_maps_to_kinds_and_unknown_values_as_lap(self):
        laps = [
            _lap(start=1000 + 60 * index, elapsed=60000, intensity=value)
            for index, value in enumerate((0, 1, 2, 3, 4, 5, 9))
        ]
        lap_set = _only(_map(_fit(laps=laps)), ActivityLapSet)
        self.assertEqual(
            [lap.kind for lap in lap_set.laps],
            [
                LapKind.LAP,
                LapKind.RECOVERY,
                LapKind.WARMUP,
                LapKind.COOLDOWN,
                LapKind.RECOVERY,
                LapKind.WORK,
                LapKind.LAP,
            ],
        )
        self.assertEqual([lap.index for lap in lap_set.laps], [0, 1, 2, 3, 4, 5, 6])

    def test_lap_after_dropped_lap_is_reindexed_from_zero(self):
        result = _map(_fit(laps=[_lap(start=1000), _lap(start=1060, elapsed=60000)]))
        lap_set = _only(result, ActivityLapSet)
        self.assertEqual(len(lap_set.laps), 1)
        self.assertEqual(lap_set.laps[0].index, 0)
        self.assertEqual(lap_set.laps[0].start_offset_s, 60.0)
        self.assertEqual(
            result.issues, (_issue("total_elapsed_time", IssueReason.MISSING),)
        )

    def test_out_of_range_lap_metric_becomes_none_with_issue(self):
        result = _map(_fit(laps=[_lap(start=1000, elapsed=60000, avg_hr=5)]))
        lap = _only(result, ActivityLapSet).laps[0]
        self.assertIsNone(lap.avg_hr)
        self.assertEqual(result.issues, (_issue("avg_hr", IssueReason.OUT_OF_RANGE),))

    def test_lap_before_time_zero_is_dropped_with_issue(self):
        result = _map(
            _fit(
                records=[_record(1000, hr=100), _record(1001, hr=101)],
                laps=[_lap(start=990, elapsed=5000), _lap(start=1000, elapsed=60000)],
            )
        )
        lap_set = _only(result, ActivityLapSet)
        self.assertEqual([lap.start_offset_s for lap in lap_set.laps], [0.0])
        self.assertEqual(
            result.issues, (_issue("start_time", IssueReason.OUT_OF_RANGE),)
        )

    def test_lap_without_start_is_dropped_with_missing_issue(self):
        result = _map(_fit(laps=[_lap(start=1000, elapsed=60000), _lap(elapsed=60000)]))
        self.assertEqual(len(_only(result, ActivityLapSet).laps), 1)
        self.assertEqual(result.issues, (_issue("start_time", IssueReason.MISSING),))

    def test_record_count_above_stream_limit_drops_streams_with_issue(self):
        data = _fit(
            records=[
                _record(1000, hr=100),
                _record(1001, hr=101),
                _record(1002, hr=102),
            ]
        )
        with mock.patch.object(mapper, "MAX_STREAM_POINTS", 2):
            result = _map(data)
        self.assertEqual(result.records, ())
        self.assertEqual(result.issues, (_issue("record", IssueReason.OUT_OF_RANGE),))

    def test_lap_count_above_limit_keeps_leading_laps_with_issue(self):
        laps = [_lap(start=1000 + 60 * index, elapsed=60000) for index in range(3)]
        with mock.patch.object(mapper, "MAX_LAPS", 2):
            result = _map(_fit(laps=laps))
        lap_set = _only(result, ActivityLapSet)
        self.assertEqual([lap.index for lap in lap_set.laps], [0, 1])
        self.assertEqual(result.issues, (_issue("lap", IssueReason.OUT_OF_RANGE),))

    def test_non_bytes_and_corrupt_bytes_give_one_invalid_type_issue(self):
        valid = _fit(records=[_record(1000, hr=100), _record(1001, hr=101)])
        for data in ("text", None, 123, bytearray(valid), b"", b"not a fit file"):
            with self.subTest(data=data):
                result = _map(data)
                self.assertEqual(result.records, ())
                self.assertEqual(
                    result.issues, (_issue("fit", IssueReason.INVALID_TYPE),)
                )

    def test_provenance_and_activity_id_are_carried_to_every_set(self):
        result = _map(
            _fit(
                records=[_record(1000, hr=100), _record(1001, hr=101)],
                laps=[_lap(start=1000, elapsed=60000)],
            )
        )
        self.assertEqual(len(result.records), 2)
        for record in result.records:
            self.assertEqual(record.provider_activity_id, ID)
            self.assertEqual(record.provenance, GARMIN)

    def test_caller_arguments_are_checked(self):
        data = _fit(records=[_record(1000, hr=100), _record(1001, hr=101)])
        with self.assertRaises((TypeError, ValueError)):
            map_fit_activity_detail(data, provider_activity_id="", provenance=GARMIN)
        with self.assertRaises((TypeError, ValueError)):
            map_fit_activity_detail(
                data, provider_activity_id="x" * 201, provenance=GARMIN
            )
        with self.assertRaises(TypeError):
            map_fit_activity_detail(data, provider_activity_id=ID, provenance="garmin")
        unattributed = Provenance(
            provider=None,
            source_kind=SourceKind.ATHLETE_ENTERED,
            source_record_id=None,
            recorded_by=RecordingOrigin.MANUAL,
            retrieved_at=None,
            label=None,
        )
        with self.assertRaises(ValueError):
            map_fit_activity_detail(
                data, provider_activity_id=ID, provenance=unattributed
            )

    def test_random_and_mutated_files_never_raise(self):
        rng = random.Random(20261019)
        valid = _fit(
            records=[_record(1000, hr=100, speed=2500), _record(1001, hr=101)],
            laps=[_lap(start=1000, elapsed=60000, avg_hr=150)],
        )
        cases = [
            bytes(rng.randrange(256) for _ in range(rng.randrange(0, 120)))
            for _ in range(150)
        ]
        for _ in range(150):
            mutated = bytearray(valid)
            for _ in range(rng.randrange(1, 5)):
                mutated[rng.randrange(14, len(mutated) - 2)] = rng.randrange(256)
            cases.append(fit_builder.refit_crcs(bytes(mutated)))
        for data in cases:
            result = _map(data)
            self.assertIsInstance(result, MappingResult)
            for record in result.records:
                self.assertIsInstance(record, ActivityStreamSet | ActivityLapSet)
            for issue in result.issues:
                self.assertIsInstance(issue, MappingIssue)


if __name__ == "__main__":
    unittest.main()
