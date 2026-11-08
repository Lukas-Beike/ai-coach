import copy
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from canonical_recovery_support import (
    recovery_inputs,
    recovery_observation,
    recovery_only_inputs,
)
from performance_day_support import canonical_from_snapshot

from backend.canonical.coverage import ProviderCoverage
from backend.canonical.vocabulary import MetricKind, ProviderId
from backend.performance.canonical_body import CanonicalBodyInputs
from backend.performance.canonical_inputs import (
    EMPTY_PERFORMANCE_INPUTS,
    PENDING_PERFORMANCE_INPUTS,
    CanonicalPerformanceInputs,
    CanonicalPerformanceSource,
    with_read_status,
)
from backend.performance.context import current_performance_context
from backend.performance.freshness import GarminSyncStatus


class PerformanceContextTests(unittest.TestCase):
    def test_none_and_empty_snapshots_are_unavailable(self):
        expected = {
            "available": False,
            "source": "Gespeicherte Provider-Daten",
            "as_of": None,
            "metrics": {},
        }
        for snapshot in (None, {}):
            result = current_performance_context(
                GarminSyncStatus.from_state({}),
                {},
                date(2026, 9, 20),
                canonical=EMPTY_PERFORMANCE_INPUTS,
            )
            recovery = result.pop("personal_recovery")
            focus = result.pop("training_focus")
            self.assertEqual(focus["zones"], [])
            self.assertEqual(focus["classified_sessions"], 0)
            self.assertEqual(result, expected)
            self.assertEqual(recovery["baselines"], [])
            self.assertEqual(recovery["sleep_deficits"], [])

    def test_composes_intervals_garmin_load_health_and_validation(self):
        today = date(2026, 9, 20)
        snapshot = {
            "synced_at": "2026-09-20T08:00:00Z",
            "athlete": {
                "icu_ftp": 300,
                "lthr": 171,
                "max_hr": 190,
                "icu_w_prime": 20,
            },
            "recent_wellness": [
                {
                    "id": today.isoformat(),
                    "ctl": 70,
                    "atl": 76,
                    "tsb": -6,
                    "sleepSecs": 27000,
                    "readiness": 8,
                }
            ],
            "recent_activities": [
                {
                    "id": "ride-1",
                    "type": "Ride",
                    "start_date_local": f"{today.isoformat()}T07:00:00",
                    "moving_time": 3600,
                    "icu_training_load": 110,
                    "average_watts": 200,
                    "average_heartrate": 150,
                }
            ],
        }
        garmin = {
            "sleep": [
                {
                    "calendarDate": today.isoformat(),
                    "sleepTimeSeconds": 28800,
                    "sleepScore": 90,
                }
            ],
            "daily_stats": [
                {
                    "calendarDate": (today - timedelta(days=1)).isoformat(),
                    "totalSteps": 1000,
                    "floorsAscended": 5,
                    "totalKilocalories": 2000,
                },
                {
                    "calendarDate": today.isoformat(),
                    "totalSteps": 9999,
                    "floorsAscended": 99,
                    "totalKilocalories": 9999,
                },
            ],
            "source_freshness": {
                "sleep": {
                    "freshness": "fresh",
                    "observed_at": today.isoformat(),
                },
                "daily_stats": {
                    "freshness": "fresh",
                    "observed_at": (today - timedelta(days=1)).isoformat(),
                },
            },
        }

        # Athlete settings, recovery and Garmin values come only from canonical
        # observations (#1411, #1415); map the fixtures.
        result = current_performance_context(
            GarminSyncStatus.from_state(garmin),
            {},
            today,
            canonical=recovery_only_inputs(
                garmin, snapshot["recent_wellness"], snapshot=snapshot
            ),
        )

        self.assertTrue(result["available"])
        self.assertEqual(result["source"], "Gespeicherte Provider-Daten")
        # The stored Intervals.icu snapshot names no sync time any more (#1728);
        # these inputs carry no activity coverage.
        self.assertIsNone(result["as_of"])
        # The Intervals.icu athlete FTP is no source; Garmin reports none here.
        self.assertIsNone(result["thresholds"]["ftp_w"])
        self.assertNotIn("w_prime_j", result["thresholds"])
        # The mapped Intervals.icu form is not shown; the current load is the
        # local curve, which has no stored load here, and no ramp rate is derived.
        self.assertNotIn("intervals_load_history", result)
        self.assertIsNone(result["current_load"]["tsb"])
        self.assertNotIn("ramp_rate", result["current_load"])
        # Provider loads are never summed (card M6): without a stored local load
        # every session of the window counts as missing.
        last_7 = result["rolling_training"]["last_7_days"]
        self.assertEqual(last_7["training_load"], 0.0)
        self.assertEqual(last_7["load_missing_sessions"], last_7["sessions"])
        self.assertEqual(result["metrics"]["steps_7d"]["value"], 1000)
        self.assertEqual(result["metrics"]["floors_7d"]["value"], 5)
        self.assertEqual(result["metrics"]["calories_7d"]["value"], 2000)
        self.assertEqual(result["metrics"]["steps_7d"]["measurement_status"], "earlier")
        self.assertTrue(result["activity_validation"]["available"])

    def test_garmin_source_freshness_and_daily_health_window_are_explicit(self):
        today = date(2026, 9, 20)
        garmin = {
            "sleep": [
                {
                    "calendarDate": today.isoformat(),
                    "sleepTimeSeconds": 28800,
                    "sleepScore": 90,
                }
            ],
            "daily_stats": [
                {"date": (today - timedelta(days=8)).isoformat(), "steps": 7},
                {"date": (today - timedelta(days=6)).isoformat(), "steps": 100},
                {"date": today.isoformat(), "steps": 999},
            ],
            "source_freshness": {
                "sleep": {
                    "freshness": "fresh",
                    "observed_at": today.isoformat(),
                },
                "daily_stats": {
                    "freshness": "partial",
                    "fetched_at": "2026-09-20T09:00:00Z",
                    "observed_at": (today - timedelta(days=1)).isoformat(),
                },
            },
        }

        result = current_performance_context(
            GarminSyncStatus.from_state(garmin),
            {},
            today,
            canonical=recovery_only_inputs(garmin),
        )

        self.assertEqual(result["metrics"]["steps_7d"]["value"], 100)
        self.assertEqual(result["metrics"]["steps_7d"]["freshness"], "partial")
        self.assertEqual(result["recovery"]["sleep_hours"], 8.0)
        self.assertEqual(
            result["recovery"]["source_freshness"]["sleep_hours"]["freshness"], "fresh"
        )

    def test_rolling_training_and_input_nonmutation(self):
        today = date(2026, 9, 20)
        snapshot = {
            "synced_at": "now",
            "athlete": {},
            "recent_wellness": [
                {"id": (today - timedelta(days=1)).isoformat(), "atl": 10, "ctl": 20},
                {"id": today.isoformat(), "atl": 12, "ctl": 20},
            ],
            "recent_activities": [
                {
                    "id": "load",
                    "type": "Ride",
                    "start_date_local": f"{today.isoformat()}T08:00:00",
                    "icu_training_load": 70,
                },
                "malformed",
            ],
        }
        garmin = {"source_freshness": {"max_metrics": {"freshness": "stale"}}}
        profile = {"weight_kg": "72"}
        before = (
            copy.deepcopy(snapshot),
            copy.deepcopy(garmin),
            copy.deepcopy(profile),
        )

        result = current_performance_context(
            GarminSyncStatus.from_state(garmin),
            profile,
            today,
            canonical=canonical_from_snapshot(snapshot, today),
        )

        # The Intervals-anchored "actual ATL" is gone (#1726): it mixed sources.
        self.assertNotIn("actual_load", result)
        self.assertIn("last_28_days", result["rolling_training"])
        self.assertEqual((snapshot, garmin, profile), before)

    def test_missing_and_malformed_lists_do_not_break_projection(self):
        snapshot = {
            "synced_at": "now",
            "athlete": "invalid",
            "recent_wellness": [
                None,
                {"id": "2026-09-20", "readiness": "bad", "ctl": 40, "weight": 70},
            ],
            "recent_activities": [None, "bad", {"type": "Unknown"}],
        }
        # A Garmin weight makes the context available.
        canonical = replace(
            canonical_from_snapshot(snapshot, date(2026, 9, 20)),
            body=CanonicalBodyInputs(
                garmin_weight_kg={date(2026, 9, 20): 70.0}, garmin_body_fat_pct={}
            ),
        )
        result = current_performance_context(
            GarminSyncStatus.from_state({}),
            {},
            date(2026, 9, 20),
            canonical=canonical,
        )

        self.assertTrue(result["available"])
        self.assertIn("metrics", result)
        self.assertIn("activity_validation", result)

    def test_missing_snapshot_with_garmin_observations_is_available(self):
        today = date(2026, 9, 20)
        nights = [
            recovery_observation(
                MetricKind.RESTING_HR,
                48 + day % 3,
                (today - timedelta(days=day)).isoformat(),
                record_id=f"rhr-{day}",
            )
            for day in range(20)
        ]
        canonical = CanonicalPerformanceInputs(recovery=recovery_inputs(nights))

        result = current_performance_context(
            GarminSyncStatus.from_state({}), {}, today, canonical=canonical
        )
        raw_only = current_performance_context(
            GarminSyncStatus.from_state(
                {"resting_hr": [{"calendarDate": "2026-09-20", "restingHR": 50}]}
            ),
            {},
            today,
            canonical=EMPTY_PERFORMANCE_INPUTS,
        )

        # Canonical observations make the context available without a snapshot.
        self.assertTrue(result["available"])
        self.assertIsNone(result["as_of"])
        self.assertFalse(raw_only["available"])
        baseline = result["personal_recovery"]["baselines"][0]
        self.assertEqual(baseline["source"], "Garmin Connect")
        self.assertEqual(baseline["metric"], "resting_hr")
        self.assertEqual(baseline["status"], "provisional")
        # The raw Garmin view alone no longer produces a baseline.
        self.assertEqual(raw_only["personal_recovery"]["baselines"], [])

    def test_garmin_only_setup_gets_the_full_context_from_observations(self):
        today = date(2026, 9, 20)
        garmin = {
            "sleep": [
                {
                    "calendarDate": today.isoformat(),
                    "sleepTimeSeconds": 28800,
                    "sleepScore": 90,
                }
            ],
            "resting_hr": [{"calendarDate": today.isoformat(), "restingHR": 47}],
        }

        result = current_performance_context(
            GarminSyncStatus.from_state(garmin),
            {},
            today,
            canonical=recovery_only_inputs(garmin),
        )

        self.assertTrue(result["available"])
        self.assertIsNone(result["as_of"])
        self.assertEqual(result["recovery"]["sleep_hours"], 8.0)
        self.assertEqual(result["recovery"]["sleep_score"], 90)
        self.assertEqual(result["recovery"]["resting_hr_bpm"], 47)
        self.assertEqual(result["recovery"]["sleep_source"], "Garmin Connect")
        for key in ("metrics", "current_load", "rolling_training", "comparisons"):
            self.assertIn(key, result)

    def test_pending_canonical_source_reports_no_values(self):
        today = date(2026, 9, 20)
        garmin = {
            "sleep": [{"calendarDate": today.isoformat(), "sleepScore": 90}],
            "resting_hr": [{"calendarDate": today.isoformat(), "restingHR": 47}],
        }

        result = current_performance_context(
            GarminSyncStatus.from_state(garmin),
            {},
            today,
            canonical=PENDING_PERFORMANCE_INPUTS,
        )

        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "canonical_pending")
        self.assertEqual(result["status"], "Daten werden vorbereitet")
        self.assertIsNone(result["as_of"])
        self.assertEqual(result["metrics"], {})
        self.assertNotIn("garmin_training_load", result)
        self.assertEqual(result["personal_recovery"]["baselines"], [])
        self.assertEqual(result["training_focus"]["classified_sessions"], 0)

    def test_inputs_without_provider_values_are_unavailable(self):
        today = date(2026, 9, 20)
        nothing = CanonicalPerformanceInputs(activities=())

        result = current_performance_context(
            GarminSyncStatus.from_state({}), {}, today, canonical=nothing
        )

        self.assertFalse(result["available"])
        self.assertNotIn("status", result)

    def test_sync_time_without_athlete_record_values_comes_from_the_coverage(self):
        # The context names the activity sync time of the canonical coverage (the
        # one reports use too), never an Intervals.icu snapshot (#1728).
        today = date(2026, 9, 20)
        canonical = replace(
            canonical_from_snapshot({}, today),
            body=CanonicalBodyInputs(
                garmin_weight_kg={today: 70.0}, garmin_body_fat_pct={}
            ),
        )
        coverage = _ProviderCoverage(datetime(2026, 9, 20, 8, tzinfo=UTC))
        source = CanonicalPerformanceSource(
            database_manager=lambda: None,
            observation_reader=lambda: None,  # type: ignore[arg-type, return-value]
            coverage=lambda: coverage,
        )

        served = with_read_status(source, None, canonical)
        assert served is not None
        result = current_performance_context(
            GarminSyncStatus(), {}, today, canonical=served
        )
        without = current_performance_context(
            GarminSyncStatus(), {}, today, canonical=canonical
        )

        self.assertEqual(served.activities_synced_at, "2026-09-20T08:00:00+00:00")
        self.assertEqual(result["as_of"], "2026-09-20T08:00:00+00:00")
        self.assertEqual(result["source"], "Gespeicherte Provider-Daten")
        self.assertTrue(without["available"])
        self.assertIsNone(without["as_of"])
        self.assertEqual(without["source"], "Gespeicherte Provider-Daten")

    def test_weekly_hrv_fallback_keeps_its_garmin_freshness(self):
        today = date(2026, 9, 7)
        garmin = {
            "hrv": [{"calendarDate": "2026-09-07", "weeklyAvg": 58}],
            "source_freshness": {
                "hrv": {"freshness": "stale", "observed_at": "2026-09-07"}
            },
        }

        recovery = current_performance_context(
            GarminSyncStatus.from_state(garmin),
            {},
            today,
            canonical=recovery_only_inputs(garmin),
        )["recovery"]

        self.assertEqual(recovery["hrv_ms_source"], "Garmin Connect (Wochenmittel)")
        self.assertEqual(recovery["source_freshness"]["hrv_ms"]["freshness"], "stale")

    def test_composed_context_has_only_neutral_performance_keys(self):
        today = date(2026, 9, 20)
        snapshot = {
            "athlete": {"icu_ftp": 300, "icu_w_prime": 20},
            "recent_wellness": [
                {
                    "id": today.isoformat(),
                    "ctl": 50,
                    "atl": 40,
                    "restingHR": 52,
                    "hrv": 45,
                    "sleepScore": 80,
                }
            ],
        }
        result = current_performance_context(
            GarminSyncStatus.from_state({}),
            {},
            today,
            canonical=canonical_from_snapshot(snapshot, today),
        )

        def keys(value):
            if isinstance(value, dict):
                for key, child in value.items():
                    yield key
                    yield from keys(child)
            elif isinstance(value, list):
                for child in value:
                    yield from keys(child)

        self.assertFalse(
            set(keys(result))
            & {"restingHR", "sleepScore", "rampRate", "icu_ftp", "icu_w_prime"}
        )
        self.assertNotIn("hrv", result["recovery"])
        self.assertNotIn("hrv", result["comparisons"])
        self.assertIsNone(result["thresholds"]["ftp_w"])
        self.assertNotIn("w_prime_j", result["thresholds"])
        self.assertNotIn("intervals_load_history", result)
        self.assertEqual(result["current_load"]["source"], "Lokal berechnet (M7)")


if __name__ == "__main__":
    unittest.main()


class _ProviderCoverage:
    """Canonical coverage with one Garmin activity fetch time, no metric windows."""

    def __init__(self, retrieved_at: datetime) -> None:
        self._retrieved_at = retrieved_at

    def coverage(self, db):
        return (
            ProviderCoverage(
                provider=ProviderId.GARMIN,
                retrieved_at=self._retrieved_at,
                activity_count=0,
                observation_count=1,
                issue_counts={},
                first_observed_on=None,
                last_observed_on=None,
                activities_retrieved_at=self._retrieved_at,
            ),
        )

    def metric_windows(self, db):
        return ()
