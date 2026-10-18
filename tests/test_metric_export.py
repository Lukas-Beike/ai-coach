"""Previewed, confirmed metric export to Intervals.icu with mocked transport."""

from __future__ import annotations

import http.client
import json
import sqlite3
import threading
import unittest
from contextlib import contextmanager
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import Mock, patch

from server_test_support import ServerTestCase, create_test_session, server

from backend.canonical.records import MetricValue, Observation, Provenance
from backend.canonical.vocabulary import (
    MetricKind,
    ProviderId,
    RecordingOrigin,
    RemoteEntityKind,
    RemoteLinkState,
    SourceKind,
    Sport,
)
from backend.config import Config
from backend.db.canonical_store import observation_natural_key
from backend.db.remote_links import RemoteLinkRepository
from backend.db.schema import initialize_schema
from backend.errors import AppError
from backend.http_api import server as http_server_module
from backend.providers.intervals_client import IntervalsClient
from backend.sync.intervals_metric_export import IntervalsMetricExport
from backend.sync.metric_export import MetricExportService
from backend.sync.metric_export_port import (
    MetricExportField,
    MetricExportPort,
    MetricWrite,
)

TODAY = date(2026, 10, 12)
NOW = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
RAW = "RAW-UPSTREAM-SENTINEL api_key=secret"
UNITS = {
    MetricKind.WEIGHT: "kg",
    MetricKind.BODY_FAT: "%",
    MetricKind.RESTING_HR: "bpm",
    MetricKind.FTP: "W",
    MetricKind.THRESHOLD_HR: "bpm",
    MetricKind.MAX_HR: "bpm",
    MetricKind.THRESHOLD_PACE: "m/s",
}


def obs(kind, value, day, provider, *, sport=None) -> Observation:
    return Observation(
        kind=kind,
        value=MetricValue(value, UNITS[kind]),
        observed_on=day,
        observed_at=None,
        provenance=Provenance(
            provider=provider,
            source_kind=SourceKind.PROVIDER_REPORTED,
            source_record_id=None,
            recorded_by=RecordingOrigin.UNKNOWN,
            retrieved_at=NOW,
            label=None,
        ),
        sport=sport,
    )


def provider_less(kind, value, day) -> Observation:
    return Observation(
        kind=kind,
        value=MetricValue(value, UNITS[kind]),
        observed_on=day,
        observed_at=None,
        provenance=Provenance(
            provider=None,
            source_kind=SourceKind.AI_ESTIMATE,
            source_record_id=None,
            recorded_by=RecordingOrigin.UNKNOWN,
            retrieved_at=NOW,
            label=None,
        ),
    )


class FakeReader:
    def __init__(self) -> None:
        self.items: list[Observation] = []

    def observations(self, db, kind, *, start=None, end=None, sport=None):
        return [
            item
            for item in self.items
            if item.kind is kind
            and (start is None or item.observed_on >= start)
            and (end is None or item.observed_on <= end)
            and (sport is None or item.sport is sport)
        ]


class FakeDatabase:
    def __init__(self) -> None:
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        initialize_schema(self.db)

    @contextmanager
    def reader(self):
        yield self.db

    @contextmanager
    def unit_of_work(self):
        with self.db:
            yield self.db


class IntervalsMetricExportEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.request = Mock(return_value={})
        config = SimpleNamespace(intervals_api_key="key", intervals_athlete_id="i1")
        self.client = IntervalsClient(cast(Config, config), request=self.request)
        self.port = IntervalsMetricExport(lambda: self.client)

    def field(self, kind: MetricKind, sport: Sport | None = None) -> MetricExportField:
        field = self.port.field_for(kind, sport)
        assert field is not None
        return field

    def write(self, kind, sport, value, *, recalc=False) -> None:
        field = self.port.field_for(kind, sport)
        assert field is not None
        self.port.write(
            [MetricWrite(field, value, date(2026, 10, 1))], recalc_hr_zones=recalc
        )

    def call(self):
        self.request.assert_called_once()
        method, url, payload, *_ = self.request.call_args.args
        return method, url, payload

    def test_port_satisfies_the_protocol(self) -> None:
        self.assertIsInstance(self.port, MetricExportPort)

    def test_wellness_writes_only_the_sent_field_of_the_day(self) -> None:
        self.write(MetricKind.WEIGHT, None, 70.456)
        self.assertEqual(
            self.call(),
            (
                "PUT",
                "https://intervals.icu/api/v1/athlete/i1/wellness/2026-10-01",
                {"id": "2026-10-01", "weight": 70.46},
            ),
        )

    def test_run_settings_recalculate_zones_only_on_request(self) -> None:
        self.write(MetricKind.THRESHOLD_HR, Sport.RUN, 170.4, recalc=True)
        self.assertEqual(
            self.call(),
            (
                "PUT",
                "https://intervals.icu/api/v1/athlete/i1/sport-settings/Run?recalcHrZones=true",
                {"lthr": 170},
            ),
        )

    def test_ride_settings_without_recalc_keep_zones(self) -> None:
        self.write(MetricKind.FTP, None, 251.6)
        self.assertEqual(
            self.call(),
            (
                "PUT",
                "https://intervals.icu/api/v1/athlete/i1/sport-settings/Ride?recalcHrZones=false",
                {"ftp": 252},
            ),
        )

    def test_reads_return_only_finite_numbers_of_the_record(self) -> None:
        self.request.return_value = {
            "id": "2026-10-01",
            "weight": 70.4,
            "restingHR": 48,
            "bodyFat": None,
            "locked": True,
            "lthr": float("nan"),
        }
        field = self.field(MetricKind.WEIGHT)
        self.assertEqual(
            self.port.read_record(field, date(2026, 10, 1)),
            {"weight": 70.4, "restingHR": 48.0},
        )
        method, url, *_ = self.request.call_args.args
        self.assertEqual(
            (method, url),
            ("GET", "https://intervals.icu/api/v1/athlete/i1/wellness/2026-10-01"),
        )
        self.request.reset_mock()
        self.request.return_value = {"ftp": 255}
        settings = self.field(MetricKind.FTP)
        self.assertEqual(
            self.port.read_record(settings, date(2026, 10, 1)), {"ftp": 255.0}
        )
        method, url, *_ = self.request.call_args.args
        self.assertEqual(
            (method, url),
            ("GET", "https://intervals.icu/api/v1/athlete/i1/sport-settings/Ride"),
        )

    def test_a_missing_wellness_day_reads_empty_and_bad_replies_fail(self) -> None:
        weight = self.field(MetricKind.WEIGHT)
        ftp = self.field(MetricKind.FTP)
        self.request.side_effect = AppError(
            404, RAW, reason="upstream_rejected", upstream_status=404
        )
        self.assertEqual(self.port.read_record(weight, date(2026, 10, 1)), {})
        with self.assertRaises(AppError):
            self.port.read_record(ftp, date(2026, 10, 1))
        self.request.side_effect = None
        self.request.return_value = ["unexpected"]
        with self.assertRaises(AppError) as caught:
            self.port.read_record(weight, date(2026, 10, 1))
        self.assertEqual(caught.exception.reason, "upstream_invalid_response")

    def test_unsupported_fields_are_not_mapped(self) -> None:
        self.assertIsNone(self.port.field_for(MetricKind.THRESHOLD_PACE, Sport.RIDE))
        self.assertIsNone(self.port.field_for(MetricKind.MAX_HR, None))
        self.assertEqual(
            self.field(MetricKind.THRESHOLD_PACE, Sport.RUN).field,
            "threshold_pace",
        )


class MetricExportServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.database = FakeDatabase()
        self.addCleanup(self.database.db.close)
        self.reader = FakeReader()
        # Live target state: wellness per day and sport settings per sport.
        self.wellness: dict[str, dict] = {}
        self.settings: dict[str, dict] = {}
        self.client = Mock()
        self.client.get_wellness.side_effect = lambda day: dict(
            self.wellness.get(day, {})
        )
        self.client.get_sport_settings.side_effect = lambda sport: dict(
            self.settings.get(sport, {})
        )
        self.client.update_wellness.return_value = {}
        self.client.update_sport_settings.return_value = {}
        self.client_factory = Mock(return_value=self.client)
        self.service = MetricExportService(
            lambda: self.database,
            lambda: self.reader,
            {ProviderId.INTERVALS: lambda: IntervalsMetricExport(self.client_factory)},
            database_lock=threading.Lock(),
            today=lambda: TODAY,
            utc_now=lambda: NOW,
        )

    def add(self, *items: Observation) -> None:
        self.reader.items.extend(items)

    def items(self, **payload):
        return {item["key"]: item for item in self.service.preview(payload)["items"]}

    def confirm(self, preview_items, **extra):
        payload = {
            "confirmed": True,
            "provider": "intervals",
            "metrics": [
                {
                    "key": item["key"],
                    "observed_on": item["observed_on"],
                    "value": item["value"],
                    "current_remote_value": item["current_remote_value"],
                }
                for item in preview_items
            ],
        }
        payload.update(extra)
        return self.service.export(payload)

    def link(self, observation):
        return RemoteLinkRepository().get(
            self.database.db,
            RemoteEntityKind.OBSERVATION,
            observation_natural_key(observation),
            "intervals",
        )

    def test_a_late_read_failure_preserves_prior_success_and_other_groups(self):
        self.add(
            obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN),
            obs(
                MetricKind.THRESHOLD_HR, 160, TODAY, ProviderId.GARMIN, sport=Sport.RUN
            ),
        )
        self.client.get_sport_settings.side_effect = [
            {"ftp": 240},
            {"lthr": 150},
            {"ftp": 240},
            RuntimeError(RAW),
        ]
        with self.assertLogs("backend.sync.metric_export", "WARNING"):
            self.assertEqual(
                self.service.sync_garmin(), {"exported": 1, "failed": 1, "conflicts": 0}
            )
        self.client.update_sport_settings.assert_called_once_with(
            "Ride", {"ftp": 250}, recalc_hr_zones=False
        )

    def test_automatic_garmin_export_is_idempotent_and_preserves_zones(self):
        self.add(obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN))
        self.settings["Ride"] = {"ftp": 240}
        receipt = self.service.sync_garmin()
        self.assertEqual(receipt, {"exported": 1, "failed": 0, "conflicts": 0})
        self.client.update_sport_settings.assert_called_once_with(
            "Ride", {"ftp": 250}, recalc_hr_zones=False
        )
        self.settings["Ride"]["ftp"] = 250
        self.assertEqual(self.service.sync_garmin()["exported"], 0)
        self.assertEqual(self.client.update_sport_settings.call_count, 1)

    def test_new_garmin_value_after_restart_preserves_a_manual_target_change(self):
        self.add(obs(MetricKind.FTP, 250, date(2026, 10, 10), ProviderId.GARMIN))
        self.service.sync_garmin()
        self.settings["Ride"] = {"ftp": 260}
        self.add(obs(MetricKind.FTP, 255, TODAY, ProviderId.GARMIN))
        restarted = MetricExportService(
            lambda: self.database,
            lambda: self.reader,
            {ProviderId.INTERVALS: lambda: IntervalsMetricExport(self.client_factory)},
            database_lock=threading.Lock(),
            today=lambda: TODAY,
            utc_now=lambda: NOW,
        )
        self.assertEqual(
            restarted.sync_garmin(), {"exported": 0, "failed": 0, "conflicts": 1}
        )
        self.assertEqual(self.client.update_sport_settings.call_count, 1)
        # Restoring the accepted target value resumes this field.
        self.settings["Ride"]["ftp"] = 250
        self.assertEqual(restarted.sync_garmin()["exported"], 1)
        self.assertEqual(
            self.client.update_sport_settings.call_args.args, ("Ride", {"ftp": 255})
        )

    def test_matching_initial_value_establishes_a_conflict_baseline(self):
        self.add(obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN))
        self.settings["Ride"] = {"ftp": 250}
        self.assertEqual(self.service.sync_garmin()["exported"], 0)
        self.settings["Ride"]["ftp"] = 260
        self.assertEqual(self.service.sync_garmin()["conflicts"], 1)
        self.client.update_sport_settings.assert_not_called()

    def test_automatic_export_uses_only_garmin_provider_measurements(self):
        self.add(
            obs(MetricKind.FTP, 250, date(2026, 10, 10), ProviderId.GARMIN),
            obs(MetricKind.FTP, 270, TODAY, ProviderId.WAHOO),
            obs(MetricKind.WEIGHT, 70, TODAY, ProviderId.INTERVALS),
            provider_less(MetricKind.THRESHOLD_PACE, 4, TODAY),
            obs(MetricKind.RESTING_HR, 50, date(2026, 10, 13), ProviderId.GARMIN),
            obs(MetricKind.BODY_FAT, 15, date(2026, 1, 1), ProviderId.GARMIN),
        )
        self.assertEqual(self.service.sync_garmin()["exported"], 1)
        self.client.update_sport_settings.assert_called_once_with(
            "Ride", {"ftp": 250}, recalc_hr_zones=False
        )
        self.client.update_wellness.assert_not_called()

    def test_conflict_does_not_block_other_fields(self):
        self.add(obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN))
        self.service.sync_garmin()
        self.settings["Ride"] = {"ftp": 260}
        self.add(
            obs(
                MetricKind.THRESHOLD_HR, 160, TODAY, ProviderId.GARMIN, sport=Sport.RIDE
            )
        )
        self.assertEqual(
            self.service.sync_garmin(), {"exported": 1, "failed": 0, "conflicts": 1}
        )
        self.assertEqual(
            self.client.update_sport_settings.call_args.args, ("Ride", {"lthr": 160})
        )

    def test_automatic_write_failure_retries_without_persisting_baseline(self):
        self.add(obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN))
        self.client.update_sport_settings.side_effect = RuntimeError(RAW)
        with self.assertLogs("backend.sync.metric_export", "WARNING") as logs:
            self.assertEqual(self.service.sync_garmin()["failed"], 1)
        self.assertNotIn(RAW, str(logs.output))
        self.client.update_sport_settings.side_effect = None
        self.assertEqual(self.service.sync_garmin()["exported"], 1)

    def test_target_change_during_automatic_export_is_not_overwritten(self):
        self.add(obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN))
        self.client.get_sport_settings.side_effect = [{"ftp": 240}, {"ftp": 260}]
        self.assertEqual(self.service.sync_garmin()["conflicts"], 1)
        self.client.update_sport_settings.assert_not_called()

    def test_manual_export_resolves_an_automatic_conflict(self):
        self.add(obs(MetricKind.FTP, 250, date(2026, 10, 10), ProviderId.GARMIN))
        self.service.sync_garmin()
        self.settings["Ride"] = {"ftp": 260}
        self.add(obs(MetricKind.FTP, 255, TODAY, ProviderId.GARMIN))
        self.assertEqual(self.service.sync_garmin()["conflicts"], 1)
        self.confirm(list(self.items().values()))
        self.settings["Ride"]["ftp"] = 255
        self.assertEqual(self.service.sync_garmin()["conflicts"], 0)

    def test_preview_lists_source_target_and_live_remote_value(self) -> None:
        # The cached target value is stale; the preview shows the live one.
        self.wellness["2026-10-10"] = {"weight": 71.2, "bodyFat": 15.0}
        self.add(
            obs(MetricKind.WEIGHT, 70.4, date(2026, 10, 10), ProviderId.GARMIN),
            obs(MetricKind.WEIGHT, 72.0, date(2026, 10, 10), ProviderId.INTERVALS),
            obs(
                MetricKind.MAX_HR,
                191,
                date(2026, 10, 1),
                ProviderId.GARMIN,
                sport=Sport.RUN,
            ),
            obs(MetricKind.FTP, 260, date(2026, 10, 2), ProviderId.WAHOO),
        )
        preview = self.service.preview({})
        self.assertEqual(preview["provider"], "intervals")
        self.assertEqual(preview["provider_label"], "Intervals.icu")
        self.assertTrue(preview["recalc_hr_zones_available"])
        items = {item["key"]: item for item in preview["items"]}
        weight = items["weight|"]
        self.assertEqual(weight["value"], 70.4)
        self.assertEqual(weight["unit"], "kg")
        self.assertEqual(weight["observed_on"], "2026-10-10")
        self.assertEqual(weight["source_provider"], "garmin")
        self.assertTrue(weight["source_label"])
        self.assertEqual(weight["target_field"], "weight")
        self.assertEqual(weight["target_label"], "Wellness · weight")
        self.assertEqual(weight["remote_record"], "wellness/2026-10-10")
        self.assertEqual(weight["current_remote_value"], 71.2)
        self.assertNotIn("current_remote_observed_on", weight)
        self.assertEqual(weight["status"], "ready")
        self.assertTrue(weight["selectable"])
        self.assertFalse(weight["zone_recalc"])
        self.assertEqual(items["max_hr|run"]["target_field"], "max_hr")
        self.assertEqual(items["max_hr|run"]["remote_record"], "sport-settings/Run")
        self.assertIsNone(items["max_hr|run"]["current_remote_value"])
        self.assertTrue(items["max_hr|run"]["zone_recalc"])
        self.assertEqual(items["ftp|ride"]["remote_record"], "sport-settings/Ride")
        # Each offered record is read once; nothing is written by a preview.
        self.client.get_wellness.assert_called_once_with("2026-10-10")
        self.assertEqual(self.client.get_sport_settings.call_count, 2)
        self.client.update_wellness.assert_not_called()
        self.client.update_sport_settings.assert_not_called()

    def test_values_from_the_target_or_without_provider_are_never_offered(
        self,
    ) -> None:
        self.add(
            obs(MetricKind.WEIGHT, 70.0, date(2026, 10, 10), ProviderId.INTERVALS),
            provider_less(MetricKind.FTP, 280, date(2026, 10, 10)),
        )
        self.assertEqual(self.service.preview({})["items"], [])
        self.client_factory.assert_not_called()

    def test_live_equal_values_are_not_selectable(self) -> None:
        self.wellness["2026-10-10"] = {"weight": 70.0}
        self.settings["Ride"] = {"ftp": 250}
        self.add(
            obs(MetricKind.WEIGHT, 70.0, date(2026, 10, 10), ProviderId.GARMIN),
            obs(MetricKind.FTP, 250, date(2026, 9, 1), ProviderId.GARMIN),
        )
        items = self.items()
        self.assertEqual(items["weight|"]["status"], "unchanged")
        self.assertEqual(items["ftp|ride"]["status"], "unchanged")
        self.assertFalse(any(item["selectable"] for item in items.values()))
        with self.assertRaises(AppError) as caught:
            self.confirm(items.values())
        self.assertEqual(caught.exception.reason, "metric_export_changed")
        self.client.update_wellness.assert_not_called()
        self.client.update_sport_settings.assert_not_called()

    def test_a_setting_stays_selectable_when_only_the_target_fetch_is_newer(
        self,
    ) -> None:
        # The fetch day of a cached target setting says nothing about when the
        # setting changed, so an older local threshold is still offered.
        self.settings["Ride"] = {"ftp": 255}
        self.add(
            obs(MetricKind.FTP, 250, date(2026, 9, 1), ProviderId.GARMIN),
            obs(MetricKind.FTP, 255, date(2026, 10, 1), ProviderId.INTERVALS),
        )
        ftp = self.items()["ftp|ride"]
        self.assertEqual(ftp["status"], "ready")
        self.assertEqual(ftp["current_remote_value"], 255)
        self.confirm([ftp])
        self.client.update_sport_settings.assert_called_once_with(
            "Ride", {"ftp": 250}, recalc_hr_zones=False
        )

    def test_a_target_value_changed_since_the_preview_sends_nothing(self) -> None:
        self.wellness["2026-10-10"] = {"weight": 71.2}
        self.add(obs(MetricKind.WEIGHT, 70.4, date(2026, 10, 10), ProviderId.GARMIN))
        preview = list(self.items().values())
        self.wellness["2026-10-10"] = {"weight": 72.5}
        with self.assertRaises(AppError) as caught:
            self.confirm(preview)
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.reason, "metric_export_changed")
        self.client.update_wellness.assert_not_called()

    def test_an_unreadable_target_fails_safely_before_any_write(self) -> None:
        self.add(obs(MetricKind.FTP, 250, date(2026, 9, 1), ProviderId.GARMIN))
        self.client.get_sport_settings.side_effect = AppError(
            502, RAW, reason="upstream_rejected", upstream_status=500
        )
        for call in (
            lambda: self.service.preview({}),
            lambda: self.service.export(
                {
                    "confirmed": True,
                    "provider": "intervals",
                    "metrics": [
                        {
                            "key": "ftp|ride",
                            "observed_on": "2026-09-01",
                            "value": 250,
                            "current_remote_value": None,
                        }
                    ],
                }
            ),
        ):
            with (
                self.assertLogs("backend.sync.metric_export", "WARNING") as logs,
                self.assertRaises(AppError) as caught,
            ):
                call()
            self.assertEqual(caught.exception.status, 502)
            self.assertEqual(
                caught.exception.reason, "metric_export_remote_unavailable"
            )
            self.assertNotIn("RAW-UPSTREAM", str(caught.exception))
            self.assertNotIn("RAW-UPSTREAM", "\n".join(logs.output))
        self.client.update_sport_settings.assert_not_called()

    def test_values_outside_the_lookback_are_not_offered(self) -> None:
        self.add(obs(MetricKind.WEIGHT, 70.0, date(2026, 6, 1), ProviderId.GARMIN))
        self.assertEqual(self.service.preview({})["items"], [])

    def test_execute_requires_confirmation_and_a_named_provider(self) -> None:
        self.add(obs(MetricKind.WEIGHT, 70.4, date(2026, 10, 10), ProviderId.GARMIN))
        metrics = [
            {
                "key": "weight|",
                "observed_on": "2026-10-10",
                "value": 70.4,
                "current_remote_value": None,
            }
        ]
        cases = (
            ({"provider": "intervals", "metrics": metrics}, "confirmation_required"),
            (
                {"confirmed": "yes", "provider": "intervals", "metrics": metrics},
                "confirmation_required",
            ),
            ({"confirmed": True, "metrics": metrics}, "provider_required"),
            (
                {"confirmed": True, "provider": "garmin", "metrics": metrics},
                "unsupported_provider",
            ),
        )
        for payload, reason in cases:
            with self.subTest(reason=reason, payload=payload):
                with self.assertRaises(AppError) as caught:
                    self.service.export(payload)
                self.assertEqual(caught.exception.status, 400)
                self.assertEqual(caught.exception.reason, reason)
        with self.assertRaises(AppError) as caught:
            self.service.preview({"provider": "garmin"})
        self.assertEqual(caught.exception.reason, "unsupported_provider")
        self.client_factory.assert_not_called()

    def test_invalid_or_changed_selections_send_nothing(self) -> None:
        self.add(obs(MetricKind.WEIGHT, 70.4, date(2026, 10, 10), ProviderId.GARMIN))
        entry = {
            "key": "weight|",
            "observed_on": "2026-10-10",
            "value": 70.4,
            "current_remote_value": None,
        }
        without_remote = {key: entry[key] for key in ("key", "observed_on", "value")}
        invalid: tuple[Any, ...] = (
            [],
            [without_remote],
            [{**entry, "current_remote_value": "71"}],
            [{**entry, "current_remote_value": float("inf")}],
            "weight|",
            [{**entry, "value": True}],
            [{**entry, "value": float("nan")}],
            [{**entry, "value": "70.4"}],
            [{**entry, "observed_on": None}],
            [entry, entry],
            [entry] * 33,
        )
        for metrics in invalid:
            with self.subTest(metrics=metrics):
                with self.assertRaises(AppError) as caught:
                    self.service.export(
                        {"confirmed": True, "provider": "intervals", "metrics": metrics}
                    )
                self.assertEqual(caught.exception.reason, "invalid_metric_export")
        with self.assertRaises(AppError) as caught:
            self.service.export(
                {
                    "confirmed": True,
                    "provider": "intervals",
                    "metrics": [entry],
                    "recalc_hr_zones": "true",
                }
            )
        self.assertEqual(caught.exception.reason, "invalid_metric_export")
        changed = (
            {**entry, "value": 69.0},
            {**entry, "observed_on": "2026-10-09"},
            {**entry, "key": "ftp|ride"},
            {**entry, "current_remote_value": 71.2},
        )
        for metric in changed:
            with self.subTest(metric=metric):
                with self.assertRaises(AppError) as caught:
                    self.service.export(
                        {
                            "confirmed": True,
                            "provider": "intervals",
                            "metrics": [metric],
                        }
                    )
                self.assertEqual(caught.exception.status, 409)
                self.assertEqual(caught.exception.reason, "metric_export_changed")
        self.client.update_wellness.assert_not_called()

    def test_confirmed_export_writes_records_and_reports_previous_value(
        self,
    ) -> None:
        weight = obs(MetricKind.WEIGHT, 70.4, date(2026, 10, 10), ProviderId.GARMIN)
        body_fat = obs(MetricKind.BODY_FAT, 14.5, date(2026, 10, 10), ProviderId.GARMIN)
        max_hr = obs(
            MetricKind.MAX_HR,
            191,
            date(2026, 10, 1),
            ProviderId.GARMIN,
            sport=Sport.RUN,
        )
        self.wellness["2026-10-10"] = {"weight": 71.2}
        self.add(weight, body_fat, max_hr)
        receipt = self.confirm(self.items().values())

        self.assertTrue(receipt["ok"])
        self.assertEqual(receipt["exported"], 3)
        self.assertEqual(receipt["failed"], 0)
        self.assertFalse(receipt["recalc_hr_zones"])
        by_key = {item["key"]: item for item in receipt["items"]}
        self.assertEqual(by_key["weight|"]["previous_remote_value"], 71.2)
        self.assertIsNone(by_key["max_hr|run"]["previous_remote_value"])
        self.assertEqual({item["status"] for item in receipt["items"]}, {"exported"})
        # Same-day wellness fields share one request; settings use their own.
        self.client.update_wellness.assert_called_once_with(
            "2026-10-10", {"weight": 70.4, "bodyFat": 14.5}
        )
        self.client.update_sport_settings.assert_called_once_with(
            "Run", {"max_hr": 191}, recalc_hr_zones=False
        )

        link = self.link(weight)
        self.assertEqual(link.sync_state, RemoteLinkState.SYNCED)
        self.assertEqual(link.remote_id, "wellness/2026-10-10/weight")
        self.assertEqual(link.last_synced_at, NOW.isoformat())
        self.assertEqual(self.link(max_hr).remote_id, "sport-settings/Run/max_hr")
        self.assertEqual(
            {item["status"] for item in self.items().values()}, {"already_exported"}
        )

    def test_recalc_is_passed_only_when_confirmed(self) -> None:
        self.add(
            obs(
                MetricKind.THRESHOLD_HR,
                170,
                date(2026, 10, 1),
                ProviderId.GARMIN,
                sport=Sport.RUN,
            )
        )
        self.confirm(self.items().values(), recalc_hr_zones=True)
        self.client.update_sport_settings.assert_called_once_with(
            "Run", {"lthr": 170}, recalc_hr_zones=True
        )

    def test_recalc_applies_only_to_threshold_settings(self) -> None:
        self.add(obs(MetricKind.WEIGHT, 70.4, date(2026, 10, 10), ProviderId.GARMIN))
        wellness_only = list(self.items().values())
        with self.assertRaises(AppError) as caught:
            self.confirm(wellness_only, recalc_hr_zones=True)
        self.assertEqual(caught.exception.status, 400)
        self.assertEqual(caught.exception.reason, "invalid_metric_export")
        self.client.update_wellness.assert_not_called()

        self.add(obs(MetricKind.FTP, 250, date(2026, 9, 1), ProviderId.GARMIN))
        self.confirm(self.items().values(), recalc_hr_zones=True)
        self.client.update_wellness.assert_called_once_with(
            "2026-10-10", {"weight": 70.4}
        )
        self.client.update_sport_settings.assert_called_once_with(
            "Ride", {"ftp": 250}, recalc_hr_zones=True
        )

    def test_a_newer_export_takes_over_the_field_link(self) -> None:
        old = obs(MetricKind.FTP, 250, date(2026, 10, 1), ProviderId.GARMIN)
        self.add(old)
        self.confirm(self.items().values())
        new = obs(MetricKind.FTP, 262, date(2026, 10, 5), ProviderId.WAHOO)
        self.add(new)
        self.assertEqual(self.items()["ftp|ride"]["status"], "ready")
        self.confirm(self.items().values())
        self.assertIsNone(self.link(old))
        self.assertEqual(self.link(new).remote_id, "sport-settings/Ride/ftp")

    def test_provider_failures_report_safe_reasons_without_raw_text(self) -> None:
        self.add(
            obs(MetricKind.WEIGHT, 70.4, date(2026, 10, 10), ProviderId.GARMIN),
            obs(MetricKind.FTP, 260, date(2026, 10, 2), ProviderId.GARMIN),
        )
        self.client.update_wellness.side_effect = AppError(
            502, RAW, reason="upstream_rejected", upstream_status=500
        )
        self.client.update_sport_settings.side_effect = RuntimeError(RAW)
        with self.assertLogs("backend.sync.metric_export", "WARNING") as logs:
            receipt = self.confirm(self.items().values())

        self.assertFalse(receipt["ok"])
        self.assertEqual((receipt["exported"], receipt["failed"]), (0, 2))
        by_key = {item["key"]: item for item in receipt["items"]}
        self.assertEqual(by_key["weight|"]["reason"], "upstream_unavailable")
        self.assertEqual(by_key["ftp|ride"]["reason"], "request_failed")
        self.assertEqual(
            by_key["weight|"]["error"], "Senden an Intervals.icu fehlgeschlagen."
        )
        self.assertNotIn("RAW-UPSTREAM", json.dumps(receipt))
        self.assertNotIn("RAW-UPSTREAM", "\n".join(logs.output))
        self.assertNotIn("secret", "\n".join(logs.output))
        self.assertEqual(
            self.database.db.execute("SELECT COUNT(*) FROM remote_links").fetchone()[0],
            0,
        )
        self.assertEqual({item["status"] for item in self.items().values()}, {"ready"})

    def test_unconfirmed_reply_counts_as_failure(self) -> None:
        self.add(obs(MetricKind.WEIGHT, 70.4, date(2026, 10, 10), ProviderId.GARMIN))
        self.client.update_wellness.return_value = None
        with self.assertLogs("backend.sync.metric_export", "WARNING"):
            receipt = self.confirm(self.items().values())
        self.assertEqual(receipt["items"][0]["reason"], "upstream_invalid_response")
        self.assertIsNone(self.link(self.reader.items[0]))


class MetricExportHttpTests(ServerTestCase):
    def setUp(self):
        super().setUp()
        self.transport = Mock(return_value={})
        patches = (
            patch.object(
                server.app_config, "security_configuration_error", return_value=None
            ),
            patch.object(
                server.PROVIDER_TRANSPORT,
                "json_http_client",
                return_value=Mock(request=self.transport),
            ),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        handler_class = server.HTTP_API.request_handler_class()
        handler_class.protocol_version = "HTTP/1.1"
        self.httpd = http_server_module.CoachHTTPServer(("127.0.0.1", 0), handler_class)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.addCleanup(self.httpd.server_close)
        self.addCleanup(self.httpd.shutdown)
        self.session = create_test_session(server)

    def call(self, path, body=None, *, session=True, csrf=True):
        connection = http.client.HTTPConnection(
            "127.0.0.1", self.httpd.server_port, timeout=10
        )
        headers = {"Content-Type": "application/json"}
        if session:
            headers["Cookie"] = f"ic_session={self.session}"
        if csrf:
            headers["X-CSRF-Token"] = "csrf"
        # A rejected request is answered before its body is read, so only an
        # authorized call carries one on the keep-alive connection.
        payload = json.dumps(body or {}).encode() if session and csrf else b""
        headers["Content-Length"] = str(len(payload))
        connection.request("POST", path, body=payload, headers=headers)
        response = connection.getresponse()
        data = response.read()
        connection.close()
        return response, data

    def test_routes_require_session_and_csrf(self):
        for path in ("/api/metric-export/preview", "/api/metric-export/execute"):
            with self.subTest(path=path):
                response, _ = self.call(path, session=False, csrf=False)
                self.assertEqual(response.status, 401)
                response, _ = self.call(path, csrf=False)
                self.assertEqual(response.status, 403)
        self.transport.assert_not_called()

    def test_preview_and_unconfirmed_execute(self):
        response, data = self.call("/api/metric-export/preview")
        self.assertEqual(response.status, 200)
        preview = json.loads(data)
        self.assertEqual(preview["provider"], "intervals")
        self.assertIsInstance(preview["items"], list)

        response, data = self.call(
            "/api/metric-export/execute",
            {
                "provider": "intervals",
                "metrics": [
                    {
                        "key": "weight|",
                        "observed_on": "2026-10-10",
                        "value": 70,
                        "current_remote_value": None,
                    }
                ],
            },
        )
        self.assertEqual(response.status, 400)
        self.assertEqual(json.loads(data)["reason"], "confirmation_required")

        response, data = self.call(
            "/api/metric-export/execute",
            {
                "confirmed": True,
                "provider": "intervals",
                "metrics": [
                    {
                        "key": "weight|",
                        "observed_on": "2026-10-10",
                        "value": 70,
                        "current_remote_value": None,
                    }
                ],
            },
        )
        self.assertEqual(response.status, 409)
        self.assertEqual(json.loads(data)["reason"], "metric_export_changed")
        self.transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
