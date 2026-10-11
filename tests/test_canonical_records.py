"""Record construction, units, provenance and validation contracts."""

from __future__ import annotations

import math
import unittest
from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime
from typing import Any

from backend.canonical.records import (
    ActivityRecord,
    MetricValue,
    Observation,
    Provenance,
)
from backend.canonical.validation import (
    METRIC_BOUNDS,
    bounded_number,
    finite_number,
    optional_aware_datetime,
    optional_bounded_number,
    optional_text,
    require_aware_datetime,
    require_date,
    require_text,
    validate_metric_value,
)
from backend.canonical.vocabulary import (
    Environment,
    LoadModel,
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)

UTC_MORNING = datetime(2026, 3, 1, 7, 30, tzinfo=UTC)
NAIVE_MORNING = datetime.fromisoformat("2026-03-01T07:30:00")


def untyped(value: object) -> Any:
    """Pass deliberately wrong types through static checks."""
    return value


def provenance(**overrides: Any) -> Provenance:
    values: dict[str, Any] = {
        "provider": ProviderId.GARMIN,
        "source_kind": SourceKind.PROVIDER_REPORTED,
        "source_record_id": "fake-record-1",
        "recorded_by": RecordingOrigin.GARMIN,
        "retrieved_at": UTC_MORNING,
        "label": "Fake Garmin export",
    }
    values.update(overrides)
    return Provenance(**values)


def observation(**overrides: Any) -> Observation:
    values: dict[str, Any] = {
        "kind": MetricKind.WEIGHT,
        "value": MetricValue(72.5, "kg"),
        "observed_on": date(2026, 3, 1),
        "observed_at": UTC_MORNING,
        "provenance": provenance(),
    }
    values.update(overrides)
    return Observation(**values)


def activity(**overrides: Any) -> ActivityRecord:
    values: dict[str, Any] = {
        "activity_id": "fake-activity-1",
        "provenance": provenance(provider=ProviderId.INTERVALS),
        "sport": Sport.RIDE,
        "environment": Environment.OUTDOOR,
        "started_at": UTC_MORNING,
        "duration_s": 3600.0,
        "distance_m": 40_000.0,
        "load": 85.0,
        "load_model": LoadModel.INTERVALS_TRAINING_LOAD,
        "avg_hr": 142.0,
        "avg_power": 190.0,
        "name": "Fake morning ride",
    }
    values.update(overrides)
    return ActivityRecord(**values)


class MetricValueTests(unittest.TestCase):
    def test_accepts_finite_numbers_with_unit(self) -> None:
        self.assertEqual(72.5, MetricValue(72.5, "kg").value)
        self.assertEqual(72, MetricValue(72, "kg").value)

    def test_stores_integers_as_floats(self) -> None:
        self.assertIsInstance(MetricValue(72, "kg").value, float)

    def test_rejects_integers_too_large_for_float(self) -> None:
        with self.assertRaisesRegex(ValueError, "value must be finite"):
            MetricValue(10**400, "kg")

    def test_rejects_non_finite_numbers(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "must be finite"),
            ):
                MetricValue(value, "kg")

    def test_rejects_booleans_text_and_none_as_numbers(self) -> None:
        for value in (True, "72.5", None):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(TypeError, "must be a number"),
            ):
                MetricValue(untyped(value), "kg")

    def test_rejects_blank_or_overlong_units(self) -> None:
        with self.assertRaisesRegex(ValueError, "unit must be non-empty text"):
            MetricValue(1.0, "   ")
        with self.assertRaisesRegex(ValueError, "at most 16 characters"):
            MetricValue(1.0, "k" * 17)


class ObservationTests(unittest.TestCase):
    def test_accepts_matching_unit_and_is_immutable(self) -> None:
        record = observation()
        self.assertEqual(MetricKind.WEIGHT, record.kind)
        self.assertEqual(72.5, record.value.value)
        self.assertFalse(hasattr(record, "__dict__"))
        with self.assertRaises(FrozenInstanceError):
            record.kind = MetricKind.FTP  # type: ignore[misc]

    def test_rejects_unit_that_does_not_match_kind(self) -> None:
        with self.assertRaisesRegex(ValueError, "weight must use unit 'kg'"):
            observation(value=MetricValue(72.5, "lb"))
        with self.assertRaisesRegex(ValueError, "body_fat must use unit '%'"):
            observation(kind=MetricKind.BODY_FAT, value=MetricValue(20.0, "kg"))

    def test_rejects_values_outside_metric_bounds(self) -> None:
        cases = (
            (MetricKind.WEIGHT, 1000.0),
            (MetricKind.THRESHOLD_HR, 300.0),
            (MetricKind.SLEEP_SCORE, -1.0),
            (MetricKind.VO2MAX, 200.0),
            (MetricKind.HRV_RMSSD, math.nan),
        )
        for kind, value in cases:
            with (
                self.subTest(kind=kind.value, value=value),
                self.assertRaises(ValueError),
            ):
                observation(kind=kind, value=MetricValue(value, kind.unit))

    def test_accepts_optional_observed_at_as_none_not_zero(self) -> None:
        record = observation(observed_at=None)
        self.assertIsNone(record.observed_at)

    def test_rejects_naive_observed_at(self) -> None:
        with self.assertRaisesRegex(ValueError, "observed_at must be"):
            observation(observed_at=NAIVE_MORNING)

    def test_rejects_datetime_or_text_as_observed_on(self) -> None:
        with self.assertRaisesRegex(TypeError, "observed_on must be a date"):
            observation(observed_on=UTC_MORNING)
        with self.assertRaisesRegex(TypeError, "observed_on must be a date"):
            observation(observed_on="2026-03-01")

    def test_rejects_wrong_nested_types(self) -> None:
        with self.assertRaisesRegex(TypeError, "kind must be a MetricKind"):
            observation(kind="weight")
        with self.assertRaisesRegex(TypeError, "value must be a MetricValue"):
            observation(value=untyped(72.5))
        with self.assertRaisesRegex(TypeError, "provenance must be a Provenance"):
            observation(provenance="garmin")


class ProvenanceTests(unittest.TestCase):
    def test_accepts_missing_optional_fields_as_none(self) -> None:
        record = provenance(
            source_record_id=None,
            retrieved_at=None,
            label=None,
        )
        self.assertIsNone(record.source_record_id)
        self.assertIsNone(record.retrieved_at)
        self.assertIsNone(record.label)

    def test_rejects_provider_and_origin_given_as_text(self) -> None:
        with self.assertRaisesRegex(TypeError, "provider must be a ProviderId"):
            provenance(provider="garmin")
        with self.assertRaisesRegex(TypeError, "source_kind must be a SourceKind"):
            provenance(source_kind="derived")
        with self.assertRaisesRegex(TypeError, "recorded_by must be a RecordingOrigin"):
            provenance(recorded_by="garmin")

    def test_athlete_ai_and_profile_values_carry_no_provider(self) -> None:
        for source_kind in (
            SourceKind.ATHLETE_ENTERED,
            SourceKind.AI_ESTIMATE,
            SourceKind.PROFILE,
        ):
            with self.subTest(source_kind=source_kind.value):
                record = provenance(provider=None, source_kind=source_kind)
                self.assertIsNone(record.provider)

    def test_derived_values_may_name_their_provider(self) -> None:
        self.assertIsNone(
            provenance(provider=None, source_kind=SourceKind.DERIVED).provider
        )
        self.assertEqual(
            ProviderId.INTERVALS,
            provenance(
                provider=ProviderId.INTERVALS, source_kind=SourceKind.DERIVED
            ).provider,
        )

    def test_provider_reported_and_device_values_require_a_provider(self) -> None:
        for source_kind in (SourceKind.PROVIDER_REPORTED, SourceKind.DEVICE_MEASURED):
            with (
                self.subTest(source_kind=source_kind.value),
                self.assertRaisesRegex(
                    ValueError, f"provider is required for {source_kind.value}"
                ),
            ):
                provenance(provider=None, source_kind=source_kind)

    def test_rejects_provider_attribution_for_athlete_ai_and_profile_values(
        self,
    ) -> None:
        for source_kind in (
            SourceKind.ATHLETE_ENTERED,
            SourceKind.AI_ESTIMATE,
            SourceKind.PROFILE,
        ):
            with (
                self.subTest(source_kind=source_kind.value),
                self.assertRaisesRegex(
                    ValueError, f"provider must be None for {source_kind.value}"
                ),
            ):
                provenance(provider=ProviderId.GARMIN, source_kind=source_kind)

    def test_rejects_naive_retrieved_at(self) -> None:
        with self.assertRaisesRegex(ValueError, "retrieved_at must be"):
            provenance(retrieved_at=NAIVE_MORNING)

    def test_rejects_blank_or_overlong_text(self) -> None:
        with self.assertRaisesRegex(ValueError, "source_record_id must be non-empty"):
            provenance(source_record_id="   ")
        with self.assertRaisesRegex(ValueError, "label must be at most 256"):
            provenance(label="x" * 257)


class ActivityRecordTests(unittest.TestCase):
    def test_accepts_zero_as_a_real_measurement(self) -> None:
        record = activity(duration_s=0.0, avg_power=0.0)
        self.assertEqual(0.0, record.duration_s)
        self.assertEqual(0.0, record.avg_power)

    def test_stores_numeric_measurements_as_floats(self) -> None:
        record = activity(duration_s=3600, avg_power=190)
        self.assertIsInstance(record.duration_s, float)
        self.assertIsInstance(record.avg_power, float)

    def test_keeps_missing_measurements_as_none(self) -> None:
        record = activity(
            duration_s=None,
            distance_m=None,
            load=None,
            avg_hr=None,
            avg_power=None,
            name=None,
        )
        self.assertIsNone(record.duration_s)
        self.assertIsNone(record.distance_m)
        self.assertIsNone(record.load)
        self.assertIsNone(record.avg_hr)
        self.assertIsNone(record.avg_power)
        self.assertIsNone(record.name)

    def test_rejects_negative_durations_distances_loads_and_power(self) -> None:
        for field in ("duration_s", "distance_m", "load", "avg_power"):
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(ValueError, f"{field} must be between"),
            ):
                activity(**{field: -1.0})

    def test_rejects_overlong_or_non_finite_measurements(self) -> None:
        with self.assertRaisesRegex(ValueError, "duration_s must be between"):
            activity(duration_s=8 * 24 * 3600.0)
        with self.assertRaisesRegex(ValueError, "distance_m must be finite"):
            activity(distance_m=math.inf)

    def test_rejects_implausible_heart_rate(self) -> None:
        for avg_hr in (5.0, 300.0):
            with (
                self.subTest(avg_hr=avg_hr),
                self.assertRaisesRegex(ValueError, "avg_hr must be between 20 and 250"),
            ):
                activity(avg_hr=avg_hr)

    def test_requires_timezone_aware_start(self) -> None:
        with self.assertRaisesRegex(ValueError, "started_at must be"):
            activity(started_at=NAIVE_MORNING)
        with self.assertRaisesRegex(TypeError, "started_at must be a datetime"):
            activity(started_at="2026-03-01T07:30:00+00:00")

    def test_rejects_blank_identifier_and_wrong_enum_types(self) -> None:
        with self.assertRaisesRegex(ValueError, "activity_id must be non-empty"):
            activity(activity_id="  ")
        with self.assertRaisesRegex(TypeError, "sport must be a Sport"):
            activity(sport="ride")
        with self.assertRaisesRegex(TypeError, "environment must be a Environment"):
            activity(environment="outdoor")
        with self.assertRaisesRegex(TypeError, "load_model must be a LoadModel"):
            activity(load_model="trimp")
        with self.assertRaisesRegex(TypeError, "provenance must be a Provenance"):
            activity(provenance=untyped("garmin"))

    def test_rejects_overlong_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "name must be at most 200"):
            activity(name="n" * 201)


class ValidationHelperTests(unittest.TestCase):
    def test_every_metric_kind_has_ordered_bounds(self) -> None:
        self.assertEqual(set(MetricKind), set(METRIC_BOUNDS))
        for kind, (lower, upper) in METRIC_BOUNDS.items():
            with self.subTest(kind=kind.value):
                self.assertLess(lower, upper)

    def test_validate_metric_value_checks_unit_then_bounds(self) -> None:
        validate_metric_value(MetricKind.READINESS, 80.0, "score")
        with self.assertRaisesRegex(ValueError, "readiness must use unit"):
            validate_metric_value(MetricKind.READINESS, 80.0, "%")
        with self.assertRaisesRegex(ValueError, "readiness value must be between"):
            validate_metric_value(MetricKind.READINESS, 101.0, "score")

    def test_finite_and_bounded_numbers(self) -> None:
        self.assertEqual(3.0, finite_number(3, "count"))
        self.assertEqual(5.0, bounded_number(5, "count", 0.0, 10.0))
        with self.assertRaisesRegex(ValueError, "count must be between 0 and 10"):
            bounded_number(11, "count", 0.0, 10.0)
        self.assertIsNone(optional_bounded_number(None, "count", 0.0, 10.0))
        self.assertEqual(2.0, optional_bounded_number(2.0, "count", 0.0, 10.0))

    def test_text_helpers(self) -> None:
        self.assertEqual(" ok ", require_text(" ok ", "name"))
        self.assertIsNone(optional_text(None, "name"))
        self.assertEqual("ok", optional_text("ok", "name"))
        with self.assertRaisesRegex(TypeError, "name must be text"):
            require_text(untyped(12), "name")
        with self.assertRaisesRegex(ValueError, "name must be non-empty"):
            require_text("   ", "name")
        with self.assertRaisesRegex(ValueError, "name must be at most 3"):
            require_text("abcd", "name", max_length=3)

    def test_datetime_and_date_helpers(self) -> None:
        self.assertIs(UTC_MORNING, require_aware_datetime(UTC_MORNING, "at"))
        self.assertIsNone(optional_aware_datetime(None, "at"))
        self.assertIs(UTC_MORNING, optional_aware_datetime(UTC_MORNING, "at"))
        with self.assertRaisesRegex(TypeError, "at must be a datetime"):
            require_aware_datetime(untyped(date(2026, 3, 1)), "at")
        with self.assertRaisesRegex(ValueError, "at must be timezone-aware"):
            optional_aware_datetime(NAIVE_MORNING, "at")
        self.assertEqual(date(2026, 3, 1), require_date(date(2026, 3, 1), "day"))
        with self.assertRaisesRegex(TypeError, "day must be a date"):
            require_date(UTC_MORNING, "day")


if __name__ == "__main__":
    unittest.main()
