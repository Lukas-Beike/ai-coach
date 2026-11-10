"""Warnings for stale load thresholds and a failing Garmin SDK (#1768)."""

import unittest
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, timedelta
from unittest import mock

from canonical_domain_support import local_zone_configuration
from performance_day_support import StubReader

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    Environment,
    MetricKind,
    ProviderId,
    RecordingOrigin,
    SourceKind,
    Sport,
    ZoneConfigurationMetric,
)
from backend.db import canonical_domain_store
from backend.performance.source_policy import NO_PREFERENCES
from backend.performance.threshold_staleness import (
    STALE_AFTER_DAYS,
    DatedThreshold,
    ThresholdStalenessService,
    assess_thresholds,
    value_text,
)

TODAY = date(2026, 11, 7)
GARMIN = ProviderId.GARMIN
RIDE_FTP = (MetricKind.FTP, Sport.RIDE)
RUN_LTHR = (MetricKind.THRESHOLD_HR, Sport.RUN)
SDK_FAILED = {"reason": "login_failed", "at": "2026-11-06T06:00:00Z"}


def _days_ago(days: int) -> date:
    return TODAY - timedelta(days=days)


def _garmin(kind: MetricKind, value: float, sport: Sport, age: int) -> Observation:
    return Observation(
        kind=kind,
        value=MetricValue(value, kind.unit),
        observed_on=_days_ago(age),
        observed_at=None,
        provenance=Provenance(
            provider=GARMIN,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=f"g:{kind.value}:{value}",
            recorded_by=RecordingOrigin.GARMIN,
            retrieved_at=None,
            label=None,
        ),
        sport=sport,
    )


def _local_ftp(threshold: float, *, indoor: bool = False, valid_from=None):
    return local_zone_configuration(
        metric=ZoneConfigurationMetric.POWER,
        sport=Sport.RIDE,
        environment=Environment.INDOOR if indoor else None,
        valid_from=valid_from,
        threshold=threshold,
        maximum=None,
        resting=None,
        limits=(100.0, 200.0, 300.0, 400.0),
    )


class AssessTests(unittest.TestCase):
    def test_fresh_thresholds_give_no_warning(self) -> None:
        active = {RIDE_FTP: DatedThreshold(260.0, GARMIN, _days_ago(STALE_AFTER_DAYS))}
        self.assertIsNone(assess_thresholds(active, {}, today=TODAY))

    def test_stale_threshold_names_value_source_and_age(self) -> None:
        active = {RIDE_FTP: DatedThreshold(260.0, GARMIN, _days_ago(70))}
        warning = assess_thresholds(active, {}, today=TODAY)
        assert warning is not None
        self.assertEqual(warning["stale_after_days"], 56)
        self.assertIsNone(warning["sdk_failure"])
        (item,) = warning["items"]
        self.assertEqual(
            {key: item[key] for key in ("label", "value_text", "source_label")},
            {"label": "FTP Rad", "value_text": "260 W", "source_label": "Garmin"},
        )
        self.assertEqual((item["age_days"], item["reason"]), (70, "stale"))

    def test_value_past_the_source_age_limit_is_expired(self) -> None:
        last = {RUN_LTHR: DatedThreshold(168.0, GARMIN, _days_ago(200))}
        warning = assess_thresholds({}, last, today=TODAY)
        assert warning is not None
        self.assertEqual(
            [(item["label"], item["reason"]) for item in warning["items"]],
            [("Schwellenpuls (LSHF) Laufen", "expired")],
        )

    def test_sdk_failure_lists_fresh_garmin_values(self) -> None:
        active = {RIDE_FTP: DatedThreshold(260.0, GARMIN, _days_ago(3))}
        warning = assess_thresholds(active, {}, today=TODAY, sdk_failure=SDK_FAILED)
        assert warning is not None
        self.assertEqual(warning["sdk_failure"], SDK_FAILED)
        self.assertEqual(warning["items"][0]["reason"], "sdk_failed")

    def test_local_override_is_unaffected_by_the_sdk(self) -> None:
        active = {RIDE_FTP: DatedThreshold(300.0, None, _days_ago(10))}
        last = {RIDE_FTP: DatedThreshold(260.0, GARMIN, _days_ago(300))}
        self.assertIsNone(
            assess_thresholds(active, last, today=TODAY, sdk_failure=SDK_FAILED)
        )

    def test_stale_local_value_warns_as_local(self) -> None:
        active = {RIDE_FTP: DatedThreshold(300.0, None, _days_ago(90))}
        warning = assess_thresholds(active, {}, today=TODAY, sdk_failure=SDK_FAILED)
        assert warning is not None
        self.assertIsNone(warning["sdk_failure"])
        item = warning["items"][0]
        self.assertEqual((item["source"], item["source_label"]), ("local", "Lokal"))

    def test_undated_local_value_is_not_judged(self) -> None:
        active = {RIDE_FTP: DatedThreshold(300.0, None, None)}
        self.assertIsNone(assess_thresholds(active, {}, today=TODAY))

    def test_indoor_ftp_is_judged_only_when_the_athlete_set_one(self) -> None:
        active = {RIDE_FTP: DatedThreshold(260.0, GARMIN, _days_ago(3))}
        self.assertIsNone(assess_thresholds(active, {}, today=TODAY))
        fresh_indoor = DatedThreshold(250.0, None, _days_ago(5))
        self.assertIsNone(
            assess_thresholds(active, {}, today=TODAY, indoor_local=fresh_indoor)
        )
        stale_indoor = DatedThreshold(250.0, None, _days_ago(70))
        warning = assess_thresholds(active, {}, today=TODAY, indoor_local=stale_indoor)
        assert warning is not None
        (item,) = warning["items"]
        self.assertEqual(
            (item["metric"], item["label"], item["reason"], item["value_text"]),
            ("indoor_ftp", "Indoor-FTP", "stale", "250 W"),
        )
        self.assertEqual((item["source"], item["age_days"]), ("local", 70))

    def test_pace_reads_per_kilometre(self) -> None:
        self.assertEqual(value_text(MetricKind.THRESHOLD_PACE, 1000 / 270), "4:30 /km")


class _Database:
    @contextmanager
    def reader(self):
        yield None


class ServiceTests(unittest.TestCase):
    def _read(self, observations, configurations=(), *, saved=None, **kwargs):
        service = ThresholdStalenessService(
            _Database,
            lambda: StubReader(tuple(observations)),
            lambda: TODAY,
            zone_configurations=lambda _db: tuple(configurations),
            preferences=lambda _db: NO_PREFERENCES,
            **kwargs,
        )
        with mock.patch.object(
            canonical_domain_store,
            "local_zone_saved_days",
            return_value=saved or {},
        ):
            return service.read()

    def test_fresh_garmin_values_give_none(self) -> None:
        self.assertIsNone(self._read((_garmin(MetricKind.FTP, 260.0, Sport.RIDE, 10),)))

    def test_stale_and_expired_garmin_values(self) -> None:
        warning = self._read(
            (
                _garmin(MetricKind.FTP, 260.0, Sport.RIDE, 70),
                _garmin(MetricKind.THRESHOLD_HR, 168.0, Sport.RUN, 200),
            )
        )
        assert warning is not None
        self.assertEqual(
            [(item["label"], item["reason"]) for item in warning["items"]],
            [("FTP Rad", "stale"), ("Schwellenpuls (LSHF) Laufen", "expired")],
        )

    def test_sdk_failure_marks_garmin_values(self) -> None:
        warning = self._read(
            (_garmin(MetricKind.FTP, 260.0, Sport.RIDE, 3),),
            sdk_failure=lambda: SDK_FAILED,
        )
        assert warning is not None
        self.assertEqual(warning["sdk_failure"], SDK_FAILED)

    def test_local_value_dates_by_valid_from_else_last_save(self) -> None:
        stale_garmin = (_garmin(MetricKind.FTP, 260.0, Sport.RIDE, 100),)
        local = _local_ftp(300.0)
        key = canonical_domain_store.zone_configuration_key(local)
        self.assertIsNone(self._read(stale_garmin, [local], saved={key: _days_ago(5)}))
        warning = self._read(stale_garmin, [local], saved={key: _days_ago(80)})
        assert warning is not None
        self.assertEqual(
            (warning["items"][0]["source"], warning["items"][0]["age_days"]),
            ("local", 80),
        )
        dated = _local_ftp(300.0, valid_from=_days_ago(60))
        warning = self._read(stale_garmin, [dated], saved={key: _days_ago(1)})
        assert warning is not None
        self.assertEqual(warning["items"][0]["age_days"], 60)

    def test_indoor_rides_use_the_ride_ftp_without_a_warning(self) -> None:
        fresh = (_garmin(MetricKind.FTP, 260.0, Sport.RIDE, 3),)
        self.assertIsNone(self._read(fresh))

    def test_only_an_explicit_stale_indoor_ftp_warns(self) -> None:
        fresh = (_garmin(MetricKind.FTP, 260.0, Sport.RIDE, 3),)
        recent = _local_ftp(250.0, indoor=True, valid_from=_days_ago(5))
        self.assertIsNone(self._read(fresh, [recent]))
        old = _local_ftp(250.0, indoor=True, valid_from=_days_ago(70))
        warning = self._read(fresh, [old])
        assert warning is not None
        (item,) = warning["items"]
        self.assertEqual(
            (item["metric"], item["reason"], item["source"], item["age_days"]),
            ("indoor_ftp", "stale", "local", 70),
        )

    def test_stale_wahoo_ftp_is_named(self) -> None:
        wahoo = replace(
            _garmin(MetricKind.FTP, 250.0, Sport.RIDE, 70),
            provenance=replace(
                _garmin(MetricKind.FTP, 250.0, Sport.RIDE, 70).provenance,
                provider=ProviderId.WAHOO,
                recorded_by=RecordingOrigin.UPLOAD,
            ),
        )
        warning = self._read((wahoo,))
        assert warning is not None
        self.assertEqual(
            (warning["items"][0]["source_label"], warning["items"][0]["reason"]),
            ("Wahoo", "stale"),
        )

    def test_undated_local_value_hides_the_expired_provider_value(self) -> None:
        expired = (_garmin(MetricKind.FTP, 260.0, Sport.RIDE, 300),)
        self.assertIsNone(self._read(expired, [_local_ftp(300.0)]))

    def test_a_failing_read_gives_none(self) -> None:
        service = ThresholdStalenessService(
            _Database,
            lambda: None,
            lambda: TODAY,
            zone_configurations=lambda _db: (),
            preferences=lambda _db: NO_PREFERENCES,
        )
        with self.assertLogs("intervals_coach", level="WARNING"):
            self.assertIsNone(service.read())


if __name__ == "__main__":
    unittest.main()
