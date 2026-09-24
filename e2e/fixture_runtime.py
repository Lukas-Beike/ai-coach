"""Fresh SQLCipher runtime for local integration tests; all providers are blocked."""
import json
import os
import sys
from datetime import timedelta

# This file is mounted only in disposable test containers, never normal startup.
os.environ.update({
    "DATA_DIR": "/data/coach-fixture-data",
    "APP_PASSWORD": "e2e-fixture-password-1234",
    "OPENAI_API_KEY": "",
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


def blocked_provider(*args, **kwargs):
    raise server.AppError(503, "Synthetic provider unavailable", reason="fixture_provider_unavailable")


server.provider_http.JsonHttpClient.request = blocked_provider


class FixtureConversationProvisionService:
    def ensure(self, *args, **kwargs):
        return "fixture-conversation"


server.coach_conversation_provision_service = FixtureConversationProvisionService
# Browser scenarios deliberately poll and reload the single disposable fixture
# far more aggressively than one athlete does. Rate limiting has dedicated unit
# coverage; disable it here to keep unrelated UI scenarios order-independent.
server.RATE_LIMITER.allow = lambda key, limit, window_seconds: (True, 0)


def fixture_coach_response(payload, **kwargs):
    """Canned model outputs exercise HTTP/worker/storage, not language inference."""
    value = payload.get("input")
    if isinstance(value, list):
        outputs = [json.loads(item["output"]) for item in value if item.get("type") == "function_call_output"]
        question = next((item.get("question") for item in outputs if item.get("question")), None)
        return {"output_text": question or "Deine Rückmeldung ist gespeichert."}
    context = json.loads(value)["dialogue"]
    current_id = context["current_user_message_id"]
    if context.get("pending_request"):
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


server.coach_response_transport = FixtureResponseTransport
initialise = server.initialise_database
artifact = {}


def stage_fixture_artifact():
    today = server.local_now().date()
    artifact.update(server.training_plan_artifact_service().stage({"payload": {
        "plan_name": "Fixture sport contract",
        "workouts": [{"date": (today + timedelta(days=index)).isoformat(), "name": f"HTTP fixture {sport}", "sport": sport, "duration_minutes": 30,
                      "description": {"Run": "- 30m Z1 HR", "WeightTraining": "Synthetic local workout",
                                      "VirtualRide": "- 30m 60%", "Swim": "- 30m Z1 Pace"}[sport]}
                     for index, sport in enumerate(("Run", "WeightTraining", "VirtualRide", "Swim"))],
    }}, "fixture-conversation", "fixture-stage"))


def initialise_fixture():
    initialise()
    stage_fixture_artifact()


class FixtureHandler(server.RequestHandler):
    def do_GET(self):
        if self.path == "/api/fixture/plan":
            try:
                self.auth_service.require_auth(self)
                with server.DB_LOCK, server.database_manager().unit_of_work() as db:
                    current = db.execute("SELECT status FROM coach_plan_artifacts WHERE id=?", (artifact.get("artifact_id"),)).fetchone()
                if not current or current["status"] != "draft":
                    stage_fixture_artifact()
                self.send_json(200, artifact)
            except server.AppError as error:
                self.send_json(error.status, {"error": error.message})
            return
        super().do_GET()


server.initialise_database = initialise_fixture
server.RequestHandler = FixtureHandler
server.main()
