"""Personal recovery resting HR read from canonical observations.

The canonical resting HR replaces a legacy baseline value only when it is the
record the legacy baseline picked: the same provider, the same day and the same
number. The labels of every personal recovery source stay byte-identical. A
populated temporary database is the end-to-end check. Every provider is mocked by
fixtures and all storage is temporary.
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
from backend.performance import personal_recovery as personal_module
from backend.performance.canonical_inputs import read_performance_inputs
from backend.performance.canonical_personal_recovery import (
    CanonicalPersonalRecoveryInputs,
    read_personal_recovery_inputs,
)
from backend.performance.context import current_performance_context
from backend.performance.personal_recovery import personal_recovery
from backend.providers.source_labels import SourceView, provider_label

INTERVALS_SOURCE = "Intervals.icu"
GARMIN_SOURCE = "Garmin Connect"
DAY = "2026-09-20"
EARLIER = "2026-09-19"
RETRIEVED = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
TODAY_DAY = date(2026, 9, 20)
NO_PROFILE: dict[str, Any] = {}


def _observation(
    value: float,
    *,
    day: str = DAY,
    provider: ProviderId = ProviderId.GARMIN,
) -> Observation:
    recorded_by = (
        RecordingOrigin.GARMIN
        if provider is ProviderId.GARMIN
        else RecordingOrigin.MANUAL
    )
    return Observation(
        kind=MetricKind.RESTING_HR,
        value=MetricValue(value, "bpm"),
        observed_on=date.fromisoformat(day),
        observed_at=None,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=f"resting_hr-{day}",
            recorded_by=recorded_by,
            retrieved_at=RETRIEVED,
            label=None,
        ),
    )


class _FakeReader:
    """Serves fixed observations for resting HR and records each read."""

    def __init__(self, observations: tuple[Observation, ...]) -> None:
        self._observations = observations
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
        return tuple(
            observation
            for observation in self._observations
            if observation.kind is kind
            and (start is None or start <= observation.observed_on)
            and (end is None or observation.observed_on <= end)
        )


def _wellness(resting_hr: int = 45) -> list[dict[str, Any]]:
    return [{"id": DAY, "restingHR": resting_hr, "sleepSecs": 27000, "hrv": 60}]


def _garmin(resting: int = 46) -> dict[str, Any]:
    return {
        "resting_hr": [{"calendarDate": DAY, "restingHeartRate": resting}],
        "sleep": [{"calendarDate": DAY, "sleepTimeSeconds": 26400}],
    }


def _canonical(
    *,
    garmin: Observation | None = None,
    intervals: Observation | None = None,
) -> CanonicalPersonalRecoveryInputs:
    return CanonicalPersonalRecoveryInputs(
        resting_hr={
            ProviderId.INTERVALS: {} if intervals is None else {DAY: intervals},
            ProviderId.GARMIN: {} if garmin is None else {DAY: garmin},
        }
    )


def _resting_baseline(result: dict[str, Any], source: str) -> dict[str, Any]:
    matches = [
        item
        for item in result["baselines"]
        if item["metric"] == "resting_hr" and item["source"] == source
    ]
    assert len(matches) == 1
    return matches[0]


def _dump(value: Any) -> str:
    return json.dumps(value, default=str, sort_keys=True)


def _personal(
    garmin: dict[str, Any],
    wellness: list[dict[str, Any]],
    canonical: CanonicalPersonalRecoveryInputs | None,
) -> dict[str, Any]:
    return personal_recovery(
        wellness, garmin, NO_PROFILE, TODAY_DAY, canonical=canonical
    )


class SourceLabelTests(unittest.TestCase):
    def test_personal_recovery_labels_are_the_legacy_strings(self) -> None:
        self.assertEqual(
            provider_label(ProviderId.INTERVALS, SourceView.DAILY_HEALTH),
            "Intervals.icu",
        )
        self.assertEqual(
            provider_label(ProviderId.GARMIN, SourceView.DAILY_HEALTH),
            "Garmin Connect",
        )

    def test_emitted_source_labels_stay_byte_identical(self) -> None:
        result = _personal(_garmin(), _wellness(), None)
        sources = {item["source"] for item in result["baselines"]}
        self.assertEqual(sources, {"Intervals.icu", "Garmin Connect"})


class ReadPersonalRecoveryInputsTests(unittest.TestCase):
    def test_resting_hr_is_read_from_the_start_without_an_end_bound(self) -> None:
        reader = _FakeReader(())
        start = date.fromisoformat(EARLIER)
        inputs = read_personal_recovery_inputs(reader, None, start=start)
        self.assertEqual(reader.calls, [(MetricKind.RESTING_HR, start, None)])
        self.assertEqual(
            inputs,
            CanonicalPersonalRecoveryInputs(
                resting_hr={ProviderId.INTERVALS: {}, ProviderId.GARMIN: {}}
            ),
        )

    def test_each_provider_gets_its_own_daily_observations(self) -> None:
        garmin = _observation(46.0, day=DAY)
        intervals = _observation(45.0, day=EARLIER, provider=ProviderId.INTERVALS)
        reader = _FakeReader((garmin, intervals))
        inputs = read_personal_recovery_inputs(
            reader, None, start=date.fromisoformat(EARLIER)
        )
        self.assertEqual(inputs.resting_hr[ProviderId.GARMIN], {DAY: garmin})
        self.assertEqual(inputs.resting_hr[ProviderId.INTERVALS], {EARLIER: intervals})

    def test_first_record_wins_within_a_provider_and_day(self) -> None:
        first = _observation(46.0, day=DAY)
        second = _observation(47.0, day=DAY)
        inputs = read_personal_recovery_inputs(
            _FakeReader((first, second)), None, start=date.fromisoformat(EARLIER)
        )
        self.assertEqual(inputs.resting_hr[ProviderId.GARMIN], {DAY: first})


class PersonalRecoveryCanonicalTests(unittest.TestCase):
    def test_canonical_none_is_the_legacy_path(self) -> None:
        self.assertEqual(
            _dump(_personal(_garmin(), _wellness(), None)),
            _dump(personal_recovery(_wellness(), _garmin(), NO_PROFILE, TODAY_DAY)),
        )

    def test_matching_garmin_resting_hr_keeps_the_legacy_output(self) -> None:
        legacy = _personal(_garmin(), _wellness(), None)
        canonical = _canonical(garmin=_observation(46.0))
        with patch.object(
            personal_module, "prefer_canonical", wraps=personal_module.prefer_canonical
        ) as spy:
            served = _personal(_garmin(), _wellness(), canonical)
        self.assertEqual(_dump(served), _dump(legacy))
        offered = [call.args[0] for call in spy.call_args_list]
        self.assertIn(canonical.resting_hr[ProviderId.GARMIN][DAY], offered)
        self.assertEqual(_resting_baseline(served, GARMIN_SOURCE)["value"], 46.0)

    def test_matching_intervals_resting_hr_keeps_the_legacy_output(self) -> None:
        legacy = _personal(_garmin(), _wellness(), None)
        canonical = _canonical(
            intervals=_observation(45.0, provider=ProviderId.INTERVALS)
        )
        served = _personal(_garmin(), _wellness(), canonical)
        self.assertEqual(_dump(served), _dump(legacy))
        self.assertEqual(_resting_baseline(served, INTERVALS_SOURCE)["value"], 45.0)

    def test_different_number_keeps_the_legacy_value(self) -> None:
        canonical = _canonical(garmin=_observation(99.0))
        served = _personal(_garmin(), _wellness(), canonical)
        self.assertEqual(_dump(served), _dump(_personal(_garmin(), _wellness(), None)))
        self.assertEqual(_resting_baseline(served, GARMIN_SOURCE)["value"], 46.0)

    def test_other_provider_keeps_the_legacy_value(self) -> None:
        canonical = _canonical(garmin=_observation(45.0, provider=ProviderId.INTERVALS))
        served = _personal(_garmin(), _wellness(), canonical)
        self.assertEqual(_dump(served), _dump(_personal(_garmin(), _wellness(), None)))

    def test_missing_day_keeps_the_legacy_value(self) -> None:
        canonical = _canonical(garmin=_observation(46.0, day=EARLIER))
        served = _personal(_garmin(), _wellness(), canonical)
        self.assertEqual(_dump(served), _dump(_personal(_garmin(), _wellness(), None)))

    def test_no_canonical_observation_for_a_provider_keeps_the_legacy_value(
        self,
    ) -> None:
        served = _personal(_garmin(), _wellness(), _canonical())
        self.assertEqual(_dump(served), _dump(_personal(_garmin(), _wellness(), None)))


class PopulatedPersonalRecoveryTests(CanonicalReadFixture):
    def test_populated_tables_reproduce_the_legacy_personal_recovery(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)
        self.assertEqual(self.write(selector.summary)["serving"], "tables")
        with self.manager.reader() as db:
            inputs = read_performance_inputs(selector, db, self.intervals)
        self.assertIsNotNone(inputs)
        assert inputs is not None
        assert inputs.personal_recovery is not None
        legacy = current_performance_context(self.intervals, self.garmin, {}, TODAY)
        with patch.object(
            personal_module, "prefer_canonical", wraps=personal_module.prefer_canonical
        ) as spy:
            canonical = current_performance_context(
                self.intervals, self.garmin, {}, TODAY, canonical=inputs
            )
        self.assertEqual(
            _dump(canonical["personal_recovery"]), _dump(legacy["personal_recovery"])
        )
        self.assertEqual(_dump(canonical), _dump(legacy))
        offered = [
            call.args[0] for call in spy.call_args_list if call.args[0] is not None
        ]
        self.assertTrue(offered, "no canonical resting HR observation was offered")
