import json
import unittest
from contextlib import contextmanager
from datetime import date

from backend.activities.read_service import ActivityReadService
from backend.errors import AppError


class _Manager:
    @contextmanager
    def unit_of_work(self):
        yield object()


class _Snapshots:
    def __init__(self, snapshot):
        self.payload = json.dumps(snapshot)

    def latest_payload(self, _db):
        return self.payload


class _Feedback:
    def __init__(self):
        self.rows = [{"activity_id": "new", "notes": "good"}]

    def list(self, _limit=100):
        return self.rows

    def attach_to_activities(self, activities):
        by_id = {row["activity_id"]: row for row in self.rows}
        return [
            {
                **item,
                **(
                    {"activity_feedback": by_id[str(item["id"])]}
                    if str(item.get("id")) in by_id
                    else {}
                ),
            }
            for item in activities
        ]


class ActivityReadServiceTests(unittest.TestCase):
    def service(self):
        snapshot = {
            "synced_at": "2026-09-20T08:00:00+00:00",
            "athlete": {},
            "recent_wellness": [],
            "recent_activities": [
                {"id": "old", "start_date_local": "2026-09-18T08:00:00", "type": "Run"},
                {"id": "new", "start_date_local": "2026-09-20T08:00:00", "type": "Run"},
                "invalid",
            ],
            "raw_provider_data": {
                "activities": [
                    {
                        "id": "new",
                        "name": "Morning run",
                        "type": "Run",
                        "start_date_local": "2026-09-20T08:00:00",
                    }
                ]
            },
        }
        return ActivityReadService(_Manager(), _Snapshots(snapshot), _Feedback())

    def test_page_filters_orders_attaches_feedback_and_uses_cursor(self):
        service = self.service()
        page = service.page(limit=1, days=3, today=date(2026, 9, 20))
        self.assertEqual(["new"], [item["id"] for item in page["activities"]])
        self.assertEqual("good", page["activities"][0]["activity_feedback"]["notes"])
        second = service.page(page["next_cursor"], 1, 3, today=date(2026, 9, 20))
        self.assertEqual(["old"], [item["id"] for item in second["activities"]])
        self.assertIsNone(second["next_cursor"])

    def test_recent_filters_by_explicit_today_without_mutating_snapshot(self):
        service = self.service()
        before = service._snapshot()
        result = service.recent(days=1, today=date(2026, 9, 20))
        self.assertEqual(["new"], [item["id"] for item in result["activities"]])
        self.assertEqual(before, service._snapshot())

    def test_detail_is_bounded_and_includes_feedback(self):
        result = self.service().detail(
            "new", garmin_snapshot={}, profile={}, today=date(2026, 9, 20)
        )
        self.assertEqual("Morning run", result["activity"]["name"])
        self.assertEqual("good", result["activity_feedback"]["notes"])
        self.assertEqual(
            "bounded sanitized detail projection of exactly one Intervals.icu activity",
            result["data_scope"],
        )

    def test_detail_rejects_invalid_or_missing_activity(self):
        service = self.service()
        with self.assertRaises(AppError) as invalid:
            service.detail("", garmin_snapshot={}, profile={}, today=date(2026, 9, 20))
        self.assertEqual("invalid_activity_request", invalid.exception.reason)
        with self.assertRaises(AppError) as missing:
            service.detail(
                "missing", garmin_snapshot={}, profile={}, today=date(2026, 9, 20)
            )
        self.assertEqual("activity_details_not_found", missing.exception.reason)


if __name__ == "__main__":
    unittest.main()
