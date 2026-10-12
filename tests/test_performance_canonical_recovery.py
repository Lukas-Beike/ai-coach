"""Current sleep score, resting HR and readiness read from canonical observations.

The canonical value replaces the legacy value only when it is the record the legacy
reader picked and carries the same number, so the serialized recovery output stays
byte-identical. A populated temporary database is the end-to-end check. Every
provider is mocked by fixtures and all storage is temporary.
"""

from __future__ import annotations

import json
import unittest
from datetime import UTC, date, datetime
from typing import Any
from unittest.mock import patch

from canonical_consumer_parity import TODAY
from canonical_read_support import CanonicalReadFixture, make_selector, populate

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.performance import recovery_context
from backend.performance.canonical_inputs import read_performance_inputs
from backend.performance.canonical_recovery import (
    CanonicalRecoveryInputs,
    prefer_canonical,
    read_recovery_inputs,
)
from backend.performance.context import current_performance_context

DAY = "2026-09-20"
EARLIER = "2026-09-19"
RETRIEVED = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
UNITS = {
    MetricKind.SLEEP_SCORE: "score",
    MetricKind.RESTING_HR: "bpm",
    MetricKind.READINESS: "score",
}


def _observation(
    kind: MetricKind,
    value: float,
    day: str = DAY,
    provider: ProviderId = ProviderId.GARMIN,
) -> Observation:
    recorded_by = (
        RecordingOrigin.GARMIN
        if provider is ProviderId.GARMIN
        else RecordingOrigin.MANUAL
    )
    return Observation(
        kind=kind,
        value=MetricValue(value, UNITS[kind]),
        observed_on=date.fromisoformat(day),
        observed_at=None,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=f"{kind.value}-{day}",
            recorded_by=recorded_by,
            retrieved_at=RETRIEVED,
            label=None,
        ),
    )


class _FakeReader:
    """Serves fixed observations per kind and records each read."""

    def __init__(self, by_kind: dict[MetricKind, list[Observation]]) -> None:
        self._by_kind = by_kind
        self.calls: list[tuple[MetricKind, date | None, date | None]] = []

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        self.calls.append((kind, start, end))
        return tuple(self._by_kind.get(kind, []))


def _garmin(sleep_score: int = 84, resting: int = 45) -> dict[str, Any]:
    return {
        "sleep": [
            {"calendarDate": DAY, "sleepTimeSeconds": 26400, "sleepScore": sleep_score}
        ],
        "resting_hr": [{"calendarDate": DAY, "restingHeartRate": resting}],
    }


def _latest(**extra: Any) -> dict[str, Any]:
    return {"id": DAY, "sleepSecs": 27000, "sleepScore": 81, "readiness": 74, **extra}


def _recovery(
    garmin: dict[str, Any],
    latest: dict[str, Any],
    canonical: CanonicalRecoveryInputs | None,
) -> dict[str, Any]:
    return recovery_context.performance_recovery_context(
        garmin, latest, [latest], TODAY, canonical=canonical
    )


def _dump(value: Any) -> str:
    return json.dumps(value, default=str)


class PreferCanonicalTests(unittest.TestCase):
    def test_missing_observation_keeps_the_legacy_value(self) -> None:
        self.assertEqual(prefer_canonical(None, 81, ProviderId.GARMIN), 81)

    def test_non_numeric_legacy_values_are_always_kept(self) -> None:
        observation = _observation(MetricKind.SLEEP_SCORE, 1.0)
        for legacy in ("81", True, None):
            with self.subTest(legacy=legacy):
                kept = prefer_canonical(observation, legacy, ProviderId.GARMIN)
                self.assertIs(kept, legacy)

    def test_other_provider_keeps_the_legacy_value(self) -> None:
        observation = _observation(
            MetricKind.SLEEP_SCORE, 81, provider=ProviderId.INTERVALS
        )
        self.assertEqual(prefer_canonical(observation, 81, ProviderId.GARMIN), 81)

    def test_other_day_keeps_the_legacy_value(self) -> None:
        observation = _observation(MetricKind.RESTING_HR, 45, day=EARLIER)
        kept = prefer_canonical(observation, 45, ProviderId.GARMIN, DAY)
        self.assertEqual(kept, 45)

    def test_different_number_keeps_the_legacy_value(self) -> None:
        observation = _observation(MetricKind.READINESS, 80.0)
        self.assertEqual(prefer_canonical(observation, 74, ProviderId.GARMIN), 74)

    def test_matching_record_keeps_the_legacy_type(self) -> None:
        integer = _observation(MetricKind.SLEEP_SCORE, 81.0)
        fraction = _observation(MetricKind.READINESS, 81.5)
        served_int = prefer_canonical(integer, 81, ProviderId.GARMIN, DAY)
        served_float = prefer_canonical(fraction, 81.5, ProviderId.GARMIN, DAY)
        self.assertIs(type(served_int), int)
        self.assertEqual(served_int, 81)
        self.assertIs(type(served_float), float)
        self.assertEqual(served_float, 81.5)

    def test_absent_day_skips_the_day_check(self) -> None:
        observation = _observation(MetricKind.RESTING_HR, 45, day=EARLIER)
        self.assertEqual(prefer_canonical(observation, 45, ProviderId.GARMIN), 45)


class ReadRecoveryInputsTests(unittest.TestCase):
    def test_each_kind_is_read_from_the_window_start_without_an_end_bound(
        self,
    ) -> None:
        reader = _FakeReader({})
        start = date.fromisoformat(EARLIER)
        inputs = read_recovery_inputs(
            reader, None, latest_wellness_day=date.fromisoformat(DAY), start=start
        )
        self.assertEqual(
            reader.calls,
            [
                (MetricKind.SLEEP_SCORE, start, None),
                (MetricKind.RESTING_HR, start, None),
                (MetricKind.READINESS, start, None),
            ],
        )
        self.assertEqual(inputs, CanonicalRecoveryInputs(None, None, None))

    def test_each_field_selects_the_observation_of_the_latest_day(self) -> None:
        older = _observation(MetricKind.SLEEP_SCORE, 70.0, day=EARLIER)
        latest = _observation(MetricKind.SLEEP_SCORE, 84.0)
        reader = _FakeReader(
            {
                MetricKind.SLEEP_SCORE: [older, latest],
                MetricKind.RESTING_HR: [_observation(MetricKind.RESTING_HR, 45.0)],
            }
        )
        inputs = read_recovery_inputs(
            reader,
            None,
            latest_wellness_day=date.fromisoformat(DAY),
            start=date.fromisoformat(EARLIER),
        )
        self.assertEqual(inputs.sleep_score, latest)
        assert inputs.resting_hr is not None
        self.assertEqual(inputs.resting_hr.value.value, 45.0)
        self.assertIsNone(inputs.readiness)


class RecoveryContextTests(unittest.TestCase):
    def test_garmin_values_with_matching_canonical_records_match_legacy(self) -> None:
        garmin, latest = _garmin(), _latest()
        canonical = CanonicalRecoveryInputs(
            sleep_score=_observation(MetricKind.SLEEP_SCORE, 84.0),
            resting_hr=_observation(MetricKind.RESTING_HR, 45.0),
            readiness=None,
        )
        legacy = _recovery(garmin, latest, None)
        served = _recovery(garmin, latest, canonical)
        self.assertEqual(_dump(served), _dump(legacy))
        self.assertEqual(served["sleep_score"], 84)
        self.assertIs(type(served["sleep_score"]), int)

    def test_mismatched_canonical_records_fall_back_to_legacy(self) -> None:
        garmin, latest = _garmin(), _latest()
        canonical = CanonicalRecoveryInputs(
            sleep_score=_observation(MetricKind.SLEEP_SCORE, 70.0),
            resting_hr=_observation(
                MetricKind.RESTING_HR, 45.0, provider=ProviderId.INTERVALS
            ),
            readiness=_observation(MetricKind.READINESS, 74.0, day=EARLIER),
        )
        legacy = _recovery(garmin, latest, None)
        self.assertEqual(_dump(_recovery(garmin, latest, canonical)), _dump(legacy))

    def test_intervals_fallback_uses_the_matching_canonical_records(self) -> None:
        latest = _latest()
        canonical = CanonicalRecoveryInputs(
            sleep_score=_observation(
                MetricKind.SLEEP_SCORE, 81.0, provider=ProviderId.INTERVALS
            ),
            resting_hr=None,
            readiness=_observation(
                MetricKind.READINESS, 74.0, provider=ProviderId.INTERVALS
            ),
        )
        legacy = _recovery({}, latest, None)
        served = _recovery({}, latest, canonical)
        self.assertEqual(_dump(served), _dump(legacy))
        self.assertEqual(served["sleep_score_source"], "Intervals.icu Wellness")
        self.assertEqual(served["readiness"], 74)

    def test_garmin_readiness_uses_the_matching_canonical_record(self) -> None:
        garmin = {"readiness": 70}
        latest = {"id": DAY}
        canonical = CanonicalRecoveryInputs(
            sleep_score=None,
            resting_hr=None,
            readiness=_observation(MetricKind.READINESS, 70.0),
        )
        legacy = _recovery(garmin, latest, None)
        served = _recovery(garmin, latest, canonical)
        self.assertEqual(_dump(served), _dump(legacy))
        self.assertEqual(served["readiness"], 70)

    def test_canonical_offer_is_made_for_the_matching_garmin_sleep_score(self) -> None:
        canonical = CanonicalRecoveryInputs(
            sleep_score=_observation(MetricKind.SLEEP_SCORE, 84.0),
            resting_hr=None,
            readiness=None,
        )
        with patch.object(
            recovery_context,
            "prefer_canonical",
            wraps=recovery_context.prefer_canonical,
        ) as spy:
            _recovery(_garmin(), _latest(), canonical)
        offered = [call.args[0] for call in spy.call_args_list]
        self.assertIn(canonical.sleep_score, offered)


class PopulatedRecoveryTests(CanonicalReadFixture):
    def test_populated_tables_reproduce_the_legacy_recovery_bytes(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)
        self.assertEqual(self.write(selector.summary)["serving"], "tables")
        with self.manager.reader() as db:
            inputs = read_performance_inputs(selector, db, self.intervals)
        self.assertIsNotNone(inputs)
        assert inputs is not None
        assert inputs.recovery is not None
        self.assertIsNotNone(inputs.recovery.sleep_score)
        legacy = current_performance_context(self.intervals, self.garmin, {}, TODAY)
        with patch.object(
            recovery_context,
            "prefer_canonical",
            wraps=recovery_context.prefer_canonical,
        ) as spy:
            canonical = current_performance_context(
                self.intervals, self.garmin, {}, TODAY, canonical=inputs
            )
        self.assertEqual(_dump(canonical["recovery"]), _dump(legacy["recovery"]))
        self.assertEqual(_dump(canonical), _dump(legacy))
        served = [
            call.args[0] for call in spy.call_args_list if call.args[0] is not None
        ]
        self.assertTrue(served, "no canonical recovery observation was offered")

    def test_selector_resolves_its_source_once_for_the_recovery_read(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)
        with (
            patch.object(selector, "reader_for", wraps=selector.reader_for) as resolved,
            self.manager.reader() as db,
        ):
            inputs = read_performance_inputs(selector, db, self.intervals)
        resolved.assert_called_once()
        self.assertIsNotNone(inputs)
