"""Server integration tests for weather calendar."""

import json
import unittest
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import call, Mock, patch

from backend.activities import calendar_projection as activity_calendar_projection
from backend.calendar import canonical as calendar_canonical, local as calendar_local
from backend.coach.context import CoachIntervalsContextService
from backend.http_api.public_weather import PublicWeatherStateService
from backend.planning import planned_units as planning_planned_units, workouts as planning_workouts
from backend.providers import calendar as calendar_provider, intervals_client as intervals_client_module, weather as weather_provider
from backend.sync import snapshots as sync_snapshots
from backend.sync.intervals import IntervalsSnapshotReader
from backend.sync.library import WorkoutLibraryRefreshService
from backend.sync.performance import PerformanceRefreshFollowupService
from backend.weather import cache as weather_cache, history as weather_history, projection as weather_projection, recommendations as weather_recommendations
from server_test_support import server, ServerTestCase
from support import IntervalsRequestRecorder, parsed_workout_fixture, RecordedIntervalsClient


class ServerWeatherCalendarTests(ServerTestCase):

    def test_public_weather_state_service_refreshes_only_when_not_local_and_hides_marker(self):
        weather = Mock()
        weather.state.return_value = {"configured": True, "_refreshed": True}
        endpoint = PublicWeatherStateService(weather)

        self.assertEqual(endpoint.state(local_only=True), {"configured": True})
        weather.state.assert_called_once_with(refresh=False)
        weather.state.reset_mock()
        weather.state.return_value = {"configured": True, "_refreshed": True}

        self.assertEqual(endpoint.state(), {"configured": True})
        weather.state.assert_called_once_with(refresh=True)

    def test_historical_sync_does_not_queue_performance_follow_up_from_common_path(self):
        snapshot = {"synced_at": "historical", "athlete": {}, "recent_activities": [], "recent_wellness": [], "upcoming_calendar": []}
        config = replace(server.CONFIG, intervals_api_key="test-key")
        with patch.object(server, "CONFIG", config), patch.object(
            IntervalsSnapshotReader, "fetch_snapshot", return_value=snapshot
        ), patch.object(WorkoutLibraryRefreshService, "refresh", return_value={"workouts": 0}), patch.object(
            PerformanceRefreshFollowupService, "enqueue_after_sync"
        ) as enqueue, patch.object(server.DailySyncMarkerService, "mark") as mark:
            server.intervals_sync_service().sync(
                "startup historical backfill",
                activity_days=90,
                end_date=date(2026, 1, 1),
            )
        enqueue.assert_not_called()
        mark.assert_not_called()

    def test_historical_snapshot_merge_preserves_current_read_model(self):
        current = {
            "synced_at": "current",
            "recent_activities": [{"id": "new"}],
            "raw_provider_data": {"athlete": {"id": "athlete"}, "activities": [{"id": "new"}], "wellness": [], "upcoming_calendar": []},
        }
        historical = {
            "synced_at": "historical",
            "recent_activities": [{"id": "old"}],
            "raw_provider_data": {"athlete": {}, "activities": [{"id": "old"}], "wellness": [{"id": "wellness-old"}], "upcoming_calendar": []},
            "provider_sync": {"calendar_window": {"start": "2020-01-01", "end": "2020-03-30"}},
        }
        merged = sync_snapshots.merge_historical_snapshot(current, historical)
        self.assertEqual(merged["recent_activities"], current["recent_activities"])
        self.assertEqual({item["id"] for item in merged["raw_provider_data"]["activities"]}, {"new", "old"})
        self.assertEqual(merged["raw_provider_data"]["wellness"], [{"id": "wellness-old"}])
        self.assertEqual(merged["synced_at"], "current")

    def test_public_calendar_source_delete_cascades_to_candidates(self):
        now = server.utc_now()
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO public_event_sources(id, name, url, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("source", "Source", "https://example.test/calendar", now, now),
            )
            db.execute(
                "INSERT INTO public_event_candidates(id, source_id, uid, name, event_date, sport, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("candidate", "source", "uid", "Event", "2026-09-01", "run", now, now),
            )
            db.execute("DELETE FROM public_event_sources WHERE id = ?", ("source",))
            self.assertEqual(db.execute("SELECT COUNT(*) AS count FROM public_event_candidates").fetchone()["count"], 0)
            with self.assertRaises(server.sqlite3.IntegrityError):
                db.execute(
                    "INSERT INTO public_event_candidates(id, source_id, uid, name, event_date, sport, created_at, updated_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    ("invalid", "missing-source", "uid", "Event", "2026-09-01", "run", now, now),
                )

    def test_daily_weather_rain_peak_uses_local_hours_and_stays_date_specific(self):
        forecast = {"daily": {"time": ["2026-09-05", "2026-09-06", "2026-09-07", "2026-09-08"]},
                    "hourly": {
                        "time": ["2026-09-05T19:00", "2026-09-05T06:00", "2026-09-05T15:00",
                                 "2026-09-06T09:00", "2026-09-06T18:00", "2026-09-07T09:00", "2026-09-07T10:00"],
                        "precipitation_probability": [80, 5, 80, 0, 0, 30, 30],
                    }}
        days = weather_projection.daily_summary(forecast)
        self.assertEqual(days[0]["rain_peak_time"], "15:00")
        self.assertIsNone(days[1]["rain_peak_time"])
        self.assertIsNone(days[2]["rain_peak_time"])
        self.assertIsNone(days[3]["rain_peak_time"])
        forecast["hourly"]["precipitation_probability"] = [None, 5, None]
        self.assertIsNone(
            weather_projection.daily_summary(forecast)[0]["rain_peak_time"]
        )

    def test_calendar_weather_history_survives_refresh_location_change_and_restart(self):
        today = server.ATHLETE_CLOCK.now().date()
        yesterday = (today - timedelta(days=1)).isoformat()
        tomorrow = (today + timedelta(days=1)).isoformat()
        server.profile_service().save({"weather_location": "Berlin"})
        old = {"query": "Berlin", "location": {"name": "Berlin"}, "fetched_at": server.utc_now(),
               "forecast": {"daily": {"time": [yesterday, tomorrow], "temperature_2m_max": [12, 18]},
                            "hourly": {"time": [f"{yesterday}T09:00", f"{yesterday}T15:00"], "precipitation_probability": [5, 80]}}}
        new = {"query": "Berlin", "location": {"name": "Berlin"}, "fetched_at": server.utc_now(),
               "forecast": {"daily": {"time": [today.isoformat(), tomorrow], "temperature_2m_max": [15, 19]}}}
        with patch.object(weather_provider.WeatherClient, "fetch", side_effect=[old, new]) as fetch:
            server.weather_service().state([], force=True)
            server.weather_service().state([], force=True)
            server.profile_service().save({"weather_location": "Emsdetten"})
            server.initialise_database()
            calendar = server.public_plan_state_service().read(local_only=True)
        self.assertEqual(fetch.call_count, 2)
        history = calendar["weather"]["days"]
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["date"], yesterday)
        self.assertEqual(history[0]["temperature_max"], 12)
        self.assertEqual(history[0]["forecast_location"], "Berlin")
        self.assertTrue(history[0]["archived_forecast"])
        context = next(day for day in calendar["daily_planning_context"] if day["date"] == yesterday)
        self.assertTrue(context["weather"]["archived_forecast"])
        self.assertEqual(context["weather"]["forecast_saved_at"], old["fetched_at"])
        self.assertEqual(context["weather"]["rain_peak_time"], "15:00")

    def test_changing_weather_location_invalidates_previous_forecast(self):
        server.profile_service().save({"weather_location": "Münster"})
        server.key_value_service().set(weather_cache.CACHE_KEY, json.dumps({"query": "Münster", "forecast": {}}))
        server.profile_service().save({"weather_location": "Köln"})
        self.assertEqual(server.key_value_service().get(weather_cache.CACHE_KEY), "")

    def test_changing_weather_location_clears_negative_cache(self):
        server.profile_service().save({"weather_location": "Berlin"})
        server.key_value_service().set(weather_cache.FAILURE_KEY, json.dumps({"count": 2, "retry_at": "2099-01-01T00:00:00+00:00"}))
        server.profile_service().save({"weather_location": "Koeln"})
        self.assertEqual(server.key_value_service().get(weather_cache.FAILURE_KEY), "")

    def test_athlete_context_location_change_clears_weather_caches(self):
        server.profile_service().save({"weather_location": "Berlin"})
        server.key_value_service().set(weather_cache.CACHE_KEY, json.dumps({"query": "Berlin", "forecast": {}}))
        server.key_value_service().set(weather_cache.FAILURE_KEY, json.dumps({"count": 2, "retry_at": "2099-01-01T00:00:00+00:00"}))
        server.athlete_context_service().save({"weather_location": "Koeln"}, [])
        self.assertEqual(server.key_value_service().get(weather_cache.CACHE_KEY), "")
        self.assertEqual(server.key_value_service().get(weather_cache.FAILURE_KEY), "")

    def test_local_weather_state_does_not_fetch_without_complete_plan_state(self):
        server.profile_service().save({"weather_location": "Berlin"})
        with patch.object(weather_provider.WeatherClient, "fetch", side_effect=AssertionError("weather must stay local")):
            weather = server.public_weather_state_service().state(local_only=True)
        self.assertTrue(weather["configured"])
        self.assertTrue(weather["loading"])

    def test_weather_background_sync_refreshes_and_reuses_three_hour_cache(self):
        server.profile_service().save({"weather_location": "Berlin"})
        forecast = {
            "query": "Berlin",
            "location": {"name": "Berlin", "country": "Deutschland"},
            "model": "ECMWF",
            "forecast": {"daily": {"time": []}, "hourly": {"time": []}},
            "fetched_at": server.utc_now(),
        }
        with patch.object(weather_provider.WeatherClient, "fetch", return_value=forecast) as fetch:
            first = server.weather_sync_service().sync("test")
            second = server.weather_sync_service().sync("test")
            manual = server.weather_sync_service().sync("manuell", force=True)
        self.assertEqual(first["status"], "ok")
        self.assertEqual(second["status"], "ok")
        self.assertEqual(manual["status"], "ok")
        self.assertEqual(fetch.call_count, 2)
        fetch.assert_called_with("Berlin")

    def test_weather_failure_uses_exponential_negative_cache_until_forced(self):
        server.profile_service().save({"weather_location": "Berlin"})
        forecast = {
            "query": "Berlin",
            "location": {"name": "Berlin", "country": "Deutschland"},
            "model": "ECMWF",
            "forecast": {"daily": {"time": []}, "hourly": {"time": []}},
            "fetched_at": server.utc_now(),
        }
        with patch.object(weather_provider.WeatherClient, "fetch", side_effect=[server.AppError(503, "upstream"), forecast]) as fetch:
            first = server.weather_service().state(refresh=True)
            second = server.weather_service().state(refresh=True)
            forced = server.weather_service().state(refresh=True, force=True)
        self.assertEqual(fetch.call_count, 2)
        self.assertIn("Wetterdaten", first["error"])
        self.assertIn("noch nicht erneut", second["error"])
        self.assertEqual(forced["fetched_at"], forecast["fetched_at"])
        self.assertEqual(server.key_value_service().get(weather_cache.FAILURE_KEY), "")

    def test_weather_refresh_rechecks_adaptive_planning(self):
        server.profile_service().save({"weather_location": "Berlin"})
        forecast = {
            "query": "Berlin",
            "location": {"name": "Berlin", "country": "Deutschland"},
            "model": "ECMWF",
            "forecast": {"daily": {"time": []}, "hourly": {"time": []}},
            "fetched_at": server.utc_now(),
        }
        with patch.object(weather_provider.WeatherClient, "fetch", return_value=forecast), patch.object(
            server.AdaptiveReplanPreviewService,
            "preview",
            return_value={"changes": [{"id": "change-1"}]},
        ) as preview:
            result = server.weather_sync_service().sync("test")
        preview.assert_called_once_with()
        self.assertTrue(result["needs_replan"])
        self.assertEqual(result["replan_changes"], 1)

    def test_coach_context_reads_weather_cache_without_refreshing_it(self):
        server.profile_service().save({"weather_location": "Berlin"})
        server.key_value_service().set(weather_cache.CACHE_KEY, json.dumps({
            "query": "Berlin",
            "location": {"name": "Berlin", "country": "Deutschland"},
            "forecast": {"daily": {"time": []}, "hourly": {"time": []}},
            "fetched_at": "2000-01-01T00:00:00+00:00",
        }))
        with patch.object(weather_provider.WeatherClient, "fetch", side_effect=AssertionError("coach context must not refresh weather")):
            context = server.coach_structured_context_service().build({"recent_activities": [], "recent_wellness": [], "upcoming_calendar": []})
        self.assertEqual(context["weather"]["fetched_at"], "2000-01-01T00:00:00+00:00")

    def test_daily_planning_context_combines_checkin_recovery_weather_and_appointments(self):
        today = server.ATHLETE_CLOCK.now().date().isoformat()
        server.sync_state_repository().save_snapshot({
            "synced_at": "2026-08-31T08:00:00+00:00",
            "athlete": {},
            "recent_activities": [],
            "recent_wellness": [{"id": today, "sleepSecs": 25200, "sleepScore": 74, "readiness": 61}],
            "upcoming_calendar": [{"id": "planned-1", "name": "Intervalle", "start_date_local": f"{today}T09:00:00", "moving_time": 3600}],
        })
        server.checkin_service().save(
            {
                "checkin_date": today,
                "soreness": 6,
                "day_form": "Schwere Beine",
                "illness": "Erkältung",
                "available_minutes": 45,
                "notes": "Nur locker möglich",
            }
        )
        server.key_value_service().set("garmin_snapshot", json.dumps({
            "sleep": [{"calendarDate": today, "sleepTimeSeconds": 28800, "sleepScore": 82}],
            "hrv": [{"calendarDate": today, "lastNightAvg": 48}],
            "readiness": [{"calendarDate": today, "trainingReadinessScore": 55}],
            "daily_stats": [{"calendarDate": today, "totalSteps": 9876, "floorsAscended": 12, "totalKilocalories": 2345}],
        }))
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO external_calendar_events(id, uid, name, event_date, start_local, end_local, duration_minutes, all_day, training_relevant, no_intensity, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("appointment-1", "uid-1", "Familientermin", today, f"{today}T18:00:00", f"{today}T20:00:00", 120, 0, 1, 0, server.utc_now()),
            )
        context = server.daily_planning_context_service().build(
            server.sync_state_repository().latest_snapshot(),
            server.sync_state_repository().latest_snapshot()["upcoming_calendar"],
            {"days": [{"date": today, "weather_code": 63, "condition": "Regen", "temperature_min": 8, "temperature_max": 13}]},
        )
        day = next(item for item in context if item["date"] == today)
        self.assertEqual(day["checkin"]["available_minutes"], 45)
        self.assertEqual(day["checkin"]["day_form"], "Schwere Beine")
        self.assertEqual(day["checkin"]["illness"], "Erkältung")
        self.assertEqual(day["recovery"]["sleep_hours"], 8.0)
        self.assertEqual(day["recovery"]["hrv"], 48)
        self.assertEqual(day["recovery"]["sources"]["hrv"], "Garmin Connect")
        self.assertEqual(day["health"], {"steps": 9876, "floors": 12, "calories": 2345, "source": "Garmin Connect"})
        self.assertEqual(day["weather"]["condition"], "Regen")
        self.assertEqual(day["appointments"][0]["name"], "Familientermin")

    def test_settings_do_not_render_calendar_events_or_public_competition_import(self):
        markup = (server.PUBLIC_DIR / "index.html").read_text(encoding="utf-8")
        app = (server.PUBLIC_DIR / "app.js").read_text(encoding="utf-8")
        backend = Path(server.__file__).read_text(encoding="utf-8")
        self.assertNotIn('id="externalCalendarEvents"', markup)
        self.assertNotIn("Wettkampfkalender importieren", markup)
        self.assertNotIn("publicCalendarImportForm", app)
        self.assertNotIn("/api/calendar/import", backend)
        self.assertNotIn("import_public_calendar", backend)
        self.assertNotIn("renderExternalCalendarMarker", app)

    def test_external_calendar_keeps_last_good_events_on_invalid_feed(self):
        today = server.ATHLETE_CLOCK.now().date().isoformat()
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO external_calendar_events(id, uid, name, event_date, start_local, end_local, duration_minutes, all_day, training_relevant, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("good-event", "good-event", "Good event", today, today + "T10:00:00+02:00", today + "T11:00:00+02:00", 60, 0, 1, server.utc_now()),
            )
        with patch.object(server, "CONFIG", replace(server.CONFIG, calendar_ical_url="https://calendar.example/feed.ics")), patch.object(
            calendar_provider, "external_calendar_url", return_value="https://calendar.example/feed.ics"
        ), patch.object(calendar_provider, "fetch_calendar_feed", return_value=b"not an ical feed"):
            with self.assertRaises(server.AppError):
                server.external_calendar_sync_service().sync("test")
        self.assertEqual(
            server.external_calendar_reader().list_events(1000)[0]["id"],
            "good-event",
        )

    def test_ical_no_training_marker_is_excluded_from_adaptive_constraints(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO external_calendar_events(id, uid, name, event_date, start_local, end_local, duration_minutes, all_day, training_relevant, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("info-only", "info-only", "Informational event", tomorrow, tomorrow + "T10:00:00+02:00", tomorrow + "T13:00:00+02:00", 180, 0, 0, server.utc_now()),
            )
        self.assertEqual(
            server.external_calendar_reader().list_events(
                1000, training_relevant_only=True
            ),
            [],
        )

    def test_ical_no_intensity_marker_requires_easy_replacement(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        draft = server.local_plan_creation_service().save([{
            "date": tomorrow, "sport": "Ride", "name": "Short threshold",
            "description": "- 5m 110%\n- 40m 55%", "duration_minutes": 45, "target": "POWER",
        }])[0]
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO external_calendar_events(id, uid, name, event_date, start_local, end_local, duration_minutes, all_day, training_relevant, no_intensity, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("no-intensity", "family-no-intensity", "Evening event", tomorrow, tomorrow + "T18:00:00+02:00", tomorrow + "T18:30:00+02:00", 30, 0, 1, 1, server.utc_now()),
            )
        preview = server.adaptive_replan_preview_service().preview()
        self.assertEqual(preview["changes"][0]["library_workout_id"], draft["id"])
        self.assertIn("NO_INTENSITY", preview["changes"][0]["after"]["rationale"])
        self.assertTrue(preview["changes"][0]["payload"]["private_calendar_adjustment"]["no_intensity_requested"])

    def test_external_calendar_sync_keeps_url_server_side_and_replaces_events(self):
        payload = (
            b"BEGIN:VCALENDAR\r\nBEGIN:VEVENT\r\nUID:family-2\r\nDTSTART:20260902T100000Z\r\n"
            b"DTEND:20260902T120000Z\r\nSUMMARY:School meeting\r\nDESCRIPTION: [NO_INTENSITY]\r\nEND:VEVENT\r\n"
            b"BEGIN:VEVENT\r\nUID:unmarked\r\nDTSTART:20260903T100000Z\r\n"
                b"DTEND:20260903T120000Z\r\nSUMMARY:Unmarked\r\nDESCRIPTION:[NO_TRAINING]\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n"
        )
        config = replace(server.CONFIG, calendar_ical_url="https://93.184.216.34/family.ics")
        preview_service = Mock()
        preview_service.preview.return_value = {
            "changes": [{"id": "change-1"}, {"id": "change-2"}]
        }
        with patch.object(server, "CONFIG", config), patch.object(calendar_provider, "fetch_calendar_feed", return_value=payload) as fetch, patch.object(
            server.ATHLETE_CLOCK, "now", return_value=datetime(2026, 9, 2, tzinfo=timezone.utc)
        ), patch.object(
            server, "adaptive_replan_preview_service", return_value=preview_service
        ):
            result = server.external_calendar_sync_service().sync("test")
            self.assertEqual(result["events"], 2)
            self.assertTrue(result["needs_replan"])
            self.assertEqual(result["replan_changes"], 2)
            preview_service.preview.assert_called_once_with()
            state = server.external_calendar_reader().state(
                configured=True,
                running=False,
                window_days=calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS,
            )
            self.assertTrue(state["configured"])
            self.assertNotIn("url", state)
            self.assertEqual(state["events"][0]["duration_minutes"], 120)
            self.assertEqual(state["events"][0]["short_only"], 0)
            self.assertEqual(
                [
                    event["uid"]
                    for event in server.external_calendar_reader().list_events(
                        1000, training_relevant_only=True
                    )
                ],
                ["family-2"],
            )
            self.assertFalse(state["events"][1]["training_relevant"])
            fetch.assert_called_once_with(config.calendar_ical_url, app_version=server.APP_VERSION)

    def test_external_calendar_sync_limits_events_to_eight_weeks(self):
        today = server.ATHLETE_CLOCK.now().date()
        in_window = today + timedelta(days=calendar_provider.EXTERNAL_CALENDAR_WINDOW_DAYS)
        outside_window = in_window + timedelta(days=1)
        payload = (
            "BEGIN:VCALENDAR\r\n"
            f"BEGIN:VEVENT\r\nUID:in-window\r\nDTSTART;VALUE=DATE:{in_window.strftime('%Y%m%d')}\r\nSUMMARY:Within window\r\nDESCRIPTION:[SHORT_ONLY]\r\nEND:VEVENT\r\n"
            f"BEGIN:VEVENT\r\nUID:outside-window\r\nDTSTART;VALUE=DATE:{outside_window.strftime('%Y%m%d')}\r\nSUMMARY:Outside window\r\nEND:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        ).encode()
        config = replace(server.CONFIG, calendar_ical_url="https://93.184.216.34/family.ics")
        with patch.object(server, "CONFIG", config), patch.object(calendar_provider, "fetch_calendar_feed", return_value=payload):
            result = server.external_calendar_sync_service().sync("test")

        self.assertEqual(result["window_days"], 56)
        self.assertEqual(result["events"], 1)
        self.assertEqual(
            server.external_calendar_reader().list_events()[0]["uid"], "in-window"
        )

    def test_external_calendar_sync_keeps_last_successful_events_on_failure(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO external_calendar_events(id, uid, name, event_date, start_local, end_local, duration_minutes, all_day, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("event-old", "family-old", "Existing appointment", tomorrow, tomorrow + "T10:00:00+02:00", tomorrow + "T11:00:00+02:00", 60, 0, server.utc_now()),
            )
        config = replace(server.CONFIG, calendar_ical_url="https://93.184.216.34/family.ics")
        with patch.object(server, "CONFIG", config), patch.object(calendar_provider, "fetch_calendar_feed", side_effect=server.AppError(502, "upstream unavailable")):
            with self.assertRaises(server.AppError):
                server.external_calendar_sync_service().sync("test")
        self.assertEqual(
            server.external_calendar_reader().list_events()[0]["id"], "event-old"
        )

    def test_external_calendar_event_reduces_hard_or_long_local_draft_only_in_preview(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        draft = server.local_plan_creation_service().save([{
            "date": tomorrow, "sport": "Ride", "name": "Threshold intervals",
            "description": "- 5m 110%\n- 115m 55%", "duration_minutes": 120, "target": "POWER",
        }])[0]
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO external_calendar_events(id, uid, name, event_date, start_local, end_local, duration_minutes, all_day, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("event-1", "family-3", "Family appointment", tomorrow, tomorrow + "T10:00:00+02:00", tomorrow + "T13:00:00+02:00", 180, 0, server.utc_now()),
            )
        preview = server.adaptive_replan_preview_service().preview()
        self.assertEqual(preview["changes"][0]["library_workout_id"], draft["id"])
        self.assertEqual(preview["changes"][0]["after"]["duration_minutes"], 60)
        adjustment = preview["changes"][0]["payload"]["private_calendar_adjustment"]
        self.assertEqual(adjustment["label"], "Aufgrund privater Termine angepasst")
        self.assertEqual(adjustment["original_duration_minutes"], 120)
        self.assertEqual(adjustment["adjusted_duration_minutes"], 60)
        self.assertEqual(server.planned_unit_service().list()[0]["moving_time"], 120 * 60)

    def test_planned_unit_preserves_private_calendar_adjustment(self):
        context = {
            "label": "Aufgrund privater Termine angepasst",
            "reason": "family calendar has one event",
            "original_duration_minutes": 120,
            "adjusted_duration_minutes": 60,
            "intensity_adjusted": True,
        }
        planned = planning_planned_units.normalize_planned_unit({
            "date": (date.today() + timedelta(days=1)).isoformat(),
            "sport": "Ride",
            "name": "Locker",
            "description": "- 60m 60% easy",
            "duration_minutes": 60,
            "private_calendar_adjustment": context,
        })
        self.assertEqual(planned["private_calendar_adjustment"], context)

    def test_adaptive_replan_persists_private_calendar_context_after_apply(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        draft = server.local_plan_creation_service().save([{
            "date": tomorrow, "sport": "Ride", "name": "Threshold intervals",
            "description": "- 5m 110%\n- 115m 55%", "duration_minutes": 120, "target": "POWER",
        }])[0]
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO external_calendar_events(id, uid, name, event_date, start_local, end_local, duration_minutes, all_day, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("event-2", "family-4", "Family appointment", tomorrow, tomorrow + "T10:00:00+02:00", tomorrow + "T13:00:00+02:00", 180, 0, server.utc_now()),
            )
        preview = server.adaptive_replan_preview_service().preview()
        server.illness_pause_sync_service().apply(preview["id"])
        persisted = server.planned_unit_service().list()[0]["private_calendar_adjustment"]
        self.assertEqual(persisted["label"], "Aufgrund privater Termine angepasst")
        self.assertEqual(persisted["events"][0]["name"], "Family appointment")
        self.assertEqual(server.planned_unit_service().list()[0]["id"], draft["id"])

    def test_training_calendar_adds_unplanned_completed_activities_without_duplicating_matches(self):
        today = date(2026, 8, 26)
        planned = [{
            "id": "event-1", "category": "WORKOUT", "type": "Ride", "name": "Plan",
            "start_date_local": f"{today.isoformat()}T00:00:00", "moving_time": 3600,
        }]
        activities = [
            {
                "id": "matched", "paired_event_id": "event-1", "type": "Ride", "name": "Plan gefahren",
                "start_date_local": f"{today.isoformat()}T07:00:00", "moving_time": 3500,
                "distance": 30000, "icu_training_load": 45, "icu_rpe": 5,
            },
            {
                "id": "extra", "type": "Run", "name": "Zusätzlicher Lauf",
                "start_date_local": f"{today.isoformat()}T18:00:00", "moving_time": 1800,
                "distance": 5000, "icu_training_load": 30, "icu_rpe": 7,
            },
        ]

        with patch.object(server.ATHLETE_CLOCK, "now", return_value=datetime(2026, 8, 26, 20, 0)):
            enriched, _ = activity_calendar_projection.planning_compliance_state(
                planned, activities, today
            )
        calendar = activity_calendar_projection.training_calendar_items(
            enriched, activities
        )

        self.assertEqual(len(calendar), 2)
        self.assertEqual(calendar[0]["compliance"]["actual_activity"]["id"], "matched")
        self.assertEqual(sum(item.get("id") == "matched" for item in calendar), 0)
        self.assertEqual(calendar[1]["id"], "extra")
        self.assertTrue(calendar[1]["is_completed_activity"])
        self.assertEqual(calendar[1]["calendar_entry_type"], "completed_activity")
        self.assertEqual(calendar[1]["icu_rpe"], 7)

    def test_plan_state_returns_enriched_training_calendar(self):
        today = date(2026, 8, 26)
        planned = [{
            "id": "event-1", "category": "WORKOUT", "type": "Run", "name": "Tempolauf",
            "start_date_local": f"{today.isoformat()}T00:00:00", "moving_time": 2400,
        }]
        snapshot = {
            "synced_at": "2026-08-26T10:00:00+00:00",
            "recent_activities": [{
                "id": "activity-1", "paired_event_id": "event-1", "type": "Run", "name": "Tempolauf erledigt",
                "start_date_local": f"{today.isoformat()}T07:00:00", "moving_time": 2280,
                "distance": 7000, "icu_training_load": 55, "icu_rpe": 8,
            }],
        }
        with (
            patch.object(
                server.SyncStateRepository,
                "latest_snapshot",
                return_value=snapshot,
            ),
            patch.object(
                server.planning_planned_unit_service.PlannedUnitService,
                "list",
                return_value=planned,
            ),
            patch.object(server.weather_service(), "state", return_value={"days": []}),
            patch.object(server.ATHLETE_CLOCK, "now", return_value=datetime(2026, 8, 26, 12, 0)),
        ):
            result = server.public_plan_state_service().read(local_only=True)

        self.assertEqual(result["planned"][0]["compliance"]["status"], "completed")
        self.assertEqual(result["training_calendar"][0]["compliance"]["actual_activity"]["icu_rpe"], 8)
        self.assertIsInstance(result["planning_compliance"], list)

    def test_canonical_planning_view_merges_sources_and_exposes_identity(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        local = server.planned_unit_service().create({
            "date": tomorrow, "sport": "Ride", "name": "Lokales Tempo",
            "description": "- 30m 85%", "duration_minutes": 30,
            "source": "library", "rationale": "Test",
        })
        remote = {
            "id": "remote-event-1", "external_id": "intervals-coach-library-1",
            "category": "WORKOUT", "type": "Ride", "name": "Lokales Tempo",
            "start_date_local": tomorrow + "T07:00:00", "moving_time": 1800,
        }
        independent = {
            "id": "remote-event-2", "category": "WORKOUT", "type": "Run", "name": "Remote Lauf",
            "start_date_local": tomorrow + "T08:00:00", "moving_time": 1200,
        }
        view = calendar_canonical.canonical_planned_workouts([remote, independent], [local])
        self.assertEqual(len(view), 3)
        local_row = next(row for row in view if row.get("local_id") == local["id"])
        self.assertEqual(local_row["sync_source"], "local")
        self.assertEqual(local_row["sync_status"], "local")
        self.assertFalse(local_row["is_remote"])
        self.assertIsNone(local_row["remote_id"])
        remote_row = next(row for row in view if row.get("remote_id") == "remote-event-2")
        self.assertEqual(remote_row["sync_source"], "intervals")
        self.assertFalse(remote_row["is_local"])

        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            payload = json.loads(db.execute("SELECT payload FROM planned_units WHERE local_id=?", (local["id"],)).fetchone()["payload"])
            payload["remote_event_id"] = "remote-event-1"
            db.execute("UPDATE planned_units SET payload=? WHERE local_id=?", (json.dumps(payload), local["id"]))
        merged = calendar_canonical.canonical_planned_workouts(
            [remote, independent], server.planned_unit_service().list()
        )
        joined = next(row for row in merged if row.get("local_id") == local["id"])
        self.assertEqual(joined["sync_source"], "local+intervals")
        self.assertEqual(joined["remote_id"], "remote-event-1")
        self.assertEqual(sum(row.get("remote_id") == "remote-event-1" for row in merged), 1)

    def test_non_relevant_external_events_are_stored_but_not_in_canonical_calendar_or_coach(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        with server.DB_LOCK, server.database_manager().unit_of_work() as db:
            db.execute(
                "INSERT INTO external_calendar_events(id, uid, name, event_date, start_local, end_local, duration_minutes, all_day, training_relevant, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("external-relevant", "relevant", "Family appointment", tomorrow, tomorrow + "T10:00:00+02:00", tomorrow + "T11:00:00+02:00", 60, 0, 1, server.utc_now()),
            )
            db.execute(
                "INSERT INTO external_calendar_events(id, uid, name, event_date, start_local, end_local, duration_minutes, all_day, training_relevant, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("external-irrelevant", "irrelevant", "Private note", tomorrow, tomorrow + "T12:00:00+02:00", tomorrow + "T13:00:00+02:00", 60, 0, 0, server.utc_now()),
            )
        calendar = calendar_local.local_calendar_events(
            [], [], server.external_calendar_reader().list_events()
        )
        self.assertEqual([item["id"] for item in calendar], ["external-relevant"])
        context = server.daily_planning_context_service().build(
            {},
            [],
            {},
            [],
            server.external_calendar_reader().list_events(
                training_relevant_only=True
            ),
        )
        self.assertEqual([item["id"] for item in context[0]["appointments"]], ["external-relevant"])

    def test_workout_payload_is_an_idempotent_calendar_event(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        payload = planning_workouts.workout_event_payload("abc", {
            "date": tomorrow,
            "sport": "Ride",
            "name": "Tempo",
            "description": "- 10m 55%\n- 20m 85%\n- 10m 55%",
            "duration_minutes": 40,
            "target": "POWER",
        }, today=server.ATHLETE_CLOCK.now().date())
        self.assertEqual(payload["category"], "WORKOUT")
        self.assertEqual(payload["moving_time"], 2400)
        self.assertEqual(payload["external_id"], "intervals-coach-abc")
        self.assertTrue(payload["start_date_local"].endswith("T00:00:00"))

    def test_calendar_conflict_is_detected_before_push(self):
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        server.remote_planned_unit_reconciler().reconcile([{"id": "existing", "name": "Existing", "category": "WORKOUT", "type": "Ride", "start_date_local": tomorrow + "T08:00:00", "moving_time": 3600}])
        self.assertEqual(server.calendar_conflict_service().conflicts({"date": tomorrow})[0]["name"], "Existing")

    def test_calendar_conflicts_use_time_windows_when_both_events_are_timed(self):
        day = (date.today() + timedelta(days=2)).isoformat()
        server.remote_planned_unit_reconciler().reconcile([{"id": "later", "name": "Later", "category": "WORKOUT", "type": "Ride", "start_date_local": day + "T12:00:00", "moving_time": 1800}])
        self.assertEqual(server.calendar_conflict_service().conflicts({"date": day, "start_date_local": day + "T08:00:00", "duration_minutes": 60}), [])
        conflict = server.calendar_conflict_service().conflicts({"date": day, "start_date_local": day + "T12:15:00", "duration_minutes": 30})[0]
        self.assertEqual(conflict["name"], "Later")
        self.assertEqual(conflict["match"], "time_window")

    def test_calendar_conflicts_ignore_archived_planned_units(self):
        day = (date.today() + timedelta(days=4)).isoformat()
        existing = server.planned_unit_service().create({
            "date": day, "sport": "Run", "name": "Archived", "description": "- 20m 60% easy",
        })
        server.planned_unit_service().update(existing["id"], {"action": "archive"})
        self.assertEqual(server.calendar_conflict_service().conflicts({"date": day}), [])

    def test_calendar_conflicts_include_local_competitions_with_date_fallback(self):
        day = (date.today() + timedelta(days=3)).isoformat()
        server.athlete_context_service().save({}, [{"name": "Local Race", "event_date": day, "sport": "Cycling", "start_date_local": day + "T10:00:00", "moving_time": 7200}])
        conflict = server.calendar_conflict_service().conflicts({"date": day})[0]
        self.assertEqual(conflict["source"], "local_competition")
        self.assertEqual(conflict["match"], "date")

    def test_library_upload_uses_single_workout_endpoint_and_canonical_sport(self):
        client = server.intervals_client(replace(server.CONFIG, intervals_api_key="test-key", intervals_athlete_id="athlete-1"))
        with patch.object(client, "get", return_value=[]), patch.object(
            client, "post", side_effect=[{"id": 12345}, {"id": "remote-1"}]
        ) as post:
            result = client.create_library_workouts([{
                "name": "Tempo",
                "description": "- 30m 85%",
                "sport": "Cycling",
            }])
        self.assertEqual(result, [{"id": "remote-1"}])
        self.assertEqual(post.call_args_list[0].args, (
            "/athlete/athlete-1/folders",
            {"name": "Intervals Coach"},
        ))
        self.assertEqual(post.call_args_list[1].args, (
            "/athlete/athlete-1/workouts",
            {"name": "Tempo", "description": "- 30m 85%", "type": "Ride", "folder_id": 12345, "target": "AUTO"},
        ))

    def test_recovery_plain_extension_note_survives_library_and_calendar_export(self):
        description = "Optional bis insgesamt 8km verlaengern.\n\n- 6km Z1 HR"
        workout = {
            "type": "Run", "description": description, "name": "Recovery 6-8km",
            "duration_minutes": 40, "moving_time": 2400,
        }
        client = server.intervals_client()
        with patch.object(client, "get_or_create_workout_folder", return_value=1), \
                patch.object(client, "post", return_value={"id": "synthetic"}) as post, \
                patch.object(client, "put", return_value={"id": "synthetic"}) as put:
            client.create_library_workouts([workout])
            self.assertEqual(post.call_args.args[1]["description"], description)
            client.update_library_workout("synthetic", workout)
            self.assertEqual(put.call_args.args[1]["description"], description)
            post.return_value = [{"id": "synthetic-event", **parsed_workout_fixture(2400, sport="Run", kind="hr", units="hr_zone", value=1, distance=6000)}]
            client.plan_library_workout("synthetic", workout, (date.today() + timedelta(days=1)).isoformat())
            payload = post.call_args.args[1][0]
            self.assertEqual(payload["description"], description)
            self.assertEqual(payload["moving_time"], 2400)

    def test_unparsed_calendar_export_is_not_marked_synced_and_retry_reuses_identity(self):
        entry = server.local_plan_creation_service().save([{
            "date": (date.today() + timedelta(days=1)).isoformat(), "sport": "Ride",
            "name": "Synthetic", "description": "- 30m 85%", "duration_minutes": 30,
        }])[0]
        with patch.object(intervals_client_module.IntervalsClient, "upsert_calendar_events", side_effect=[
            [{"id": "synthetic-event", "workout_doc": {"steps": []}}],
            [{"id": "synthetic-event", **parsed_workout_fixture()}],
        ]) as upsert:
            with self.assertRaises(server.AppError):
                server.planned_calendar_sync_service().sync_entry(entry["id"])
            failed = server.planned_unit_service().list()[0]
            self.assertEqual(failed["sync_status"], "sync_error")
            self.assertEqual(failed["remote_event_id"], "synthetic-event")
            server.planned_calendar_sync_service().sync_entry(entry["id"])
            self.assertEqual(server.planned_unit_service().list()[0]["sync_status"], "synced")
            self.assertEqual(upsert.call_args_list[0].args[0][0]["external_id"], upsert.call_args_list[1].args[0][0]["external_id"])

    def test_historical_garmin_collection_excludes_recovery_and_current_metrics(self):
        from backend.providers.garmin import GarminCollectionOptions, collect_garmin_data

        class FakeGarmin:
            def get_activities_by_date(self, start, end):
                return [{"start": start, "end": end}]

            def __getattr__(self, name):
                raise AssertionError(f"historical collector called {name}")

        result = collect_garmin_data(
            FakeGarmin(),
            [(date(2026, 1, 1), date(2026, 3, 31))],
            start=date(2026, 1, 1),
            today=date(2026, 3, 31),
            synced_at="2026-09-01T00:00:00+00:00",
            external_call=lambda _service, _source, operation, _details: operation(),
            redact=lambda value: value,
            options=GarminCollectionOptions(include_recovery=False, include_current_metrics=False),
        )

        self.assertEqual(len(result["activities"]), 1)
        self.assertNotIn("sleep", result)
        self.assertNotIn("body_battery", result)
        self.assertEqual(set(result["provider_sync"]["pagination"]), {"activities"})

    def test_library_plan_ignores_stale_provider_calendar_until_imported(self):
        server.workout_library_remote_reconciler().reconcile([{
            "id": 43, "name": "Tempo", "type": "Ride",
            "description": "- 30m 85%", "moving_time": 1800,
        }])
        library = server.workout_library_service().list()[0]
        tomorrow = (date.today() + timedelta(days=1)).isoformat()
        server.sync_state_repository().save_snapshot({
            "synced_at": "now", "athlete": {}, "recent_activities": [], "recent_wellness": [],
            "upcoming_calendar": [{"id": "remote-event", "name": "Bereits geplant", "start_date_local": tomorrow + "T09:00:00"}],
        })
        result = server.workout_library_plan_service().apply([{
            "library_workout_id": library["id"], "date": tomorrow,
        }])
        self.assertEqual(result["status"], "local")
        self.assertEqual(len(server.workout_library_service().list()), 1)
        self.assertEqual(len(server.planned_unit_service().list()), 1)

    def test_coach_intervals_context_limits_activities_and_excludes_past_calendar(self):
        today = server.ATHLETE_CLOCK.now().date()
        activities = [
            {"id": f"ride-{index}", "type": "Ride", "name": f"Ride {index}", "start_date_local": (today - timedelta(days=index)).isoformat(), "moving_time": 3600, "icu_training_load": 50}
            for index in range(7)
        ] + [
            {"id": f"run-{index}", "type": "Run", "name": f"Run {index}", "start_date_local": (today - timedelta(days=index)).isoformat(), "moving_time": 1800, "icu_training_load": 25}
            for index in range(6)
        ]
        snapshot = {
            "synced_at": "now",
            "athlete": {},
            "recent_activities": activities,
            "recent_wellness": [],
            "upcoming_calendar": [
                {"id": "past", "name": "Past workout", "start_date_local": (today - timedelta(days=1)).isoformat()},
                {"id": "future", "name": "Future workout", "start_date_local": (today + timedelta(days=1)).isoformat(), "description": "- 60m 65%"},
            ],
        }
        server.planned_unit_service().create({
            "date": (today + timedelta(days=1)).isoformat(), "sport": "Ride",
            "name": "Future workout", "description": "- 60m 65%", "duration_minutes": 60,
        })
        result = CoachIntervalsContextService().project(
            snapshot, server.planned_unit_service().list(250, future_only=True), today
        )
        self.assertEqual([item["name"] for item in result["recent_activities_by_sport"]["Radfahren"]], [f"Ride {index}" for index in range(5)])
        self.assertEqual([item["name"] for item in result["recent_activities_by_sport"]["Laufen"]], [f"Run {index}" for index in range(5)])
        self.assertEqual([item["name"] for item in result["planned_workouts"]], ["Future workout"])
        self.assertEqual(result["activity_rollups_by_sport"]["Radfahren"]["last_7_days"]["sessions"], 7)

    def test_calendar_display_settings_are_persisted_and_validated(self):
        self.assertEqual(server.SETTINGS.calendar_display_settings(), {"past_weeks": 1, "future_weeks": 4})
        self.assertEqual(
            server.SETTINGS.save_calendar_display_settings({"past_weeks": 3, "future_weeks": 12}),
            {"status": "ok", "past_weeks": 3, "future_weeks": 12},
        )
        self.assertEqual(server.SETTINGS.calendar_display_settings(), {"past_weeks": 3, "future_weeks": 12})
        with self.assertRaises(server.AppError):
            server.SETTINGS.save_calendar_display_settings({"past_weeks": -1})
        with self.assertRaises(server.AppError):
            server.SETTINGS.save_calendar_display_settings({"future_weeks": 53})
        server.key_value_service().set("calendar_display_past_weeks", "invalid")
        self.assertEqual(server.SETTINGS.calendar_display_settings()["past_weeks"], 1)

    def test_explicit_plan_push_records_a_remote_calendar_write(self):
        recorder = IntervalsRequestRecorder()
        client = RecordedIntervalsClient(recorder)
        with patch.object(server, "intervals_client", return_value=client):
            result = server.workout_library_sync_service().plan_remote(
                "remote-workout-1",
                {"name": "Planned", "type": "Ride"},
                (date.today() + timedelta(days=1)).isoformat(),
            )
        self.assertEqual(result["id"], "remote-planned-event")
        self.assertEqual([call["method"] for call in recorder.mutations], ["POST"])

    def test_weather_shows_fourteen_days_and_recommends_outdoor_time_for_five_days(self):
        today = server.ATHLETE_CLOCK.now().date()
        daily_dates = [(today + timedelta(days=offset)).isoformat() for offset in range(14)]
        hourly_times = []
        hourly_precipitation = []
        for day_offset, day in enumerate(daily_dates):
            for hour in range(24):
                hourly_times.append(f"{day}T{hour:02d}:00")
                hourly_precipitation.append(5 if day_offset == 1 and hour in (16, 17) else 70)
        forecast = {
            "daily": {
                "time": daily_dates,
                "weather_code": [1] * 14,
                "temperature_2m_min": [10] * 14,
                "temperature_2m_max": [20] * 14,
                "apparent_temperature_min": [9] * 14,
                "apparent_temperature_max": [19] * 14,
                "precipitation_probability_max": [70] * 14,
                "rain_sum": [1] * 14,
                "showers_sum": [0] * 14,
                "snowfall_sum": [0] * 14,
                "wind_speed_10m_max": [15] * 14,
                "wind_gusts_10m_max": [25] * 14,
                "wind_direction_10m_dominant": [225] * 14,
                "sunrise": [f"{day}T06:00" for day in daily_dates],
                "sunset": [f"{day}T20:00" for day in daily_dates],
            },
            "hourly": {
                "time": hourly_times,
                "temperature_2m": [18] * len(hourly_times),
                "apparent_temperature": [18] * len(hourly_times),
                "precipitation_probability": hourly_precipitation,
                "rain": [0] * len(hourly_times),
                "showers": [0] * len(hourly_times),
                "snowfall": [0] * len(hourly_times),
                "weather_code": [1] * len(hourly_times),
                "wind_speed_10m": [15] * len(hourly_times),
                "wind_direction_10m": [225] * len(hourly_times),
                "wind_gusts_10m": [25] * len(hourly_times),
            },
        }
        tomorrow = (today + timedelta(days=1)).isoformat()
        day_six = (today + timedelta(days=6)).isoformat()
        planned = [
            {"id": "ride-1", "name": "Lange Ausfahrt", "type": "Ride", "start_date_local": tomorrow + "T09:00:00", "moving_time": 7200},
            {"id": "indoor-1", "name": "Trainer", "type": "VirtualRide", "start_date_local": tomorrow + "T18:00:00", "moving_time": 3600},
            {"id": "ride-2", "name": "Spätere Ausfahrt", "type": "Ride", "start_date_local": day_six + "T09:00:00", "moving_time": 3600},
        ]
        server.profile_service().save({"weather_location": "Münster"})
        with patch.object(server.provider_http_client(), "request", side_effect=[
            {"results": [{"name": "Münster", "country": "Deutschland", "country_code": "DE", "latitude": 51.96, "longitude": 7.63, "timezone": "Europe/Berlin"}]},
            forecast,
            forecast,
        ]) as weather_request:
            weather = server.weather_service().state(planned)
        self.assertEqual(len(weather["days"]), 14)
        self.assertEqual(weather["model"], "ICON-D2 (0–2 Tage) + ECMWF IFS HRES (3–14 Tage)")
        self.assertIn("models=ecmwf_ifs", weather_request.call_args_list[1].args[1])
        self.assertIn("models=icon_d2", weather_request.call_args_list[2].args[1])
        self.assertEqual(weather["days"][0]["wind_direction_dominant"], 225)
        self.assertEqual(len(weather["recommendations"]), 1)
        self.assertEqual(weather["recommendations"][0]["event_id"], "ride-1")
        self.assertTrue(weather["recommendations"][0]["suggested_time"].startswith("16:00"))
        expected_availability = "Wochenende" if date.fromisoformat(tomorrow).weekday() >= 5 else "nach der Arbeit"
        self.assertEqual(weather["recommendations"][0]["availability"], expected_availability)
        self.assertEqual(
            weather["days"][0]["icon"], weather_projection.WEATHER_ICONS[1]
        )
        enriched = weather_history.add_to_planned(
            planned,
            weather,
            default_name=server.PLANNED_WORKOUT_LABEL,
        )
        self.assertIn("weather_recommendation", enriched[0])
        self.assertNotIn("weather_recommendation", enriched[1])
        self.assertNotIn("weather_recommendation", enriched[2])

    def test_weather_recommendation_respects_weekday_work_and_friday_hours(self):
        monday = date(2026, 8, 31)
        friday = date(2026, 9, 4)

        def forecast_for(target, low_hours):
            times = [f"{target.isoformat()}T{hour:02d}:00" for hour in range(24)]
            precipitation = [5 if hour in low_hours else 80 for hour in range(24)]
            return {
                "hourly": {
                    "time": times,
                    "apparent_temperature": [18] * 24,
                    "precipitation_probability": precipitation,
                    "rain": [0] * 24,
                    "showers": [0] * 24,
                    "wind_speed_10m": [12] * 24,
                    "wind_gusts_10m": [20] * 24,
                    "wind_direction_10m": [180] * 24,
                    "weather_code": [1] * 24,
                }
            }

        monday_result = weather_recommendations.weather_recommendation(
            {"id": "monday", "type": "Ride", "start_date_local": f"{monday}T08:00:00", "moving_time": 7200},
            forecast_for(monday, {8, 9, 16, 17}),
        )
        self.assertEqual(monday_result["suggested_time"], "16:00–18:00 Uhr")
        self.assertEqual(monday_result["availability"], "nach der Arbeit")

        friday_result = weather_recommendations.weather_recommendation(
            {"id": "friday", "type": "Run", "start_date_local": f"{friday}T08:00:00", "moving_time": 3600},
            forecast_for(friday, {8, 14}),
        )
        self.assertEqual(friday_result["suggested_time"], "14:00–15:00 Uhr")
        self.assertEqual(friday_result["availability"], "nach der Arbeit")


if __name__ == "__main__":
    unittest.main()
