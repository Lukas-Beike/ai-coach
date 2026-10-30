"""Current sport thresholds and VO2max read from canonical observations.

The threshold heart rate and VO2max values are read from the canonical observations
of the snapshot's own sync. Each comparison is between whole metric dictionaries,
including source labels, so the canonical read must reproduce the legacy output.
All storage is temporary and every provider is mocked by fixtures.
"""

from __future__ import annotations

import contextlib
import copy
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

from canonical_consumer_cases import (
    CASES,
    RETRIEVED_AT,
    TODAY,
    Case,
    _latest_wellness,
    _latest_wellness_day,
    _observations,
)
from canonical_read_support import CanonicalReadFixture, make_selector, populate
from performance_day_support import latest_day

from backend.canonical.records import Observation
from backend.canonical.vocabulary import MetricKind, ProviderId, Sport
from backend.coach.context import CoachPerformanceContextReader
from backend.performance import garmin_metrics as performance_garmin_metrics
from backend.performance.canonical_current import (
    CanonicalCurrentInputs,
    read_current_inputs,
    read_wahoo_fallbacks,
)
from backend.performance.canonical_inputs import (
    CanonicalPerformanceSource,
    read_performance_inputs,
)
from backend.performance.context import current_performance_context
from backend.performance.current_metrics import current_performance_metrics
from backend.providers.source_labels import SourceView, observation_source_label
from backend.providers.wahoo_threshold_mapping import (
    map_wahoo_power_zones,
    map_wahoo_user,
)
from backend.runtime.ports import ObservationReader

SYNC_DAY = date(2026, 10, 12)
SENSOR_KINDS = (MetricKind.THRESHOLD_HR, MetricKind.VO2MAX)
SYNC_KINDS = (MetricKind.THRESHOLD_HR, MetricKind.VO2MAX, MetricKind.WEIGHT)


class ObservationStub(ObservationReader):
    """Serves observations by kind, inclusive observed_on window and sport."""

    def __init__(self, observations: tuple[Observation, ...]) -> None:
        self._observations = observations
        self.calls: list[tuple[MetricKind, date | None, date | None, Sport | None]] = []

    def observations(
        self,
        db: Any,
        kind: MetricKind,
        *,
        start: date | None = None,
        end: date | None = None,
        sport: Sport | None = None,
    ) -> tuple[Observation, ...]:
        self.calls.append((kind, start, end, sport))
        return tuple(
            observation
            for observation in self._observations
            if observation.kind is kind
            and (start is None or start <= observation.observed_on)
            and (end is None or observation.observed_on <= end)
            and (sport is None or observation.sport is sport)
        )


def _case(name: str) -> Case:
    return next(case for case in CASES if case.name == name)


def _legacy(case: Case) -> dict[str, Any]:
    garmin = performance_garmin_metrics.garmin_performance_metrics(case.garmin, TODAY)
    return current_performance_metrics(
        case.intervals,
        case.profile,
        garmin,
        latest_wellness=latest_day(case.intervals.get("recent_wellness", [])),
    )


def _read(
    reader: ObservationStub, snapshot: dict[str, Any] | None
) -> CanonicalCurrentInputs | None:
    """Read a snapshot with its latest wellness day, as the assembly does."""
    latest = _latest_wellness_day(_latest_wellness(snapshot or {}))
    return read_current_inputs(reader, None, latest_wellness_day=latest, as_of=TODAY)


def _canonical(case: Case, observations: tuple[Observation, ...] | None = None) -> Any:
    garmin = performance_garmin_metrics.garmin_performance_metrics(case.garmin, TODAY)
    reader = ObservationStub(
        _observations(case) if observations is None else observations
    )
    inputs = _read(reader, case.intervals)
    return current_performance_metrics(
        case.intervals,
        case.profile,
        garmin,
        canonical=inputs,
        latest_wellness=latest_day(case.intervals.get("recent_wellness", [])),
    )


def _inputs(case: Case) -> CanonicalCurrentInputs:
    inputs = _read(ObservationStub(_observations(case)), case.intervals)
    assert inputs is not None
    return inputs


# (sport, Intervals type, legacy metric key, sport-setting field, kind, value)
SPORT_METRICS: Final = (
    (Sport.RIDE, "Ride", "bike_threshold_hr_bpm", "lthr", MetricKind.THRESHOLD_HR, 175),
    (Sport.RUN, "Run", "run_threshold_hr_bpm", "lthr", MetricKind.THRESHOLD_HR, 180),
    (Sport.RIDE, "Ride", "cycling_vo2max_ml_kg_min", "vo2max", MetricKind.VO2MAX, 55.5),
    (Sport.RUN, "Run", "running_vo2max_ml_kg_min", "vo2max", MetricKind.VO2MAX, 53.5),
)


def _setting(entry_id: int, sport_type: str, **fields: float) -> dict[str, Any]:
    return {"id": entry_id, "types": [sport_type], **fields}


def _with_sport_settings(settings: list[dict[str, Any]]) -> Case:
    case = _case("intervals_only")
    intervals = copy.deepcopy(case.intervals)
    intervals["athlete"]["sport_settings"] = settings
    return replace(case, intervals=intervals)


def _sync_sport_values(case: Case, sport: Sport, kind: MetricKind) -> list[float]:
    """Values of this sync's Intervals observations of ``kind`` for ``sport``."""
    return [
        observation.value.value
        for observation in _observations(case)
        if observation.kind is kind
        and observation.sport is sport
        and observation.provenance.provider is ProviderId.INTERVALS
    ]


def _sensor_rows(case: Case, *, retrieved_at: datetime) -> tuple[Observation, ...]:
    """Intervals threshold and VO2max rows of ``case``, re-stamped to ``retrieved_at``."""
    return tuple(
        replace(
            observation,
            provenance=replace(observation.provenance, retrieved_at=retrieved_at),
        )
        for observation in _observations(case)
        if observation.kind in SENSOR_KINDS
        and observation.provenance.provider is ProviderId.INTERVALS
    )


class CanonicalCurrentParityTests(unittest.TestCase):
    def test_each_consumer_case_matches_the_legacy_current_metrics(self) -> None:
        for case in CASES:
            with self.subTest(case=case.name):
                self.assertEqual(_canonical(case), _legacy(case))

    def test_sport_values_missing_from_the_legacy_snapshot_stay_legacy(self) -> None:
        case = _case("intervals_only")
        without_sport_lthr = copy.deepcopy(case.intervals)
        for setting in without_sport_lthr["athlete"]["sport_settings"]:
            setting.pop("lthr", None)
        variant = replace(case, intervals=without_sport_lthr)
        metrics = _canonical(variant, _observations(case))
        self.assertEqual(metrics, _legacy(variant))

    def test_athlete_wide_threshold_is_the_fallback_with_the_general_label(
        self,
    ) -> None:
        case = _case("intervals_only")
        intervals = copy.deepcopy(case.intervals)
        intervals["athlete"]["lthr"] = 171
        for setting in intervals["athlete"]["sport_settings"]:
            setting.pop("lthr", None)
        variant = replace(case, intervals=intervals)
        metrics = _canonical(variant, _observations(variant))
        self.assertEqual(metrics, _legacy(variant))
        self.assertEqual(metrics["bike_threshold_hr_bpm"]["value"], 171)
        self.assertEqual(
            metrics["bike_threshold_hr_bpm"]["source"], "Intervals.icu (allgemein)"
        )
        inputs = _read(ObservationStub(_observations(variant)), variant.intervals)
        assert inputs is not None and inputs.athlete_threshold_hr is not None
        self.assertIsNone(inputs.athlete_threshold_hr.sport)
        self.assertEqual(
            observation_source_label(
                inputs.athlete_threshold_hr, SourceView.CURRENT_METRIC
            ),
            "Intervals.icu (allgemein)",
        )

    def test_sport_labels_match_the_legacy_view(self) -> None:
        inputs = _inputs(_case("intervals_only"))
        assert inputs.bike_threshold_hr and inputs.cycling_vo2max
        for observation in (inputs.bike_threshold_hr[0], inputs.cycling_vo2max[0]):
            self.assertEqual(
                observation_source_label(observation, SourceView.CURRENT_METRIC),
                "Intervals.icu",
            )

    def test_rows_from_an_earlier_sync_never_change_the_current_values(self) -> None:
        case = _case("intervals_only")
        stale = tuple(
            replace(row, value=replace(row.value, value=row.value.value + 50))
            for row in _sensor_rows(case, retrieved_at=RETRIEVED_AT - timedelta(days=1))
        )
        self.assertEqual(
            _canonical(case, (*_observations(case), *stale)), _legacy(case)
        )

    def test_garmin_rows_never_enter_the_intervals_current_values(self) -> None:
        case = _case("complete")
        garmin_only = tuple(
            observation
            for observation in _observations(case)
            if observation.provenance.provider is ProviderId.GARMIN
        )
        inputs = _read(ObservationStub(garmin_only), case.intervals)
        self.assertIsNone(inputs)


class CanonicalSportMatchTests(unittest.TestCase):
    """A canonical sport value is used only when it equals the legacy-selected value."""

    def test_first_entry_without_the_metric_keeps_the_legacy_value(self) -> None:
        for _sport, sport_type, key, field, _kind, value in SPORT_METRICS:
            with self.subTest(key=key):
                case = _with_sport_settings(
                    [_setting(1, sport_type), _setting(2, sport_type, **{field: value})]
                )
                self.assertEqual(_canonical(case), _legacy(case))

    def test_first_matching_entry_wins_over_a_later_different_value(self) -> None:
        for sport, sport_type, key, field, kind, value in SPORT_METRICS:
            with self.subTest(key=key):
                first, second = value, value + 7
                case = _with_sport_settings(
                    [
                        _setting(1, sport_type, **{field: first}),
                        _setting(2, sport_type, **{field: second}),
                    ]
                )
                metrics = _canonical(case)
                self.assertEqual(metrics, _legacy(case))
                self.assertEqual(metrics[key]["value"], first)
                self.assertEqual(metrics[key]["source"], "Intervals.icu")
                self.assertEqual(
                    sorted(_sync_sport_values(case, sport, kind)), [first, second]
                )

    def test_single_entry_takes_the_canonical_label_and_value(self) -> None:
        for sport, sport_type, key, field, kind, value in SPORT_METRICS:
            with self.subTest(key=key):
                case = _with_sport_settings([_setting(1, sport_type, **{field: value})])
                metrics = _canonical(case)
                self.assertEqual(metrics, _legacy(case))
                self.assertEqual(metrics[key]["value"], value)
                self.assertEqual(metrics[key]["source"], "Intervals.icu")
                self.assertEqual(_sync_sport_values(case, sport, kind), [value])


class CanonicalCurrentInputTests(unittest.TestCase):
    def test_reads_use_the_utc_sync_day_with_one_day_either_side(self) -> None:
        case = _case("intervals_only")
        reader = ObservationStub(_observations(case))
        _read(reader, case.intervals)
        window = (SYNC_DAY - timedelta(days=1), SYNC_DAY + timedelta(days=1))
        # The sync instant is found by one unbounded read per current-metric kind
        # and for the athlete record's eFTP.
        self.assertEqual(
            reader.calls[:4],
            [(kind, None, None, None) for kind in (*SYNC_KINDS, MetricKind.EFTP)],
        )
        # The Wahoo fallbacks follow, unwindowed: stored FTP, then weight. The
        # wellness-day eFTP is read last, for the latest wellness day only.
        latest = _latest_wellness_day(_latest_wellness(case.intervals))
        self.assertEqual(
            reader.calls[4:],
            [
                (MetricKind.THRESHOLD_HR, *window, None),
                (MetricKind.VO2MAX, *window, None),
                (MetricKind.WEIGHT, *window, None),
                (MetricKind.EFTP, *window, None),
                (MetricKind.FTP, None, None, None),
                (MetricKind.WEIGHT, None, None, None),
                (MetricKind.EFTP, latest, latest, Sport.RIDE),
            ],
        )

    def test_weight_window_extends_to_an_older_latest_wellness_day(self) -> None:
        case = _case("intervals_only")
        reader = ObservationStub(_observations(case))
        read_current_inputs(
            reader, None, latest_wellness_day=date(2026, 10, 1), as_of=TODAY
        )
        # The Intervals weight read is windowed; the Wahoo weight read follows it.
        self.assertIn(
            (MetricKind.WEIGHT, date(2026, 10, 1), SYNC_DAY + timedelta(days=1), None),
            reader.calls,
        )

    def test_observations_without_an_intervals_sync_instant_yield_none(self) -> None:
        case = _case("intervals_only")
        observations = _observations(case)
        unstamped = tuple(
            replace(
                observation,
                provenance=replace(observation.provenance, retrieved_at=None),
            )
            for observation in observations
        )
        reader = ObservationStub(unstamped)
        self.assertIsNone(read_current_inputs(reader, None, as_of=TODAY))
        self.assertEqual({call[1:] for call in reader.calls}, {(None, None, None)})

    def test_sync_without_stored_sport_values_yields_none(self) -> None:
        self.assertIsNone(read_current_inputs(ObservationStub(()), None, as_of=TODAY))


def _eftp_case(*, athlete: float | None, wellness: float | None) -> Case:
    """The intervals-only case with ride and run eFTP on the athlete and latest day."""
    base = _case("intervals_only")
    intervals = copy.deepcopy(base.intervals)
    settings = intervals["athlete"]["sport_settings"]
    settings[0]["eftp"] = athlete
    settings[1]["eftp"] = 311
    entries = [{"types": ["Run"], "eftp": 312}]
    if wellness is not None:
        entries.append({"types": ["Ride"], "eftp": wellness})
    intervals["recent_wellness"][-1]["sportInfo"] = entries
    return replace(base, intervals=intervals)


class CanonicalEftpInputTests(unittest.TestCase):
    def _inputs(
        self, case: Case, observations: tuple[Observation, ...] | None = None
    ) -> CanonicalCurrentInputs | None:
        reader = ObservationStub(
            _observations(case) if observations is None else observations
        )
        return _read(reader, case.intervals)

    def test_athlete_and_wellness_ride_eftp_are_read_and_run_is_ignored(self) -> None:
        inputs = self._inputs(_eftp_case(athlete=262, wellness=265))
        assert inputs is not None
        assert inputs.athlete_eftp is not None and inputs.wellness_eftp is not None
        self.assertEqual(inputs.athlete_eftp.value.value, 262)
        self.assertEqual(inputs.wellness_eftp.value.value, 265)
        self.assertIs(inputs.athlete_eftp.sport, Sport.RIDE)
        self.assertIs(inputs.wellness_eftp.sport, Sport.RIDE)

    def test_the_athlete_eftp_comes_from_the_athlete_record_only(self) -> None:
        inputs = self._inputs(_eftp_case(athlete=None, wellness=265))
        assert inputs is not None
        self.assertIsNone(inputs.athlete_eftp)
        self.assertEqual(inputs.wellness_eftp and inputs.wellness_eftp.value.value, 265)

    def test_the_wellness_eftp_is_the_latest_wellness_day_only(self) -> None:
        case = _eftp_case(athlete=None, wellness=265)
        intervals = copy.deepcopy(case.intervals)
        intervals["recent_wellness"][0]["sportInfo"] = [
            {"types": ["Ride"], "eftp": 250}
        ]
        del intervals["recent_wellness"][-1]["sportInfo"]
        inputs = self._inputs(replace(case, intervals=intervals))
        assert inputs is not None
        self.assertIsNone(inputs.wellness_eftp)

    def test_an_older_sync_athlete_eftp_never_changes_the_current_value(self) -> None:
        case = _eftp_case(athlete=262, wellness=None)
        current = _observations(case)
        earlier = RETRIEVED_AT - timedelta(days=1)
        stale = tuple(
            replace(
                row,
                value=replace(row.value, value=row.value.value + 5),
                provenance=replace(row.provenance, retrieved_at=earlier),
            )
            for row in current
            if row.kind is MetricKind.EFTP
        )
        inputs = self._inputs(case, (*current, *stale))
        assert inputs is not None and inputs.athlete_eftp is not None
        self.assertEqual(inputs.athlete_eftp.value.value, 262)
        others = tuple(row for row in current if row.kind is not MetricKind.EFTP)
        inputs = self._inputs(case, (*others, *stale))
        assert inputs is not None
        self.assertIsNone(inputs.athlete_eftp)

    def test_an_athlete_record_with_only_an_eftp_still_defines_the_sync(self) -> None:
        # No threshold, VO2max or weight: the athlete eFTP observation alone sets
        # the sync instant (the snapshot reader read the setting without them).
        case = _eftp_case(athlete=262, wellness=None)
        only_athlete_eftp = tuple(
            row
            for row in _observations(case)
            if row.kind is MetricKind.EFTP
            and row.sport is Sport.RIDE
            and row.provenance.source_record_id != row.observed_on.isoformat()
        )
        inputs = self._inputs(case, only_athlete_eftp)
        assert inputs is not None and inputs.athlete_eftp is not None
        self.assertEqual(inputs.athlete_eftp.value.value, 262)

    def test_a_wellness_only_eftp_keeps_the_inputs_without_an_intervals_sync(
        self,
    ) -> None:
        case = _eftp_case(athlete=None, wellness=265)
        only_eftp = tuple(
            row
            for row in _observations(case)
            if row.kind is MetricKind.EFTP and row.sport is Sport.RIDE
        )
        inputs = self._inputs(case, only_eftp)
        assert inputs is not None
        self.assertIsNone(inputs.athlete_eftp)
        self.assertEqual(inputs.wellness_eftp and inputs.wellness_eftp.value.value, 265)
        self.assertIsNone(inputs.athlete_threshold_hr)

    def test_no_eftp_observation_keeps_the_legacy_shaped_inputs(self) -> None:
        case = _case("intervals_only")
        inputs = self._inputs(case)
        assert inputs is not None
        self.assertIsNone(inputs.athlete_eftp)
        self.assertIsNone(inputs.wellness_eftp)

    def test_the_eftp_current_value_is_labelled_like_the_legacy_metric(self) -> None:
        case = _eftp_case(athlete=262, wellness=265)
        garmin = performance_garmin_metrics.garmin_performance_metrics({}, TODAY)
        metrics = current_performance_metrics(
            case.intervals, {}, garmin, canonical=self._inputs(case)
        )
        self.assertEqual(
            metrics["cycling_eftp_watts"],
            {
                "value": 262,
                "unit": "W",
                "source": "Intervals.icu",
                "source_provider": "intervals",
                "note": "",
            },
        )


class CanonicalWeightTests(unittest.TestCase):
    def test_wellness_weight_matches_the_legacy_value_and_label(self) -> None:
        case = _case("intervals_only")
        metrics = _canonical(case)
        self.assertEqual(metrics["weight_kg"], _legacy(case)["weight_kg"])
        self.assertEqual(metrics["weight_kg"]["value"], 80.6)
        self.assertEqual(metrics["weight_kg"]["source"], "Intervals.icu Wellness")

    def test_athlete_weight_is_the_fallback_with_the_intervals_label(self) -> None:
        case = _case("sparse_profile")
        intervals = copy.deepcopy(case.intervals)
        del intervals["recent_wellness"][-1]["weight"]
        variant = replace(case, intervals=intervals)
        metrics = _canonical(variant, _observations(variant))
        self.assertEqual(metrics["weight_kg"], _legacy(variant)["weight_kg"])
        self.assertEqual(metrics["weight_kg"]["value"], 79.9)
        self.assertEqual(metrics["weight_kg"]["source"], "Intervals.icu")

    def test_older_wellness_day_weight_is_never_used(self) -> None:
        case = _case("intervals_only")
        intervals = copy.deepcopy(case.intervals)
        del intervals["recent_wellness"][-1]["weight"]
        variant = replace(case, intervals=intervals)
        observations = _observations(variant)
        inputs = _read(ObservationStub(observations), variant.intervals)
        assert inputs is not None
        self.assertIsNone(inputs.wellness_weight)
        metrics = _canonical(variant, observations)
        self.assertEqual(metrics["weight_kg"], _legacy(variant)["weight_kg"])
        self.assertNotEqual(metrics["weight_kg"]["value"], 80.9)

    def test_weight_rows_from_an_earlier_sync_never_change_the_current_weight(
        self,
    ) -> None:
        case = _case("intervals_only")
        earlier = RETRIEVED_AT - timedelta(days=1)
        stale = tuple(
            replace(
                row,
                value=replace(row.value, value=row.value.value + 5),
                provenance=replace(row.provenance, retrieved_at=earlier),
            )
            for row in _observations(case)
            if row.kind is MetricKind.WEIGHT
        )
        self.assertEqual(
            _canonical(case, (*_observations(case), *stale)), _legacy(case)
        )


class CanonicalCurrentFromTablesTests(CanonicalReadFixture):
    def test_populated_tables_reproduce_the_legacy_current_metrics(self) -> None:
        populate(self)
        selector = make_selector(self)
        self.assertEqual(self.write(selector.summary)["serving"], "tables")
        with self.manager.reader() as db:
            inputs = read_performance_inputs(selector, db, as_of=TODAY)
        self.assertIsNotNone(inputs)
        assert inputs is not None
        self.assertIsNotNone(inputs.current)
        legacy = current_performance_context(self.intervals, self.garmin, {}, TODAY)
        canonical = current_performance_context(
            self.intervals, self.garmin, {}, TODAY, canonical=inputs
        )
        # Intended difference (#1412): eFTP is read from canonical observations only,
        # so it is absent without canonical inputs. The canonical value is the
        # fixture athlete's Ride eFTP, labelled as before.
        ride = next(
            setting
            for setting in self.intervals["raw_provider_data"]["athlete"][
                "sportSettings"
            ]
            if setting["types"] == ["Ride"]
        )
        self.assertIsNone(legacy["metrics"]["cycling_eftp_watts"]["value"])
        self.assertEqual(
            canonical["metrics"]["cycling_eftp_watts"],
            {
                "value": ride["eftp"],
                "unit": "W",
                "source": "Intervals.icu",
                "source_provider": "intervals",
                "note": "",
            },
        )
        for key in legacy["metrics"].keys() - {"cycling_eftp_watts"}:
            self.assertEqual(canonical["metrics"][key], legacy["metrics"][key], key)


def _wahoo_ftp(value: float, sport_family: int = 0) -> Observation:
    (record,) = map_wahoo_power_zones(
        [
            {
                "id": 1,
                "workout_type_family_id": sport_family,
                "ftp": value,
                "updated_at": "2026-10-01T10:00:00Z",
            }
        ],
        zone=UTC,
        retrieved_at=RETRIEVED_AT,
    ).records
    return record


def _wahoo_weight(value: float) -> Observation:
    (record,) = map_wahoo_user(
        {"weight": value}, observed_on=SYNC_DAY, retrieved_at=RETRIEVED_AT
    ).records
    return record


class WahooFallbackReadTests(unittest.TestCase):
    def test_stored_wahoo_ftp_and_weight_are_the_only_current_inputs(self) -> None:
        reader = ObservationStub((_wahoo_ftp(250), _wahoo_weight(78.5)))

        inputs = read_wahoo_fallbacks(reader, None, as_of=TODAY)

        assert inputs is not None
        assert inputs.wahoo_ftp is not None
        assert inputs.wahoo_weight is not None
        self.assertEqual((), inputs.bike_threshold_hr)
        self.assertIsNone(inputs.athlete_weight)
        self.assertEqual(250, inputs.wahoo_ftp.value.value)
        self.assertEqual(78.5, inputs.wahoo_weight.value.value)

    def test_only_a_wahoo_ride_ftp_is_read(self) -> None:
        wahoo_ftp = _wahoo_ftp(300)
        intervals_ftp = replace(
            wahoo_ftp,
            provenance=replace(wahoo_ftp.provenance, provider=ProviderId.INTERVALS),
        )
        run_ftp = _wahoo_ftp(280, sport_family=1)

        self.assertIsNone(
            read_wahoo_fallbacks(ObservationStub((intervals_ftp,)), None, as_of=TODAY)
        )
        self.assertIsNone(
            read_wahoo_fallbacks(ObservationStub((run_ftp,)), None, as_of=TODAY)
        )

    def test_no_stored_wahoo_rows_yields_none(self) -> None:
        self.assertIsNone(read_wahoo_fallbacks(ObservationStub(()), None, as_of=TODAY))

    def test_wahoo_rows_alone_feed_the_current_inputs(self) -> None:
        reader = ObservationStub((_wahoo_ftp(250), _wahoo_weight(78.5)))

        inputs = read_current_inputs(reader, None, as_of=TODAY)

        assert inputs is not None
        assert inputs.wahoo_ftp is not None
        assert inputs.wahoo_weight is not None
        self.assertEqual(250, inputs.wahoo_ftp.value.value)
        self.assertEqual(78.5, inputs.wahoo_weight.value.value)


AS_OF: Final = TODAY
WAHOO_AGE_LIMIT_DAYS: Final = 90


def _wahoo_ftp_on(value: float, day: date) -> Observation:
    (record,) = map_wahoo_power_zones(
        [
            {
                "id": 1,
                "workout_type_family_id": 0,
                "ftp": value,
                "updated_at": f"{day.isoformat()}T10:00:00Z",
            }
        ],
        zone=UTC,
        retrieved_at=RETRIEVED_AT,
    ).records
    return record


def _wahoo_weight_on(value: float, day: date) -> Observation:
    (record,) = map_wahoo_user(
        {"weight": value}, observed_on=day, retrieved_at=RETRIEVED_AT
    ).records
    return record


class _UnitOfWorkManager:
    """Opens a unit of work without a database; the stub reader needs no connection."""

    def unit_of_work(self) -> contextlib.AbstractContextManager[None]:
        return contextlib.nullcontext()

    read_snapshot = unit_of_work


class WahooAgeLimitProductionReadTests(unittest.TestCase):
    """A Wahoo FTP or weight older than its limit is not current on the read day.

    The stored rows stay readable: history keeps them, and a read on a day within
    the limit still uses them.
    """

    SNAPSHOT: Final = {"recent_wellness": [{"id": AS_OF.isoformat()}]}

    class ActivityReader:
        def activity_rows(self, _db, *, start=None, end=None, limit=None):
            return ()

    def _stored(self, day: date) -> ObservationStub:
        return ObservationStub((_wahoo_ftp_on(250, day), _wahoo_weight_on(78.5, day)))

    def test_a_wahoo_value_91_days_old_is_not_current(self) -> None:
        stale = AS_OF - timedelta(days=WAHOO_AGE_LIMIT_DAYS + 1)
        inputs = read_performance_inputs(
            self._stored(stale),
            None,
            activity_reader=self.ActivityReader(),
            as_of=AS_OF,
        )
        assert inputs is not None
        self.assertIsNone(inputs.current)

    def test_a_wahoo_value_90_days_old_is_current(self) -> None:
        limit = AS_OF - timedelta(days=WAHOO_AGE_LIMIT_DAYS)
        inputs = read_performance_inputs(
            self._stored(limit),
            None,
            activity_reader=self.ActivityReader(),
            as_of=AS_OF,
        )
        assert inputs is not None
        assert inputs.current is not None
        assert inputs.current.wahoo_ftp is not None
        assert inputs.current.wahoo_weight is not None
        self.assertEqual(250, inputs.current.wahoo_ftp.value.value)
        self.assertEqual(78.5, inputs.current.wahoo_weight.value.value)

    def test_the_stale_value_stays_stored_and_is_read_within_the_limit(self) -> None:
        stale = AS_OF - timedelta(days=WAHOO_AGE_LIMIT_DAYS + 1)
        reader = self._stored(stale)
        read_performance_inputs(
            reader,
            None,
            activity_reader=self.ActivityReader(),
            as_of=AS_OF,
        )
        # History: the store still returns both stale Wahoo rows.
        self.assertEqual(
            [stale], [o.observed_on for o in reader.observations(None, MetricKind.FTP)]
        )
        self.assertEqual(
            [stale],
            [o.observed_on for o in reader.observations(None, MetricKind.WEIGHT)],
        )
        # Reads: the same rows are used once the read day is within the limit.
        within = stale + timedelta(days=WAHOO_AGE_LIMIT_DAYS)
        inputs = read_performance_inputs(
            reader,
            None,
            activity_reader=self.ActivityReader(),
            as_of=within,
        )
        assert inputs is not None
        assert inputs.current is not None
        assert inputs.current.wahoo_ftp is not None
        self.assertEqual(250, inputs.current.wahoo_ftp.value.value)

    def test_the_coach_context_read_applies_the_athlete_day(self) -> None:
        stale = AS_OF - timedelta(days=WAHOO_AGE_LIMIT_DAYS + 1)
        reader = self._stored(stale)
        source = CanonicalPerformanceSource(
            database_manager=_UnitOfWorkManager,
            observation_reader=lambda: reader,
            activity_rows=self.ActivityReader,
        )
        context = CoachPerformanceContextReader(
            None, None, None, today=lambda: AS_OF, canonical=source
        )
        _snapshot, inputs = context.read_snapshot(lambda: self.SNAPSHOT)
        assert inputs is not None
        self.assertIsNone(inputs.current)
