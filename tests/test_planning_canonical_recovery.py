"""Planning daily recovery: canonical values replace legacy ones only when they match.

The planning view keeps every legacy value and source label. A switched field
(sleep score, resting HR, readiness) takes the canonical observation of its day only
when that observation comes from the provider the legacy view named and carries the
same number. The populated temporary database test proves the planning daily
context equals the legacy context. All providers are mocked and all storage is
temporary.
"""

from __future__ import annotations

import json
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from canonical_read_support import CanonicalReadFixture, make_selector, populate

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
)
from backend.performance import planning_recovery
from backend.performance.canonical_recovery import CanonicalDailyRecovery
from backend.performance.planning_recovery import (
    GARMIN_SOURCE,
    INTERVALS_WELLNESS_SOURCE,
    planning_recovery_by_date,
    with_canonical_recovery,
)
from backend.planning.daily_context_service import DailyPlanningContextService
from backend.runtime.ports import ObservationSourceSelector

DAY = "2026-09-20"
OTHER_DAY = "2026-09-21"
RETRIEVED = datetime(2026, 9, 20, 8, 0, tzinfo=UTC)
TODAY = date(2026, 10, 10)
UNITS = {
    MetricKind.SLEEP_SCORE: "score",
    MetricKind.RESTING_HR: "bpm",
    MetricKind.READINESS: "score",
}
EMPTY = CanonicalDailyRecovery(sleep_score={}, resting_hr={}, readiness={})


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


def _legacy(field: str, value: Any, source: str, day: str = DAY) -> dict[str, Any]:
    return {day: {field: value, "sources": {field: source}}}


def _daily(**maps: dict[str, Observation]) -> CanonicalDailyRecovery:
    return CanonicalDailyRecovery(
        sleep_score=maps.get("sleep_score", {}),
        resting_hr=maps.get("resting_hr", {}),
        readiness=maps.get("readiness", {}),
    )


class _SpyReader:
    """Serves fixed observations per kind, records each read, and counts selections."""

    def __init__(self, by_kind: dict[MetricKind, list[Observation]]) -> None:
        self._by_kind = by_kind
        self.calls: list[tuple[MetricKind, date | None, date | None]] = []
        self.selected = 0

    def reader_for(self, db: Any) -> _SpyReader:
        self.selected += 1
        return self

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


class _CountingSelector:
    """Wraps the real selector; the reader it chooses records the kinds it serves."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.kinds: set[str] = set()

    def reader_for(self, db: Any) -> _CountingSelector:
        self._inner.reader_for(db)
        return self

    def observations(self, db: Any, kind: MetricKind, **kwargs: Any) -> Any:
        self.kinds.add(kind.value)
        return self._inner.observations(db, kind, **kwargs)


class _FakeDatabaseManager:
    def __init__(self) -> None:
        self.units = 0

    @contextmanager
    def unit_of_work(self) -> Iterator[str]:
        self.units += 1
        yield "db"


class _FakeKeyValues:
    def __init__(self, values: dict[str, Any]) -> None:
        self._values = values

    def get(self, db: Any, key: str) -> Any:
        return self._values.get(key)


class _NoBattery:
    def current(self, snapshot: Any) -> None:
        return None


class _EmptyFeed:
    def list(self, limit: int) -> list[Any]:
        return []


def _service(
    manager: Any,
    key_values: Any,
    canonical_reader: Any = None,
) -> DailyPlanningContextService:
    return DailyPlanningContextService(
        manager,
        key_values,
        _EmptyFeed(),
        _EmptyFeed(),
        _NoBattery(),
        _EmptyFeed(),
        lambda: TODAY,
        35,
        canonical_reader=canonical_reader,
    )


def _build(service: DailyPlanningContextService, snapshot: dict[str, Any]) -> Any:
    return service.build(
        snapshot=snapshot,
        planned=[],
        weather={},
        checkins=[],
        calendar_events=[],
    )


class WithCanonicalRecoveryTests(unittest.TestCase):
    def test_matching_garmin_sleep_score_is_selected_and_keeps_type(self) -> None:
        legacy = _legacy("sleep_score", 84, GARMIN_SOURCE)
        canonical = _daily(
            sleep_score={DAY: _observation(MetricKind.SLEEP_SCORE, 84.0)}
        )
        with patch.object(
            planning_recovery,
            "prefer_canonical",
            wraps=planning_recovery.prefer_canonical,
        ) as prefer:
            result = with_canonical_recovery(legacy, canonical)
        prefer.assert_called_once()
        self.assertEqual(prefer.call_args.args[2], ProviderId.GARMIN)
        self.assertEqual(prefer.call_args.args[3], DAY)
        self.assertIs(type(result[DAY]["sleep_score"]), int)
        self.assertEqual(result[DAY]["sleep_score"], 84)

    def test_matching_intervals_readiness_is_selected(self) -> None:
        legacy = _legacy("readiness", 74, INTERVALS_WELLNESS_SOURCE)
        canonical = _daily(
            readiness={
                DAY: _observation(
                    MetricKind.READINESS, 74, provider=ProviderId.INTERVALS
                )
            }
        )
        with patch.object(
            planning_recovery,
            "prefer_canonical",
            wraps=planning_recovery.prefer_canonical,
        ) as prefer:
            result = with_canonical_recovery(legacy, canonical)
        self.assertEqual(prefer.call_args.args[2], ProviderId.INTERVALS)
        self.assertEqual(result[DAY]["readiness"], 74)

    def test_large_int_legacy_is_not_matched_by_a_rounded_float(self) -> None:
        # Canonical validation bounds real observations, so the gate is exercised
        # directly with a stand-in whose float value rounds to the legacy int.
        observation: Any = SimpleNamespace(
            provenance=SimpleNamespace(provider=ProviderId.GARMIN),
            observed_on=date.fromisoformat(DAY),
            value=SimpleNamespace(value=9_007_199_254_740_992.0),
        )
        result = planning_recovery.prefer_canonical(
            observation, 9_007_199_254_740_993, ProviderId.GARMIN, DAY
        )
        self.assertIs(type(result), int)
        self.assertEqual(result, 9_007_199_254_740_993)

    def test_missing_canonical_day_keeps_legacy_value(self) -> None:
        legacy = _legacy("resting_hr", 49, GARMIN_SOURCE)
        canonical = _daily(
            resting_hr={OTHER_DAY: _observation(MetricKind.RESTING_HR, 49, OTHER_DAY)}
        )
        result = with_canonical_recovery(legacy, canonical)
        self.assertEqual(result[DAY]["resting_hr"], 49)

    def test_provider_mismatch_keeps_legacy_value(self) -> None:
        legacy = _legacy("sleep_score", 84, GARMIN_SOURCE)
        canonical = _daily(
            sleep_score={
                DAY: _observation(
                    MetricKind.SLEEP_SCORE, 90, provider=ProviderId.INTERVALS
                )
            }
        )
        result = with_canonical_recovery(legacy, canonical)
        self.assertEqual(result[DAY]["sleep_score"], 84)
        self.assertEqual(result[DAY]["sources"]["sleep_score"], GARMIN_SOURCE)

    def test_value_mismatch_keeps_legacy_value(self) -> None:
        legacy = _legacy("resting_hr", 49, GARMIN_SOURCE)
        canonical = _daily(resting_hr={DAY: _observation(MetricKind.RESTING_HR, 52)})
        result = with_canonical_recovery(legacy, canonical)
        self.assertEqual(result[DAY]["resting_hr"], 49)

    def test_multi_record_garmin_day_keeps_the_legacy_record(self) -> None:
        # The legacy view picks one Garmin record of a two-record day (80 here). A
        # canonical observation of the other record (84) carries a different number,
        # so the legacy value is kept.
        garmin = {
            "sleep": [
                {"calendarDate": DAY, "sleepScore": 80},
                {"calendarDate": DAY, "sleepScore": 84},
            ]
        }
        legacy = planning_recovery_by_date([], garmin, {}, None)
        self.assertEqual(legacy[DAY]["sleep_score"], 80)
        canonical = _daily(sleep_score={DAY: _observation(MetricKind.SLEEP_SCORE, 84)})
        result = with_canonical_recovery(legacy, canonical)
        self.assertEqual(result[DAY]["sleep_score"], 80)

    def test_string_legacy_value_is_kept(self) -> None:
        legacy = _legacy("readiness", "74", INTERVALS_WELLNESS_SOURCE)
        canonical = _daily(
            readiness={
                DAY: _observation(
                    MetricKind.READINESS, 74, provider=ProviderId.INTERVALS
                )
            }
        )
        result = with_canonical_recovery(legacy, canonical)
        self.assertEqual(result[DAY]["readiness"], "74")

    def test_unknown_source_label_keeps_legacy_value(self) -> None:
        legacy = _legacy("sleep_score", 84, "Some other source")
        canonical = _daily(sleep_score={DAY: _observation(MetricKind.SLEEP_SCORE, 84)})
        result = with_canonical_recovery(legacy, canonical)
        self.assertEqual(result[DAY]["sleep_score"], 84)

    def test_unswitched_values_and_days_without_switched_fields_stay_untouched(
        self,
    ) -> None:
        legacy = {
            DAY: {"sleep_hours": 7.5, "hrv": 61, "sources": {"hrv": GARMIN_SOURCE}},
            OTHER_DAY: {"sleep_score": 80, "sources": {"sleep_score": GARMIN_SOURCE}},
        }
        canonical = _daily(
            sleep_score={OTHER_DAY: _observation(MetricKind.SLEEP_SCORE, 80, OTHER_DAY)}
        )
        result = with_canonical_recovery(legacy, canonical)
        self.assertEqual(
            result[DAY],
            {"sleep_hours": 7.5, "hrv": 61, "sources": {"hrv": GARMIN_SOURCE}},
        )
        self.assertEqual(result[OTHER_DAY]["sleep_score"], 80)

    def test_empty_canonical_maps_leave_the_legacy_view_unchanged(self) -> None:
        legacy = _legacy("resting_hr", 49, GARMIN_SOURCE)
        expected = json.dumps(legacy, sort_keys=True)
        result = with_canonical_recovery(legacy, EMPTY)
        self.assertEqual(json.dumps(result, sort_keys=True), expected)


class DailyPlanningCanonicalWiringTests(unittest.TestCase):
    def test_without_a_canonical_reader_only_one_unit_is_used(self) -> None:
        manager = _FakeDatabaseManager()
        garmin = {"sleep": [{"calendarDate": DAY, "sleepScore": 84}]}
        service = _service(
            manager,
            _FakeKeyValues({"garmin_snapshot": json.dumps(garmin)}),
        )
        result = _build(service, {"recent_wellness": []})
        self.assertEqual(manager.units, 1)
        self.assertEqual(result[0]["recovery"]["sleep_score"], 84)

    def test_reader_is_selected_once_and_read_over_the_legacy_day_span(self) -> None:
        manager = _FakeDatabaseManager()
        garmin = {
            "sleep": [{"calendarDate": OTHER_DAY, "sleepScore": 80}],
            "resting_hr": [{"calendarDate": DAY, "restingHeartRate": 49}],
        }
        reader = _SpyReader(
            {
                MetricKind.SLEEP_SCORE: [
                    _observation(MetricKind.SLEEP_SCORE, 80, OTHER_DAY)
                ],
                MetricKind.RESTING_HR: [_observation(MetricKind.RESTING_HR, 49, DAY)],
            }
        )
        self.assertIsInstance(reader, ObservationSourceSelector)
        service = _service(
            manager,
            _FakeKeyValues({"garmin_snapshot": json.dumps(garmin)}),
            canonical_reader=lambda: reader,
        )
        result = _build(service, {"recent_wellness": []})
        self.assertEqual(manager.units, 1)
        self.assertEqual(reader.selected, 1)
        span = (date(2026, 9, 20), date(2026, 9, 21))
        self.assertEqual(
            reader.calls,
            [
                (MetricKind.SLEEP_SCORE, *span),
                (MetricKind.RESTING_HR, *span),
                (MetricKind.READINESS, *span),
            ],
        )
        by_date = {day["date"]: day for day in result}
        self.assertEqual(by_date[DAY]["recovery"]["resting_hr"], 49)
        self.assertEqual(by_date[OTHER_DAY]["recovery"]["sleep_score"], 80)

    def test_no_legacy_recovery_skips_the_canonical_read(self) -> None:
        manager = _FakeDatabaseManager()
        reader = _SpyReader({})
        service = _service(manager, _FakeKeyValues({}), canonical_reader=lambda: reader)
        _build(service, {"recent_wellness": []})
        self.assertEqual(reader.selected, 0)
        self.assertEqual(reader.calls, [])


class CanonicalPlanningEndToEndTests(CanonicalReadFixture):
    """Populated temporary database: the planning daily context equals legacy."""

    def test_planning_daily_context_from_tables_equals_legacy(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.write(selector.refresh)
        self.assertEqual(self.write(selector.summary)["serving"], "tables")
        counting = _CountingSelector(selector)
        legacy = _build(_service(self.manager, self.key_values), self.intervals)
        canonical = _build(
            _service(self.manager, self.key_values, lambda: counting), self.intervals
        )
        self.assertEqual(canonical, legacy)
        self.assertTrue(
            any(day["recovery"].get("sleep_score") is not None for day in legacy)
        )
        self.assertEqual(counting.kinds, {"sleep_score", "resting_hr", "readiness"})


if __name__ == "__main__":
    unittest.main()
