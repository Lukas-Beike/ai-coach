"""Planning daily recovery is read from canonical observations.

Sleep, HRV, resting HR, readiness, CTL, ATL, form (TSB) and the daily totals come
from the injected observation reader over a window that ends on the athlete's local
date. Body battery is not mapped to observations and stays a read of the morning
battery. The populated temporary database tests pin the table-served view of the
shared fixture, which matched the deleted stored-snapshot reader (#1416), and prove
that it does not depend on the snapshot. All providers are mocked and all storage
is temporary.
"""

from __future__ import annotations

import sqlite3
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, timedelta
from typing import Any

from canonical_read_support import CanonicalReadFixture, make_selector, populate
from canonical_recovery_support import RecordingReader, recovery_observation

from backend.canonical.records import Observation
from backend.canonical.section_items import split_section
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.db.garmin_store import put_section
from backend.db.schema import initialize_schema
from backend.performance.planning_recovery import (
    GARMIN_SOURCE,
    INTERVALS_WELLNESS_SOURCE,
    canonical_planning_recovery,
    planning_recovery_view,
)
from backend.planning.daily_context_service import (
    RECOVERY_WINDOW_DAYS,
    DailyPlanningContextService,
)
from backend.runtime.ports import ObservationSourceSelector

DAY = "2026-09-20"
OTHER_DAY = "2026-09-21"
TODAY = date(2026, 10, 10)
WINDOW = (TODAY - timedelta(days=RECOVERY_WINDOW_DAYS), TODAY)


def _day(values: dict[str, Any], garmin: tuple[str, ...] = ()) -> dict[str, Any]:
    """One served day; ``garmin`` names the fields Garmin supplied."""
    return {
        **values,
        "sources": {
            field: GARMIN_SOURCE if field in garmin else INTERVALS_WELLNESS_SOURCE
            for field in values
        },
    }


# The populated fixture's window, as the deleted stored-snapshot reader also
# served it before #1416 removed that reader.
EXPECTED_WINDOW = {
    "2026-10-08": _day(
        {
            "sleep_hours": 7.3,
            "sleep_score": 82,
            "hrv": 64.0,
            "readiness": 74,
            "resting_hr": 49,
            "ctl": 52.1,
            "atl": 60.4,
            "tsb": -8.3,
        }
    ),
    "2026-10-09": _day(
        {
            "sleep_hours": 7.0,
            "sleep_score": 78,
            "hrv": 62.0,
            "readiness": 70,
            "resting_hr": 50,
            "ctl": 52.8,
            "atl": 58.9,
            "tsb": -6.1,
        },
        ("sleep_hours", "sleep_score"),
    ),
    "2026-10-10": _day(
        {
            "sleep_hours": 7.8,
            "sleep_score": 86,
            "hrv": 61,
            "readiness": 79,
            "resting_hr": 49,
            "ctl": 53.4,
            "atl": 57.0,
            "tsb": -3.6,
        },
        ("sleep_hours", "sleep_score", "hrv", "resting_hr"),
    ),
}


def _observation(
    kind: MetricKind,
    value: float,
    day: str = DAY,
    provider: ProviderId = ProviderId.GARMIN,
) -> Observation:
    return recovery_observation(kind, value, day, provider)


class _SpyReader(RecordingReader):
    """Serves fixed observations per kind, records each read, and counts selections."""

    def __init__(self, by_kind: dict[MetricKind, list[Observation]]) -> None:
        super().__init__(by_kind)
        self.selected = 0

    def reader_for(self, db: Any) -> _SpyReader:
        self.selected += 1
        return self


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
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        initialize_schema(self.db)

    @contextmanager
    def unit_of_work(self) -> Iterator[sqlite3.Connection]:
        self.units += 1
        yield self.db

    def reader(self):
        return self.unit_of_work()


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
    manager: Any, key_values: Any, observation_reader: Any
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
        lambda: observation_reader,
    )


def _build(service: DailyPlanningContextService, snapshot: dict[str, Any]) -> Any:
    return service.build(
        planned=[],
        weather={},
        checkins=[],
        calendar_events=[],
    )


class CanonicalPlanningRecoveryTests(unittest.TestCase):
    def _view(self, by_kind: dict[MetricKind, list[Observation]]) -> dict[str, Any]:
        return canonical_planning_recovery(
            RecordingReader(by_kind), "db", start=WINDOW[0], end=WINDOW[1]
        )

    def test_every_value_names_the_provider_that_supplied_it(self) -> None:
        view = self._view(
            {
                MetricKind.SLEEP_SCORE: [_observation(MetricKind.SLEEP_SCORE, 84)],
                MetricKind.READINESS: [
                    _observation(
                        MetricKind.READINESS, 74, provider=ProviderId.INTERVALS
                    )
                ],
                MetricKind.CTL: [
                    _observation(MetricKind.CTL, 55.5, provider=ProviderId.INTERVALS)
                ],
            }
        )
        self.assertEqual(
            view[DAY],
            {
                "sleep_score": 84,
                "readiness": 74,
                "ctl": 55.5,
                "sources": {
                    "sleep_score": GARMIN_SOURCE,
                    "readiness": INTERVALS_WELLNESS_SOURCE,
                    "ctl": INTERVALS_WELLNESS_SOURCE,
                },
            },
        )

    def test_garmin_wins_sleep_and_intervals_wins_readiness(self) -> None:
        view = self._view(
            {
                MetricKind.SLEEP_SCORE: [
                    _observation(
                        MetricKind.SLEEP_SCORE, 90, provider=ProviderId.INTERVALS
                    ),
                    _observation(MetricKind.SLEEP_SCORE, 84),
                ],
                MetricKind.READINESS: [
                    _observation(MetricKind.READINESS, 60),
                    _observation(
                        MetricKind.READINESS, 74, provider=ProviderId.INTERVALS
                    ),
                ],
            }
        )
        self.assertEqual(view[DAY]["sleep_score"], 84)
        self.assertEqual(view[DAY]["sources"]["sleep_score"], GARMIN_SOURCE)
        self.assertEqual(view[DAY]["readiness"], 74)
        self.assertEqual(view[DAY]["sources"]["readiness"], INTERVALS_WELLNESS_SOURCE)

    def test_sleep_duration_is_served_in_hours(self) -> None:
        view = self._view(
            {
                MetricKind.SLEEP_DURATION: [
                    _observation(MetricKind.SLEEP_DURATION, 27000)
                ]
            }
        )
        self.assertEqual(view[DAY]["sleep_hours"], 7.5)

    def test_load_is_taken_from_intervals_only(self) -> None:
        view = self._view(
            {
                MetricKind.ATL: [
                    _observation(MetricKind.ATL, 50, provider=ProviderId.GARMIN),
                    _observation(MetricKind.ATL, 57, provider=ProviderId.INTERVALS),
                ]
            }
        )
        self.assertEqual(view[DAY]["atl"], 57)
        self.assertEqual(view[DAY]["sources"]["atl"], INTERVALS_WELLNESS_SOURCE)

    def test_no_observations_yield_no_days(self) -> None:
        self.assertEqual(self._view({}), {})

    def test_each_kind_is_read_once_over_the_given_window(self) -> None:
        reader = RecordingReader({})
        canonical_planning_recovery(reader, "db", start=WINDOW[0], end=WINDOW[1])
        self.assertEqual(
            reader.calls,
            [
                (kind, *WINDOW)
                for kind in (
                    MetricKind.SLEEP_DURATION,
                    MetricKind.SLEEP_SCORE,
                    MetricKind.HRV_RMSSD,
                    MetricKind.READINESS,
                    MetricKind.RESTING_HR,
                    MetricKind.CTL,
                    MetricKind.ATL,
                    MetricKind.FORM,
                )
            ],
        )


class PlanningRecoveryViewTests(unittest.TestCase):
    def test_form_and_body_battery_are_added_to_the_canonical_view(self) -> None:
        reader = RecordingReader(
            {
                MetricKind.SLEEP_SCORE: [_observation(MetricKind.SLEEP_SCORE, 84)],
                MetricKind.FORM: [
                    _observation(MetricKind.FORM, -4.5, provider=ProviderId.INTERVALS)
                ],
            }
        )
        view = planning_recovery_view(
            reader,
            "db",
            start=WINDOW[0],
            end=WINDOW[1],
            morning_battery_history={DAY: 61},
            morning_body_battery=None,
        )
        self.assertEqual(
            view[DAY],
            {
                "sleep_score": 84,
                "tsb": -4.5,
                "body_battery": 61,
                "sources": {
                    "sleep_score": GARMIN_SOURCE,
                    "tsb": INTERVALS_WELLNESS_SOURCE,
                    "body_battery": GARMIN_SOURCE,
                },
            },
        )


class DailyPlanningCanonicalWiringTests(unittest.TestCase):
    def test_reader_is_selected_once_and_read_over_the_local_date_window(self) -> None:
        manager = _FakeDatabaseManager()
        reader = _SpyReader(
            {
                MetricKind.SLEEP_SCORE: [
                    _observation(MetricKind.SLEEP_SCORE, 80, OTHER_DAY)
                ],
                MetricKind.RESTING_HR: [_observation(MetricKind.RESTING_HR, 49, DAY)],
            }
        )
        self.assertIsInstance(reader, ObservationSourceSelector)
        service = _service(manager, _FakeKeyValues({}), reader)
        # The snapshot has no wellness rows: the window must not depend on them.
        result = _build(service, {"recent_wellness": []})
        self.assertEqual(manager.units, 1)
        self.assertEqual(reader.selected, 1)
        self.assertEqual({call[1:] for call in reader.calls}, {WINDOW})
        # Five recovery kinds, CTL, ATL and form, then the five daily totals.
        self.assertEqual(len(reader.calls), 13)
        by_date = {day["date"]: day for day in result}
        self.assertEqual(by_date[DAY]["recovery"]["resting_hr"], 49)
        self.assertEqual(by_date[OTHER_DAY]["recovery"]["sleep_score"], 80)

    def test_recovery_does_not_need_any_snapshot_section(self) -> None:
        reader = _SpyReader(
            {MetricKind.SLEEP_SCORE: [_observation(MetricKind.SLEEP_SCORE, 84)]}
        )
        service = _service(_FakeDatabaseManager(), _FakeKeyValues({}), reader)
        for snapshot in ({}, None, {"recent_wellness": "broken"}):
            with self.subTest(snapshot=snapshot):
                result = _build(service, snapshot)  # type: ignore[arg-type]
                by_date = {day["date"]: day for day in result}
                self.assertEqual(by_date[DAY]["recovery"]["sleep_score"], 84)

    def test_stored_garmin_recovery_sections_are_not_read(self) -> None:
        manager = _FakeDatabaseManager()
        put_section(
            manager.db,
            "sleep",
            split_section([{"calendarDate": DAY, "sleepScore": 99}]),
            fetched_at="2026-10-10T08:00:00+00:00",
            now="2026-10-10T08:00:00+00:00",
            mapper_version=1,
            replace=True,
        )
        reader = _SpyReader({})
        service = _service(manager, _FakeKeyValues({}), reader)
        by_date = {day["date"]: day for day in _build(service, {})}
        self.assertNotIn("sleep_score", by_date.get(DAY, {}).get("recovery", {}))


class CanonicalPlanningEndToEndTests(CanonicalReadFixture):
    """Populated temporary database: the table-served view of the fixture."""

    def _served(self, selector: Any) -> dict[str, dict[str, Any]]:
        def view(db: Any) -> dict[str, dict[str, Any]]:
            return planning_recovery_view(
                selector.reader_for(db),
                db,
                start=WINDOW[0],
                end=WINDOW[1],
                morning_battery_history={},
                morning_body_battery=None,
            )

        return self.write(view)

    def test_recovery_from_tables_serves_the_fixture_window(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.assertEqual(self.write(selector.summary)["serving"], "tables")
        self.assertEqual(self._served(selector), EXPECTED_WINDOW)

    def test_recovery_before_the_first_backfill_is_empty(self) -> None:
        # The backfill has not run, so the selector serves nothing yet.
        selector = make_selector(self)
        self.assertFalse(self.write(selector.serves_tables))
        self.assertEqual(self._served(selector), {})

    def test_tables_serve_the_context_without_canonical_snapshot_sections(
        self,
    ) -> None:
        populate(self)
        selector = make_selector(self)
        self.assertEqual(self.write(selector.summary)["serving"], "tables")
        # No snapshot section is read any more, not even the wellness rows.
        stripped = {"synced_at": self.intervals["synced_at"]}
        counting = _CountingSelector(selector)
        with_sections = _build(
            _service(self.manager, self.key_values, counting), self.intervals
        )
        without_sections = _build(
            _service(self.manager, self.key_values, counting), stripped
        )
        self.assertEqual(without_sections, with_sections)
        self.assertTrue(
            any(day["recovery"].get("sleep_score") is not None for day in with_sections)
        )
        self.assertEqual(
            counting.kinds,
            {
                "sleep_duration",
                "sleep_score",
                "hrv_rmssd",
                "readiness",
                "resting_hr",
                "ctl",
                "atl",
                "form",
                "steps",
                "floors",
                "daily_energy_total",
                "daily_energy_active",
                "daily_energy_resting",
            },
        )


if __name__ == "__main__":
    unittest.main()
