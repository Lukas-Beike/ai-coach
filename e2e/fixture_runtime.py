"""Fresh SQLCipher runtime for local integration tests; all providers are blocked."""
import json
import os
import sys
from datetime import timedelta

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
    if current_message in {"E2E nutrition: confirm meal", "E2E nutrition: half portion", "E2E nutrition: update meal", "E2E nutrition: delete meal"}:
        nutrition = server.NUTRITION_ASSEMBLY.service()
        templates = nutrition.list_templates()
        if current_message == "E2E nutrition: confirm meal":
            name = "save_nutrition_template"
            arguments = {"payload": {"name": "Fixture breakfast", "description": "80 g oats - <img src=x onerror=alert(1)>", "kcal": 400, "carbs_g": 60, "protein_g": 12, "fat_g": 8, "source": "coach"}}
        elif current_message == "E2E nutrition: half portion":
            name = "log_nutrition_template"
            arguments = {"id": templates[0]["id"], "portions": 0.5}
        elif current_message == "E2E nutrition: update meal":
            name = "save_nutrition_template"
            arguments = {"payload": {**templates[0], "kcal": 600}}
            arguments["payload"].pop("updated_at", None)
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


class FixtureHandler(server.HTTP_API.request_handler_class()):
    def do_GET(self):
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
