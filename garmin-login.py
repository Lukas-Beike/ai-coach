"""One-time interactive Garmin login; stores refresh tokens in the persistent /data volume."""
from __future__ import annotations

import os
from getpass import getpass
from pathlib import Path

from garminconnect import Garmin


email = os.environ.get("GARMIN_EMAIL") or input("Garmin E-Mail: ").strip()
password = os.environ.get("GARMIN_PASSWORD") or getpass("Garmin Passwort: ")
tokenstore = os.environ.get("GARMINTOKENS", "/data/garmin_tokens")
Path(tokenstore).parent.mkdir(parents=True, exist_ok=True)
client = Garmin(email, password, prompt_mfa=lambda: getpass("Garmin MFA-Code: "))
client.login(tokenstore)
print(f"Garmin-Login erfolgreich. Tokenstore: {tokenstore}")
