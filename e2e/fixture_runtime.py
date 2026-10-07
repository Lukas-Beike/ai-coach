"""Fresh SQLCipher runtime for local integration tests; all providers are blocked."""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

BLS_OATS_ID = "bls:C133000"
FIXTURE_DEMO_SEED_VERSION = "5"

# This file is mounted only in disposable test containers, never normal startup.
os.environ.update(
    {
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
    }
)
sys.path.insert(0, "/app")
import server
from backend.http_api import auth as http_auth

FIXTURE_SOURCE = "synthetic fixture"

FIXTURE_BIKE_NAME = "Fixture road bike"


def blocked_provider(*args, **kwargs):
    raise server.AppError(
        503, "Synthetic provider unavailable", reason="fixture_provider_unavailable"
    )


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
        outputs = [
            json.loads(item["output"])
            for item in value
            if item.get("type") == "function_call_output"
        ]
        question = next(
            (item.get("question") for item in outputs if item.get("question")), None
        )
        return {"output_text": question or "Deine Rückmeldung ist gespeichert."}
    decoded = json.loads(value)
    current_message = decoded.get("current_message")
    if current_message == "E2E fixture: OpenAI timeout":
        raise server.AppError(
            504, "Synthetic private provider detail", reason="provider_timeout"
        )
    provider_failure_codes = {
        "E2E fixture: OpenAI credit balance exhausted": "credit_balance_exhausted",
        "E2E fixture: OpenAI model not found": "model_not_found",
        "E2E fixture: OpenAI access denied": "permission_denied",
    }
    if current_message in provider_failure_codes:
        return server.provider_state_service().validate_openai_response(
            "/responses",
            {
                "status": "failed",
                "error": {
                    "code": provider_failure_codes[current_message],
                    "message": "Synthetic private provider detail",
                },
            },
        )
    context = decoded["dialogue"]
    current_id = context["current_user_message_id"]
    if current_message in {
        "E2E nutrition: confirm meal",
        "E2E nutrition: half portion",
        "E2E nutrition: update meal",
        "E2E nutrition: delete meal",
        "E2E nutrition: database oats",
        "E2E nutrition: confirm database meal",
        "E2E nutrition: mixed meal",
    }:
        nutrition = server.NUTRITION_ASSEMBLY.service()
        templates = nutrition.list_templates()
        if current_message == "E2E nutrition: mixed meal":
            product = nutrition.save_product(
                {
                    "name": "Synthetic whey <img src=x>",
                    "brand": "Fixture",
                    "source": "packaging_label",
                    "basis_amount": 100,
                    "basis_unit": "g",
                    "kcal": 400,
                    "carbs_g": 8.3,
                    "protein_g": 80,
                    "fat_g": 5,
                }
            )
            name = "save_nutrition_entry"
            arguments = {
                "payload": {
                    "description": "Mixed meal <script>alert(1)</script>",
                    "source": "manual",
                    "components": [
                        {
                            "kind": "local_product",
                            "product_id": product["id"],
                            "amount": 60,
                            "unit": "g",
                        },
                        {
                            "kind": "database",
                            "food_id": BLS_OATS_ID,
                            "amount": 3,
                            "unit": "g",
                        },
                        {
                            "kind": "manual",
                            "name": "Creatine",
                            "amount": 8,
                            "unit": "g",
                            "kcal": 0,
                            "carbs_g": 0,
                            "protein_g": 0,
                            "fat_g": 0,
                        },
                    ],
                }
            }
        elif current_message == "E2E nutrition: confirm database meal":
            name = "save_nutrition_template"
            arguments = {
                "payload": {
                    "name": "Database oats",
                    "description": "50 g Haferflocken",
                    "kcal": 999,
                    "source": "coach",
                    "food_ingredients": [
                        {"food_id": BLS_OATS_ID, "amount": 50, "unit": "g"}
                    ],
                }
            }
        elif current_message == "E2E nutrition: database oats":
            name = "save_nutrition_entry"
            arguments = {
                "payload": {
                    "description": "50 g Haferflocken",
                    "kcal": 999,
                    "source": "coach",
                    "food_ingredients": [
                        {"food_id": BLS_OATS_ID, "amount": 50, "unit": "g"}
                    ],
                }
            }
        elif current_message == "E2E nutrition: confirm meal":
            name = "save_nutrition_template"
            arguments = {
                "payload": {
                    "name": "Fixture breakfast",
                    "description": "80 g oats - <img src=x onerror=alert(1)>",
                    "kcal": 400,
                    "carbs_g": 60,
                    "protein_g": 12,
                    "fat_g": 8,
                    "source": "coach",
                }
            }
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
            "summary": "Synthetic nutrition request",
            "source_message_ids": [current_id],
            "target": "local",
            "scope": ["local_nutrition"],
            "period": None,
            "constraints": [],
            "remote_write": False,
            "sync_scope": None,
        }
    elif context.get("pending_request"):
        name = "save_checkin"
        arguments = {
            "payload": {"notes": "Schwere Beine"},
            "_request": {
                "summary": "Tagesform aus der Rückfrage speichern",
                "source_message_ids": [current_id],
                "target": "local",
                "scope": ["local_checkin"],
                "period": None,
                "constraints": [],
                "remote_write": False,
                "sync_scope": None,
            },
        }
    else:
        name = "clarify_coach_request"
        arguments = {
            "source_message_ids": [current_id],
            "summary": "Tagesform für heute festhalten",
            "question": "Wie fühlen sich deine Beine an?",
        }
    return {
        "output": [
            {
                "type": "function_call",
                "name": name,
                "call_id": f"fixture-dialogue-{current_id}",
                "arguments": json.dumps(arguments),
            }
        ]
    }


class FixtureResponseTransport:
    """Provider-free adapter for the canned browser conversation fixture."""

    def request(self, payload):
        return fixture_coach_response(payload)

    def background_request(
        self, payload, *, response_id=None, on_response_id=None, cancel_event=None
    ):
        return fixture_coach_response(
            payload,
            response_id=response_id,
            on_response_id=on_response_id,
            cancel_event=cancel_event,
        )

    def stream_request(
        self, payload, on_text_delta, cancel_event=None, on_response_id=None
    ):
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
        for entity_type, entity_ids in (
            ("planned_unit", unit_ids),
            ("training_plan", plan_ids),
        ):
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
    artifact.update(
        server.COACH_PLANNING_TOOLS.training_plan_artifact_service().stage(
            {
                "payload": {
                    "plan_name": "Fixture sport contract",
                    "workouts": [
                        {
                            "date": (today + timedelta(days=index)).isoformat(),
                            "name": f"HTTP fixture {sport}",
                            "sport": sport,
                            "duration_minutes": 30,
                            "description": {
                                "Run": "- 30m Z1 HR",
                                "WeightTraining": "Synthetic local workout",
                                "VirtualRide": "- 30m 60%",
                                "Swim": "- 30m Z1 Pace",
                            }[sport],
                        }
                        for index, sport in enumerate(
                            ("Run", "WeightTraining", "VirtualRide", "Swim")
                        )
                    ],
                }
            },
            "fixture-conversation",
            "fixture-stage",
        )
    )


def initialise_fixture():
    initialise()
    # Opt-in standard data: the demo container seeds itself on every start.
    # Both seeds are idempotent and versioned, so restarts are safe.
    if os.environ.get("FIXTURE_AUTO_SEED") == "1":
        seed_training_features()
        seed_preview_demo()


FIXTURE_ACTIVITY_TIME = "T08:00:00"


def demo_performance_history(today):
    """Weekly synthetic performance observations across the 90-day chart window."""
    ages = [*range(89, 0, -7), 0]
    history = []
    for index, age in enumerate(ages):
        progress = index / (len(ages) - 1)
        variation = (index % 3 - 1) * 0.4
        history.append(
            {
                "date": (today - timedelta(days=age)).isoformat(),
                "metrics": {
                    "cycling_ftp_watts": round(262 + 22 * progress + variation),
                    "cycling_vo2max_ml_kg_min": round(
                        49.5 + 2.6 * progress + variation / 4, 1
                    ),
                    "running_vo2max_ml_kg_min": round(
                        47.2 + 2.2 * progress + variation / 4, 1
                    ),
                    "run_threshold_pace_seconds_per_km": round(
                        298 - 24 * progress - variation
                    ),
                },
            }
        )
    return history


def seed_training_features():
    from backend.activities.detail_store import ActivityDetailStore, summary_fingerprint
    from backend.performance.power_profile import power_profile
    from backend.performance.session_analysis import aerobic_analysis, interval_quality

    now = server.ATHLETE_CLOCK.now()
    rows = [
        {
            "id": "feature-ride-1",
            "name": "Fixture steady ride",
            "type": "Ride",
            "device_name": "Fixture meter",
            "start_date_local": now.date().isoformat() + FIXTURE_ACTIVITY_TIME,
            "moving_time": 3600,
            "distance": 25000,
            "icu_training_load": 50,
        },
        {
            "id": "feature-ride-2",
            "name": "Fixture previous ride",
            "type": "Ride",
            "device_name": "Fixture meter",
            "start_date_local": (now.date() - timedelta(days=7)).isoformat()
            + FIXTURE_ACTIVITY_TIME,
            "moving_time": 3600,
            "distance": 25000,
            "icu_training_load": 50,
        },
    ]
    for row in rows:
        row["icu_hr_zone_times"] = [600, 1800, 600, 450, 150]
        row["icu_zone_times"] = [
            {"id": f"Z{index + 1}", "secs": seconds}
            for index, seconds in enumerate([600, 1500, 600, 450, 300, 100, 50])
        ]
    wellness = _fixture_demo_wellness(now.date())
    week_start = now.date() - timedelta(days=now.date().weekday())
    for weeks_ago in range(2, 8):
        rows.append(
            {
                "id": f"feature-history-{weeks_ago}",
                "name": "Fixture historical ride",
                "type": "Ride",
                "start_date_local": (
                    week_start - timedelta(weeks=weeks_ago)
                ).isoformat()
                + FIXTURE_ACTIVITY_TIME,
                "moving_time": 3600,
                "distance": 25000,
                "icu_training_load": 60 + (weeks_ago % 3) * 30,
            }
        )
    for offset, sport, duration, distance in [
        (0, "Run", 2400, 6000),
        (2, "Ride", 4500, 32000),
        (3, "Run", 1800, 4200),
    ]:
        day = week_start + timedelta(days=offset)
        if day < now.date():
            rows.append(
                {
                    "id": f"feature-week-{offset}",
                    "name": f"Fixture {sport}",
                    "type": sport,
                    "start_date_local": day.isoformat() + FIXTURE_ACTIVITY_TIME,
                    "moving_time": duration,
                    "distance": distance,
                    "icu_training_load": 30,
                }
            )
    snapshot = {
        "synced_at": server.runtime_clock.utc_now(),
        "athlete": {},
        "recent_wellness": wellness,
        "recent_activities": rows,
        "raw_provider_data": {"activities": rows, "wellness": wellness},
    }
    with server.database_manager().unit_of_work() as db:
        db.execute(
            "DELETE FROM kv WHERE key LIKE 'equipment:%' OR key LIKE 'equipment_assignment:%' OR key LIKE 'equipment_maintenance:%' OR key = 'garmin_equipment_initialized'"
        )
        server.SNAPSHOT_REPOSITORY.save(db, snapshot, snapshot["synced_at"])
        garmin_full = _fixture_demo_garmin(
            now.date(), demo_performance_history(now.date())
        )
        garmin_full.update(
            {
                "synced_at": snapshot["synced_at"],
                "performance_history": demo_performance_history(now.date()),
                "training_status": [
                    {
                        "calendarDate": (
                            now.date() - timedelta(days=offset)
                        ).isoformat(),
                        "acuteTrainingLoadDTO": {
                            "acuteTrainingLoad": 420 + offset % 12 * 15
                        },
                    }
                    for offset in range(90)
                ],
                "activities": [
                    {
                        "activityId": f"demo-{index}",
                        "startTimeLocal": now.date().isoformat()
                        + FIXTURE_ACTIVITY_TIME,
                        "trainingEffectLabel": label,
                        "activityTrainingLoad": load,
                    }
                    for index, (label, load) in enumerate(
                        [
                            ("AEROBIC_BASE", 40),
                            ("TEMPO", 80),
                            ("ANAEROBIC_CAPACITY", 30),
                        ]
                    )
                ],
                "gear": [
                    {
                        "gearUUID": "11111111-1111-4111-8111-111111111111",
                        "gearName": "Fixture Garmin bike",
                        "gearTypeName": "Fahrrad",
                        "gearStatusName": "Aktiv",
                        "maximumMeters": 100000,
                        "stats": {"totalDistance": 25000, "totalActivities": 1},
                    }
                ],
            }
        )
        server.KEY_VALUE_REPOSITORY.set(db, "garmin_snapshot", json.dumps(garmin_full))
    targets = {
        "steps": [{"duration": 3600, "target": "200W", "kind": "power"}],
        "basis": {},
        "observed_at": server.runtime_clock.utc_now(),
        "matching": "synthetic exact fixture",
        "planned_unit_id": "fixture-target",
    }
    for activity in rows[:2]:
        detailed = {
            **activity,
            "icu_ftp": 250,
            "streams": {
                "time": list(range(3601)),
                "watts": [200] * 3601,
                "heartrate": [140] * 3601,
            },
            "laps": [{"start_time": 0, "end_time": 3600}],
        }
        ActivityDetailStore(server.database_manager()).save(
            activity["id"],
            {
                "activity_id": activity["id"],
                "activity": detailed,
                "summary_sha256": summary_fingerprint(activity),
                "target_snapshot": targets,
                "session_analysis": {
                    "aerobic": aerobic_analysis(detailed),
                    "interval_quality": interval_quality(detailed, targets),
                    "power_profile": power_profile(detailed),
                },
                "source": "Intervals.icu synthetic fixture",
                "observed_at": server.runtime_clock.utc_now(),
                "full_resolution": True,
                "available_streams": ["time", "watts", "heartrate"],
            },
        )
    server.ATHLETE_DATA.profile().save(
        {**server.ATHLETE_DATA.profile().get(), "sleep_target_hours": 8}
    )
    equipment = server.ATHLETE_DATA.equipment().save(
        {
            "name": FIXTURE_BIKE_NAME,
            "sport": "Ride",
            "kind": "bike",
            "start_date": (now.date() - timedelta(days=10)).isoformat(),
            "initial_distance_km": 0,
            "initial_hours": 0,
            "maintenance_km": 20,
        }
    )["equipment"]
    server.ATHLETE_DATA.equipment().assign(
        {"activity_id": "feature-ride-1", "equipment_id": equipment["id"]}
    )
    server.PLANNING_DATA.competition().save(
        {
            "name": "Fixture cycling target",
            "event_date": (now.date() + timedelta(days=30)).isoformat(),
            "sport": "Ride",
            "priority": "A",
        }
    )
    units = server.PLANNING_DATA.planned_unit().list(500)
    planned = next(
        (unit for unit in units if unit.get("name") == "Fixture fueling ride"), None
    )
    if planned is None:
        planned = server.PLANNING_WORKFLOWS.local_plan_creation_service().save(
            [
                {
                    "date": (now.date() + timedelta(days=1)).isoformat(),
                    "name": "Fixture fueling ride",
                    "sport": "Ride",
                    "description": "- 90m 200w Steady",
                    "duration_minutes": 90,
                    "target": "AUTO",
                    "rationale": "Synthetic fixture",
                }
            ]
        )[0]
    return {"planned_unit_id": planned["id"], "equipment_id": equipment["id"]}


def _fixture_demo_wellness(today):
    """Return 90 dated Intervals wellness samples with deliberate body gaps."""
    return [
        {
            "id": (today - timedelta(days=offset)).isoformat(),
            "sleepSecs": (7 + offset % 3 / 4) * 3600,
            "restingHR": 50 + offset % 3,
            "hrv": None if offset == 3 else 45 + offset % 4,
            "hrv_method": "RMSSD",
            "ctl": 27 + (89 - offset) * 0.18 + [0, 1, 2, 1, -1, -2, -1][offset % 7],
            "atl": 26 + (89 - offset) * 0.08 + [0, 2, 4, 1, -1, -2, 1][offset % 7],
            "eftp": 260 + (89 - offset) * 0.25,
            "weight": round(73.4 - (89 - offset) * 0.018 + (offset % 5) * 0.12, 2)
            if offset % 5 != 4
            else None,
            "bodyFat": round(16.8 - (89 - offset) * 0.015 + (offset % 3) * 0.2, 1)
            if offset % 9 == 0
            else None,
            "sport_info": [
                {
                    "types": ["Ride"],
                    "mmp_model": {
                        "ftp": round(258 + (89 - offset) * 0.28 + (offset % 4) * 1.4)
                    },
                }
            ],
        }
        for offset in range(90)
    ]


def _fixture_demo_garmin(today, history):
    """Return a provider-shaped Garmin payload with dated and sparse metrics."""
    daily_stats = []
    weight = []
    for offset in range(90):
        day = today - timedelta(days=offset)
        daily_stats.append(
            {
                "calendarDate": day.isoformat(),
                "activeKilocalories": 0 if offset == 12 else 420 + (offset % 6) * 35,
                "bmrKilocalories": 0 if offset == 12 else 1540 + (offset % 4) * 8,
                "totalKilocalories": 0 if offset == 12 else 1960 + (offset % 6) * 42,
                "totalSteps": 6500 + (offset % 5) * 900,
            }
        )
        # Weight is measured every other day; body fat is intentionally sparse.
        if offset % 2 != 1:
            row = {
                "calendarDate": day.isoformat(),
                "weightKg": round(
                    73.8 - (89 - min(offset, 89)) * 0.02 + (offset % 4) * 0.1, 2
                ),
            }
            if offset % 10 == 0:
                row.update(
                    {
                        "bodyFat": round(17.4 - (89 - min(offset, 89)) * 0.02, 1),
                        "bodyFatUnit": "percent",
                    }
                )
            weight.append(row)
    return {
        "source": FIXTURE_SOURCE,
        "synced_at": server.runtime_clock.utc_now(),
        "source_freshness": {
            "daily_stats": {
                "freshness": "current",
                "fetched_at": server.runtime_clock.utc_now(),
            }
        },
        "performance_history": history,
        "weight": weight,
        "daily_stats": daily_stats,
        "training_status": [
            {
                "calendarDate": (today - timedelta(days=offset)).isoformat(),
                "acuteTrainingLoadDTO": {"acuteTrainingLoad": 420 + offset % 12 * 15},
            }
            for offset in range(90)
        ],
        "activities": [
            {
                "activityId": f"demo-{index}",
                "startTimeLocal": today.isoformat() + FIXTURE_ACTIVITY_TIME,
                "trainingEffectLabel": label,
                "activityTrainingLoad": load,
            }
            for index, (label, load) in enumerate(
                [("AEROBIC_BASE", 40), ("TEMPO", 80), ("ANAEROBIC_CAPACITY", 30)]
            )
        ],
        "gear": [
            {
                "gearUUID": "11111111-1111-4111-8111-111111111111",
                "gearName": "Demo-Rennrad",
                "gearTypeName": "Fahrrad",
                "gearStatusName": "Aktiv",
                "maximumMeters": 1000000,
                "stats": {"totalDistance": 425000, "totalActivities": 128},
            },
            {
                "gearUUID": "22222222-2222-4222-8222-222222222222",
                "gearName": "Demo-Laufschuhe",
                "gearTypeName": "Laufschuhe",
                "gearStatusName": "Aktiv",
                "maximumMeters": 300000,
                "stats": {"totalDistance": 410000, "totalActivities": 62},
            },
            {
                "gearUUID": "33333333-3333-4333-8333-333333333333",
                "gearName": "Demo chain component",
                "gearTypeName": "Component",
                "gearStatusName": "Aktiv",
                "maximumMeters": 250000,
                "stats": {"totalDistance": 0, "totalActivities": 0},
            },
        ],
        "max_metrics": [
            {
                "calendarDate": today.isoformat(),
                "running": {"vo2MaxPreciseValue": 50.7},
                "cycling": {"vo2MaxPreciseValue": 53.1},
            }
        ],
        "cycling_ftp": {"power": 284, "calendarDate": today.isoformat()},
        "sleep": [
            {
                "calendarDate": (today - timedelta(days=offset)).isoformat(),
                "sleepTimeSeconds": (7.2 + offset % 3 / 4) * 3600,
            }
            for offset in range(90)
        ],
        "resting_hr": [
            {
                "calendarDate": (today - timedelta(days=offset)).isoformat(),
                "restingHeartRate": 49 + offset % 3,
            }
            for offset in range(90)
        ],
        "hrv": [
            {
                "calendarDate": (today - timedelta(days=offset)).isoformat(),
                "lastNightAvg": 46 + offset % 5,
            }
            for offset in range(90)
        ],
    }


def _fixture_equipment_definitions(road_id):
    """Return active/archived gear and target boundary examples."""
    return [
        (road_id, FIXTURE_BIKE_NAME, "Ride", "bike", "active", None, 20, None),
        (
            "00000000-0000-4000-8000-000000000002",
            "Fixture archived trainer",
            "Ride",
            "bike",
            "archived",
            None,
            None,
            None,
        ),
        (
            "00000000-0000-4000-8000-000000000003",
            "Fixture Garmin linked bike",
            "Ride",
            "bike",
            "active",
            "11111111-1111-4111-8111-111111111111",
            1000,
            1000000,
        ),
        (
            "00000000-0000-4000-8000-000000000004",
            "Fixture Garmin archived shoes",
            "Run",
            "shoes",
            "archived",
            "22222222-2222-4222-8222-222222222222",
            None,
            300000,
        ),
        (
            "00000000-0000-4000-8000-000000000005",
            "Fixture replacement chain",
            "Ride",
            "component",
            "active",
            None,
            250,
            None,
        ),
        (
            "00000000-0000-4000-8000-000000000006",
            "Fixture Garmin-linked chain",
            "Ride",
            "component",
            "active",
            "33333333-3333-4333-8333-333333333333",
            200,
            250000,
        ),
        (
            "00000000-0000-4000-8000-000000000007",
            "Fixture archived chain",
            "Ride",
            "component",
            "archived",
            None,
            None,
            None,
        ),
    ]


def _fixture_seed_equipment(today, garmin_snapshot):
    """Seed local and Garmin-linked gear, including boundary counter examples."""
    service = server.ATHLETE_DATA.equipment()
    garmin_distances_km = {}
    for row in garmin_snapshot.get("gear") or []:
        if not isinstance(row, dict) or not row.get("gearUUID"):
            continue
        stats = row.get("stats")
        distance = stats.get("totalDistance") if isinstance(stats, dict) else None
        if not isinstance(distance, (int, float)) or isinstance(distance, bool):
            continue
        garmin_distances_km[str(row["gearUUID"])] = round(distance / 1000, 2)
    items = service.read().get("items", [])
    existing = {item.get("name"): item for item in items}
    road = existing.get(FIXTURE_BIKE_NAME)
    road_id = road["id"] if road else None
    saved = {}
    for (
        item_id,
        name,
        sport,
        kind,
        status,
        garmin_uuid,
        target_km,
        maximum_meters,
    ) in _fixture_equipment_definitions(road_id):
        item = existing.get(name)
        if item is None:
            payload = {
                "name": name,
                "sport": sport,
                "kind": kind,
                "status": status,
                "start_date": (today - timedelta(days=35)).isoformat(),
                "initial_distance_km": 0,
                "initial_hours": 0,
                "maintenance_km": 250 if kind == "bike" else None,
            }
            if kind == "component" and road_id:
                payload["parent_id"] = road_id
            result = service.save(payload)
            item = result["equipment"]
            existing[name] = item
            if name == FIXTURE_BIKE_NAME:
                road_id = item["id"]
        item.update(
            {"lifetime_target_km": target_km, "garmin_maximum_meters": maximum_meters}
        )
        if target_km is not None:
            item["lifetime_target_source"] = "local"
        elif maximum_meters is not None:
            item["lifetime_target_source"] = "garmin"
        if name == FIXTURE_BIKE_NAME:
            item["initial_distance_km"] = 0
        if garmin_uuid:
            item["garmin_uuid"] = garmin_uuid
            item["garmin_distance_km"] = garmin_distances_km.get(garmin_uuid)
        saved[item["id"]] = item
    now = server.runtime_clock.utc_now()
    with server.database_manager().unit_of_work() as db:
        for item_id, item in saved.items():
            db.execute(
                "UPDATE kv SET value=?, updated_at=? WHERE key=?",
                (json.dumps(item, ensure_ascii=False), now, "equipment:" + item_id),
            )
    if not any(
        item.get("activity_id") == "feature-ride-1"
        and item.get("equipment_id") == road_id
        for item in service.read().get("assignments", [])
    ):
        service.assign({"activity_id": "feature-ride-1", "equipment_id": road_id})
    return saved


def _fixture_calendar_payload(today):
    """Build the fixture feed with descriptive titles and parsed markers."""
    start = today + timedelta(days=2)

    def stamp(day, hour="090000"):
        return day.strftime("%Y%m%d") + "T" + hour

    return "\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Intervals Coach Fixture//EN",
            f"BEGIN:VEVENT\nUID:fixture-no-training\nDTSTART:{stamp(start)}\nDTEND:{stamp(start, '100000')}\nSUMMARY:Fixture [NO_TRAINING] recovery marker\nDESCRIPTION:Fixture rest marker from the event title\nEND:VEVENT",
            f"BEGIN:VEVENT\nUID:fixture-no-intensity\nDTSTART:{stamp(start + timedelta(days=1))}\nDTEND:{stamp(start + timedelta(days=1), '103000')}\nSUMMARY:Fixture easy ride\nDESCRIPTION:[NO_INTENSITY]\nEND:VEVENT",
            f"BEGIN:VEVENT\nUID:fixture-title-description\nDTSTART:{stamp(start + timedelta(days=2))}\nDTEND:{stamp(start + timedelta(days=2), '110000')}\nSUMMARY:Fixture title example\nDESCRIPTION:Description from synthetic calendar\nEND:VEVENT",
            f"BEGIN:VEVENT\nUID:fixture-both\nDTSTART:{stamp(start + timedelta(days=3))}\nDTEND:{stamp(start + timedelta(days=3), '100000')}\nSUMMARY:Fixture both markers\nDESCRIPTION:[NO_TRAINING] [NO_INTENSITY]\nEND:VEVENT",
            f"BEGIN:VEVENT\nUID:fixture-multiday\nDTSTART;VALUE=DATE:{(start + timedelta(days=4)).strftime('%Y%m%d')}\nDTEND;VALUE=DATE:{(start + timedelta(days=6)).strftime('%Y%m%d')}\nSUMMARY:Fixture camp [NO_INTENSITY]\nDESCRIPTION:Two day synthetic camp\nEND:VEVENT",
            f"BEGIN:VEVENT\nUID:fixture-series\nDTSTART:{stamp(start + timedelta(days=7))}\nDTEND:{stamp(start + timedelta(days=7), '100000')}\nRRULE:FREQ=WEEKLY;COUNT=3\nSUMMARY:Fixture weekly series\nDESCRIPTION:[SHORT_ONLY]\nEND:VEVENT",
            f"BEGIN:VEVENT\nUID:fixture-series\nRECURRENCE-ID:{stamp(start + timedelta(days=14))}\nSTATUS:CANCELLED\nSUMMARY:Fixture cancelled series occurrence\nEND:VEVENT",
            "END:VCALENDAR",
            "",
        ]
    ).encode()


def _fixture_seed_calendar(today):
    """Parse a representative iCalendar payload and persist its expanded rows."""
    from zoneinfo import ZoneInfo

    from backend.providers.calendar import parse_ical_calendar

    events = parse_ical_calendar(
        _fixture_calendar_payload(today),
        local_zone=ZoneInfo("Europe/Berlin"),
        today=today,
        window_start=today,
        window_end=today + timedelta(days=56),
    )
    now = server.runtime_clock.utc_now()
    with server.database_manager().unit_of_work() as db:
        db.execute("DELETE FROM external_calendar_events WHERE uid LIKE 'fixture-%'")
        for event in events:
            fields = [
                "id",
                "uid",
                "name",
                "event_date",
                "start_local",
                "end_local",
                "duration_minutes",
                "all_day",
                "training_relevant",
                "no_training",
                "no_intensity",
                "short_only",
                "updated_at",
            ]
            values = [
                event["id"],
                event["uid"],
                event["name"],
                event["event_date"],
                event["start_local"],
                event["end_local"],
                event["duration_minutes"],
                int(event["all_day"]),
                int(event.get("training_relevant", True)),
                int(event.get("no_training", False)),
                int(event.get("no_intensity", False)),
                int(event.get("short_only", False)),
                now,
            ]
            db.execute(
                f"INSERT OR REPLACE INTO external_calendar_events ({', '.join(fields)}) VALUES ({', '.join('?' for _ in fields)})",
                values,
            )
        server.KEY_VALUE_REPOSITORY.set(db, "last_external_calendar_sync_at", now)
    return len(events)


def _fixture_seed_wave2(today, snapshot, garmin):
    """Add broad synthetic activities, analyses, feedback and race targets.

    IDs and payload values are fixture-owned; ``INSERT OR REPLACE`` style
    persistence through the existing services makes v1/v2 upgrades repeatable.
    """
    from backend.activities.detail_store import ActivityDetailStore, summary_fingerprint
    from backend.performance.power_profile import power_profile, running_profile
    from backend.performance.session_analysis import aerobic_analysis, interval_quality

    # The v1 upgrade contract test supplies a deliberately minimal mocked
    # database connection; broad wave2 records are only meaningful with the
    # real disposable SQLCipher connection.
    with server.database_manager().unit_of_work() as probe:
        if not hasattr(probe, "execute"):
            return

    activities = [
        item
        for item in (snapshot.get("recent_activities") or [])
        if isinstance(item, dict)
    ]
    by_id = {str(item.get("id") or item.get("activityId")): item for item in activities}
    for offset in range(90):
        day = today - timedelta(days=offset)
        sport, subtype = (
            ("VirtualRide", "indoor")
            if offset % 3 == 0
            else (("Ride", "outdoor") if offset % 3 == 1 else ("Run", "outdoor"))
        )
        activity_id = f"wave2-{offset:03d}"
        row = {
            "id": activity_id,
            "activityId": activity_id,
            "name": f"Synthetic {subtype} {sport.lower()} {offset:03d}",
            "type": sport,
            "sport": sport,
            "sub_sport": subtype,
            "device_name": (
                "Zwift Synthetic Trainer"
                if sport == "VirtualRide"
                else "Garmin Edge Synthetic"
                if sport == "Ride"
                else "Garmin Forerunner Synthetic"
            ),
            "start_date_local": f"{day.isoformat()}T{('06:30:00' if sport == 'Run' else '18:00:00')}",
            "moving_time": (35 + offset % 5 * 10) * 60,
            "distance": (6000 + offset * 37)
            if sport == "Run"
            else (24000 + offset * 111),
            "icu_training_load": 24 + (offset * 7) % 75,
            "icu_rpe": (offset % 11) if offset % 7 else None,
            "source": FIXTURE_SOURCE,
        }
        by_id[activity_id] = row
    merged = sorted(
        by_id.values(),
        key=lambda item: str(item.get("start_date_local") or ""),
        reverse=True,
    )
    snapshot["recent_activities"] = merged
    raw = (
        snapshot.get("raw_provider_data")
        if isinstance(snapshot.get("raw_provider_data"), dict)
        else {}
    )
    snapshot["raw_provider_data"] = {**raw, "activities": merged}
    snapshot.setdefault("synced_at", server.runtime_clock.utc_now())
    with server.database_manager().unit_of_work() as db:
        server.SNAPSHOT_REPOSITORY.save(db, snapshot, snapshot["synced_at"])
    for offset in range(0, 90, 9):
        activity = by_id[f"wave2-{offset:03d}"]
        payload = {
            "activity_name": activity["name"],
            "activity_date": activity["start_date_local"][:10],
            "notes": "Synthetic session feedback" if offset % 18 else "",
            "session_rpe": 0
            if offset == 0
            else (None if offset == 18 else offset % 10),
            "deviation_reason": "fixture" if offset % 18 == 0 else "",
        }
        # Use the repository in the current fixture transaction so this helper
        # also works in the lightweight upgrade unit test with a mocked manager.
        with server.database_manager().unit_of_work() as db:
            server.ACTIVITY_FEEDBACK_REPOSITORY.upsert(
                db, {"activity_id": activity["id"], **payload}
            )
    store = ActivityDetailStore(server.database_manager())
    targets = {
        "steps": [{"duration": 300, "target": "200W", "kind": "power"}],
        "basis": {},
        "observed_at": server.runtime_clock.utc_now(),
        "matching": "synthetic exact fixture",
        "planned_unit_id": "wave2-target",
    }
    # Cache representative full-resolution analyses. The summary fingerprint
    # is computed from exactly the summary object stored in the snapshot.
    detail_offsets = (0, 1, 2, 9, 28, 29, 81, 82, 83)
    for offset in detail_offsets:
        activity = by_id[f"wave2-{offset:03d}"]
        n = int(activity["moving_time"]) + 1
        if activity["type"] == "Run":
            watts = [None] * n
            heart_rate = [135 + ((i // 60) % 5) for i in range(n)]
            base_speed = [
                3.1 + ((i // 180) % 4) * 0.12 + ((offset % 3) * 0.03) for i in range(n)
            ]
            scale = activity["distance"] / sum(base_speed[:-1])
            speed = [value * scale for value in base_speed]
            distance = [0.0]
            for value in speed[:-1]:
                distance.append(distance[-1] + value)
            streams = {
                "time": list(range(n)),
                "watts": watts,
                "heartrate": heart_rate,
                "velocity_smooth": speed,
                "distance": distance,
                "moving": [1] * n,
            }
        else:
            watts = [170 + ((i // 45) % 4) * 30 for i in range(n)]
            heart_rate = [125 + ((i // 90) % 6) * 5 for i in range(n)]
            streams = {
                "time": list(range(n)),
                "watts": watts,
                "heartrate": heart_rate,
                "moving": [1] * n,
            }
        detailed = {
            **activity,
            "icu_ftp": 260,
            "streams": streams,
            "laps": [{"start_time": 0, "end_time": n - 1}],
        }
        store.save(
            activity["id"],
            {
                "activity_id": activity["id"],
                "activity": detailed,
                "summary_sha256": summary_fingerprint(activity),
                "target_snapshot": targets,
                "session_analysis": {
                    "aerobic": aerobic_analysis(detailed),
                    "interval_quality": interval_quality(detailed, targets),
                    "power_profile": power_profile(detailed),
                    "running_profile": running_profile(detailed),
                },
                "source": FIXTURE_SOURCE,
                "observed_at": server.runtime_clock.utc_now(),
                "full_resolution": True,
                "available_streams": sorted(streams),
            },
        )
    # Local competitions are durable athlete targets; update by name to avoid
    # duplicate rows on every browser reload or v1/v2 upgrade.
    existing = {
        item.get("name") for item in server.PLANNING_DATA.competition().list(100)
    }
    for name, days, sport, distance, target in (
        ("Synthetic Half Marathon", 45, "Run", "21.1 km", "01:45:00"),
        ("Synthetic Marathon", 120, "Run", "42.2 km", "03:45:00"),
        ("Synthetic Bike Gran Fondo", 75, "Ride", "150 km", "04:30:00"),
    ):
        if name not in existing:
            server.PLANNING_DATA.competition().save(
                {
                    "name": name,
                    "event_date": (today + timedelta(days=days)).isoformat(),
                    "sport": sport,
                    "priority": "A",
                    "distance": distance,
                    "target": target,
                    "notes": "Synthetic fixture race target",
                }
            )
    garmin.update(
        {
            "source": FIXTURE_SOURCE,
            "source_freshness": {
                **(garmin.get("source_freshness") or {}),
                **{
                    k: {
                        "freshness": "current",
                        "fetched_at": server.runtime_clock.utc_now(),
                    }
                    for k in (
                        "endurance_score",
                        "running_tolerance",
                        "cycling_ftp_history",
                    )
                },
            },
            "cycling_ftp_history": [
                {
                    "calendarDate": (today - timedelta(days=i * 14)).isoformat(),
                    "functionalThresholdPower": 255 + i * 4,
                    "unit": "synthetic watts",
                }
                for i in range(7)
            ],
            "endurance_score": [
                {
                    "calendarDate": (today - timedelta(days=i * 7)).isoformat(),
                    "score": 600 + i * 7,
                    "unit": "synthetic score",
                }
                for i in range(13)
            ],
            "running_tolerance": [
                {
                    "calendarDate": (today - timedelta(days=i * 7)).isoformat(),
                    "tolerance": 42 + i * 0.8,
                    "unit": "synthetic load",
                }
                for i in range(13)
            ],
            "sleep": [
                {
                    "calendarDate": (today - timedelta(days=i)).isoformat(),
                    "sleepTimeSeconds": 25200 + (i % 3) * 900,
                    "sleepStartTimestampGMT": int(
                        (
                            datetime.combine(
                                today - timedelta(days=i),
                                datetime.min.time(),
                                tzinfo=timezone.utc,
                            )
                            - timedelta(hours=1, minutes=30)
                        ).timestamp()
                        * 1000
                    ),
                    "sleepEndTimestampGMT": int(
                        (
                            datetime.combine(
                                today - timedelta(days=i),
                                datetime.min.time(),
                                tzinfo=timezone.utc,
                            )
                            + timedelta(hours=6)
                        ).timestamp()
                        * 1000
                    ),
                    "sleepStartTimestampLocal": int(
                        (
                            datetime.combine(
                                today - timedelta(days=i),
                                datetime.min.time(),
                                tzinfo=timezone(timedelta(hours=2)),
                            )
                            - timedelta(hours=1, minutes=30)
                        ).timestamp()
                        * 1000
                    ),
                    "sleepEndTimestampLocal": int(
                        (
                            datetime.combine(
                                today - timedelta(days=i),
                                datetime.min.time(),
                                tzinfo=timezone(timedelta(hours=2)),
                            )
                            + timedelta(hours=6)
                        ).timestamp()
                        * 1000
                    ),
                }
                for i in range(90)
            ],
        }
    )
    from backend.performance.history import append_garmin_performance_history

    append_garmin_performance_history(garmin, None, today)
    with server.database_manager().unit_of_work() as db:
        server.KEY_VALUE_REPOSITORY.set(db, "garmin_snapshot", json.dumps(garmin))


def _upgrade_preview_demo(today):
    """Add the expanded standard-fixture records without duplicating v1 data."""
    with server.database_manager().unit_of_work() as db:
        payload = server.SNAPSHOT_REPOSITORY.latest_payload(db)
        snapshot = json.loads(payload) if payload else {}
    wellness = snapshot.get("recent_wellness")
    if not isinstance(wellness, list):
        wellness = []
    if not wellness:
        wellness = [
            {
                "id": (today - timedelta(days=offset)).isoformat(),
                "eftp": 260 + offset / 4,
            }
            for offset in range(90)
        ]
    for row in wellness:
        try:
            day = datetime.fromisoformat(
                str(row.get("id") or row.get("date"))[:10]
            ).date()
        except (TypeError, ValueError):
            continue
        offset = (today - day).days
        if not 0 <= offset < 90:
            continue
        row.setdefault(
            "weight",
            round(73.4 - (89 - offset) * 0.018 + (offset % 5) * 0.12, 2)
            if offset % 5 != 4
            else None,
        )
        row.setdefault(
            "bodyFat",
            round(16.8 - (89 - offset) * 0.015 + (offset % 3) * 0.2, 1)
            if offset % 9 == 0
            else None,
        )
        row.setdefault(
            "sport_info",
            [
                {
                    "types": ["Ride"],
                    "mmp_model": {
                        "ftp": round(258 + (89 - offset) * 0.28 + (offset % 4) * 1.4)
                    },
                }
            ],
        )
    raw = snapshot.get("raw_provider_data")
    raw = raw if isinstance(raw, dict) else {}
    snapshot.update(
        {
            "recent_wellness": wellness,
            "raw_provider_data": {**raw, "wellness": wellness},
        }
    )
    snapshot.setdefault("synced_at", server.runtime_clock.utc_now())
    garmin = _fixture_demo_garmin(today, demo_performance_history(today))
    with server.database_manager().unit_of_work() as db:
        server.SNAPSHOT_REPOSITORY.save(db, snapshot, snapshot["synced_at"])
        server.KEY_VALUE_REPOSITORY.set(db, "garmin_snapshot", json.dumps(garmin))
    _fixture_seed_equipment(today, garmin)
    _fixture_seed_calendar(today)
    _fixture_seed_wave2(today, snapshot, garmin)
    with server.database_manager().unit_of_work() as db:
        server.KEY_VALUE_REPOSITORY.set(
            db, "preview_demo_seed_version", FIXTURE_DEMO_SEED_VERSION
        )
    return {"ready": True, "seed_version": FIXTURE_DEMO_SEED_VERSION}


def seed_preview_demo():
    """Populate only the disposable preview with fake data across the main areas."""
    with server.database_manager().unit_of_work() as db:
        version = server.KEY_VALUE_REPOSITORY.get(db, "preview_demo_seed_version")
        legacy_seeded = server.KEY_VALUE_REPOSITORY.get(db, "preview_demo_seeded")
        if version == FIXTURE_DEMO_SEED_VERSION:
            return {"ready": True}
    if legacy_seeded or version:
        return _upgrade_preview_demo(server.ATHLETE_CLOCK.now().date())
    seed_training_features()
    today = server.ATHLETE_CLOCK.now().date()
    server.ATHLETE_DATA.profile().save(
        {
            **server.ATHLETE_DATA.profile().get(),
            "name": "Demo-Athlet",
            "sports": "Cycling, Running",
            "goals": "Ausdauer verbessern und entspannt beim Radmarathon starten.",
            "training_background": "Mehrere Jahre Rad- und Lauftraining. Synthetisches Beispielprofil.",
            "typical_weekly_volume": "6–8 Stunden",
            "availability": "Dienstag, Donnerstag und Wochenende",
            "weight_kg": 72,
            "height_cm": 180,
            "sleep_target_hours": 8,
            "equipment": "Rennrad mit Leistungsmesser, Laufschuhe",
            "fueling_tolerance": "60–80 g Kohlenhydrate pro Stunde",
        }
    )
    for offset in range(56):
        day = today - timedelta(days=offset)
        server.ATHLETE_DATA.checkin().save(
            {
                "checkin_date": day.isoformat(),
                "soreness": offset % 4,
                "stress": 2 + offset % 4,
                "motivation": 7 + offset % 3,
                "available_minutes": 90,
                "day_form": "Erholt" if offset % 3 else "Etwas schwere Beine",
                "day_status": "rest" if day.weekday() == 1 else "unknown",
                "tag_answers": {
                    "travel": offset % 7 == 0,
                    "late_meal": offset % 3 == 0,
                    "high_stress": offset % 4 == 0,
                },
            }
        )
    nutrition = server.NUTRITION_ASSEMBLY.service()
    nutrition.save_template(
        {
            "name": "Demo-Porridge",
            "description": "Haferflocken, Banane und Joghurt",
            "kcal": 520,
            "carbs_g": 78,
            "protein_g": 22,
            "fat_g": 12,
            "source": "manual",
        }
    )
    for offset in range(7):
        for description, kcal, carbs, protein, fat in [
            ("Porridge mit Banane", 520, 78, 22, 12),
            ("Reis mit Gemüse und Tofu", 720, 95, 32, 22),
            ("Pasta mit Tomatensauce", 650, 90, 25, 18),
        ]:
            nutrition.log_meal(
                {
                    "meal_date": (today - timedelta(days=offset)).isoformat(),
                    "description": description,
                    "kcal": kcal,
                    "carbs_g": carbs,
                    "protein_g": protein,
                    "fat_g": fat,
                    "source": "manual",
                }
            )
    workouts = [
        {
            "date": (today + timedelta(days=offset)).isoformat(),
            "name": name,
            "sport": sport,
            "duration_minutes": duration,
            "description": description,
            "target": "AUTO",
            "rationale": "Synthetische Vorschau",
        }
        for offset, name, sport, duration, description in [
            (2, "Lockerer Dauerlauf", "Run", 40, "- 40m Z1 HR"),
            (
                3,
                "Radintervalle",
                "Ride",
                60,
                "- 15m 50%\n- 5m 100%\n- 5m 50%\n- 5m 100%\n- 5m 50%\n- 5m 100%\n- 5m 50%\n- 15m 50%",
            ),
            (5, "Grundlagenausfahrt", "Ride", 90, "- 90m 65%"),
        ]
    ]
    server.PLANNING_WORKFLOWS.local_plan_creation_service().save(workouts)
    history = demo_performance_history(today)
    garmin = _fixture_demo_garmin(today, history)
    _fixture_seed_equipment(today, garmin)
    _fixture_seed_calendar(today)
    # Wave 2 broadens the disposable dataset while keeping all identifiers
    # deterministic so repeated fixture requests remain idempotent.
    snapshot = {"recent_activities": []}
    with server.database_manager().unit_of_work() as db:
        payload = server.SNAPSHOT_REPOSITORY.latest_payload(db)
        snapshot = json.loads(payload) if payload else snapshot
    _fixture_seed_wave2(today, snapshot, garmin)
    with server.database_manager().unit_of_work() as db:
        server.KEY_VALUE_REPOSITORY.set(db, "garmin_snapshot", json.dumps(garmin))
        for role, content in [
            ("user", "Wie sieht meine Trainingswoche aus?"),
            (
                "assistant",
                "## Deine Beispielwoche\n\nDu hast Rad- und Laufeinheiten absolviert. Für die nächsten Tage sind ein lockerer Lauf, Radintervalle und eine Grundlagenausfahrt geplant.\n\nAchte auf ausreichenden Schlaf und regelmäßige Mahlzeiten. Diese Unterhaltung und alle Werte sind synthetische Testdaten.",
            ),
        ]:
            server.CHAT_REPOSITORY.add(db, role, content)
        server.KEY_VALUE_REPOSITORY.set(db, "preview_demo_seeded", "1")
        server.KEY_VALUE_REPOSITORY.set(
            db, "preview_demo_seed_version", FIXTURE_DEMO_SEED_VERSION
        )
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
            from backend.activities.detail_store import (
                ActivityDetailStore,
                summary_fingerprint,
            )
            from backend.performance.session_analysis import (
                aerobic_analysis,
                interval_quality,
            )

            today = server.ATHLETE_CLOCK.now().date().isoformat()
            activity = {
                "id": "FixtureCase-1",
                "name": "Synthetic ride <img src=x>",
                "type": "Ride",
                "start_date_local": f"{today}T08:00:00",
                "moving_time": 3600,
                "distance": 25000,
                "icu_training_load": 50,
            }
            snapshot = {
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "athlete": {},
                "recent_wellness": [],
                "recent_activities": [activity],
                "raw_provider_data": {"activities": [activity]},
            }
            with server.database_manager().unit_of_work() as db:
                server.SNAPSHOT_REPOSITORY.save(db, snapshot, snapshot["synced_at"])
            detailed = {
                **activity,
                "icu_ftp": 250,
                "streams": {
                    "time": list(range(3601)),
                    "watts": [200] * 3601,
                    "heartrate": [140] * 3601,
                },
            }
            ActivityDetailStore(server.database_manager()).save(
                activity["id"],
                {
                    "activity_id": activity["id"],
                    "activity": detailed,
                    "summary_sha256": summary_fingerprint(activity),
                    "session_analysis": {
                        "aerobic": aerobic_analysis(detailed),
                        "interval_quality": interval_quality(detailed, None),
                    },
                    "source": "Intervals.icu",
                    "observed_at": datetime.now(timezone.utc).isoformat(),
                    "full_resolution": True,
                    "available_streams": ["time", "watts", "heartrate"],
                },
            )
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
if __name__ == "__main__":
    server.main()
