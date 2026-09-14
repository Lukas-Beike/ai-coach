"""Explicit application configuration loading.

This module has no application imports and performs no work at import time.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import re
from typing import Mapping, MutableMapping


DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


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
