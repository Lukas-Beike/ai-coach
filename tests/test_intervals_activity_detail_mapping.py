import unittest
from dataclasses import replace
from datetime import UTC, datetime

from backend.activities.detail_projection import detailed_activity
from backend.canonical.activity_detail import (
    MAX_LAPS,
    ActivityLapSet,
    ActivityStreamSet,
    ZoneDistribution,
)
from backend.canonical.mapping import IssueReason, MappingIssue
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
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
from backend.providers.intervals_activity_detail_mapping import (
    MAPPER_VERSION,
    map_intervals_activity_detail,
    map_legacy_activity_detail,
    zone_times,
)
from backend.providers.intervals_activity_fields import activity_detail_laps
from backend.providers.intervals_activity_mapping import INTERVALS_LABEL
from backend.sync.activity_details import normalize_streams

ID = "9001"
RETRIEVED = datetime(2026, 10, 18, 8, 0, tzinfo=UTC)
OBSERVED = "2026-10-18T08:00:00+00:00"


def _fresh(detail, streams=None):
    return map_intervals_activity_detail(
        detail,
        {} if streams is None else streams,
        recorded_by=RecordingOrigin.UNKNOWN,
        retrieved_at=RETRIEVED,
    )


def _fresh_streams(streams):
    return _fresh({"id": ID}, streams)


def _records_of(result, cls):
    return [record for record in result.records if isinstance(record, cls)]


def _only(result, cls):
    records = _records_of(result, cls)
    if len(records) != 1:
        raise AssertionError(f"expected one {cls.__name__}, got {len(records)}")
    return records[0]


def _issue(field, reason, ref=ID):
    return MappingIssue(ref, field, reason)


class IntervalsActivityDetailStreamTests(unittest.TestCase):
    def test_alias_precedence_takes_first_alias_with_usable_points(self):
        result = _fresh_streams(
            {
                "time": [0, 1, 2],
                "velocity": [1.0, 1.0, 1.0],
                "speed": [2.0, 2.0, 2.0],
                "velocity_smooth": [3.0, 3.0, 3.0],
                "grade": [1.0, 1.0, 1.0],
                "grade_smooth": [2.0, 2.0, 2.0],
                "power": [100, 100, 100],
                "watts": [200, 200, 200],
            }
        )

        channels = _only(result, ActivityStreamSet).channels

        self.assertEqual(channels[StreamChannel.SPEED_MPS], (3.0, 3.0, 3.0))
        self.assertEqual(channels[StreamChannel.GRADE_PCT], (2.0, 2.0, 2.0))
        self.assertEqual(channels[StreamChannel.POWER_W], (200.0, 200.0, 200.0))
        self.assertEqual(result.issues, ())

    def test_present_all_none_alias_falls_through_without_issue(self):
        result = _fresh_streams(
            {
                "time": [0, 1, 2],
                "velocity_smooth": [None, None, None],
                "velocity": [4.0, 4.0, 4.0],
            }
        )

        channels = _only(result, ActivityStreamSet).channels

        self.assertEqual(channels[StreamChannel.SPEED_MPS], (4.0, 4.0, 4.0))
        self.assertEqual(result.issues, ())

    def test_rejected_alias_reports_one_issue_and_next_alias_is_used(self):
        result = _fresh_streams(
            {
                "time": [0, 1, 2],
                "velocity_smooth": [999.0, 999.0, 999.0],
                "velocity": [4.0, 4.0, 4.0],
            }
        )

        channels = _only(result, ActivityStreamSet).channels

        self.assertEqual(channels[StreamChannel.SPEED_MPS], (4.0, 4.0, 4.0))
        self.assertEqual(
            result.issues, (_issue("velocity_smooth", IssueReason.OUT_OF_RANGE),)
        )

    def test_moving_flags_become_one_and_zero(self):
        result = _fresh_streams(
            {"time": [0, 1, 2], "moving": [True, False, True], "distance": [0, 1, 2]}
        )

        channels = _only(result, ActivityStreamSet).channels

        self.assertEqual(channels[StreamChannel.MOVING], (1.0, 0.0, 1.0))
        self.assertEqual(result.issues, ())

    def test_out_of_range_point_becomes_gap_with_one_issue(self):
        result = _fresh_streams(
            {
                "time": [0, 1, 2],
                "heartrate": [60, 999, 62],
                "distance": [0, 1, 2],
            }
        )

        channels = _only(result, ActivityStreamSet).channels

        self.assertEqual(channels[StreamChannel.HEART_RATE_BPM], (60.0, None, 62.0))
        self.assertEqual(
            result.issues, (_issue("heartrate", IssueReason.OUT_OF_RANGE),)
        )

    def test_time_axis_problems_yield_no_stream_set_and_one_issue(self):
        cases = (
            (
                {"time": [0, 2, 1], "distance": [0, 1, 2]},
                "time",
                IssueReason.OUT_OF_RANGE,
            ),
            (
                {"time": [0, None, 2], "distance": [0, 1, 2]},
                "time",
                IssueReason.INVALID_NUMBER,
            ),
            (
                {"time": [0, 1, 1e9], "distance": [0, 1, 2]},
                "time",
                IssueReason.OUT_OF_RANGE,
            ),
            ({"distance": [0, 1, 2]}, "time", IssueReason.MISSING),
        )
        for streams, field, reason in cases:
            with self.subTest(field=field, reason=reason.value):
                result = _fresh_streams(streams)

                self.assertEqual(result.records, ())
                self.assertEqual(result.issues, (_issue(field, reason),))

    def test_channel_with_different_length_is_dropped(self):
        result = _fresh_streams(
            {"time": [0, 1, 2], "distance": [0, 1], "heartrate": [60, 61, 62]}
        )

        stream_set = _only(result, ActivityStreamSet)

        self.assertEqual(
            set(stream_set.channels),
            {StreamChannel.TIME_S, StreamChannel.HEART_RATE_BPM},
        )
        self.assertEqual(result.issues, (_issue("distance", IssueReason.INVALID_TYPE),))

    def test_time_only_or_unknown_keys_yield_no_stream_set_and_no_issue(self):
        result = _fresh_streams(
            {"time": [0, 1, 2], "pace": [300, 300, 300], "timer": [0, 1, 2]}
        )

        self.assertEqual(result.records, ())
        self.assertEqual(result.issues, ())

    def test_fresh_streams_are_full_resolution_and_legacy_depends_on_flag(self):
        streams = {"time": [0, 1], "heartrate": [60, 61]}
        fresh = _only(_fresh_streams(streams), ActivityStreamSet)
        self.assertEqual(fresh.resolution, StreamResolution.FULL)
        self.assertEqual(fresh.origin, ActivityDetailOrigin.FETCH)

        for flag, expected in (
            (True, StreamResolution.FULL),
            (None, StreamResolution.DOWNSAMPLED),
        ):
            with self.subTest(flag=flag):
                record = {
                    "activity_id": ID,
                    "observed_at": OBSERVED,
                    "activity": {"streams": streams},
                }
                if flag is not None:
                    record["full_resolution"] = flag
                stream_set = _only(
                    map_legacy_activity_detail(
                        record, recorded_by=RecordingOrigin.UNKNOWN
                    ),
                    ActivityStreamSet,
                )

                self.assertEqual(stream_set.resolution, expected)
                self.assertEqual(
                    stream_set.origin, ActivityDetailOrigin.LEGACY_BACKFILL
                )


class IntervalsActivityDetailLapTests(unittest.TestCase):
    def test_kinds_are_mapped_and_laps_sorted_and_reindexed(self):
        detail = {
            "id": ID,
            "icu_intervals": [
                {
                    "type": "recovery",
                    "start_time": 600,
                    "end_time": 900,
                    "name": " Rest ",
                },
                {
                    "type": "WORK",
                    "start_time": 0,
                    "end_time": 600,
                    "moving_time": 600,
                    "average_watts": 250,
                },
                {"type": "warmup", "start_time": 900, "end_time": 1000},
            ],
        }

        lap_set = _only(_fresh(detail), ActivityLapSet)

        self.assertEqual(lap_set.lap_source, LapSource.PROVIDER_INTERVALS)
        self.assertEqual([lap.index for lap in lap_set.laps], [0, 1, 2])
        self.assertEqual(
            [lap.kind for lap in lap_set.laps],
            [LapKind.WORK, LapKind.RECOVERY, LapKind.LAP],
        )
        self.assertEqual(lap_set.laps[0].avg_power, 250.0)
        self.assertEqual(lap_set.laps[0].moving_duration_s, 600.0)
        self.assertEqual(lap_set.laps[1].name, "Rest")

    def test_invalid_offsets_skip_the_lap_with_issues(self):
        detail = {
            "id": ID,
            "icu_intervals": [
                {"start_time": "soon", "end_time": 100},
                {"start_time": 100, "end_time": 50},
                {"end_time": 60},
                {"start_time": 0, "end_time": 60},
                "not a lap",
            ],
        }

        result = _fresh(detail)

        lap_set = _only(result, ActivityLapSet)
        self.assertEqual(len(lap_set.laps), 1)
        self.assertEqual(lap_set.laps[0].end_offset_s, 60.0)
        self.assertEqual(
            result.issues,
            (
                _issue("start_time", IssueReason.INVALID_NUMBER),
                _issue("end_time", IssueReason.OUT_OF_RANGE),
                _issue("start_time", IssueReason.MISSING),
                _issue("icu_intervals", IssueReason.INVALID_TYPE),
            ),
        )

    def test_out_of_range_metric_is_dropped_and_lap_kept(self):
        detail = {
            "id": ID,
            "icu_intervals": [
                {
                    "start_time": 0,
                    "end_time": 60,
                    "moving_time": 60,
                    "average_watts": -5,
                }
            ],
        }

        result = _fresh(detail)

        lap = _only(result, ActivityLapSet).laps[0]
        self.assertIsNone(lap.avg_power)
        self.assertEqual(lap.moving_duration_s, 60.0)
        self.assertEqual(
            result.issues, (_issue("average_watts", IssueReason.OUT_OF_RANGE),)
        )

    def test_fractional_lap_intensity_is_stored_as_percent(self):
        rows = [
            {"start_time": 0, "end_time": 60, "icu_intensity": 0.78},
            {"start_time": 60, "end_time": 120, "icu_intensity": 85.5},
        ]

        result = _fresh({"id": ID, "icu_intervals": rows})

        laps = _only(result, ActivityLapSet).laps
        self.assertEqual([lap.intensity_pct for lap in laps], [78.0, 85.5])
        self.assertEqual(result.issues, ())

    def test_laps_beyond_the_maximum_are_capped_with_one_issue(self):
        rows = [
            {"start_time": index * 10, "end_time": index * 10 + 5}
            for index in range(MAX_LAPS + 5)
        ]

        result = _fresh({"id": ID, "icu_intervals": rows})

        lap_set = _only(result, ActivityLapSet)
        self.assertEqual(len(lap_set.laps), MAX_LAPS)
        self.assertEqual(lap_set.laps[-1].index, MAX_LAPS - 1)
        self.assertEqual(lap_set.laps[-1].start_offset_s, (MAX_LAPS - 1) * 10.0)
        self.assertEqual(
            result.issues, (_issue("icu_intervals", IssueReason.OUT_OF_RANGE),)
        )


class IntervalsActivityDetailZoneTests(unittest.TestCase):
    def test_plain_zone_list_is_positional(self):
        result = _fresh({"id": ID, "icu_hr_zone_times": [600, 300.5, 0]})

        zones = _only(result, ZoneDistribution)

        self.assertEqual(zones.metric, ZoneMetric.HEART_RATE)
        self.assertEqual(zones.boundary_source, ZoneBoundarySource.UNKNOWN)
        self.assertEqual([bucket.index for bucket in zones.buckets], [1, 2, 3])
        self.assertEqual([bucket.seconds for bucket in zones.buckets], [600, 300.5, 0])
        self.assertEqual(result.issues, ())

    def test_id_zones_skip_non_numeric_ids_with_one_issue(self):
        result = _fresh(
            {
                "id": ID,
                "icu_zone_times": [
                    {"id": "Z1", "secs": 100},
                    {"id": "SS", "secs": 5},
                    {"id": "Z2", "secs": 50},
                ],
            }
        )

        zones = _only(result, ZoneDistribution)

        self.assertEqual(zones.metric, ZoneMetric.POWER)
        self.assertEqual([bucket.index for bucket in zones.buckets], [1, 2])
        self.assertEqual([bucket.label for bucket in zones.buckets], ["Z1", "Z2"])
        self.assertEqual([bucket.seconds for bucket in zones.buckets], [100, 50])
        self.assertEqual(
            result.issues, (_issue("icu_zone_times", IssueReason.UNSUPPORTED),)
        )

    def test_gap_in_plain_list_drops_the_distribution(self):
        result = _fresh({"id": ID, "icu_hr_zone_times": [600, "x", 300]})

        self.assertEqual(_records_of(result, ZoneDistribution), [])
        self.assertEqual(
            result.issues, (_issue("icu_hr_zone_times", IssueReason.INVALID_NUMBER),)
        )

    def test_non_list_zone_payload_is_reported(self):
        result = _fresh({"id": ID, "icu_zone_times": {"Z1": 100}})

        self.assertEqual(_records_of(result, ZoneDistribution), [])
        self.assertEqual(
            result.issues, (_issue("icu_zone_times", IssueReason.INVALID_TYPE),)
        )

    def test_id_zone_with_invalid_seconds_drops_the_distribution(self):
        result = _fresh(
            {
                "id": ID,
                "icu_zone_times": [
                    {"id": "Z1", "secs": "bad"},
                    {"id": "Z2", "secs": 50},
                ],
            }
        )

        self.assertEqual(_records_of(result, ZoneDistribution), [])
        self.assertEqual(
            result.issues, (_issue("icu_zone_times", IssueReason.INVALID_NUMBER),)
        )

    def test_invalid_seconds_on_a_skipped_id_keep_the_distribution(self):
        result = _fresh(
            {
                "id": ID,
                "icu_zone_times": [
                    {"id": "Z1", "secs": 100},
                    {"id": "Z2", "secs": 50},
                    {"id": "SS", "secs": None},
                ],
            }
        )

        zones = _only(result, ZoneDistribution)

        self.assertEqual([bucket.label for bucket in zones.buckets], ["Z1", "Z2"])
        self.assertEqual([bucket.seconds for bucket in zones.buckets], [100, 50])

    def test_zone_times_keeps_bounded_numbers_and_ids(self):
        self.assertEqual(zone_times("not a list"), [])
        self.assertEqual(
            zone_times([1, True, float("nan"), {"id": "Z1" + "x" * 30, "secs": 2}]),
            [1, None, None, {"id": "Z1" + "x" * 18, "secs": 2}],
        )


class IntervalsActivityDetailCoreTests(unittest.TestCase):
    def test_mapper_version_is_one(self):
        self.assertEqual(MAPPER_VERSION, 1)

    def test_records_are_ordered_streams_laps_heart_rate_then_power(self):
        detail = {
            "id": ID,
            "icu_intervals": [{"start_time": 0, "end_time": 2}],
            "icu_hr_zone_times": [10],
            "icu_zone_times": [20],
        }
        streams = {"time": [0, 1, 2], "distance": [0, 1, 2]}

        result = _fresh(detail, streams)

        self.assertEqual(
            [type(record) for record in result.records],
            [ActivityStreamSet, ActivityLapSet, ZoneDistribution, ZoneDistribution],
        )
        self.assertEqual(
            [record.metric for record in result.records[2:]],
            [ZoneMetric.HEART_RATE, ZoneMetric.POWER],
        )

    def test_provenance_names_intervals_and_the_activity(self):
        result = _fresh({"id": 4321, "icu_hr_zone_times": [60]})

        zones = _only(result, ZoneDistribution)

        self.assertEqual(zones.provider_activity_id, "4321")
        self.assertEqual(zones.provenance.provider, ProviderId.INTERVALS)
        self.assertEqual(zones.provenance.source_kind, SourceKind.PROVIDER_REPORTED)
        self.assertEqual(zones.provenance.source_record_id, "4321")
        self.assertEqual(zones.provenance.recorded_by, RecordingOrigin.UNKNOWN)
        self.assertEqual(zones.provenance.retrieved_at, RETRIEVED)
        self.assertEqual(zones.provenance.label, INTERVALS_LABEL)

    def test_invalid_ids_yield_one_issue_and_no_records(self):
        cases = (
            ({}, "id", IssueReason.MISSING),
            ({"id": None}, "id", IssueReason.MISSING),
            ({"id": "   "}, "id", IssueReason.MISSING),
            ({"id": True}, "id", IssueReason.INVALID_TYPE),
            ({"id": ["9001"]}, "id", IssueReason.INVALID_TYPE),
            ({"id": "x" * 500}, "id", IssueReason.OUT_OF_RANGE),
            ({"id": 10**1000}, "id", IssueReason.OUT_OF_RANGE),
        )
        for detail, field, reason in cases:
            with self.subTest(field=field, reason=reason.value):
                result = _fresh(detail, {"time": [0, 1], "distance": [0, 1]})

                self.assertEqual(result.records, ())
                self.assertEqual(result.issues, (MappingIssue(None, field, reason),))

    def test_naive_retrieved_at_and_wrong_recorded_by_raise_for_callers(self):
        with self.assertRaises(ValueError):
            map_intervals_activity_detail(
                {"id": ID},
                {},
                recorded_by=RecordingOrigin.UNKNOWN,
                retrieved_at=datetime(2026, 10, 18, 8, 0),  # noqa: DTZ001
            )
        with self.assertRaises(TypeError):
            map_legacy_activity_detail({"activity_id": ID}, recorded_by="garmin")

    def test_garbage_inputs_never_raise(self):
        garbage = (
            None,
            [],
            "text",
            5,
            True,
            {},
            {"id": None},
            {"id": True},
            {"id": []},
            {"id": "x" * 500},
            {"id": ID, "streams": "bad"},
            {"id": ID, "streams": {"time": None}},
            {"id": ID, "streams": {"time": [0, "x", float("inf")]}},
            {"id": ID, "streams": {"time": [0, 1], "distance": {"a": 1}}},
            {"id": ID, "icu_intervals": "bad", "icu_hr_zone_times": {"a": 1}},
            {"id": ID, "icu_intervals": [None, {"start_time": [1]}, 5]},
            {"id": ID, "icu_intervals": [{"start_time": 0, "end_time": 1, "name": 7}]},
            {"id": ID, "icu_zone_times": [{"id": None}, {"secs": "x"}, float("nan")]},
        )
        for index, value in enumerate(garbage):
            with self.subTest(fresh=index):
                map_intervals_activity_detail(
                    value,
                    value,
                    recorded_by=RecordingOrigin.UNKNOWN,
                    retrieved_at=RETRIEVED,
                )
            with self.subTest(legacy=index):
                map_legacy_activity_detail(value, recorded_by=RecordingOrigin.UNKNOWN)
                map_legacy_activity_detail(
                    {"activity_id": ID, "observed_at": OBSERVED, "activity": value},
                    recorded_by=RecordingOrigin.UNKNOWN,
                )


class IntervalsActivityDetailLegacyTests(unittest.TestCase):
    def _detail(self):
        # Synthetic fixture without interval "type": stored laps never kept it.
        return {
            "id": ID,
            "name": "Synthetic intervals",
            "moving_time": 1000,
            "icu_intervals": [
                {
                    "start_time": 0,
                    "end_time": 600,
                    "moving_time": 600,
                    "distance": 2000,
                    "average_watts": 250,
                    "average_heartrate": 150,
                },
                {"start_time": 600, "end_time": 900, "average_watts": 120},
            ],
            "icu_hr_zone_times": [300, 400, 300],
            "icu_zone_times": [{"id": "Z1", "secs": 100}, {"id": "SS", "secs": 5}],
        }

    def _streams(self):
        return normalize_streams(
            [
                {"type": "time", "data": [0, 1, 2, 3]},
                {"type": "distance", "data": [0.0, 1.5, 3.0, 4.5]},
                {"type": "heartrate", "data": [120, 130, None, 140]},
                {"type": "watts", "data": [200, 210, 220, 230]},
            ]
        )

    def test_legacy_record_maps_like_fresh_fetch_except_origin(self):
        detail = self._detail()
        streams = self._streams()
        record = {
            "activity_id": ID,
            "activity": {
                **detailed_activity({**detail, "laps": activity_detail_laps(detail)}),
                "streams": streams,
            },
            "observed_at": OBSERVED,
            "full_resolution": True,
        }

        fresh = _fresh(detail, streams)
        legacy = map_legacy_activity_detail(record, recorded_by=RecordingOrigin.UNKNOWN)

        self.assertEqual(legacy.issues, fresh.issues)
        self.assertEqual(len(legacy.records), 4)
        self.assertEqual(
            legacy.records,
            tuple(
                replace(record, origin=ActivityDetailOrigin.LEGACY_BACKFILL)
                for record in fresh.records
            ),
        )
        self.assertTrue(
            all(
                record.origin is ActivityDetailOrigin.LEGACY_BACKFILL
                for record in legacy.records
            )
        )
        lap_set = _only(legacy, ActivityLapSet)
        self.assertTrue(all(lap.kind is LapKind.LAP for lap in lap_set.laps))

    def test_bad_observed_at_yields_one_issue_and_no_records(self):
        for observed_at in ("18.10.2026", "2026-10-18T08:00:00"):
            with self.subTest(observed_at=observed_at):
                result = map_legacy_activity_detail(
                    {
                        "activity_id": ID,
                        "observed_at": observed_at,
                        "activity": self._detail(),
                    },
                    recorded_by=RecordingOrigin.UNKNOWN,
                )

                self.assertEqual(result.records, ())
                self.assertEqual(
                    result.issues, (_issue("observed_at", IssueReason.INVALID_TYPE),)
                )


if __name__ == "__main__":
    unittest.main()
