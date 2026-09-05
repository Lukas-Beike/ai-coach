"""Fresh SQLCipher runtime for local integration tests; all providers are blocked."""
import os
import sys
from datetime import timedelta

# This file is mounted only in disposable test containers, never normal startup.
os.environ.update({
    "DATA_DIR": "/tmp/coach-fixture-data",
    "APP_PASSWORD": "e2e-fixture-password-1234",
    "OPENAI_API_KEY": "",
    "INTERVALS_API_KEY": "",
    "GARMIN_EMAIL": "",
    "GARMIN_PASSWORD": "",
    "GARMINTOKENS": "/tmp/fixture-no-tokens",
    "GARMIN_FIXTURE_PATH": "",
    "CALENDAR_ICAL_URL": "",
    "COOKIE_SECURE": "false",
})
sys.path.insert(0, "/app")
import server


def blocked_provider(*args, **kwargs):
    raise server.AppError(503, "Synthetic provider unavailable", reason="fixture_provider_unavailable")


server.http_json = blocked_provider
server.ensure_conversation = lambda: "fixture-conversation"
initialise = server.initialise_database
artifact = {}


def initialise_fixture():
    initialise()
    today = server.local_now().date()
    artifact.update(server._stage_coach_artifact("fixture-conversation", "fixture-stage", {
        "plan_name": "Fixture sport contract",
        "workouts": [{"date": (today + timedelta(days=index)).isoformat(), "name": f"HTTP fixture {sport}", "sport": sport, "duration_minutes": 30, "description": "Synthetic local workout"}
                     for index, sport in enumerate(("Run", "WeightTraining", "VirtualRide", "Swim"))],
    }))


class FixtureHandler(server.RequestHandler):
    def do_GET(self):
        if self.path == "/api/fixture/plan":
            try:
                server.require_auth(self)
                self.send_json(200, artifact)
            except server.AppError as error:
                self.send_json(error.status, {"error": error.message})
            return
        super().do_GET()


server.initialise_database = initialise_fixture
server.RequestHandler = FixtureHandler
server.main()
