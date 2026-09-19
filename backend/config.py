"""Explicit application configuration loading.

This module has no application imports and performs no work at import time.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.errors import AppError

DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"
SETTINGS_SECRET_KEYS = ("OPENAI_API_KEY", "GEMINI_API_KEY", "INTERVALS_API_KEY", "GARMIN_PASSWORD")
SETTINGS_VALUE_KEYS = ("GARMIN_EMAIL", "GARMINTOKENS", "GARMIN_FIXTURE_PATH")
SETTINGS_KEYS = SETTINGS_SECRET_KEYS + SETTINGS_VALUE_KEYS


def _read_local_env(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _parse_local_env_line(raw_line: str) -> tuple[str, str] | None:
    line = raw_line.strip()
    if not line or line.startswith("#"):
        return None
    if line.startswith("export "):
        line = line[7:].lstrip()
    key, separator, value = line.partition("=")
    key = key.strip()
    if not separator or not re.fullmatch(r"(?a:(?!\d)\w+)", key):
        return None
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return key, value


def load_local_env(root: Path, data_dir: Path, environ: MutableMapping[str, str] | None = None) -> None:
    """Load persisted settings without overriding non-empty process values."""
    target = environ if environ is not None else os.environ
    for env_path in (root / ".env", data_dir / ".env"):
        for raw_line in _read_local_env(env_path):
            parsed = _parse_local_env_line(raw_line)
            if parsed and not target.get(parsed[0]):
                target[parsed[0]] = parsed[1]


def _env_int(environ: Mapping[str, str], name: str, default: int) -> int:
    try:
        return int(environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(environ: Mapping[str, str], name: str, default: bool = False) -> bool:
    value = str(environ.get(name, "")).strip().casefold()
    return default if not value else value in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    port: int
    openai_api_key: str
    openai_base_url: str
    openai_model: str
    gemini_api_key: str
    gemini_model: str
    ai_provider: str
    intervals_api_key: str
    intervals_athlete_id: str
    garmin_email: str
    garmin_password: str
    garmin_tokenstore: str
    garmin_fixture_path: str
    calendar_ical_url: str
    app_password: str
    secure_cookies: bool
    data_retention_days: int


def security_configuration_error(config: Config, *, sqlcipher_available: bool) -> str | None:
    if not config.app_password:
        return "APP_PASSWORD ist nicht konfiguriert. Lege ein langes, zufälliges Passwort als Container-Umgebungsvariable fest."
    if len(config.app_password) < 12:
        return "APP_PASSWORD muss mindestens 12 Zeichen lang sein."
    if not sqlcipher_available:
        return "SQLCipher ist nicht verfügbar; die verschlüsselte Datenbank kann nicht geöffnet werden."
    return None


def _submitted_settings(values: Any) -> dict[str, str]:
    if not isinstance(values, dict):
        raise AppError(400, "Die Einstellungen müssen als Objekt gesendet werden.")
    updates: dict[str, str] = {}
    for key in SETTINGS_KEYS:
        if key not in values:
            continue
        raw = str(values.get(key) or "").replace("\r", "").replace("\n", "").strip()
        if raw:
            updates[key] = raw
    if not updates:
        raise AppError(400, "Keine neuen Zugangsdaten oder Einstellungen eingegeben.")
    return updates


def _read_settings_file(env_path: Path) -> list[str]:
    try:
        return env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
    except OSError as exc:
        raise AppError(500, f".env konnte nicht gelesen werden: {exc}") from exc


def _rewrite_settings_lines(
    lines: list[str],
    updates: dict[str, str],
    environ: MutableMapping[str, str] | None = None,
) -> list[str]:
    seen: set[str] = set()
    rewritten: list[str] = []
    for line in lines:
        match = re.match(r"^(\s*(?:export\s+)?)(?a:((?!\d)\w+))(\s*=).*$", line)
        key = match.group(2) if match else None
        if key in updates and match:
            rewritten.append(f"{match.group(1)}{key}={updates[key]}")
            seen.add(key)
        else:
            rewritten.append(line)
    for key, value in updates.items():
        if key not in seen:
            rewritten.append(f"{key}={value}")
        target = environ if environ is not None else os.environ
        target[key] = value
    return rewritten


def save_persistent_settings(
    data_dir: Path,
    values: Any,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, Any]:
    """Persist explicitly submitted settings without returning their values."""
    updates = _submitted_settings(values)
    env_path = data_dir / ".env"
    target = environ if environ is not None else os.environ
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        rewritten = _rewrite_settings_lines(_read_settings_file(env_path), updates, target)
        env_path.write_text("\n".join(rewritten) + "\n", encoding="utf-8")
    except AppError:
        raise
    except OSError as exc:
        raise AppError(500, f".env konnte nicht gespeichert werden: {exc}") from exc
    return {"status": "ok", "updated": sorted(updates), "restart_required": True}


def load_config(root: Path, data_dir: Path, environ: MutableMapping[str, str] | None = None) -> Config:
    """Load one independent configuration snapshot from explicit paths."""
    target = environ if environ is not None else os.environ
    load_local_env(root, data_dir, target)
    value = target.get
    return Config(
        port=_env_int(target, "PORT", 8090),
        openai_api_key=value("OPENAI_API_KEY", ""),
        openai_base_url=value("OPENAI_BASE_URL", DEFAULT_OPENAI_BASE_URL),
        openai_model=value("OPENAI_MODEL", "gpt-5.6-luna"),
        gemini_api_key=value("GEMINI_API_KEY", ""),
        gemini_model=value("GEMINI_MODEL", "gemini-3.8-flash"),
        ai_provider=value("AI_PROVIDER", "").strip().casefold(),
        intervals_api_key=value("INTERVALS_API_KEY", ""),
        intervals_athlete_id=value("INTERVALS_ATHLETE_ID", "0"),
        garmin_email=value("GARMIN_EMAIL", ""),
        garmin_password=value("GARMIN_PASSWORD", ""),
        garmin_tokenstore=value("GARMINTOKENS", str(data_dir / "garmin_tokens")),
        garmin_fixture_path=value("GARMIN_FIXTURE_PATH", ""),
        calendar_ical_url=value("CALENDAR_ICAL_URL", ""),
        app_password=value("APP_PASSWORD", ""),
        secure_cookies=_env_bool(target, "COOKIE_SECURE"),
        data_retention_days=_env_int(target, "DATA_RETENTION_DAYS", -1),
    )
