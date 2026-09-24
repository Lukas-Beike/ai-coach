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
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

from backend.config import Config
from backend.errors import AppError

REDACTED_PATH = "[REDACTED_PATH]"
REDACTED_URL_QUERY_KEYS = frozenset({
    "access_token", "api_key", "apikey", "auth", "authorization", "credential", "key",
    "password", "refresh_token", "secret", "signature", "sig", "token",
})
URL_VALUE_RE = re.compile(r"(?i)https?://[^\s<>\"'`]+")
OPENAI_RESPONSE_ERROR_CODES = frozenset({
    "server_error", "rate_limit_exceeded", "invalid_prompt", "data_residency_mismatch",
    "bio_policy", "misalignment_policy_violation", "vector_store_timeout", "invalid_image",
    "invalid_image_format", "invalid_base64_image", "invalid_image_url", "image_too_large",
    "image_too_small", "image_parse_error", "image_content_policy_violation", "invalid_image_mode",
    "image_file_too_large", "unsupported_image_media_type", "empty_image_file",
    "failed_to_download_image", "image_file_not_found",
})

DIAGNOSTIC_CAPTURE_DURATION_SECONDS = 60 * 60
DIAGNOSTIC_CAPTURE_MAX_ENTRIES = 1500
DIAGNOSTIC_CAPTURE_STATE_KEY = "diagnostic_capture_state"
DIAGNOSTIC_CAPTURE_ENTRIES_KEY = "diagnostic_capture_entries"
DIAGNOSTIC_CAPTURE_VALIDATION_ERROR = "Die Diagnoseaufzeichnung erwartet enabled=true oder enabled=false."


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


def safe_response_headers(headers: Any, *, redact: Callable[[str], str]) -> dict[str, str]:
    """Keep only bounded transport headers suitable for diagnostics."""
    if headers is None:
        return {}
    allowed = {"content-type", "content-length", "date", "retry-after", "server"}
    result: dict[str, str] = {}
    try:
        for key, value in headers.items():
            name = str(key).strip().casefold()
            if name in allowed or name.startswith("x-ratelimit-"):
                result[name] = redact(str(value))[:160]
    except (AttributeError, TypeError, ValueError, RuntimeError):
        return {}
    return result


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


def safe_diagnostic_context(value: Any) -> dict[str, Any]:
    """Keep selected request metadata useful without retaining request contents."""
    if not isinstance(value, dict):
        return {}
    safe: dict[str, Any] = {}
    allowed = {"window_start", "window_end", "date", "latest", "range_supported", "email_configured", "tokenstore_exists"}
    for key, item in value.items():
        key_text = str(key)[:80]
        if key_text in allowed:
            safe[key_text] = item if item is None or isinstance(item, (bool, int, float)) else str(item)[:40]
    return safe


def diagnostic_mapping_shape(value: dict[Any, Any], depth: int) -> dict[str, Any]:
    fields = [
        text[:80] if re.fullmatch(r"(?a:[A-Za-z][\w-]{0,79})", text) else "[nonstandard]"
        for key in list(value)[:50]
        for text in (str(key),)
    ]
    result: dict[str, Any] = {"type": "object", "field_count": len(value), "fields": fields}
    if depth < 1 and value:
        result["sample"] = diagnostic_response_shape(next(iter(value.values())), depth + 1)
    return result


def diagnostic_sequence_shape(value: list[Any] | tuple[Any, ...], depth: int) -> dict[str, Any]:
    result: dict[str, Any] = {"type": "array", "items": len(value)}
    if depth < 1 and value:
        result["item_shape"] = diagnostic_response_shape(value[0], depth + 1)
    return result


def diagnostic_response_shape(value: Any, depth: int = 0) -> dict[str, Any]:
    """Describe a response without retaining athlete or provider payload values."""
    if value is None:
        return {"type": "null"}
    if isinstance(value, dict):
        return diagnostic_mapping_shape(value, depth)
    if isinstance(value, (list, tuple)):
        return diagnostic_sequence_shape(value, depth)
    if isinstance(value, bool):
        return {"type": "boolean"}
    if isinstance(value, (int, float)):
        return {"type": "number"}
    if isinstance(value, str):
        return {"type": "string", "length": len(value)}
    return {"type": type(value).__name__}


def diagnostic_capture_response(value: Any) -> dict[str, Any]:
    """Return response shape metadata without retaining response contents."""
    return {"shape": diagnostic_response_shape(value)}


def safe_diagnostic_error(exc: BaseException) -> dict[str, Any]:
    """Expose only classified technical exception metadata during user debugging."""
    status = getattr(exc, "status", None) or getattr(exc, "code", None)
    result: dict[str, Any] = {"type": type(exc).__name__}
    if isinstance(status, int) and not isinstance(status, bool):
        result["status"] = status
    reason = str(getattr(exc, "reason", "") or "").strip()
    if reason and re.fullmatch(r"[a-z_]{1,80}", reason):
        result["reason"] = reason
    validation_reason = str(getattr(exc, "validation_reason", "") or "").strip()
    if validation_reason and re.fullmatch(r"[a-z_]{1,80}", validation_reason):
        result["validation_reason"] = validation_reason
    provider_code = getattr(exc, "provider_error_code", None)
    if isinstance(provider_code, str) and provider_code in OPENAI_RESPONSE_ERROR_CODES:
        result["provider_error_code"] = provider_code
    return result


def _utc_datetime(clock: Callable[[], datetime | str]) -> datetime:
    value = clock()
    if isinstance(value, datetime):
        current = value
    else:
        current = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


class DiagnosticCapture:
    """Own user-enabled, bounded diagnostic capture state and synchronization."""

    def __init__(
        self,
        get_kv: Callable[[str], str | None],
        set_kv: Callable[[str, str], None],
        redactor: Redactor,
        clock: Callable[[], datetime | str],
        *,
        duration_seconds: int = DIAGNOSTIC_CAPTURE_DURATION_SECONDS,
        max_entries: int = DIAGNOSTIC_CAPTURE_MAX_ENTRIES,
        state_key: str = DIAGNOSTIC_CAPTURE_STATE_KEY,
        entries_key: str = DIAGNOSTIC_CAPTURE_ENTRIES_KEY,
    ) -> None:
        self._get_kv = get_kv
        self._set_kv = set_kv
        self._redactor = redactor
        self._clock = clock
        self._duration_seconds = duration_seconds
        self._max_entries = max_entries
        self._state_key = state_key
        self._entries_key = entries_key
        self._lock = threading.RLock()

    def _state(self) -> dict[str, Any]:
        try:
            value = json.loads(self._get_kv(self._state_key) or "{}")
        except (TypeError, ValueError):
            value = {}
        return value if isinstance(value, dict) else {}

    def _entries(self) -> list[dict[str, Any]]:
        try:
            entries = json.loads(self._get_kv(self._entries_key) or "[]")
        except (TypeError, ValueError):
            return []
        if not isinstance(entries, list):
            return []
        return [
            self._redactor.sanitize_log_value(entry)
            for entry in entries
            if isinstance(entry, dict)
        ][-self._max_entries:]

    def _active(self, state: dict[str, Any], now: datetime) -> bool:
        expires_at = str(state.get("expires_at") or "")
        try:
            expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if expiry.tzinfo is None:
                return False
            return expiry.astimezone(timezone.utc) > now
        except (TypeError, ValueError):
            return False

    def status(self) -> dict[str, Any]:
        with self._lock:
            state = self._state()
            now = _utc_datetime(self._clock)
            active = self._active(state, now)
            if not active and state:
                self._set_kv(self._state_key, "")
            expires_at = str(state.get("expires_at") or "")
            entries = self._entries()
            return {
                "active": active,
                "started_at": state.get("started_at") if active else None,
                "expires_at": expires_at if active else None,
                "entries": len(entries),
                "maximum_entries": self._max_entries,
            }

    def entries(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._entries()

    def set_enabled(self, enabled: Any) -> dict[str, Any]:
        """Enable a one-hour, user-initiated technical capture or stop it early."""
        if enabled is not True and enabled is not False:
            raise AppError(400, DIAGNOSTIC_CAPTURE_VALIDATION_ERROR)
        with self._lock:
            if enabled:
                now = _utc_datetime(self._clock)
                expires_at = (now + timedelta(seconds=self._duration_seconds)).isoformat()
                self._set_kv(
                    self._state_key,
                    json.dumps({"started_at": now.isoformat(), "expires_at": expires_at}, separators=(",", ":")),
                )
                self._set_kv(self._entries_key, "[]")
            else:
                self._set_kv(self._state_key, "")
            return self.status()

    def capture(self, event: str, details: dict[str, Any]) -> None:
        """Persist bounded metadata only while the athlete enabled capture."""
        with self._lock:
            state = self._state()
            now = _utc_datetime(self._clock)
            if not self._active(state, now):
                if state:
                    self._set_kv(self._state_key, "")
                return
            entries = self._entries()
            entries.append({
                "timestamp": now.isoformat(),
                "event": self._redactor.sanitize_log_value(str(event)[:80]),
                "details": self._redactor.sanitize_log_value(details),
            })
            self._set_kv(
                self._entries_key,
                json.dumps(entries[-self._max_entries:], ensure_ascii=False, separators=(",", ":")),
            )
