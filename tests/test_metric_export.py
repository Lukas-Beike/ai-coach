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
from typing import cast
from unittest.mock import Mock, patch

from server_test_support import ServerTestCase, create_test_session, server

from backend import change_history
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
from backend.history.undo_service import HistoryUndoService
from backend.http_api import server as http_server_module
from backend.providers import http as provider_http
from backend.providers.intervals_client import IntervalsClient
from backend.sync.intervals_metric_export import IntervalsMetricExport
from backend.sync.metric_export import MetricExportService
from backend.sync.metric_export_consent import (
    DEFAULT_FIELDS,
    EXPORT_FIELDS,
    LEGACY_FLAG_KEY,
)
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


_THRESHOLD_KINDS = frozenset(
    {
        MetricKind.FTP,
        MetricKind.THRESHOLD_HR,
        MetricKind.MAX_HR,
        MetricKind.THRESHOLD_PACE,
    }
)


def newest_thresholds(reader: FakeReader):
    """A threshold source: the newest non-Intervals value per key.

    The resolver's precedence is tested in test_current_thresholds; the service
    sends whatever the source resolves (AI estimates are left to its own guard).
    """

    def thresholds(_db):
        result: dict[tuple[MetricKind, Sport], Observation] = {}
        for item in sorted(reader.items, key=lambda item: item.observed_on):
            if (
                item.kind in _THRESHOLD_KINDS
                and item.provenance.provider is not ProviderId.INTERVALS
                and item.observed_on <= TODAY
            ):
                result[(item.kind, item.sport or Sport.RIDE)] = item
        return result

    return thresholds


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
            thresholds=newest_thresholds(self.reader),
            today=lambda: TODAY,
            utc_now=lambda: NOW,
        )

        # The earlier single consent flag: all fields, as before (#1668).
        self.database.db.execute(
            "INSERT INTO kv(key, value, updated_at) VALUES (?, 'true', ?)",
            (LEGACY_FLAG_KEY, NOW.isoformat()),
        )

    def add(self, *items: Observation) -> None:
        self.reader.items.extend(items)

    def link(self, observation):
        return RemoteLinkRepository().get(
            self.database.db,
            RemoteEntityKind.OBSERVATION,
            observation_natural_key(observation),
            "intervals",
        )

    def test_automatic_export_requires_persisted_named_consent(self):
        self.database.db.execute(
            "DELETE FROM kv WHERE key='garmin_metric_export_enabled'"
        )
        self.assertIsNone(self.service.sync_automatic())
        self.service.configure_automatic(
            {
                "enabled": False,
                "confirmed": True,
                "source": "garmin",
                "provider": "intervals",
            }
        )
        self.add(obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN))
        self.assertIsNone(self.service.sync_automatic())
        self.client_factory.assert_not_called()
        for payload in (
            {"enabled": True},
            {
                "enabled": True,
                "confirmed": True,
                "source": "garmin",
                "provider": "wahoo",
            },
        ):
            with self.assertRaises(AppError):
                self.service.configure_automatic(payload)
        self.assertIsNone(self.service.sync_automatic())

    def configure(self, **payload):
        return self.service.configure_automatic(
            {"confirmed": True, "source": "garmin", "provider": "intervals", **payload}
        )

    def test_legacy_consent_keeps_all_fields_until_saved_per_field(self):
        self.add(obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN))
        self.assertEqual(self.service.sync_automatic()["exported"], 1)

        receipt = self.configure(enabled=True, fields=["weight", "resting_hr"])

        self.assertTrue(receipt["enabled"])
        changed = {item["key"]: item["enabled"] for item in receipt["changes"]}
        self.assertFalse(changed["ftp"])
        self.assertNotIn("weight", changed)
        self.add(obs(MetricKind.FTP, 255, TODAY, ProviderId.GARMIN))
        self.add(obs(MetricKind.WEIGHT, 70, TODAY, ProviderId.GARMIN))
        self.assertEqual(self.service.sync_automatic()["exported"], 1)
        self.assertEqual(self.client.update_wellness.call_count, 1)

    def test_new_consent_starts_with_heart_rate_and_pace_thresholds_only(self):
        self.configure(enabled=False)
        receipt = self.configure(enabled=True)

        enabled = {item["key"] for item in receipt["fields"] if item["enabled"]}
        self.assertEqual(enabled, set(DEFAULT_FIELDS))
        self.assertEqual(enabled, {"threshold_hr", "max_hr", "threshold_pace"})
        self.add(obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN))
        self.assertEqual(self.service.sync_automatic()["exported"], 0)
        self.client_factory.return_value.update_sport_settings.assert_not_called()

    def test_revoking_keeps_the_legacy_flag_in_step(self):
        self.configure(enabled=False)

        row = self.database.db.execute(
            "SELECT value FROM kv WHERE key=?", (LEGACY_FLAG_KEY,)
        ).fetchone()
        self.assertEqual(row[0], "false")
        self.assertIsNone(self.service.sync_automatic())

    def test_a_single_field_change_applies_to_the_stored_consent(self):
        self.configure(enabled=True, fields=["weight", "resting_hr"])

        receipt = self.configure(enabled=True, field="ftp", field_enabled=True)

        enabled = {item["key"] for item in receipt["fields"] if item["enabled"]}
        self.assertEqual(enabled, {"weight", "resting_hr", "ftp"})
        self.assertEqual([item["key"] for item in receipt["changes"]], ["ftp"])
        receipt = self.configure(enabled=True, field="weight", field_enabled=False)
        self.assertEqual(
            {item["key"] for item in receipt["fields"] if item["enabled"]},
            {"resting_hr", "ftp"},
        )

    def test_unreadable_or_revoked_consent_sends_nothing(self):
        self.add(obs(MetricKind.WEIGHT, 70, TODAY, ProviderId.GARMIN))
        for key, value in (
            ("garmin_metric_export_fields", '[["weight"]]'),
            ("garmin_metric_export_fields", '{"weight": true}'),
            ("garmin_metric_export_fields", "not json"),
            (LEGACY_FLAG_KEY, "false"),
        ):
            with self.subTest(key=key, value=value):
                self.configure(enabled=True, fields=["weight"])
                self.database.db.execute(
                    "UPDATE kv SET value=? WHERE key=?", (value, key)
                )
                self.assertIsNone(self.service.sync_automatic())
        self.client.update_wellness.assert_not_called()

    def test_unknown_or_empty_fields_are_rejected(self):
        for fields in ([], ["ctl"], "weight"):
            with self.subTest(fields=fields), self.assertRaises(AppError):
                self.configure(enabled=True, fields=fields)
        for change in (
            {"field": "ctl", "field_enabled": True},
            {"field": "weight", "field_enabled": "yes"},
            {"field": "weight", "field_enabled": True, "fields": ["weight"]},
        ):
            with self.subTest(change=change), self.assertRaises(AppError):
                self.configure(enabled=True, **change)

    def test_new_wellness_day_preserves_existing_target_value(self):
        self.add(obs(MetricKind.WEIGHT, 70, date(2026, 10, 10), ProviderId.GARMIN))
        self.assertEqual(self.service.sync_automatic()["exported"], 1)
        self.add(obs(MetricKind.WEIGHT, 71, TODAY, ProviderId.GARMIN))
        self.wellness[TODAY.isoformat()] = {"weight": 72}
        self.assertEqual(self.service.sync_automatic()["conflicts"], 1)
        self.assertEqual(self.client.update_wellness.call_count, 1)

    def test_normalized_body_fat_does_not_conflict_and_accepts_updates(self):
        self.add(obs(MetricKind.BODY_FAT, 15.06, TODAY, ProviderId.GARMIN))
        self.assertEqual(self.service.sync_automatic()["exported"], 1)
        self.wellness[TODAY.isoformat()] = {"bodyFat": 15.1}
        self.assertEqual(
            self.service.sync_automatic(), {"exported": 0, "failed": 0, "conflicts": 0}
        )
        self.reader.items = [obs(MetricKind.BODY_FAT, 15.26, TODAY, ProviderId.GARMIN)]
        self.assertEqual(self.service.sync_automatic()["exported"], 1)
        self.assertEqual(
            self.client.update_wellness.call_args.args,
            (TODAY.isoformat(), {"bodyFat": 15.3}),
        )

    def test_the_resolved_threshold_overwrites_a_different_target_value(self):
        self.add(obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN))
        self.settings["Ride"] = {"ftp": 240}
        self.assertEqual(
            self.service.sync_automatic(), {"exported": 1, "failed": 0, "conflicts": 0}
        )
        self.client.update_sport_settings.assert_called_once_with(
            "Ride", {"ftp": 250}, recalc_hr_zones=False
        )

    def test_a_late_read_failure_preserves_prior_success_and_other_groups(self):
        self.add(
            obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN),
            obs(
                MetricKind.THRESHOLD_HR, 160, TODAY, ProviderId.GARMIN, sport=Sport.RUN
            ),
        )
        self.client.get_sport_settings.side_effect = [
            {},
            {},
            {},
            RuntimeError(RAW),
        ]
        with self.assertLogs("intervals_coach", "WARNING"):
            self.assertEqual(
                self.service.sync_automatic(),
                {"exported": 1, "failed": 1, "conflicts": 0},
            )
        self.client.update_sport_settings.assert_called_once_with(
            "Ride", {"ftp": 250}, recalc_hr_zones=False
        )

    def test_automatic_threshold_export_is_idempotent(self):
        self.add(obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN))
        receipt = self.service.sync_automatic()
        self.assertEqual(receipt, {"exported": 1, "failed": 0, "conflicts": 0})
        self.client.update_sport_settings.assert_called_once_with(
            "Ride", {"ftp": 250}, recalc_hr_zones=False
        )
        self.settings["Ride"] = {"ftp": 250}
        self.assertEqual(self.service.sync_automatic()["exported"], 0)
        self.assertEqual(self.client.update_sport_settings.call_count, 1)

    def test_a_target_side_threshold_change_is_overwritten_after_restart(self):
        self.add(obs(MetricKind.FTP, 250, date(2026, 10, 10), ProviderId.GARMIN))
        self.service.sync_automatic()
        self.settings["Ride"] = {"ftp": 260}
        restarted = MetricExportService(
            lambda: self.database,
            lambda: self.reader,
            {ProviderId.INTERVALS: lambda: IntervalsMetricExport(self.client_factory)},
            thresholds=newest_thresholds(self.reader),
            today=lambda: TODAY,
            utc_now=lambda: NOW,
        )
        self.assertEqual(
            restarted.sync_automatic(), {"exported": 1, "failed": 0, "conflicts": 0}
        )
        self.assertEqual(
            self.client.update_sport_settings.call_args.args, ("Ride", {"ftp": 250})
        )

    def test_matching_initial_wellness_value_establishes_a_conflict_baseline(self):
        self.configure(enabled=True, fields=["weight"])
        self.add(obs(MetricKind.WEIGHT, 70, TODAY, ProviderId.GARMIN))
        self.wellness[TODAY.isoformat()] = {"weight": 70}
        self.assertEqual(self.service.sync_automatic()["exported"], 0)
        self.wellness[TODAY.isoformat()]["weight"] = 72
        self.assertEqual(self.service.sync_automatic()["conflicts"], 1)
        self.client.update_wellness.assert_not_called()

    def test_body_metrics_use_only_garmin_measurements(self):
        self.add(
            obs(MetricKind.FTP, 250, date(2026, 10, 10), ProviderId.GARMIN),
            obs(MetricKind.FTP, 270, TODAY, ProviderId.WAHOO),
            obs(MetricKind.WEIGHT, 70, TODAY, ProviderId.INTERVALS),
            obs(MetricKind.WEIGHT, 71, TODAY, ProviderId.WAHOO),
            provider_less(MetricKind.THRESHOLD_PACE, 4, TODAY),
            obs(MetricKind.RESTING_HR, 50, date(2026, 10, 13), ProviderId.GARMIN),
            obs(MetricKind.BODY_FAT, 15, date(2026, 1, 1), ProviderId.GARMIN),
        )
        self.assertEqual(self.service.sync_automatic()["exported"], 1)
        # The resolved threshold is sent; an AI estimate never is.
        self.client.update_sport_settings.assert_called_once_with(
            "Ride", {"ftp": 270}, recalc_hr_zones=False
        )
        self.client.update_wellness.assert_not_called()

    def test_a_wellness_conflict_does_not_block_thresholds(self):
        self.add(obs(MetricKind.WEIGHT, 70, TODAY, ProviderId.GARMIN))
        self.wellness[TODAY.isoformat()] = {"weight": 72}
        self.add(
            obs(
                MetricKind.THRESHOLD_HR, 160, TODAY, ProviderId.GARMIN, sport=Sport.RIDE
            )
        )
        self.assertEqual(
            self.service.sync_automatic(), {"exported": 1, "failed": 0, "conflicts": 1}
        )
        self.assertEqual(
            self.client.update_sport_settings.call_args.args, ("Ride", {"lthr": 160})
        )

    def test_automatic_write_failure_retries_without_persisting_baseline(self):
        self.add(obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN))
        self.client.update_sport_settings.side_effect = RuntimeError(RAW)
        with self.assertLogs("intervals_coach", "WARNING") as logs:
            self.assertEqual(self.service.sync_automatic()["failed"], 1)
        self.assertNotIn(RAW, str(logs.output))
        self.client.update_sport_settings.side_effect = None
        self.assertEqual(self.service.sync_automatic()["exported"], 1)

    def test_target_change_during_automatic_export_is_not_overwritten(self):
        self.add(obs(MetricKind.WEIGHT, 70, TODAY, ProviderId.GARMIN))
        self.client.get_wellness.side_effect = [{}, {"weight": 72}]
        self.assertEqual(self.service.sync_automatic()["conflicts"], 1)
        self.client.update_wellness.assert_not_called()

    def test_threshold_written_with_the_value_read_just_before(self):
        self.add(obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN))
        self.client.get_sport_settings.side_effect = [{}, {"ftp": 260}]
        self.assertEqual(self.service.sync_automatic()["exported"], 1)
        (row,) = self.history()
        self.assertEqual(
            json.loads(row["diff"])["fields"]["ftp"], {"before": 260, "after": 250}
        )

    def history(self):
        return [
            dict(row)
            for row in self.database.db.execute(
                "SELECT * FROM change_history ORDER BY created_at, rowid"
            )
        ]

    def test_heart_rate_thresholds_recalculate_target_zones(self):
        self.add(
            obs(
                MetricKind.THRESHOLD_HR, 170, TODAY, ProviderId.GARMIN, sport=Sport.RUN
            ),
            obs(
                MetricKind.THRESHOLD_PACE,
                4.2,
                TODAY,
                ProviderId.GARMIN,
                sport=Sport.RUN,
            ),
        )
        self.service.sync_automatic()
        self.client.update_sport_settings.assert_called_once_with(
            "Run", {"lthr": 170, "threshold_pace": 4.2}, recalc_hr_zones=True
        )

    def test_a_local_threshold_is_exported(self):
        local = Observation(
            kind=MetricKind.FTP,
            value=MetricValue(300, "W"),
            observed_on=TODAY,
            observed_at=None,
            provenance=Provenance(
                provider=None,
                source_kind=SourceKind.ATHLETE_ENTERED,
                source_record_id=None,
                recorded_by=RecordingOrigin.MANUAL,
                retrieved_at=None,
                label=None,
            ),
            sport=Sport.RIDE,
        )
        self.add(local)
        self.assertEqual(self.service.sync_automatic()["exported"], 1)
        self.client.update_sport_settings.assert_called_once_with(
            "Ride", {"ftp": 300}, recalc_hr_zones=False
        )

    def test_an_automatic_run_reads_only_consented_records(self):
        self.configure(enabled=True, fields=["threshold_hr"])
        self.add(
            obs(MetricKind.WEIGHT, 70, TODAY, ProviderId.GARMIN),
            obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN),
            obs(
                MetricKind.THRESHOLD_HR, 170, TODAY, ProviderId.GARMIN, sport=Sport.RUN
            ),
        )
        self.client.get_wellness.side_effect = RuntimeError(RAW)
        self.assertEqual(self.service.sync_automatic()["exported"], 1)
        self.client.get_wellness.assert_not_called()
        self.assertEqual(
            [call.args for call in self.client.get_sport_settings.call_args_list],
            [("Run",), ("Run",)],
        )

    def test_running_ftp_needs_its_own_consent(self):
        self.add(obs(MetricKind.FTP, 310, TODAY, ProviderId.GARMIN, sport=Sport.RUN))
        # The legacy flag covers the fields of its time, not running FTP.
        self.assertEqual(self.service.sync_automatic()["exported"], 0)
        self.configure(enabled=True, field="run_ftp", field_enabled=True)
        self.assertEqual(self.service.sync_automatic()["exported"], 1)
        self.client.update_sport_settings.assert_called_once_with(
            "Run", {"ftp": 310}, recalc_hr_zones=False
        )

    def test_history_fields_match_the_consent_keys(self):
        self.assertEqual(set(change_history.METRIC_EXPORT_FIELDS), set(EXPORT_FIELDS))

    def test_writes_are_in_the_change_history_without_undo(self):
        self.add(obs(MetricKind.FTP, 250, TODAY, ProviderId.GARMIN))
        self.service.sync_automatic()
        self.settings["Ride"] = {"ftp": 250}
        self.service.sync_automatic()
        (row,) = self.history()
        self.assertEqual(
            (row["entity_type"], row["entity_id"], row["action"], row["source"]),
            ("metric_export", "intervals:sport-settings/Ride", "update", "automatic"),
        )
        self.assertEqual(
            change_history.public_view(row)["diff"]["fields"],
            {"ftp": {"changed": True}},
        )
        # An earlier release recorded manual exports; they stay listed, not undoable.
        with self.database.unit_of_work() as db:
            change_history.record_change(
                db,
                change_history.METRIC_EXPORT_ENTITY,
                "intervals:wellness/2026-10-10",
                "update",
                {"weight": 72.0},
                {"weight": 70.4},
                source="manual",
            )
        self.assertEqual(
            [(item["entity_id"], item["source"]) for item in self.history()][1],
            ("intervals:wellness/2026-10-10", "manual"),
        )
        self.assertEqual(
            {
                key: change_history.public_view(row)[key]
                for key in ("remote_sync", "undoable")
            },
            {"remote_sync": "remote", "undoable": False},
        )
        undo = HistoryUndoService(
            self.database, *([Mock()] * 7), profile_mutation_coordinator=Mock()
        )
        with self.assertRaises(AppError) as caught:
            undo.preview(row["id"])
        self.assertEqual(caught.exception.status, 400)

    def test_values_the_target_reported_are_never_sent_back(self) -> None:
        self.add(
            obs(MetricKind.WEIGHT, 70.0, date(2026, 10, 10), ProviderId.INTERVALS),
            obs(MetricKind.FTP, 280, TODAY, ProviderId.INTERVALS),
        )
        self.assertEqual(
            self.service.sync_automatic(), {"exported": 0, "failed": 0, "conflicts": 0}
        )
        self.client.update_wellness.assert_not_called()
        self.client.update_sport_settings.assert_not_called()

    def test_values_outside_the_lookback_are_not_exported(self) -> None:
        self.add(obs(MetricKind.WEIGHT, 70.0, date(2026, 6, 1), ProviderId.GARMIN))
        self.assertEqual(
            self.service.sync_automatic(), {"exported": 0, "failed": 0, "conflicts": 0}
        )
        self.client.update_wellness.assert_not_called()

    def test_an_unreadable_target_fails_safely_before_any_write(self) -> None:
        self.add(obs(MetricKind.FTP, 250, date(2026, 9, 1), ProviderId.GARMIN))
        self.client.get_sport_settings.side_effect = AppError(
            502, RAW, reason="upstream_rejected", upstream_status=500
        )
        with (
            self.assertLogs("intervals_coach", "WARNING") as logs,
            self.assertRaises(AppError) as caught,
        ):
            self.service.sync_automatic()
        self.assertEqual(caught.exception.status, 502)
        self.assertEqual(caught.exception.reason, "metric_export_remote_unavailable")
        self.assertNotIn("RAW-UPSTREAM", str(caught.exception))
        self.assertNotIn("RAW-UPSTREAM", "\n".join(logs.output))
        self.client.update_sport_settings.assert_not_called()

    def test_an_export_records_the_link_of_each_sent_field(self) -> None:
        weight = obs(MetricKind.WEIGHT, 70.4, date(2026, 10, 10), ProviderId.GARMIN)
        max_hr = obs(
            MetricKind.MAX_HR,
            191,
            date(2026, 10, 1),
            ProviderId.GARMIN,
            sport=Sport.RUN,
        )
        self.add(weight, max_hr)
        receipt = self.service.sync_automatic()

        self.assertEqual(receipt, {"exported": 2, "failed": 0, "conflicts": 0})
        link = self.link(weight)
        self.assertEqual(link.sync_state, RemoteLinkState.SYNCED)
        self.assertEqual(link.remote_id, "wellness/2026-10-10/weight")
        self.assertEqual(link.last_synced_at, NOW.isoformat())
        self.assertEqual(self.link(max_hr).remote_id, "sport-settings/Run/max_hr")

    def test_a_newer_export_takes_over_the_field_link(self) -> None:
        old = obs(MetricKind.FTP, 250, date(2026, 10, 1), ProviderId.GARMIN)
        self.add(old)
        self.service.sync_automatic()
        new = obs(MetricKind.FTP, 262, date(2026, 10, 5), ProviderId.WAHOO)
        self.add(new)
        self.service.sync_automatic()
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
        with self.assertLogs("intervals_coach", "WARNING") as logs:
            receipt = self.service.sync_automatic()

        self.assertEqual(receipt, {"exported": 0, "failed": 2, "conflicts": 0})
        self.assertNotIn("RAW-UPSTREAM", "\n".join(logs.output))
        self.assertNotIn("secret", "\n".join(logs.output))
        self.assertEqual(
            self.database.db.execute("SELECT COUNT(*) FROM remote_links").fetchone()[0],
            0,
        )

    def test_unconfirmed_reply_counts_as_failure(self) -> None:
        weight = obs(MetricKind.WEIGHT, 70.4, date(2026, 10, 10), ProviderId.GARMIN)
        self.add(weight)
        self.client.update_wellness.return_value = None
        with self.assertLogs("intervals_coach", "WARNING"):
            receipt = self.service.sync_automatic()
        self.assertEqual(receipt, {"exported": 0, "failed": 1, "conflicts": 0})
        self.assertIsNone(self.link(weight))


class MetricExportHttpTests(ServerTestCase):
    def setUp(self):
        super().setUp()
        self.transport = Mock(return_value={})
        patches = (
            patch.object(
                server.app_config, "security_configuration_error", return_value=None
            ),
            patch.object(provider_http.JsonHttpClient, "request", self.transport),
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
        path = "/api/metric-export/automatic"
        response, _ = self.call(path, session=False, csrf=False)
        self.assertEqual(response.status, 401)
        response, _ = self.call(path, csrf=False)
        self.assertEqual(response.status, 403)
        self.transport.assert_not_called()

    def test_automatic_configuration_requires_explicit_source_target_and_confirmation(
        self,
    ):
        response, _ = self.call("/api/metric-export/automatic", {"enabled": True})
        self.assertEqual(response.status, 400)
        for enabled in (True, False):
            response, data = self.call(
                "/api/metric-export/automatic",
                {
                    "enabled": enabled,
                    "confirmed": True,
                    "source": "garmin",
                    "provider": "intervals",
                },
            )
            self.assertEqual(response.status, 200)
            self.assertEqual(json.loads(data)["enabled"], enabled)
        self.transport.assert_not_called()

    def test_manual_preview_and_execute_routes_are_not_registered(self):
        for path in ("/api/metric-export/preview", "/api/metric-export/execute"):
            with self.subTest(path=path):
                response, _ = self.call(path)
                self.assertEqual(response.status, 404)
        self.transport.assert_not_called()


if __name__ == "__main__":
    unittest.main()
