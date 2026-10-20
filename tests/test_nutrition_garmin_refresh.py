from __future__ import annotations

import unittest
from contextlib import nullcontext
from datetime import date
from unittest.mock import Mock, patch

from backend.errors import AppError
from backend.sync.garmin_service import (
    GarminNutritionRefreshService,
    GarminRemoteReader,
)
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter


class GarminNutritionRefreshTests(unittest.TestCase):
    def test_remote_energy_without_range_api_is_unsupported_without_daily_loop(self) -> None:
        reader = GarminRemoteReader.__new__(GarminRemoteReader)
        client = Mock(spec=["get_user_summary"])
        reader.configured = Mock(return_value=True)
        reader._external_call = lambda _cancel: lambda _service, _operation, call, _details: call()
        reader._authenticated_client = lambda _external: (client, "")
        reader._garmin_tokens = None

        with self.assertRaises(AppError) as raised:
            reader.fetch_nutrition_data(
                "daily_stats", date(2026, 7, 1), date(2026, 9, 24)
            )

        self.assertEqual(raised.exception.reason, "not_supported")
        client.get_user_summary.assert_not_called()

    def test_targeted_writer_preserves_snapshot_sync_time_and_coverage(self) -> None:
        key_values = Mock()
        writer = GarminSnapshotWriter(key_values, lambda: None)
        writer._coverage.persist = Mock()
        snapshot = {"synced_at": "old", "daily_stats": [], "sleep": []}
        db = object()
        counters = Mock()

        with patch(
            "backend.sync.garmin_snapshot_writer.ingest_garmin_payload",
            return_value=counters,
        ), patch(
            "backend.sync.garmin_snapshot_writer.garmin_payload_coverage",
            side_effect=AssertionError("targeted refresh must not recompute coverage"),
        ):
            result = writer.write_nutrition_refresh(
                db, snapshot, "daily_stats", "new", []
            )

        self.assertIs(result, counters)
        writer._coverage.persist.assert_not_called()
        self.assertEqual(snapshot["synced_at"], "old")
        key_values.set.assert_called_once()

    def test_remote_energy_refresh_prefers_one_range_request(self) -> None:
        reader = GarminRemoteReader.__new__(GarminRemoteReader)
        client = Mock()
        client.get_daily_summaries.return_value = [
            {"calendarDate": "2026-09-23", "totalKilocalories": 2000},
            {"calendarDate": "2026-09-24", "totalKilocalories": 2100},
        ]
        reader.configured = Mock(return_value=True)
        reader._external_call = lambda _cancel: lambda _service, _operation, call, _details: call()
        reader._authenticated_client = lambda _external: (client, "")
        reader._garmin_tokens = None

        records, complete = reader.fetch_nutrition_data(
            "daily_stats", date(2026, 9, 23), date(2026, 9, 24)
        )

        self.assertTrue(complete)
        self.assertEqual(len(records), 2)
        client.get_daily_summaries.assert_called_once_with("2026-09-23", "2026-09-24")
        client.get_user_summary.assert_not_called()

    def test_remote_body_refresh_uses_only_the_weight_range(self) -> None:
        reader = GarminRemoteReader.__new__(GarminRemoteReader)
        client = Mock()
        client.get_weigh_ins.return_value = {
            "weighIns": [{"date": "2026-09-24", "weight": 70.5}]
        }
        reader.configured = Mock(return_value=True)
        reader._external_call = lambda _cancel: lambda _service, _operation, call, _details: call()
        reader._authenticated_client = lambda _external: (client, "")
        reader._garmin_tokens = None

        records, complete = reader.fetch_nutrition_data(
            "weight", date(2026, 9, 1), date(2026, 9, 24)
        )

        self.assertTrue(complete)
        self.assertEqual(
            records,
            [{"calendarDate": "2026-09-24", "date": "2026-09-24", "weight": 70.5}],
        )
        client.get_weigh_ins.assert_called_once_with("2026-09-01", "2026-09-24")
        client.get_daily_summaries.assert_not_called()

    def test_remote_body_refresh_filters_nested_out_of_range_records(self) -> None:
        reader = GarminRemoteReader.__new__(GarminRemoteReader)
        client = Mock()
        client.get_weigh_ins.return_value = {
            "weighIns": [
                {"date": "2026-09-24", "weight": 70.5},
                {"date": "2026-09-25", "weight": 71.0},
            ]
        }
        reader.configured = Mock(return_value=True)
        reader._external_call = lambda _cancel: lambda _service, _operation, call, _details: call()
        reader._authenticated_client = lambda _external: (client, "")
        reader._garmin_tokens = None

        records, complete = reader.fetch_nutrition_data(
            "weight", date(2026, 9, 24), date(2026, 9, 24)
        )

        self.assertFalse(complete)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["calendarDate"], "2026-09-24")
        self.assertEqual(records[0]["weight"], 70.5)

    def test_remote_body_refresh_keeps_body_fat_only_measurements_and_normalizes_date(self) -> None:
        reader = GarminRemoteReader.__new__(GarminRemoteReader)
        client = Mock()
        client.get_weigh_ins.return_value = {
            "weighIns": [
                {
                    "calendarDate": "2026-09-24",
                    "date": "2026-09-25",
                    "bodyFat": 18.5,
                    "bodyFatUnit": "%",
                }
            ]
        }
        reader.configured = Mock(return_value=True)
        reader._external_call = lambda _cancel: lambda _service, _operation, call, _details: call()
        reader._authenticated_client = lambda _external: (client, "")
        reader._garmin_tokens = None

        records, complete = reader.fetch_nutrition_data(
            "weight", date(2026, 9, 24), date(2026, 9, 24)
        )

        self.assertTrue(complete)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["bodyFat"], 18.5)
        self.assertEqual(records[0]["bodyFatUnit"], "%")
        self.assertEqual(records[0]["calendarDate"], "2026-09-24")

    def make_service(self):
        reader = Mock()
        reader.fetch_nutrition_data.return_value = (
            [{"calendarDate": "2026-09-24", "totalKilocalories": 2100}],
            True,
        )
        manager = Mock()
        manager.unit_of_work.return_value = nullcontext(object())
        writer = Mock()
        payloads = Mock()
        payloads.snapshot.return_value = {
            "synced_at": "2026-09-23T12:00:00Z",
            "daily_stats": [{"calendarDate": "2026-09-23", "totalKilocalories": 2000}],
            "source_freshness": {"sleep": {"freshness": "current"}},
        }
        coordination = Mock()
        coordination.operation.return_value = nullcontext()
        coordination.acquire.return_value = True
        service = GarminNutritionRefreshService(
            reader,
            manager,
            writer,
            payloads,
            coordination,
            lambda: "2026-09-24T12:00:00Z",
            lambda: True,
        )
        return service, reader, manager, writer, coordination

    def test_refresh_reads_and_persists_only_the_selected_garmin_source(self) -> None:
        service, reader, manager, writer, coordination = self.make_service()

        result = service.refresh(
            "daily_stats", date(2026, 9, 24), date(2026, 9, 24)
        )

        self.assertEqual(result["status"], "ok")
        reader.fetch_nutrition_data.assert_called_once_with(
            "daily_stats", date(2026, 9, 24), date(2026, 9, 24)
        )
        writer.write_nutrition_refresh.assert_called_once()
        persisted = writer.write_nutrition_refresh.call_args.args[1]
        self.assertEqual(persisted["daily_stats"], [
            {"calendarDate": "2026-09-24", "totalKilocalories": 2100},
            {"calendarDate": "2026-09-23", "totalKilocalories": 2000},
        ])
        self.assertEqual(persisted["source_freshness"]["sleep"], {"freshness": "current"})
        self.assertEqual(persisted["synced_at"], "2026-09-23T12:00:00Z")
        self.assertEqual(
            persisted["nutrition_refresh"]["daily_stats"]["2026-09-24"]["freshness"],
            "current",
        )
        manager.unit_of_work.assert_called_once()
        coordination.release.assert_called_once()

    def test_empty_body_refresh_is_partial_and_retains_prior_measurement_as_stale(self) -> None:
        service, reader, _manager, writer, _coordination = self.make_service()
        reader.fetch_nutrition_data.return_value = ([], True)
        snapshot = {
            "synced_at": "2026-09-20T12:00:00Z",
            "weight": [{"date": "2026-09-20", "weight": 70.0}],
        }
        service._payload_service.snapshot.return_value = snapshot

        result = service.refresh("weight", date(2026, 9, 1), date(2026, 9, 24))

        self.assertEqual(result["status"], "partial")
        persisted = writer.write_nutrition_refresh.call_args.args[1]
        self.assertEqual(persisted["weight"], [{"date": "2026-09-20", "weight": 70.0}])
        self.assertEqual(
            persisted["nutrition_refresh"]["weight"]["2026-09-24"]["freshness"],
            "partial",
        )

    def test_provider_failure_returns_partial_without_persisting_stale_as_fresh(self) -> None:
        service, reader, _manager, writer, _coordination = self.make_service()
        reader.fetch_nutrition_data.side_effect = RuntimeError("provider unavailable")

        result = service.refresh(
            "daily_stats", date(2026, 9, 24), date(2026, 9, 24)
        )

        self.assertEqual(result, {"status": "partial", "reason": "provider_unavailable"})
        writer.write.assert_not_called()

    def test_unconfigured_provider_returns_explicit_partial_result(self) -> None:
        service, reader, _manager, writer, _coordination = self.make_service()
        service._configured = lambda: False

        result = service.refresh("weight", date(2026, 9, 1), date(2026, 9, 24))

        self.assertEqual(result, {"status": "partial", "reason": "not_configured"})
        reader.fetch_nutrition_data.assert_not_called()
        writer.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
