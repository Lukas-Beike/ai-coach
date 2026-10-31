from __future__ import annotations

import copy
import unittest
from contextlib import nullcontext
from datetime import date, timedelta
from typing import Any, cast
from unittest.mock import Mock, patch

from performance_day_support import garmin_body_from_payload

from backend.errors import AppError
from backend.performance.body import body_history
from backend.performance.freshness import GarminSyncStatus
from backend.performance.garmin_weight import garmin_weight_records
from backend.providers.garmin import merge_weight_snapshots
from backend.sync.garmin_service import (
    GarminNutritionRefreshService,
    GarminRemoteReader,
)
from backend.sync.garmin_snapshot_writer import GarminSnapshotWriter


class GarminNutritionRefreshTests(unittest.TestCase):
    def test_weight_snapshot_merge_keeps_distinct_samples_from_one_day(self) -> None:
        first = {"date": "2026-09-24", "weight": 70.5, "timestamp": "07:00"}
        second = {"date": "2026-09-24", "weight": 70.7, "timestamp": "19:00"}

        merged = merge_weight_snapshots([first, second], [first])

        self.assertEqual(merged, [{"weight": [first, second]}])

    def test_weight_snapshot_merge_preserves_shifted_history_and_keeps_it_walkable(
        self,
    ) -> None:
        start = date(2026, 1, 1)
        samples = [
            {"date": (start + timedelta(days=day)).isoformat(), "weight": 70 + day / 10}
            for day in range(90)
        ]
        snapshot = merge_weight_snapshots(
            [{"weighIns": samples, "userProfile": {"weightUnit": "kg"}}], []
        )

        for window_start in (6, 12, 18, 24):
            shifted = [
                {
                    "date": (start + timedelta(days=day)).isoformat(),
                    "weight": 70 + day / 10,
                }
                for day in range(window_start, window_start + 84)
            ]
            snapshot = merge_weight_snapshots(
                [{"weighIns": shifted, "userProfile": {"weightUnit": "kg"}}],
                snapshot,
            )
            self.assertEqual(len(snapshot), 1)

        rows = snapshot[0]["weight"]
        days = {row["date"] for row in rows}
        self.assertEqual(len(rows), 108)
        self.assertTrue(
            all(
                (start + timedelta(days=day)).isoformat() in days
                for day in range(85, 91)
            )
        )
        self.assertIn((start + timedelta(days=107)).isoformat(), days)
        self.assertEqual(len(garmin_weight_records({"weight": snapshot})), len(rows))

    def test_large_history_retains_old_rows_and_walks_newest_rows_first(self) -> None:
        start = date(2025, 1, 1)
        samples = [
            {
                "date": (start + timedelta(days=day)).isoformat(),
                "weight": 70 + day / 100,
            }
            for day in range(510)
        ]

        snapshot = merge_weight_snapshots(
            [{"weighIns": samples, "dailyWeightSummaries": list(range(2100))}], []
        )

        rows = snapshot[0]["weight"]
        walked = garmin_weight_records({"weight": snapshot})
        self.assertEqual(len(rows), 510)
        self.assertIn({"date": start.isoformat(), "weight": 70.0}, rows)
        self.assertIn(((start + timedelta(days=509)).isoformat(), 75.09), walked)
        self.assertNotIn((start.isoformat(), 70.0), walked)

    def test_large_daily_weight_summaries_project_latest_weight_and_body_fat(
        self,
    ) -> None:
        start = date(2025, 1, 1)
        today = start + timedelta(days=599)
        summaries = [
            {
                "summaryDate": (start + timedelta(days=day)).isoformat(),
                "latestWeight": {"weight": 72000, "bodyFat": 17.0},
            }
            for day in range(600)
        ]
        correction = {
            "summaryDate": today.isoformat(),
            "latestWeight": {"weight": 73200, "bodyFat": 18.5},
        }

        merged = merge_weight_snapshots(
            [{"dailyWeightSummaries": [correction]}],
            [{"dailyWeightSummaries": summaries}],
        )
        garmin = {"weight": merged}
        projection = body_history(
            None,
            GarminSyncStatus.from_state(garmin),
            today,
            canonical=garmin_body_from_payload(garmin, today),
            wellness_days=(),
            activities=(),
            garmin_ftp={},
        )
        metrics = projection["windows"]["14d"]["metrics"]
        weight_point = next(
            row
            for row in metrics["weight_kg"][1]["points"]
            if row["date"] == today.isoformat()
        )
        body_fat_point = next(
            row
            for row in metrics["body_fat_pct"][1]["points"]
            if row["date"] == today.isoformat()
        )

        self.assertEqual(len(merged[0]["dailyWeightSummaries"]), 601)
        self.assertEqual(weight_point["value"], 73.2)
        self.assertEqual(body_fat_point["value"], 18.5)

    def test_weight_snapshot_merge_collects_all_alias_sections(self) -> None:
        sections = {
            "weighIns": [{"samplePk": 1, "date": "2026-10-10", "weight": 70}],
            "weigh_ins": [{"samplePk": 2, "date": "2026-10-09", "weight": 69}],
            "weight": [{"samplePk": 3, "date": "2026-10-08", "weight": 68}],
        }

        merged = merge_weight_snapshots([sections], [])

        self.assertEqual({row["samplePk"] for row in merged[0]["weight"]}, {1, 2, 3})

    def test_opaque_alias_does_not_overwrite_merged_readings(self) -> None:
        legacy = {"weighIns": {"legacyPayload": {"raw": True}}}
        current = {"weighIns": [{"samplePk": 9, "date": "2026-10-10", "weight": 70}]}
        legacy_before = copy.deepcopy(legacy)
        current_before = copy.deepcopy(current)

        merged = merge_weight_snapshots([current], [legacy])

        self.assertEqual(merged[0]["weight"], current["weighIns"])
        self.assertEqual(
            merged[0]["_garmin_weight_opaque_sections"]["sections"]["weighIns"],
            [legacy["weighIns"]],
        )
        self.assertEqual(legacy, legacy_before)
        self.assertEqual(current, current_before)
        repeated = merge_weight_snapshots([current], merged)
        self.assertEqual(
            repeated[0]["_garmin_weight_opaque_sections"],
            merged[0]["_garmin_weight_opaque_sections"],
        )

    def test_weight_snapshot_merge_replaces_timestamped_corrections_and_keeps_metadata(
        self,
    ) -> None:
        prior = {
            "weighIns": [
                {
                    "samplePk": 17,
                    "timestampGMT": "2026-10-10T07:00:00Z",
                    "weight": 70.0,
                    "metadata": {"scale": {"source": "garmin"}},
                },
                {"samplePk": 33, "date": "2026-10-09", "weight": 69.8},
                {"date": "2026-10-10", "weight": 70.3},
            ],
            "userProfile": {"weightUnit": "kg", "weight": 70.0, "region": "EU"},
            "dailyWeightSummaries": [{"date": "2026-10-09", "weight": 69.8}],
            "rawExtension": {"version": 1, "samples": [{"field": "old"}]},
        }
        correction = {
            "weighIns": [
                {
                    "samplePk": 17,
                    "timestampGMT": "2026-10-10T07:00:00Z",
                    "weight": 70.1,
                    "metadata": {"scale": {"source": "garmin", "corrected": True}},
                },
                {
                    "samplePk": 18,
                    "timestampGMT": "2026-10-10T07:00:00Z",
                    "weight": 70.2,
                },
                {
                    "recordId": 17,
                    "timestampGMT": "2026-10-10T07:00:00Z",
                    "weight": 70.4,
                },
                {"samplePk": 33, "date": "2026-10-09", "weight": 69.9},
                {
                    "timestamp": "2026-10-10T19:00:00Z",
                    "date": "2026-10-10",
                    "weight": 70.5,
                },
            ],
            "userProfile": {"weightUnit": "kg", "region": "EU", "locale": "de"},
            "dailyWeightSummaries": [{"date": "2026-10-10", "weight": 70.1}],
            "rawExtension": {"version": 2, "samples": [{"field": "new"}]},
        }
        prior_before = copy.deepcopy(prior)
        correction_before = copy.deepcopy(correction)

        merged = merge_weight_snapshots([correction], [prior])

        self.assertEqual(len(merged), 1)
        self.assertEqual(len(merged[0]["weight"]), 6)
        corrected = next(
            row for row in merged[0]["weight"] if row.get("samplePk") == 17
        )
        self.assertEqual(corrected["weight"], 70.1)
        self.assertEqual(
            next(
                row["weight"]
                for row in merged[0]["weight"]
                if row.get("samplePk") == 33
            ),
            69.9,
        )
        self.assertIn(
            70.2,
            [row["weight"] for row in merged[0]["weight"] if row.get("samplePk") == 18],
        )
        self.assertTrue(any(row.get("recordId") == 17 for row in merged[0]["weight"]))
        self.assertTrue(corrected["metadata"]["scale"]["corrected"])
        self.assertEqual(merged[0]["userProfile"]["region"], "EU")
        self.assertEqual(merged[0]["userProfile"]["weight"], 70.0)
        self.assertEqual(merged[0]["userProfile"]["locale"], "de")
        self.assertEqual(len(merged[0]["dailyWeightSummaries"]), 2)
        self.assertEqual(merged[0]["rawExtension"]["version"], 2)
        self.assertEqual(len(merged[0]["rawExtension"]["samples"]), 2)
        self.assertEqual(prior, prior_before)
        self.assertEqual(correction, correction_before)

    def test_refresh_merges_legacy_dict_and_raw_window_with_day_85_to_90_samples(
        self,
    ) -> None:
        service, reader, _manager, writer, _coordination = self.make_service()
        start = date(2026, 6, 26)
        existing = {
            "legacySnapshot": True,
            "weighIns": [
                {
                    "date": (start + timedelta(days=offset)).isoformat(),
                    "weight": 68 + offset / 10,
                }
                for offset in range(85, 91)
            ],
        }
        incoming = {
            "weighIns": [
                {"date": "2026-09-19T07:00:00", "weight": 70.5},
                {"date": "2026-09-19T19:00:00", "weight": 70.7},
            ],
            "unit": "kg",
        }
        service._payload_service.view.return_value = {"weight": existing}
        reader.fetch_nutrition_data.return_value = ([incoming], True)

        result = service.refresh("weight", start, date(2026, 9, 24))

        self.assertEqual(result["status"], "ok")
        persisted = writer.write_refresh.call_args.kwargs["view"]
        self.assertEqual(len(persisted["weight"]), 1)
        self.assertTrue(persisted["weight"][0]["legacySnapshot"])
        self.assertEqual(persisted["weight"][0]["unit"], "kg")
        self.assertEqual(len(persisted["weight"][0]["weight"]), 8)

    def test_remote_energy_without_range_api_is_unsupported_without_daily_loop(
        self,
    ) -> None:
        reader = cast(Any, GarminRemoteReader.__new__(GarminRemoteReader))
        client = Mock(spec=["get_user_summary"])
        reader.configured = Mock(return_value=True)
        reader._external_call = lambda _cancel: (
            lambda _service, _operation, call, _details: call()
        )
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
        cast(Any, writer._coverage).persist = Mock()
        view = {"synced_at": "old", "daily_stats": [], "sleep": []}
        db = object()
        counters = Mock()

        with (
            patch(
                "backend.sync.garmin_snapshot_writer.ingest_garmin_payload",
                return_value=counters,
            ),
            patch(
                "backend.sync.garmin_snapshot_writer.garmin_ingest_coverage",
                side_effect=AssertionError(
                    "targeted refresh must not recompute coverage"
                ),
            ),
            patch("backend.sync.garmin_snapshot_writer.garmin_store") as store,
        ):
            store.read_state.return_value = {}
            store.split_state.return_value = {"synced_at": "old"}
            result = writer.write_refresh(
                db,
                fetched_at="new",
                sections={"daily_stats": []},
                view=view,
                windows={},
                allowed=frozenset({"daily_stats"}),
            )

        self.assertIs(result, counters)
        cast(Any, writer._coverage).persist.assert_not_called()
        self.assertEqual(store.write_state.call_args.args[1], {"synced_at": "old"})
        with self.assertRaises(ValueError):
            writer.write_refresh(
                db,
                fetched_at="new",
                sections={"sleep": []},
                view=view,
                windows={},
                allowed=frozenset({"daily_stats"}),
            )

    def test_remote_energy_refresh_prefers_one_range_request(self) -> None:
        reader = cast(Any, GarminRemoteReader.__new__(GarminRemoteReader))
        client = Mock()
        client.get_daily_summaries.return_value = [
            {
                "calendarDate": "2026-09-23",
                "totalKilocalories": 2000,
                "bmrKilocalories": 1700,
            },
            {
                "calendarDate": "2026-09-24",
                "totalKilocalories": 2100,
                "calories": {"burnedResting": 1700},
            },
        ]
        reader.configured = Mock(return_value=True)
        reader._external_call = lambda _cancel: (
            lambda _service, _operation, call, _details: call()
        )
        reader._authenticated_client = lambda _external: (client, "")
        reader._garmin_tokens = None

        records, complete = reader.fetch_nutrition_data(
            "daily_stats", date(2026, 9, 23), date(2026, 9, 24)
        )

        self.assertTrue(complete)
        self.assertEqual(len(records), 2)
        client.get_daily_summaries.assert_called_once_with("2026-09-23", "2026-09-24")
        client.get_user_summary.assert_not_called()

    def test_remote_energy_refresh_reads_missing_resting_energy_per_day(self) -> None:
        reader = cast(Any, GarminRemoteReader.__new__(GarminRemoteReader))
        client = Mock()
        client.get_daily_summaries.return_value = [
            {"calendarDate": "2026-09-24", "calories": {"burnedTotal": 733}}
        ]
        client.get_user_summary.return_value = {
            "calendarDate": "2026-09-24",
            "bmrKilocalories": 2313,
        }
        reader.configured = Mock(return_value=True)
        reader._external_call = lambda _cancel: (
            lambda _service, _operation, call, _details: call()
        )
        reader._authenticated_client = lambda _external: (client, "")
        reader._garmin_tokens = None

        records, complete = reader.fetch_nutrition_data(
            "daily_stats", date(2026, 9, 24), date(2026, 9, 24)
        )

        self.assertTrue(complete)
        self.assertEqual(records[0]["bmrKilocalories"], 2313)
        self.assertEqual(records[0]["calories"], {"burnedTotal": 733})
        client.get_user_summary.assert_called_once_with("2026-09-24")

    def test_remote_body_refresh_uses_only_the_weight_range(self) -> None:
        reader = cast(Any, GarminRemoteReader.__new__(GarminRemoteReader))
        client = Mock()
        client.get_weigh_ins.return_value = {
            "weighIns": [{"date": "2026-09-24", "weight": 70.5}]
        }
        reader.configured = Mock(return_value=True)
        reader._external_call = lambda _cancel: (
            lambda _service, _operation, call, _details: call()
        )
        reader._authenticated_client = lambda _external: (client, "")
        reader._garmin_tokens = None

        records, complete = reader.fetch_nutrition_data(
            "weight", date(2026, 9, 1), date(2026, 9, 24)
        )

        self.assertTrue(complete)
        self.assertEqual(
            records,
            [{"weighIns": [{"date": "2026-09-24", "weight": 70.5}]}],
        )
        client.get_weigh_ins.assert_called_once_with("2026-09-01", "2026-09-24")
        client.get_daily_summaries.assert_not_called()

    def test_remote_body_refresh_preserves_raw_history_and_multiple_daily_samples(
        self,
    ) -> None:
        reader = cast(Any, GarminRemoteReader.__new__(GarminRemoteReader))
        client = Mock()
        raw = {
            "weighIns": [
                {"date": "2026-08-01", "weight": 68.2},
                {"date": "2026-09-24T07:00:00", "weight": 70.5},
                {"date": "2026-09-24T19:00:00", "weight": 70.7},
                {"date": "2026-09-25", "weight": 71.0},
            ],
            "userProfile": {"weightUnit": "kg"},
        }
        client.get_weigh_ins.return_value = raw
        reader.configured = Mock(return_value=True)
        reader._external_call = lambda _cancel: (
            lambda _service, _operation, call, _details: call()
        )
        reader._authenticated_client = lambda _external: (client, "")
        reader._garmin_tokens = None

        records, complete = reader.fetch_nutrition_data(
            "weight", date(2026, 9, 24), date(2026, 9, 24)
        )

        self.assertTrue(complete)
        self.assertEqual(records, [raw])
        self.assertEqual(len(records[0]["weighIns"]), 4)

    def test_remote_body_refresh_keeps_body_fat_only_measurements_and_normalizes_date(
        self,
    ) -> None:
        reader = cast(Any, GarminRemoteReader.__new__(GarminRemoteReader))
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
        reader._external_call = lambda _cancel: (
            lambda _service, _operation, call, _details: call()
        )
        reader._authenticated_client = lambda _external: (client, "")
        reader._garmin_tokens = None

        records, complete = reader.fetch_nutrition_data(
            "weight", date(2026, 9, 24), date(2026, 9, 24)
        )

        self.assertTrue(complete)
        self.assertEqual(len(records), 1)
        self.assertEqual(records, [client.get_weigh_ins.return_value])

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
        payloads.view.return_value = {
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

        result = service.refresh("daily_stats", date(2026, 9, 24), date(2026, 9, 24))

        self.assertEqual(result["status"], "ok")
        reader.fetch_nutrition_data.assert_called_once_with(
            "daily_stats", date(2026, 9, 24), date(2026, 9, 24)
        )
        writer.write_refresh.assert_called_once()
        persisted = writer.write_refresh.call_args.kwargs["view"]
        self.assertEqual(
            persisted["daily_stats"],
            [
                {"calendarDate": "2026-09-24", "totalKilocalories": 2100},
                {"calendarDate": "2026-09-23", "totalKilocalories": 2000},
            ],
        )
        self.assertEqual(
            persisted["source_freshness"]["sleep"], {"freshness": "current"}
        )
        self.assertEqual(persisted["synced_at"], "2026-09-23T12:00:00Z")
        self.assertEqual(
            persisted["nutrition_refresh"]["daily_stats"]["2026-09-24"]["freshness"],
            "current",
        )
        manager.unit_of_work.assert_called_once()
        coordination.release.assert_called_once()

    def test_empty_body_refresh_is_partial_and_retains_prior_measurement_as_stale(
        self,
    ) -> None:
        service, reader, _manager, writer, _coordination = self.make_service()
        reader.fetch_nutrition_data.return_value = ([], True)
        snapshot = {
            "synced_at": "2026-09-20T12:00:00Z",
            "weight": [{"date": "2026-09-20", "weight": 70.0}],
        }
        service._payload_service.view.return_value = snapshot

        result = service.refresh("weight", date(2026, 9, 1), date(2026, 9, 24))

        self.assertEqual(result["status"], "partial")
        persisted = writer.write_refresh.call_args.kwargs["view"]
        self.assertEqual(
            persisted["weight"],
            [{"weight": [{"date": "2026-09-20", "weight": 70.0}]}],
        )
        self.assertEqual(
            persisted["nutrition_refresh"]["weight"]["2026-09-24"]["freshness"],
            "partial",
        )

    def test_provider_failure_returns_partial_without_persisting_stale_as_fresh(
        self,
    ) -> None:
        service, reader, _manager, writer, _coordination = self.make_service()
        reader.fetch_nutrition_data.side_effect = RuntimeError("provider unavailable")

        result = service.refresh("daily_stats", date(2026, 9, 24), date(2026, 9, 24))

        self.assertEqual(
            result, {"status": "partial", "reason": "provider_unavailable"}
        )
        writer.write.assert_not_called()

    def test_unconfigured_provider_returns_explicit_partial_result(self) -> None:
        service, reader, _manager, writer, _coordination = self.make_service()
        cast(Any, service)._configured = lambda: False

        result = service.refresh("weight", date(2026, 9, 1), date(2026, 9, 24))

        self.assertEqual(result, {"status": "partial", "reason": "not_configured"})
        reader.fetch_nutrition_data.assert_not_called()
        writer.write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
