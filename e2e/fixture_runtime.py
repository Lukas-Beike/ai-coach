"""Fresh SQLCipher runtime for local integration tests; all providers are blocked."""
import os
import sys

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
server.main()
