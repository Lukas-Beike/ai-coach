"""The envelope of served activity details, through the production read assembly."""

import tempfile
import unittest
from datetime import date

from activity_row_support import NoObservations, SnapshotActivityRows, StoredCoverage
from canonical_detail_support import add_session_record, open_manager

from backend.canonical.vocabulary import ProviderId
from backend.http_api.activity_assembly import ActivityReadAssembly, ActivityReadSources
from backend.performance.freshness import NO_GARMIN_SYNC_STATUS

TODAY = date(2026, 9, 20)
ENVELOPE_KEYS = ("activity_feedback", "equipment", "activity_validation")
NO_DATA = {
    "available": False,
    "status": "no_completed_activity",
    "scope": "Keine abgeschlossene Einheit mit verwertbarem Zeitstempel vorhanden.",
}


class _Snapshots:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def latest_snapshot(self, _db):
        return self.snapshot


class _Feedback:
    def __init__(self, rows):
        self.rows = rows

    def list(self, _limit=100):
        return self.rows


class DetailEnvelopeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.manager = open_manager(directory.name)
        self.addCleanup(self.manager.close)
        add_session_record(self.manager, ProviderId.INTERVALS, "i1", "act_i")
        add_session_record(self.manager, ProviderId.GARMIN, "g1", "act_g")
        add_session_record(
            self.manager, ProviderId.WAHOO, "w1", "act_w", recorded_by="wahoo"
        )
        snapshots = _Snapshots(
            {
                "synced_at": "2026-09-20T08:00:00+00:00",
                "athlete": {},
                "raw_provider_data": {
                    "activities": [
                        {
                            "id": "i1",
                            "type": "Ride",
                            "start_date_local": "2026-09-10T07:00:00",
                            "moving_time": 3600,
                        }
                    ]
                },
            }
        )
        self.equipment_reads = []
        self.configured = ["intervals", "garmin", "weather"]
        feedback = self.feedback = _Feedback(
            [
                {"activity_id": reference, "notes": reference}
                for reference in ("i1", "act_g", "act_w")
            ]
        )
        self.assembly = ActivityReadAssembly(
            lambda: self.manager,
            ActivityReadSources(
                lambda: SnapshotActivityRows(snapshots),
                observation_reader=NoObservations,
                coverage=lambda: StoredCoverage(None),
            ),
            lambda: feedback,
            self.read_equipment,
            refreshable_providers=lambda: self.configured,
        )

    def read_equipment(self, activity_id):
        self.equipment_reads.append(activity_id)
        return {
            "items": [{"id": f"bike-{activity_id}"}],
            "assignments": [
                {"activity_id": activity_id, "equipment_id": f"bike-{activity_id}"}
            ],
        }

    def detail(self, activity_id):
        return self.assembly.activity_read().detail(
            activity_id, garmin_status=NO_GARMIN_SYNC_STATUS, profile={}, today=TODAY
        )

    def test_envelope_is_filled_for_intervals_garmin_and_wahoo_sessions(self):
        for activity_id, reference in (
            ("act_i", "i1"),
            ("act_g", "act_g"),
            ("act_w", "act_w"),
        ):
            with self.subTest(activity_id):
                document = self.detail(activity_id)

                self.assertEqual(activity_id, document["session"]["activity_id"])
                for key in ENVELOPE_KEYS:
                    self.assertIsNotNone(document[key])
                self.assertEqual(reference, document["activity_feedback"]["notes"])
                self.assertEqual([{"id": f"bike-{reference}"}], document["equipment"])
                self.assertEqual(reference, self.equipment_reads[-1])

    def test_validation_uses_the_intervals_summary_or_reports_no_data(self):
        validation = self.detail("i1")["activity_validation"]
        self.assertTrue(validation["available"])
        self.assertNotEqual("no_completed_activity", validation["status"])

        for activity_id in ("act_g", "act_w"):
            with self.subTest(activity_id):
                self.assertEqual(
                    NO_DATA, self.detail(activity_id)["activity_validation"]
                )

    def test_session_rpe_load_comes_from_the_summary_and_its_feedback(self):
        load = self.detail("i1")["session_rpe_load"]
        self.assertEqual(
            ("act_i1", None, "no_rating"),
            (load["activity_id"], load["value"], load["reason"]),
        )
        self.feedback.rows[0]["session_rpe"] = 5
        load = self.detail("i1")["session_rpe_load"]
        self.assertEqual(("athlete_feedback", 5), (load["rpe_source"], load["rpe"]))
        for activity_id in ("act_g", "act_w"):
            with self.subTest(activity_id):
                self.assertIsNone(self.detail(activity_id)["session_rpe_load"])

    def test_refresh_is_offered_for_configured_detail_providers_only(self):
        def refreshable(activity_id):
            return {
                entry["provider"]: entry["refreshable"]
                for entry in self.detail(activity_id)["detail_data"]["providers"]
            }

        self.assertEqual({"intervals": True}, refreshable("act_i"))
        self.assertEqual({"garmin": True}, refreshable("act_g"))
        self.assertEqual({"wahoo": False}, refreshable("act_w"))
        self.configured = ["intervals", "wahoo"]
        self.assertEqual({"garmin": False}, refreshable("act_g"))


if __name__ == "__main__":
    unittest.main()
