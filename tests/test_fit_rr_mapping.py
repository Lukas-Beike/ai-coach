"""RR intervals from FIT hrv messages (global 78) and the first threshold they give (#1867).

Synthetic FIT files come from the struct-based builder in ``test_fit_file``; the
beat series is the designed ramp of ``test_dfa_alpha1``.
"""

import struct
import unittest
from datetime import UTC, datetime

from backend.canonical.activity_detail import ActivityStreamSet
from backend.canonical.records import Provenance
from backend.canonical.vocabulary import (
    DfaQuality,
    HeartRateSource,
    ProviderId,
    RecordingOrigin,
    SourceKind,
)
from backend.providers.fit_activity_detail_mapping import map_fit_activity_detail
from backend.providers.fit_file import FitMessage, fit_messages
from backend.providers.fit_rr_mapping import MAX_RR_INTERVALS, rr_intervals_ms
from tests import test_fit_file as fit_builder
from tests.test_dfa_alpha1 import ramp

UINT8, UINT16, UINT32, ENUM = (
    fit_builder.UINT8,
    fit_builder.UINT16,
    fit_builder.UINT32,
    fit_builder.ENUM,
)
RECORD = [(253, UINT32), (3, UINT8)]
DEVICE = [(0, UINT8), (1, UINT8), (2, UINT16), (3, UINT32), (4, UINT16), (25, ENUM)]
INVALID = 0xFFFF
PROVENANCE = Provenance(
    provider=ProviderId.GARMIN,
    source_kind=SourceKind.PROVIDER_REPORTED,
    source_record_id=None,
    recorded_by=RecordingOrigin.GARMIN,
    retrieved_at=datetime(2026, 11, 9, tzinfo=UTC),
    label=None,
)


def add_hrv(builder, local, intervals_ms):
    """Append hrv messages of up to five intervals each: field 0, uint16 array, /1000 s."""
    builder.raw(
        struct.pack("<BBBHB", 0x40 | local, 0, 0, 78, 1)
        + struct.pack("<BBB", 0, 10, UINT16)
    )
    for start in range(0, len(intervals_ms), 5):
        chunk = [
            INVALID if value is None else round(value)
            for value in intervals_ms[start : start + 5]
        ]
        chunk += [INVALID] * (5 - len(chunk))
        builder.raw(bytes([local]) + struct.pack("<5H", *chunk))


def fit_with_rr(intervals_ms, *, strap=True, records=12):
    builder = fit_builder.FitBuilder()
    builder.define(1, 23, DEVICE)
    builder.data(1, {0: 0, 1: 0, 2: 1, 3: 111, 4: 3500, 25: 5})
    if strap:
        builder.data(1, {0: 1, 1: 120, 2: 1, 3: 3351234567, 4: 2000, 25: 1})
    builder.define(0, 20, RECORD)
    for second in range(records):
        builder.data(0, {253: 1_000_000 + second, 3: 140 + second})
    add_hrv(builder, 2, intervals_ms)
    return builder.build()


def streams(data) -> ActivityStreamSet:
    result = map_fit_activity_detail(
        data, provider_activity_id="a1", provenance=PROVENANCE
    )
    return next(r for r in result.records if isinstance(r, ActivityStreamSet))


class HrvMessageParsingTests(unittest.TestCase):
    def test_message_78_is_read_in_file_order_in_milliseconds(self) -> None:
        data = fit_with_rr([800, 812, None, 790, 805, 1000, 1010])
        messages = fit_messages(data)
        self.assertEqual(sum(1 for number, _ in messages if number == 78), 2)
        # 0xFFFF is the FIT invalid value of a uint16: skipped, not 65.535 s.
        self.assertEqual(
            rr_intervals_ms(messages), [[800.0, 812.0], [790.0, 805.0, 1000.0, 1010.0]]
        )

    def test_a_single_value_message_and_other_messages_are_handled(self) -> None:
        builder = fit_builder.FitBuilder()
        builder.define(0, 20, RECORD).data(0, {253: 1_000_000, 3: 140})
        builder.raw(
            struct.pack("<BBBHB", 0x41, 0, 0, 78, 1) + struct.pack("<BBB", 0, 2, UINT16)
        )
        builder.raw(bytes([1]) + struct.pack("<H", 640))
        self.assertEqual(rr_intervals_ms(fit_messages(builder.build())), [[640.0]])
        self.assertEqual(rr_intervals_ms([]), [])

    def test_the_series_is_bounded(self) -> None:
        messages: list[FitMessage] = [
            (78, {0: [800] * 5}) for _ in range(MAX_RR_INTERVALS // 5 + 10)
        ]
        self.assertEqual(sum(map(len, rr_intervals_ms(messages))), MAX_RR_INTERVALS)


class DropoutSegmentTests(unittest.TestCase):
    def test_padding_after_the_last_value_is_no_break(self) -> None:
        messages: list[FitMessage] = [(78, {0: [800, 810, None, None, None]})]
        self.assertEqual(rr_intervals_ms(messages), [[800.0, 810.0]])

    def test_an_invalid_slot_between_values_splits_the_series(self) -> None:
        messages: list[FitMessage] = [
            (78, {0: [800, None, 810, 820, 830]}),
            (78, {0: [840, 850, 860, 870, 880]}),
        ]
        self.assertEqual(
            rr_intervals_ms(messages),
            [[800.0], [810.0, 820.0, 830.0, 840.0, 850.0, 860.0, 870.0, 880.0]],
        )

    def test_missing_messages_leave_a_file_clock_gap_that_splits_the_series(
        self,
    ) -> None:
        def stretch(start, count):
            beats = [{0: [1000] * 5} for _ in range(count)]
            clock = start
            out: list[FitMessage] = []
            for fields in beats:
                clock += 5  # five one-second beats
                out.append((20, {253: clock}))
                out.append((78, fields))
            return out

        steady_file = stretch(1_000_000, 6)
        self.assertEqual(len(rr_intervals_ms(steady_file)), 1)
        # 60 s of records without any hrv message in between.
        later = stretch(1_000_000 + 30 + 60, 6)
        segments = rr_intervals_ms(steady_file + later)
        self.assertEqual([len(segment) for segment in segments], [30, 30])

    def test_batched_messages_that_run_ahead_of_the_clock_are_no_break(self) -> None:
        messages: list[FitMessage] = [(20, {253: 1_000_000})]
        messages += [(78, {0: [1000] * 5}) for _ in range(6)]
        self.assertEqual([len(s) for s in rr_intervals_ms(messages)], [30])


class FirstThresholdFromFitTests(unittest.TestCase):
    def test_a_chest_strap_recording_gives_the_estimate_and_keeps_no_rr(self) -> None:
        stream_set = streams(fit_with_rr(ramp(0)))
        self.assertIs(stream_set.hr_source, HeartRateSource.CHEST_STRAP)
        result = stream_set.dfa_alpha1
        assert result is not None
        self.assertAlmostEqual(result.estimate_bpm, 153.0, delta=7.0)
        self.assertIs(result.quality, DfaQuality.GOOD)
        # The set holds the derived result and the record channels only.
        self.assertEqual(
            sorted(channel.value for channel in stream_set.channels),
            ["heart_rate_bpm", "time_s"],
        )

    def test_without_a_strap_the_wrist_sensor_gets_no_estimate(self) -> None:
        stream_set = streams(fit_with_rr(ramp(0), strap=False))
        self.assertIsNot(stream_set.hr_source, HeartRateSource.CHEST_STRAP)
        self.assertIsNone(stream_set.dfa_alpha1)

    def test_a_strap_without_hrv_messages_or_a_crossing_gets_none(self) -> None:
        self.assertIsNone(streams(fit_with_rr([])).dfa_alpha1)
        self.assertIsNone(streams(fit_with_rr([800] * 300)).dfa_alpha1)


if __name__ == "__main__":
    unittest.main()
