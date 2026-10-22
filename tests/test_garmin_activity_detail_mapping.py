import copy
import json
import unittest
from datetime import UTC, datetime
from pathlib import Path

from backend.canonical.activity_detail import (
    ActivityLapSet,
    ActivityStreamSet,
    ZoneDistribution,
)
from backend.canonical.mapping import IssueReason, MappingIssue, MappingResult
from backend.canonical.vocabulary import (
    ActivityDetailOrigin,
    LapSource,
    ProviderId,
    RecordingOrigin,
    StreamChannel,
    StreamResolution,
    ZoneBoundarySource,
    ZoneMetric,
)
from backend.providers.garmin_activity_detail_mapping import (
    MAPPER_VERSION,
    map_garmin_activity_detail,
)

ID = "123456789"
RETRIEVED = datetime(2026, 10, 18, 8, 0, tzinfo=UTC)
FIXTURES = (
    Path(__file__).parent / "fixtures" / "providers" / "garmin" / "activity_detail"
)


def _fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _collected(**overrides):
    collected = {
        "activity_id": ID,
        "details": _fixture("details"),
        "splits": _fixture("splits"),
        "hr_zones": _fixture("hr_zones"),
        "power_zones": _fixture("power_zones"),
    }
    collected.update(overrides)
    return copy.deepcopy(collected)


def _map(collected):
    return map_garmin_activity_detail(
        collected, recorded_by=RecordingOrigin.GARMIN, retrieved_at=RETRIEVED
    )


def _records_of(result, cls):
    return [record for record in result.records if isinstance(record, cls)]


def _only(result, cls):
    found = _records_of(result, cls)
    if len(found) != 1:
        raise AssertionError(f"expected one {cls.__name__}, got {len(found)}")
    return found[0]


def _issue(field, reason, ref=ID):
    return MappingIssue(ref, field, reason)


def _set_rows(details, index, values):
    """Replace one metric column of the fixture rows with the given values."""
    for row, value in zip(details["activityDetailMetrics"], values, strict=True):
        row["metrics"][index] = value


class GarminActivityDetailMappingTests(unittest.TestCase):
    def test_mapper_version_includes_the_lap_max_speed(self):
        self.assertGreaterEqual(MAPPER_VERSION, 2)

    def test_full_fixture_maps_every_set_without_issues(self):
        result = _map(_collected())

        self.assertEqual(result.issues, ())
        self.assertEqual(len(result.records), 4)
        stream = _only(result, ActivityStreamSet)
        laps = _only(result, ActivityLapSet)
        zones = _records_of(result, ZoneDistribution)
        self.assertEqual(
            sorted(zone.metric for zone in zones),
            [
                ZoneMetric.HEART_RATE,
                ZoneMetric.POWER,
            ],
        )
        for record in (stream, laps, *zones):
            self.assertEqual(record.provider_activity_id, ID)
            self.assertEqual(record.provenance.provider, ProviderId.GARMIN)
            self.assertEqual(record.provenance.source_record_id, ID)
            self.assertEqual(record.provenance.recorded_by, RecordingOrigin.GARMIN)
            self.assertEqual(record.provenance.retrieved_at, RETRIEVED)
            self.assertEqual(record.provenance.label, "Garmin Connect")
            self.assertEqual(record.origin, ActivityDetailOrigin.FETCH)

    def test_streams_map_each_channel_with_downsampled_resolution(self):
        stream = _only(_map(_collected()), ActivityStreamSet)

        self.assertEqual(stream.resolution, StreamResolution.DOWNSAMPLED)
        self.assertEqual(
            set(stream.channels),
            {
                StreamChannel.TIME_S,
                StreamChannel.DISTANCE_M,
                StreamChannel.HEART_RATE_BPM,
                StreamChannel.CADENCE_RPM,
                StreamChannel.POWER_W,
                StreamChannel.ALTITUDE_M,
                StreamChannel.SPEED_MPS,
                StreamChannel.TEMPERATURE_C,
            },
        )
        self.assertEqual(stream.channels[StreamChannel.TIME_S], (0.0, 1.0, 2.0, 3.0))
        self.assertEqual(
            stream.channels[StreamChannel.HEART_RATE_BPM],
            (96.0, 110.0, 131.0, 147.0),
        )
        self.assertEqual(
            stream.channels[StreamChannel.DISTANCE_M], (0.0, 3.4, 7.1, 11.2)
        )

    def test_bike_cadence_wins_over_run_cadence(self):
        details = _fixture("details")
        _set_rows(details, 7, [85.0, 88.0, 90.0, 92.0])

        stream = _only(_map(_collected(details=details)), ActivityStreamSet)

        self.assertEqual(
            stream.channels[StreamChannel.CADENCE_RPM], (84.0, 86.0, 88.0, 90.0)
        )

    def test_one_leg_run_cadence_is_kept_when_bike_has_no_points(self):
        details = _fixture("details")
        _set_rows(details, 3, [None, None, None, None])
        _set_rows(details, 7, [85.0, 88.0, 90.0, 92.0])

        stream = _only(_map(_collected(details=details)), ActivityStreamSet)

        self.assertEqual(
            stream.channels[StreamChannel.CADENCE_RPM], (85.0, 88.0, 90.0, 92.0)
        )

    def test_out_of_range_point_becomes_gap_with_one_value_free_issue(self):
        details = _fixture("details")
        _set_rows(details, 2, [96.0, 400.0, 131.0, 147.0])

        result = _map(_collected(details=details))
        stream = _only(result, ActivityStreamSet)

        self.assertEqual(
            stream.channels[StreamChannel.HEART_RATE_BPM],
            (96.0, None, 131.0, 147.0),
        )
        self.assertIn(
            _issue("directHeartRate", IssueReason.OUT_OF_RANGE), result.issues
        )
        self.assertEqual(len(result.issues), 1)

    def test_unknown_metric_keys_are_ignored_silently(self):
        result = _map(_collected())

        self.assertEqual(result.issues, ())
        stream = _only(result, ActivityStreamSet)
        self.assertNotIn(StreamChannel.MOVING, stream.channels)

    def test_non_increasing_time_axis_drops_streams_only(self):
        details = _fixture("details")
        _set_rows(details, 0, [0.0, 1.0, 1.0, 2.0])

        result = _map(_collected(details=details))

        self.assertEqual(_records_of(result, ActivityStreamSet), [])
        self.assertIn(_issue("sumDuration", IssueReason.OUT_OF_RANGE), result.issues)
        _only(result, ActivityLapSet)

    def test_time_gap_drops_streams(self):
        details = _fixture("details")
        _set_rows(details, 0, [0.0, None, 2.0, 3.0])

        result = _map(_collected(details=details))

        self.assertEqual(_records_of(result, ActivityStreamSet), [])
        self.assertEqual(
            result.issues, (_issue("sumDuration", IssueReason.INVALID_NUMBER),)
        )

    def test_missing_time_metric_drops_streams_with_missing_issue(self):
        details = _fixture("details")
        details["metricDescriptors"] = [
            item
            for item in details["metricDescriptors"]
            if item["key"] != "sumDuration"
        ]

        result = _map(_collected(details=details))

        self.assertEqual(_records_of(result, ActivityStreamSet), [])
        self.assertIn(_issue("sumDuration", IssueReason.MISSING), result.issues)

    def test_elapsed_time_axis_wins_over_timer_time(self):
        details = _fixture("details")
        details["metricDescriptors"].append(
            {"metricsIndex": 10, "key": "sumElapsedDuration"}
        )
        for row, elapsed in zip(
            details["activityDetailMetrics"], (0.0, 1.0, 5.0, 6.0), strict=True
        ):
            row["metrics"].append(elapsed)

        streams = _only(_map(_collected(details=details)), ActivityStreamSet)

        self.assertEqual(streams.channels[StreamChannel.TIME_S], (0.0, 1.0, 5.0, 6.0))

    def test_short_unknown_trailing_metric_keeps_streams(self):
        details = _fixture("details")
        details["activityDetailMetrics"][1]["metrics"].pop()

        _only(_map(_collected(details=details)), ActivityStreamSet)

    def test_short_metric_row_drops_streams_as_length_mismatch(self):
        details = _fixture("details")
        details["activityDetailMetrics"][1]["metrics"] = [1.0, 3.4]

        result = _map(_collected(details=details))

        self.assertEqual(_records_of(result, ActivityStreamSet), [])
        self.assertIn(
            _issue("activityDetailMetrics", IssueReason.INVALID_TYPE), result.issues
        )

    def test_lap_run_cadence_is_not_mapped(self):
        splits = _fixture("splits")
        del splits["lapDTOs"][0]["averageBikeCadence"]
        splits["lapDTOs"][0]["averageRunCadence"] = 176.0

        result = _map(_collected(splits=splits))
        laps = _only(result, ActivityLapSet)

        self.assertIsNone(laps.laps[1].avg_cadence)
        self.assertEqual(result.issues, ())

    def test_laps_are_ordered_by_lap_index_with_cumulative_offsets(self):
        result = _map(_collected())
        laps = _only(result, ActivityLapSet)

        self.assertEqual(laps.lap_source, LapSource.DEVICE_LAPS)
        self.assertEqual([lap.index for lap in laps.laps], [0, 1])
        first, second = laps.laps
        self.assertEqual((first.start_offset_s, first.end_offset_s), (0.0, 300.0))
        self.assertEqual((second.start_offset_s, second.end_offset_s), (300.0, 540.0))
        self.assertEqual(first.avg_hr, 138.0)
        self.assertEqual(first.avg_cadence, 86.0)
        self.assertEqual(first.moving_duration_s, 299.0)
        self.assertEqual(second.normalized_power, 248.0)
        self.assertEqual(second.avg_speed_mps, 4.17)

    def test_laps_keep_input_order_without_lap_index(self):
        splits = _fixture("splits")
        for row in splits["lapDTOs"]:
            del row["lapIndex"]

        laps = _only(_map(_collected(splits=splits)), ActivityLapSet)

        self.assertEqual(laps.laps[0].end_offset_s, 240.0)
        self.assertEqual(laps.laps[0].avg_hr, 150.0)
        self.assertEqual(laps.laps[1].start_offset_s, 240.0)

    def test_lap_max_speed_is_mapped_and_out_of_range_values_are_dropped(self):
        splits = _fixture("splits")
        # lapDTOs[1] has the lower lapIndex, so it becomes the first lap.
        splits["lapDTOs"][1]["maxSpeed"] = 6.5
        splits["lapDTOs"][0]["maxSpeed"] = 500.0

        result = _map(_collected(splits=splits))
        first, second = _only(result, ActivityLapSet).laps

        self.assertEqual(first.max_speed_mps, 6.5)
        self.assertIsNone(second.max_speed_mps)
        self.assertIn(_issue("maxSpeed", IssueReason.OUT_OF_RANGE), result.issues)

    def test_invalid_lap_metric_is_dropped_and_lap_is_kept(self):
        splits = _fixture("splits")
        splits["lapDTOs"][0]["averageHR"] = "fast"

        result = _map(_collected(splits=splits))
        laps = _only(result, ActivityLapSet)

        self.assertIsNone(laps.laps[1].avg_hr)
        self.assertEqual(laps.laps[1].avg_power, 240.0)
        self.assertIn(_issue("averageHR", IssueReason.INVALID_NUMBER), result.issues)

    def test_invalid_duration_ends_the_laps_at_that_lap(self):
        splits = _fixture("splits")
        # lapIndex 2 sorts last: the first lap is kept, nothing after the bad one.
        splits["lapDTOs"][0]["duration"] = -5.0

        result = _map(_collected(splits=splits))
        laps = _only(result, ActivityLapSet)

        self.assertEqual(len(laps.laps), 1)
        self.assertEqual(
            (laps.laps[0].start_offset_s, laps.laps[0].end_offset_s), (0.0, 300.0)
        )
        self.assertIn(_issue("duration", IssueReason.OUT_OF_RANGE), result.issues)

    def test_invalid_first_lap_duration_keeps_no_shifted_laps(self):
        splits = _fixture("splits")
        splits["lapDTOs"][1]["duration"] = None

        result = _map(_collected(splits=splits))

        self.assertEqual(_records_of(result, ActivityLapSet), [])
        self.assertIn(_issue("duration", IssueReason.MISSING), result.issues)

    def test_elapsed_lap_duration_wins_over_timer_duration(self):
        splits = _fixture("splits")
        splits["lapDTOs"][1]["elapsedDuration"] = 330.0

        laps = _only(_map(_collected(splits=splits)), ActivityLapSet)

        self.assertEqual(laps.laps[0].end_offset_s, 330.0)
        self.assertEqual(
            (laps.laps[1].start_offset_s, laps.laps[1].end_offset_s), (330.0, 570.0)
        )

    def test_laps_without_usable_duration_produce_no_lap_set(self):
        splits = {"lapDTOs": [{"duration": "later"}]}

        result = _map(_collected(splits=splits))

        self.assertEqual(_records_of(result, ActivityLapSet), [])
        self.assertEqual(
            result.issues, (_issue("duration", IssueReason.INVALID_NUMBER),)
        )

    def test_lap_count_is_capped_at_max_laps(self):
        splits = {"lapDTOs": [{"duration": 1.0} for _ in range(201)]}

        result = _map(_collected(splits=splits))
        laps = _only(result, ActivityLapSet)

        self.assertEqual(len(laps.laps), 200)
        self.assertEqual(laps.laps[-1].end_offset_s, 200.0)
        self.assertIn(_issue("lapDTOs", IssueReason.OUT_OF_RANGE), result.issues)

    def test_provider_zone_boundaries_fill_lower_and_upper(self):
        result = _map(_collected())
        hr = next(
            zone
            for zone in _records_of(result, ZoneDistribution)
            if zone.metric is ZoneMetric.HEART_RATE
        )

        self.assertEqual(hr.boundary_source, ZoneBoundarySource.PROVIDER_REPORTED)
        self.assertEqual(
            [bucket.lower for bucket in hr.buckets], [0, 110, 130, 150, 170]
        )
        self.assertEqual(
            [bucket.upper for bucket in hr.buckets], [110, 130, 150, 170, None]
        )
        self.assertEqual(
            [bucket.seconds for bucket in hr.buckets], [120, 600, 900, 300, 30]
        )

    def test_missing_zone_boundary_marks_distribution_unknown(self):
        hr_zones = _fixture("hr_zones")
        del hr_zones[2]["zoneLowBoundary"]

        result = _map(_collected(hr_zones=hr_zones))
        hr = next(
            zone
            for zone in _records_of(result, ZoneDistribution)
            if zone.metric is ZoneMetric.HEART_RATE
        )

        self.assertEqual(hr.boundary_source, ZoneBoundarySource.UNKNOWN)
        self.assertTrue(all(bucket.lower is None for bucket in hr.buckets))
        self.assertTrue(all(bucket.upper is None for bucket in hr.buckets))
        self.assertEqual(result.issues, ())

    def test_duplicate_zone_drops_only_that_distribution(self):
        hr_zones = _fixture("hr_zones")
        hr_zones[3]["zoneNumber"] = 3

        result = _map(_collected(hr_zones=hr_zones))

        metrics = [zone.metric for zone in _records_of(result, ZoneDistribution)]
        self.assertEqual(metrics, [ZoneMetric.POWER])
        self.assertEqual(result.issues, (_issue("hr_zones", IssueReason.OUT_OF_RANGE),))

    def test_zone_gap_drops_distribution(self):
        power_zones = _fixture("power_zones")
        power_zones[3]["zoneNumber"] = 6

        result = _map(_collected(power_zones=power_zones))

        self.assertEqual(
            [zone.metric for zone in _records_of(result, ZoneDistribution)],
            [ZoneMetric.HEART_RATE],
        )
        self.assertEqual(
            result.issues, (_issue("power_zones", IssueReason.OUT_OF_RANGE),)
        )

    def test_non_positive_zone_number_drops_distribution(self):
        hr_zones = _fixture("hr_zones")
        hr_zones[0]["zoneNumber"] = 0

        result = _map(_collected(hr_zones=hr_zones))

        self.assertEqual(result.issues, (_issue("hr_zones", IssueReason.OUT_OF_RANGE),))

    def test_invalid_seconds_drop_distribution_with_one_issue(self):
        power_zones = _fixture("power_zones")
        power_zones[1]["secsInZone"] = "lots"

        result = _map(_collected(power_zones=power_zones))

        self.assertEqual(
            [zone.metric for zone in _records_of(result, ZoneDistribution)],
            [ZoneMetric.HEART_RATE],
        )
        self.assertEqual(
            result.issues, (_issue("power_zones", IssueReason.INVALID_NUMBER),)
        )

    def test_decreasing_boundaries_keep_seconds_with_unknown_bounds(self):
        power_zones = _fixture("power_zones")
        power_zones[2]["zoneLowBoundary"] = 90

        result = _map(_collected(power_zones=power_zones))

        power = next(
            z
            for z in _records_of(result, ZoneDistribution)
            if z.metric is ZoneMetric.POWER
        )
        self.assertEqual(power.boundary_source, ZoneBoundarySource.UNKNOWN)
        self.assertEqual({bucket.lower for bucket in power.buckets}, {None})
        self.assertEqual(result.issues, ())

    def test_absent_parts_are_silent(self):
        result = _map({"activity_id": ID})

        self.assertEqual(result.records, ())
        self.assertEqual(result.issues, ())

    def test_missing_or_blank_activity_id_maps_nothing(self):
        for value, reason in (
            (None, IssueReason.MISSING),
            ("   ", IssueReason.MISSING),
            (123, IssueReason.INVALID_TYPE),
            ("x" * 201, IssueReason.OUT_OF_RANGE),
        ):
            with self.subTest(value=reason):
                result = _map({**_collected(), "activity_id": value})

                self.assertEqual(result.records, ())
                self.assertEqual(
                    result.issues, (MappingIssue(None, "activity_id", reason),)
                )

    def test_malformed_inputs_never_raise(self):
        cases = [
            None,
            "x",
            7,
            [],
            {},
            {"activity_id": ID, "details": "x"},
            {"activity_id": ID, "details": {"metricDescriptors": "x"}},
            {
                "activity_id": ID,
                "details": {"metricDescriptors": [None], "activityDetailMetrics": []},
            },
            {
                "activity_id": ID,
                "details": {
                    "metricDescriptors": [{"key": "sumDuration", "metricsIndex": True}],
                    "activityDetailMetrics": [{"metrics": []}],
                },
            },
            {
                "activity_id": ID,
                "details": {
                    "metricDescriptors": [
                        {"key": "sumDuration", "metricsIndex": 10**9}
                    ],
                    "activityDetailMetrics": [{"metrics": [1.0]}],
                },
            },
            {
                "activity_id": ID,
                "details": {
                    "metricDescriptors": [{"key": "sumDuration", "metricsIndex": 0}],
                    "activityDetailMetrics": [None],
                },
            },
            {"activity_id": ID, "splits": "x"},
            {"activity_id": ID, "splits": {"lapDTOs": 5}},
            {"activity_id": ID, "splits": {"lapDTOs": [None, "x"]}},
            {"activity_id": ID, "splits": {"lapDTOs": [{"duration": float("nan")}]}},
            {"activity_id": ID, "hr_zones": {"a": 1}},
            {"activity_id": ID, "hr_zones": [None]},
            {"activity_id": ID, "power_zones": [{"zoneNumber": True}]},
            {
                "activity_id": ID,
                "power_zones": [{"zoneNumber": 1, "secsInZone": float("nan")}],
            },
        ]
        for case in cases:
            with self.subTest(case=repr(case)[:60]):
                result = _map(case)

                self.assertIsInstance(result, MappingResult)
                self.assertTrue(all(isinstance(i, MappingIssue) for i in result.issues))

    def test_issues_never_contain_provider_values(self):
        details = _fixture("details")
        _set_rows(details, 2, ["SENTINEL-4242", 96.0, 131.0, 147.0])
        splits = _fixture("splits")
        splits["lapDTOs"][0]["averageHR"] = "SENTINEL-7319"

        result = _map(_collected(details=details, splits=splits))

        self.assertTrue(result.issues)
        for issue in result.issues:
            self.assertNotIn("SENTINEL", repr(issue))
            self.assertEqual(issue.record_ref, ID)

    def test_caller_arguments_are_checked(self):
        with self.assertRaises(TypeError):
            map_garmin_activity_detail(
                _collected(), recorded_by="garmin", retrieved_at=RETRIEVED
            )
        with self.assertRaises(ValueError):
            map_garmin_activity_detail(
                _collected(),
                recorded_by=RecordingOrigin.GARMIN,
                retrieved_at=datetime(2026, 10, 18, 8, 0),  # noqa: DTZ001 - naive on purpose
            )


if __name__ == "__main__":
    unittest.main()
