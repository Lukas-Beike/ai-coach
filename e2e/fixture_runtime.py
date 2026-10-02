"""Fresh SQLCipher runtime for local integration tests; all providers are blocked."""
import json
import os
import sys
from datetime import timedelta, datetime, timezone

# This file is mounted only in disposable test containers, never normal startup.
os.environ.update({
    "DATA_DIR": "/data/coach-fixture-data",
    "APP_PASSWORD": "e2e-fixture-password-1234",
    "OPENAI_API_KEY": "e2e-fixture-openai-key",
    "INTERVALS_API_KEY": "",
    "GARMIN_EMAIL": "",
    "GARMIN_PASSWORD": "",
    "GARMINTOKENS": "/data/fixture-no-tokens",
    "GARMIN_FIXTURE_PATH": "",
    "CALENDAR_ICAL_URL": "",
    "COOKIE_SECURE": "false",
})
sys.path.insert(0, "/app")
import server
from backend.http_api import auth as http_auth


def blocked_provider(*args, **kwargs):
    raise server.AppError(503, "Synthetic provider unavailable", reason="fixture_provider_unavailable")


server.provider_http.JsonHttpClient.request = blocked_provider


class FixtureConversationProvisionService:
    def ensure(self, *args, **kwargs):
        return "fixture-conversation"


server.COACH_CONVERSATION.provision_service = FixtureConversationProvisionService
# Browser scenarios deliberately poll and reload the single disposable fixture
# far more aggressively than one athlete does. Rate limiting has dedicated unit
# coverage; disable it here to keep unrelated UI scenarios order-independent.
http_auth.RATE_LIMITER.allow = lambda key, limit, window_seconds: (True, 0)


def fixture_coach_response(payload, **kwargs):
    """Canned model outputs exercise HTTP/worker/storage, not language inference."""
    value = payload.get("input")
    if isinstance(value, list):
        outputs = [json.loads(item["output"]) for item in value if item.get("type") == "function_call_output"]
        question = next((item.get("question") for item in outputs if item.get("question")), None)
        return {"output_text": question or "Deine Rückmeldung ist gespeichert."}
    decoded = json.loads(value)
    current_message = decoded.get("current_message")
    if current_message == "E2E fixture: OpenAI timeout":
        raise server.AppError(504, "Synthetic private provider detail", reason="provider_timeout")
    provider_failure_codes = {
        "E2E fixture: OpenAI credit balance exhausted": "credit_balance_exhausted",
        "E2E fixture: OpenAI model not found": "model_not_found",
        "E2E fixture: OpenAI access denied": "permission_denied",
    }
    if current_message in provider_failure_codes:
        return server.provider_state_service().validate_openai_response("/responses", {
            "status": "failed",
            "error": {"code": provider_failure_codes[current_message], "message": "Synthetic private provider detail"},
        })
    context = decoded["dialogue"]
    current_id = context["current_user_message_id"]
    if current_message in {"E2E nutrition: confirm meal", "E2E nutrition: half portion", "E2E nutrition: update meal", "E2E nutrition: delete meal", "E2E nutrition: database oats", "E2E nutrition: confirm database meal"}:
        nutrition = server.NUTRITION_ASSEMBLY.service()
        templates = nutrition.list_templates()
        if current_message == "E2E nutrition: confirm database meal":
            name = "save_nutrition_template"
            arguments = {"payload": {"name": "Database oats", "description": "50 g Haferflocken", "kcal": 999, "source": "coach", "food_ingredients": [{"food_id": "bls:C133000", "amount": 50, "unit": "g"}]}}
        elif current_message == "E2E nutrition: database oats":
            name = "save_nutrition_entry"
            arguments = {"payload": {"description": "50 g Haferflocken", "kcal": 999, "source": "coach", "food_ingredients": [{"food_id": "bls:C133000", "amount": 50, "unit": "g"}]}}
        elif current_message == "E2E nutrition: confirm meal":
            name = "save_nutrition_template"
            arguments = {"payload": {"name": "Fixture breakfast", "description": "80 g oats - <img src=x onerror=alert(1)>", "kcal": 400, "carbs_g": 60, "protein_g": 12, "fat_g": 8, "source": "coach"}}
        elif current_message == "E2E nutrition: half portion":
            name = "log_nutrition_template"
            arguments = {"id": templates[0]["id"], "portions": 0.5}
        elif current_message == "E2E nutrition: update meal":
            name = "save_nutrition_template"
            arguments = {"payload": {**templates[0], "kcal": 600}}
            arguments["payload"].pop("updated_at", None)
            arguments["payload"].pop("nutrition_basis", None)
        else:
            name = "delete_nutrition_template"
            arguments = {"id": templates[0]["id"]}
        arguments["_request"] = {
            "summary": "Synthetic nutrition request", "source_message_ids": [current_id],
            "target": "local", "scope": ["local_nutrition"], "period": None,
            "constraints": [], "remote_write": False, "sync_scope": None,
        }
    elif context.get("pending_request"):
        name = "save_checkin"
        arguments = {"payload": {"notes": "Schwere Beine"}, "_request": {
            "summary": "Tagesform aus der Rückfrage speichern", "source_message_ids": [current_id],
            "target": "local", "scope": ["local_checkin"], "period": None,
            "constraints": [], "remote_write": False, "sync_scope": None,
        }}
    else:
        name = "clarify_coach_request"
        arguments = {"source_message_ids": [current_id], "summary": "Tagesform für heute festhalten",
                     "question": "Wie fühlen sich deine Beine an?"}
    return {"output": [{"type": "function_call", "name": name,
                        "call_id": f"fixture-dialogue-{current_id}", "arguments": json.dumps(arguments)}]}


class FixtureResponseTransport:
    """Provider-free adapter for the canned browser conversation fixture."""

    def request(self, payload):
        return fixture_coach_response(payload)

    def background_request(self, payload, *, response_id=None, on_response_id=None, cancel_event=None):
        return fixture_coach_response(
            payload,
            response_id=response_id,
            on_response_id=on_response_id,
            cancel_event=cancel_event,
        )

    def stream_request(self, payload, on_text_delta, cancel_event=None, on_response_id=None):
        # Preserve the fixture's previous behavior: no synthetic text deltas.
        return fixture_coach_response(
            payload,
            on_text_delta=on_text_delta,
            cancel_event=cancel_event,
            on_response_id=on_response_id,
        )


server.COACH_CONVERSATION.response_transport = FixtureResponseTransport
initialise = server.initialise_database
artifact = {}


def stage_fixture_artifact():
    with server.DB_LOCK, server.database_manager().unit_of_work() as db:
        units = db.execute(
            "SELECT local_id, plan_id FROM planned_units "
            "WHERE json_extract(payload, '$.plan_name')=? "
            "AND json_extract(payload, '$.name') LIKE 'HTTP fixture %'",
            ("Fixture sport contract",),
        ).fetchall()
        unit_ids = [row["local_id"] for row in units]
        plan_ids = sorted({row["plan_id"] for row in units if row["plan_id"]})
        for entity_type, entity_ids in (("planned_unit", unit_ids), ("training_plan", plan_ids)):
            if entity_ids:
                placeholders = ",".join("?" for _ in entity_ids)
                db.execute(
                    f"DELETE FROM change_history WHERE entity_type=? "
                    f"AND entity_id IN ({placeholders})",
                    (entity_type, *entity_ids),
                )
        if unit_ids:
            placeholders = ",".join("?" for _ in unit_ids)
            db.execute(
                f"DELETE FROM planned_units WHERE local_id IN ({placeholders})",
                unit_ids,
            )
        if plan_ids:
            placeholders = ",".join("?" for _ in plan_ids)
            db.execute(
                f"DELETE FROM training_plans WHERE id IN ({placeholders})", plan_ids
            )
        db.execute(
            "DELETE FROM coach_commands WHERE artifact_id IN "
            "(SELECT id FROM coach_plan_artifacts WHERE client_turn_id=?)",
            ("fixture-stage",),
        )
        db.execute(
            "DELETE FROM coach_plan_artifacts WHERE client_turn_id=?",
            ("fixture-stage",),
        )

    today = server.ATHLETE_CLOCK.now().date()
    artifact.update(server.COACH_PLANNING_TOOLS.training_plan_artifact_service().stage({"payload": {
        "plan_name": "Fixture sport contract",
        "workouts": [{"date": (today + timedelta(days=index)).isoformat(), "name": f"HTTP fixture {sport}", "sport": sport, "duration_minutes": 30,
                      "description": {"Run": "- 30m Z1 HR", "WeightTraining": "Synthetic local workout",
                                      "VirtualRide": "- 30m 60%", "Swim": "- 30m Z1 Pace"}[sport]}
                     for index, sport in enumerate(("Run", "WeightTraining", "VirtualRide", "Swim"))],
    }}, "fixture-conversation", "fixture-stage"))


def initialise_fixture():
    initialise()


FIXTURE_ACTIVITY_TIME = "T08:00:00"


def seed_training_features():
    from backend.activities.detail_store import ActivityDetailStore, summary_fingerprint
    from backend.performance.power_profile import power_profile
    from backend.performance.session_analysis import aerobic_analysis, interval_quality

    now = server.ATHLETE_CLOCK.now()
    rows = [
        {"id": "feature-ride-1", "name": "Fixture steady ride", "type": "Ride", "device_name": "Fixture meter",
         "start_date_local": now.date().isoformat() + FIXTURE_ACTIVITY_TIME, "moving_time": 3600, "distance": 25000, "icu_training_load": 50},
        {"id": "feature-ride-2", "name": "Fixture previous ride", "type": "Ride", "device_name": "Fixture meter",
         "start_date_local": (now.date() - timedelta(days=7)).isoformat() + FIXTURE_ACTIVITY_TIME, "moving_time": 3600, "distance": 25000, "icu_training_load": 50},
    ]
    for row in rows:
        row["icu_hr_zone_times"] = [600, 1800, 600, 450, 150]
        row["icu_zone_times"] = [
            {"id": f"Z{index + 1}", "secs": seconds}
            for index, seconds in enumerate([600, 1500, 600, 450, 300, 100, 50])
        ]
    wellness = [{"id": (now.date() - timedelta(days=offset)).isoformat(), "sleepSecs": (7 + offset % 3 / 4) * 3600,
                 "restingHR": 50 + offset % 3, "hrv": None if offset == 3 else 45 + offset % 4,
                 "hrv_method": "RMSSD", "ctl": 25 + (34 - offset) * .15, "atl": 30 + offset % 7,
                 "eftp": 260 + (34 - offset) / 3} for offset in range(56)]
    week_start = now.date() - timedelta(days=now.date().weekday())
    for weeks_ago in range(2, 8):
        rows.append({"id": f"feature-history-{weeks_ago}", "name": "Fixture historical ride", "type": "Ride",
                     "start_date_local": (week_start - timedelta(weeks=weeks_ago)).isoformat() + FIXTURE_ACTIVITY_TIME,
                     "moving_time": 3600, "distance": 25000, "icu_training_load": 60 + (weeks_ago % 3) * 30})
    for offset, sport, duration, distance in [(0, "Run", 2400, 6000), (2, "Ride", 4500, 32000), (3, "Run", 1800, 4200)]:
        day = week_start + timedelta(days=offset)
        if day < now.date():
            rows.append({"id": f"feature-week-{offset}", "name": f"Fixture {sport}", "type": sport,
                         "start_date_local": day.isoformat() + FIXTURE_ACTIVITY_TIME, "moving_time": duration,
                         "distance": distance, "icu_training_load": 30})
    snapshot = {"synced_at": server.runtime_clock.utc_now(), "athlete": {}, "recent_wellness": wellness,
                "recent_activities": rows, "raw_provider_data": {"activities": rows}}
    with server.database_manager().unit_of_work() as db:
        server.SNAPSHOT_REPOSITORY.save(db, snapshot, snapshot["synced_at"])
        server.KEY_VALUE_REPOSITORY.set(db, "garmin_snapshot", json.dumps({"synced_at": snapshot["synced_at"],
            "performance_history": [
                {"date": (now.date() - timedelta(days=55)).isoformat(), "metrics": {"cycling_ftp_watts": 200}},
                {"date": now.date().isoformat(), "metrics": {"cycling_ftp_watts": 210}},
            ],
            "activities": [{"activityId": f"demo-{index}", "startTimeLocal": now.date().isoformat() + FIXTURE_ACTIVITY_TIME,
                "trainingEffectLabel": label, "activityTrainingLoad": load}
                for index, (label, load) in enumerate([("AEROBIC_BASE", 40), ("TEMPO", 80), ("ANAEROBIC_CAPACITY", 30)])],
            "gear": [{"gearUUID": "11111111-1111-4111-8111-111111111111", "gearName": "Fixture Garmin bike",
                      "gearTypeName": "Fahrrad", "gearStatusName": "Aktiv", "maximumMeters": 100000,
                      "stats": {"totalDistance": 25000, "totalActivities": 1}}]}))
    targets = {"steps": [{"duration": 3600, "target": "200W", "kind": "power"}], "basis": {},
               "observed_at": server.runtime_clock.utc_now(), "matching": "synthetic exact fixture", "planned_unit_id": "fixture-target"}
    for activity in rows[:2]:
        detailed = {**activity, "icu_ftp": 250, "streams": {"time": list(range(3601)), "watts": [200] * 3601, "heartrate": [140] * 3601},
                    "laps": [{"start_time": 0, "end_time": 3600}]}
        ActivityDetailStore(server.database_manager()).save(activity["id"], {
            "activity_id": activity["id"], "activity": detailed, "summary_sha256": summary_fingerprint(activity),
            "target_snapshot": targets, "session_analysis": {"aerobic": aerobic_analysis(detailed),
            "interval_quality": interval_quality(detailed, targets), "power_profile": power_profile(detailed)},
            "source": "Intervals.icu synthetic fixture", "observed_at": server.runtime_clock.utc_now(), "full_resolution": True,
            "available_streams": ["time", "watts", "heartrate"]})
    server.ATHLETE_DATA.profile().save({**server.ATHLETE_DATA.profile().get(), "sleep_target_hours": 8})
    equipment = server.ATHLETE_DATA.equipment().save({"name": "Fixture road bike", "sport": "Ride", "kind": "bike",
        "start_date": (now.date() - timedelta(days=10)).isoformat(), "initial_distance_km": 0, "initial_hours": 0, "maintenance_km": 20})["equipment"]
    server.ATHLETE_DATA.equipment().assign({"activity_id": "feature-ride-1", "equipment_id": equipment["id"]})
    server.PLANNING_DATA.competition().save({"name": "Fixture cycling target", "event_date": (now.date() + timedelta(days=30)).isoformat(), "sport": "Ride", "priority": "A"})
    units = server.PLANNING_DATA.planned_unit().list(500)
    planned = next((unit for unit in units if unit.get("name") == "Fixture fueling ride"), None)
    if planned is None:
        planned = server.PLANNING_WORKFLOWS.local_plan_creation_service().save([{"date": (now.date() + timedelta(days=1)).isoformat(),
            "name": "Fixture fueling ride", "sport": "Ride", "description": "- 90m 200w Steady", "duration_minutes": 90,
            "target": "AUTO", "rationale": "Synthetic fixture"}])[0]
    return {"planned_unit_id": planned["id"], "equipment_id": equipment["id"]}


def seed_preview_demo():
    """Populate only the disposable preview with fake data across the main areas."""
    with server.database_manager().unit_of_work() as db:
        if server.KEY_VALUE_REPOSITORY.get(db, "preview_demo_seeded"):
            return {"ready": True}
    seed_training_features()
    today = server.ATHLETE_CLOCK.now().date()
    server.ATHLETE_DATA.profile().save({
        **server.ATHLETE_DATA.profile().get(), "name": "Demo-Athlet", "sports": "Cycling, Running",
        "goals": "Ausdauer verbessern und entspannt beim Radmarathon starten.",
        "training_background": "Mehrere Jahre Rad- und Lauftraining. Synthetisches Beispielprofil.",
        "typical_weekly_volume": "6–8 Stunden", "availability": "Dienstag, Donnerstag und Wochenende",
        "weight_kg": 72, "height_cm": 180, "sleep_target_hours": 8,
        "equipment": "Rennrad mit Leistungsmesser, Laufschuhe", "fueling_tolerance": "60–80 g Kohlenhydrate pro Stunde",
    })
    for offset in range(56):
        day = today - timedelta(days=offset)
        server.ATHLETE_DATA.checkin().save({"checkin_date": day.isoformat(), "soreness": offset % 4,
            "stress": 2 + offset % 4, "motivation": 7 + offset % 3, "available_minutes": 90,
            "day_form": "Erholt" if offset % 3 else "Etwas schwere Beine",
            "day_status": "rest" if day.weekday() == 1 else "unknown",
            "tag_answers": {"travel": offset % 7 == 0, "late_meal": offset % 3 == 0, "high_stress": offset % 4 == 0}})
    nutrition = server.NUTRITION_ASSEMBLY.service()
    nutrition.save_template({"name": "Demo-Porridge", "description": "Haferflocken, Banane und Joghurt",
        "kcal": 520, "carbs_g": 78, "protein_g": 22, "fat_g": 12, "source": "manual"})
    for offset in range(7):
        for description, kcal, carbs, protein, fat in [("Porridge mit Banane", 520, 78, 22, 12),
                ("Reis mit Gemüse und Tofu", 720, 95, 32, 22), ("Pasta mit Tomatensauce", 650, 90, 25, 18)]:
            nutrition.log_meal({"meal_date": (today - timedelta(days=offset)).isoformat(),
                "description": description, "kcal": kcal, "carbs_g": carbs, "protein_g": protein,
                "fat_g": fat, "source": "manual"})
    workouts = [{"date": (today + timedelta(days=offset)).isoformat(), "name": name, "sport": sport,
                 "duration_minutes": duration, "description": description, "target": "AUTO", "rationale": "Synthetische Vorschau"}
                for offset, name, sport, duration, description in [
                    (2, "Lockerer Dauerlauf", "Run", 40, "- 40m Z1 HR"),
                    (3, "Radintervalle", "Ride", 60, "- 15m 50%\n- 5m 100%\n- 5m 50%\n- 5m 100%\n- 5m 50%\n- 5m 100%\n- 5m 50%\n- 15m 50%"),
                    (5, "Grundlagenausfahrt", "Ride", 90, "- 90m 65%")]]
    server.PLANNING_WORKFLOWS.local_plan_creation_service().save(workouts)
    history = [{"date": (today - timedelta(days=offset)).isoformat(), "metrics": {
        "cycling_ftp_watts": 270 + (42 - offset) / 3,
        "cycling_vo2max_ml_kg_min": 51 + (42 - offset) / 20,
        "running_vo2max_ml_kg_min": 49 + (42 - offset) / 25,
        "run_threshold_pace_seconds_per_km": 270 - (42 - offset) / 2}}
        for offset in range(42, -1, -1)]
    garmin = {"synced_at": server.runtime_clock.utc_now(), "performance_history": history,
        "activities": [{"activityId": f"demo-{index}", "startTimeLocal": today.isoformat() + FIXTURE_ACTIVITY_TIME,
            "trainingEffectLabel": label, "activityTrainingLoad": load}
            for index, (label, load) in enumerate([("AEROBIC_BASE", 40), ("TEMPO", 80), ("ANAEROBIC_CAPACITY", 30)])],
        "gear": [{"gearUUID": "11111111-1111-4111-8111-111111111111", "gearName": "Demo-Rennrad", "gearTypeName": "Fahrrad", "gearStatusName": "Aktiv", "maximumMeters": 10000000, "stats": {"totalDistance": 4250000, "totalActivities": 128}},
                 {"gearUUID": "22222222-2222-4222-8222-222222222222", "gearName": "Demo-Laufschuhe", "gearTypeName": "Laufschuhe", "gearStatusName": "Aktiv", "maximumMeters": 600000, "stats": {"totalDistance": 410000, "totalActivities": 62}}],
        "max_metrics": [{"calendarDate": today.isoformat(), "running": {"vo2MaxPreciseValue": 50.7}, "cycling": {"vo2MaxPreciseValue": 53.1}}],
        "cycling_ftp": {"power": 284, "calendarDate": today.isoformat()},
        "sleep": [{"calendarDate": (today - timedelta(days=offset)).isoformat(), "sleepTimeSeconds": (7.2 + offset % 3 / 4) * 3600} for offset in range(56)],
        "resting_hr": [{"calendarDate": (today - timedelta(days=offset)).isoformat(), "restingHeartRate": 49 + offset % 3} for offset in range(56)],
        "hrv": [{"calendarDate": (today - timedelta(days=offset)).isoformat(), "lastNightAvg": 46 + offset % 5} for offset in range(56)]}
    with server.database_manager().unit_of_work() as db:
        server.KEY_VALUE_REPOSITORY.set(db, "garmin_snapshot", json.dumps(garmin))
        for role, content in [("user", "Wie sieht meine Trainingswoche aus?"),
                ("assistant", "## Deine Beispielwoche\n\nDu hast Rad- und Laufeinheiten absolviert. Für die nächsten Tage sind ein lockerer Lauf, Radintervalle und eine Grundlagenausfahrt geplant.\n\nAchte auf ausreichenden Schlaf und regelmäßige Mahlzeiten. Diese Unterhaltung und alle Werte sind synthetische Testdaten.")]:
            server.CHAT_REPOSITORY.add(db, role, content)
        server.KEY_VALUE_REPOSITORY.set(db, "preview_demo_seeded", "1")
    return {"ready": True}


class FixtureHandler(server.HTTP_API.request_handler_class()):
    def do_GET(self):
        if self.path == "/api/fixture/demo":
            try:
                self.auth_service.require_auth(self)
                self.send_json(200, seed_preview_demo())
            except server.AppError as error:
                self.send_json(error.status, {"error": error.message})
            return
        if self.path == "/api/fixture/features":
            try:
                self.auth_service.require_auth(self)
                self.send_json(200, seed_training_features())
            except server.AppError as error:
                self.send_json(error.status, {"error": error.message})
            return
        if self.path == "/api/fixture/activity":
            self.auth_service.require_auth(self)
            from backend.activities.detail_store import ActivityDetailStore, summary_fingerprint
            from backend.performance.session_analysis import aerobic_analysis, interval_quality

            today = server.ATHLETE_CLOCK.now().date().isoformat()
            activity = {"id": "FixtureCase-1", "name": "Synthetic ride <img src=x>",
                        "type": "Ride", "start_date_local": f"{today}T08:00:00",
                        "moving_time": 3600, "distance": 25000, "icu_training_load": 50}
            snapshot = {"synced_at": datetime.now(timezone.utc).isoformat(), "athlete": {}, "recent_wellness": [],
                        "recent_activities": [activity], "raw_provider_data": {"activities": [activity]}}
            with server.database_manager().unit_of_work() as db:
                server.SNAPSHOT_REPOSITORY.save(db, snapshot, snapshot["synced_at"])
            detailed = {**activity, "icu_ftp": 250, "streams": {
                    "time": list(range(0, 3601)), "watts": [200] * 3601,
                    "heartrate": [140] * 3601}}
            ActivityDetailStore(server.database_manager()).save(activity["id"], {
                "activity_id": activity["id"], "activity": detailed,
                "summary_sha256": summary_fingerprint(activity),
                "session_analysis": {"aerobic": aerobic_analysis(detailed), "interval_quality": interval_quality(detailed, None)},
                "source": "Intervals.icu", "observed_at": datetime.now(timezone.utc).isoformat(),
                "full_resolution": True, "available_streams": ["time", "watts", "heartrate"],
            })
            self.send_json(200, {"activity_id": activity["id"]})
            return
        if self.path == "/api/fixture/plan":
            try:
                self.auth_service.require_auth(self)
                stage_fixture_artifact()
                self.send_json(200, artifact)
            except server.AppError as error:
                self.send_json(error.status, {"error": error.message})
            except Exception as error:  # noqa: BLE001 - report fixture setup failures as HTTP
                self.send_json(
                    500,
                    {"error": type(error).__name__, "reason": "fixture_setup_failed"},
                )
            return
        super().do_GET()


server.initialise_database = initialise_fixture
server.HTTP_API.request_handler_class = lambda: FixtureHandler
server.main()
