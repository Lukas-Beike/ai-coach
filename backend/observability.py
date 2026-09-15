"""Redaction and structured logging helpers.

The module deliberately has no application-level side effects.  Configuration
is supplied by the caller so that secrets are read only while a value is being
redacted and tests can use isolated configuration snapshots.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

from backend.config import Config

REDACTED_PATH = "[REDACTED_PATH]"
REDACTED_URL_QUERY_KEYS = frozenset({
    "access_token", "api_key", "apikey", "auth", "authorization", "credential", "key",
    "password", "refresh_token", "secret", "signature", "sig", "token",
})
URL_VALUE_RE = re.compile(r"(?i)https?://[^\s<>\"'`]+")


def _secret_variants(value: Any) -> set[str]:
    """Return raw and URL-encoded forms without exposing the value."""
    candidate = str(value or "")
    if not candidate:
        return set()
    variants = {candidate}
    for _ in range(2):
        for item in tuple(variants):
            variants.add(unquote(item))
            variants.add(quote(item, safe=""))
    return {item for item in variants if len(item) >= 4}


def safe_url_netloc(parsed: Any) -> str:
    """Keep a provider host for diagnostics while dropping URL userinfo."""
    try:
        hostname = str(parsed.hostname or "")
        port = parsed.port
    except ValueError:
        return "[REDACTED_HOST]"
    if not hostname:
        return "[REDACTED_HOST]"
    host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
    return f"{host}:{port}" if port else host


def safe_provider_path(path: str) -> str:
    """Keep route structure while removing provider resource identifiers."""
    safe_segments = []
    redact_next = False
    for segment in str(path or "").split("/"):
        if not segment:
            continue
        decoded = unquote(segment)
        was_redacted = redact_next
        if was_redacted:
            safe_segments.append(REDACTED_PATH)
            redact_next = False
        elif re.fullmatch(r"(?:api|v\d+|[a-z][a-z_-]{0,31})", decoded):
            safe_segments.append(decoded)
        else:
            safe_segments.append(REDACTED_PATH)
        if not was_redacted and decoded.casefold() in {
            "athlete", "activities", "activity", "event", "events", "profile", "user", "workout", "workouts",
        }:
            redact_next = True
    return "/" + "/".join(safe_segments)


def _unguessable_url_path_segment(segment: str) -> bool:
    decoded = unquote(segment)
    if len(decoded) >= 32:
        return True
    if len(decoded) < 16:
        return False
    classes = sum(bool(re.search(pattern, decoded)) for pattern in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]"))
    return classes >= 2 and len(set(decoded)) >= 8


def _redact_url(match: re.Match[str]) -> str:
    raw = match.group(0)
    trailing = ""
    while raw and raw[-1] in ".,;:!?)]}":
        trailing = raw[-1] + trailing
        raw = raw[:-1]
    try:
        parsed = urlparse(raw)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
            return match.group(0)
        path_segments = []
        for segment in parsed.path.split("/"):
            path_segments.append(REDACTED_PATH if _unguessable_url_path_segment(segment) else segment)
        path = "/".join(path_segments)
        query_pairs = []
        for key, item in parse_qsl(parsed.query, keep_blank_values=True):
            safe_item = "[REDACTED]" if key.casefold().replace("-", "_") in REDACTED_URL_QUERY_KEYS else item
            query_pairs.append((key, safe_item))
        safe = urlunparse((parsed.scheme.casefold(), safe_url_netloc(parsed), path, "", urlencode(query_pairs), ""))
        return safe + trailing
    except (TypeError, ValueError):
        return "[REDACTED_URL]" + trailing


class Redactor:
    """Redact secrets and sensitive provider metadata from values and errors."""

    def __init__(self, config_supplier: Callable[[], Config]) -> None:
        self._config_supplier = config_supplier

    def safe_calendar_url(self) -> str:
        config = self._config_supplier()
        return self._safe_calendar_url_for_config(config)

    @staticmethod
    def _safe_calendar_url_for_config(config: Config) -> str:
        try:
            parsed = urlparse(str(getattr(config, "calendar_ical_url", "") or ""))
            if parsed.scheme.casefold() in {"http", "https"} and parsed.netloc:
                return urlunparse((parsed.scheme.casefold(), safe_url_netloc(parsed), "/redacted", "", "", ""))
        except (TypeError, ValueError):
            pass
        return "[REDACTED_CALENDAR_URL]"

    def redact_text(self, value: str) -> str:
        """Redact configured secrets and credential-bearing URLs case-insensitively."""
        config = self._config_supplier()
        redacted = str(value or "")
        calendar_url = str(getattr(config, "calendar_ical_url", "") or "")
        calendar_safe_url = self._safe_calendar_url_for_config(config)
        for variant in sorted(_secret_variants(calendar_url), key=len, reverse=True):
            redacted = re.sub(re.escape(variant), calendar_safe_url, redacted, flags=re.IGNORECASE)
        redacted = URL_VALUE_RE.sub(_redact_url, redacted)
        secret_values = (
            getattr(config, "openai_api_key", ""),
            getattr(config, "gemini_api_key", ""),
            getattr(config, "intervals_api_key", ""),
            getattr(config, "garmin_email", ""),
            getattr(config, "garmin_password", ""),
            getattr(config, "garmin_tokenstore", ""),
            getattr(config, "garmin_fixture_path", ""),
            getattr(config, "app_password", ""),
        )
        for secret_value in secret_values:
            for variant in sorted(_secret_variants(secret_value), key=len, reverse=True):
                redacted = re.sub(re.escape(variant), "[REDACTED]", redacted, flags=re.IGNORECASE)
        redacted = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED_OPENAI_KEY]", redacted)
        redacted = re.sub(r"\bAIza[A-Za-z0-9_-]{20,}\b", "[REDACTED_GEMINI_KEY]", redacted)
        redacted = re.sub(r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(basic|bearer)\s+[^\s,\"'}]+", r"\1[REDACTED]", redacted)
        return redacted

    def sanitize_log_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            return {str(key): self.sanitize_log_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [self.sanitize_log_value(item) for item in value]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return self.redact_text(str(value))


class JsonLogFormatter(logging.Formatter):
    """Serialize log records as compact JSON after redacting all values."""

    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self._redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", "log"),
            "message": record.getMessage(),
        }
        context = getattr(record, "context", None)
        if context:
            entry["context"] = context
        if record.exc_info:
            entry["traceback"] = self.formatException(record.exc_info)
        return json.dumps(self._redactor.sanitize_log_value(entry), ensure_ascii=False, separators=(",", ":"))


def configure_logging(
    logger: logging.Logger,
    data_dir: Path,
    log_path: Path,
    redactor: Redactor,
    *,
    stream: TextIO | None = None,
) -> None:
    """Configure one rotating file handler and one stream handler idempotently."""
    if logger.handlers:
        return
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = JsonLogFormatter(redactor)

    file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)


def external_result_context(result: Any) -> dict[str, Any]:
    """Return useful result metadata without logging response contents."""
    if result is None:
        return {"result_type": "null"}
    if isinstance(result, dict):
        return {"result_type": "object", "result_fields": len(result)}
    if isinstance(result, (list, tuple)):
        return {"result_type": "array", "result_items": len(result)}
    return {"result_type": type(result).__name__}
