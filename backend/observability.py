"""Redaction and structured logging helpers.

The module deliberately has no application-level side effects.  Configuration
is supplied by the caller so that secrets are read only while a value is being
redacted and tests can use isolated configuration snapshots.
"""

from __future__ import annotations

import base64
import json
import logging
import re
import sys
import threading
from collections.abc import Callable
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, TextIO
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

from backend.config import Config

REDACTED_PATH = "[REDACTED_PATH]"
REDACTED_URL_QUERY_KEYS = frozenset(
    {
        "access_token",
        "api_key",
        "apikey",
        "auth",
        "authorization",
        "credential",
        "key",
        "password",
        "refresh_token",
        "secret",
        "signature",
        "sig",
        "token",
    }
)
URL_VALUE_RE = re.compile(r"(?i)https?://[^\s<>\"'`]+")
OPENAI_RESPONSE_ERROR_CODES = frozenset(
    {
        "server_error",
        "rate_limit_exceeded",
        "model_not_found",
        "unsupported_parameter",
        "context_length_exceeded",
        "insufficient_quota",
        "billing_hard_limit_reached",
        "invalid_api_key",
        "permission_denied",
        "invalid_prompt",
        "data_residency_mismatch",
        "bio_policy",
        "misalignment_policy_violation",
        "vector_store_timeout",
        "invalid_image",
        "invalid_image_format",
        "invalid_base64_image",
        "invalid_image_url",
        "image_too_large",
        "image_too_small",
        "image_parse_error",
        "image_content_policy_violation",
        "invalid_image_mode",
        "image_file_too_large",
        "unsupported_image_media_type",
        "empty_image_file",
        "failed_to_download_image",
        "image_file_not_found",
    }
)

DIAGNOSTIC_CAPTURE_MAX_ENTRIES = 10000
DIAGNOSTIC_CAPTURE_MAX_BYTES = 16 * 1024 * 1024
DIAGNOSTIC_CAPTURE_MAX_ENTRY_BYTES = 1024 * 1024
DIAGNOSTIC_CAPTURE_ENTRIES_KEY = "diagnostic_capture_entries"
_REDACTED = "[REDACTED]"
_DIAGNOSTIC_SECRET_FIELDS = frozenset(
    {
        "key",
        "credentials",
        "session",
        "sessionid",
        "sessionhash",
        "sessionkey",
        "sessionkeyhash",
        "signature",
        "oauth1",
        "oauth2",
        "csrftoken",
        "csrf",
    }
)
_DIAGNOSTIC_SECRET_SUFFIXES = (
    "password",
    "passwd",
    "passphrase",
    "passwordhash",
    "secret",
    "token",
    "apikey",
    "privatekey",
    "databasekey",
    "encryptionkey",
    "credential",
    "authorization",
    "cookie",
    "csrfhash",
    "sessionid",
    "sessionhash",
)
_DIAGNOSTIC_BINARY_FIELDS = frozenset({"inlinedata", "filedata", "audio", "inputaudio"})
_DIAGNOSTIC_AUTH_RE = re.compile(r"""(?i)\b(?:bearer|basic)\s+[^\s,;"'}]+""")
_DIAGNOSTIC_LABELED_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|secret|api[_-]?key|token|authorization|cookie)\s*[:=]"
)
_DIAGNOSTIC_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.DOTALL
)
_DIAGNOSTIC_DATA_URL_RE = re.compile(r"""data:[^\s,;]+(?:;[^,]*)?,[^\s"']+""")


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
    host = (
        f"[{hostname}]"
        if ":" in hostname and not hostname.startswith("[")
        else hostname
    )
    return f"{host}:{port}" if port else host


def safe_response_headers(
    headers: Any, *, redact: Callable[[str], str]
) -> dict[str, str]:
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
            "athlete",
            "activities",
            "activity",
            "event",
            "events",
            "profile",
            "user",
            "workout",
            "workouts",
        }:
            redact_next = True
    return "/" + "/".join(safe_segments)


def _unguessable_url_path_segment(segment: str) -> bool:
    decoded = unquote(segment)
    if len(decoded) >= 32:
        return True
    if len(decoded) < 16:
        return False
    classes = sum(
        bool(re.search(pattern, decoded))
        for pattern in (r"[a-z]", r"[A-Z]", r"\d", r"[^A-Za-z0-9]")
    )
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
            path_segments.append(
                REDACTED_PATH if _unguessable_url_path_segment(segment) else segment
            )
        path = "/".join(path_segments)
        query_pairs = []
        for key, item in parse_qsl(parsed.query, keep_blank_values=True):
            safe_item = (
                _REDACTED
                if key.casefold().replace("-", "_") in REDACTED_URL_QUERY_KEYS
                else item
            )
            query_pairs.append((key, safe_item))
        safe = urlunparse(
            (
                parsed.scheme.casefold(),
                safe_url_netloc(parsed),
                path,
                "",
                urlencode(query_pairs),
                "",
            )
        )
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
                return urlunparse(
                    (
                        parsed.scheme.casefold(),
                        safe_url_netloc(parsed),
                        "/redacted",
                        "",
                        "",
                        "",
                    )
                )
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
            redacted = re.sub(
                re.escape(variant), calendar_safe_url, redacted, flags=re.IGNORECASE
            )
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
            for variant in sorted(
                _secret_variants(secret_value), key=len, reverse=True
            ):
                redacted = re.sub(
                    re.escape(variant), _REDACTED, redacted, flags=re.IGNORECASE
                )
        redacted = re.sub(
            r"\bsk-[A-Za-z0-9_-]{8,}\b", "[REDACTED_OPENAI_KEY]", redacted
        )
        redacted = re.sub(
            r"\bAIza[A-Za-z0-9_-]{20,}\b", "[REDACTED_GEMINI_KEY]", redacted
        )
        redacted = re.sub(
            r"(?i)(authorization[\"']?\s*[:=]\s*[\"']?)(basic|bearer)\s+[^\s,\"'}]+",
            r"\1" + _REDACTED,
            redacted,
        )
        return redacted

    def sanitize_log_value(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, dict):
            return {
                str(key): self.sanitize_log_value(item) for key, item in value.items()
            }
        if isinstance(value, (list, tuple)):
            return [self.sanitize_log_value(item) for item in value]
        if value is None or isinstance(value, (bool, int, float)):
            return value
        return self.redact_text(str(value))

    def sanitize_diagnostic_value(self, value: Any) -> Any:
        """Retain diagnostic content while removing credentials before storage."""
        config = self._config_supplier()
        encoded_secrets = _encoded_diagnostic_secrets(config)
        return _clean_diagnostic_value(value, self, encoded_secrets)


def _encoded_diagnostic_secrets(config: Config) -> tuple[str, ...]:
    attributes = (
        "openai_api_key",
        "gemini_api_key",
        "intervals_api_key",
        "garmin_email",
        "garmin_password",
        "app_password",
        "calendar_ical_url",
    )
    secrets: set[str] = set()
    for attribute in attributes:
        secret = str(getattr(config, attribute, "") or "")
        if len(secret) >= 4:
            secrets.update(
                (
                    base64.b64encode(secret.encode()).decode(),
                    json.dumps(secret, ensure_ascii=True)[1:-1],
                )
            )
    return tuple(sorted(secrets, key=len, reverse=True))


def _redact_labeled_secrets(value: str) -> str:
    pieces: list[str] = []
    cursor = 0
    for match in _DIAGNOSTIC_LABELED_SECRET_RE.finditer(value):
        newline = value.find("\n", match.end())
        line_end = len(value) if newline < 0 else newline
        delimiters = [
            position
            for char in (",", ";")
            if (position := value.find(char, match.end(), line_end)) >= 0
        ]
        end = min(delimiters, default=line_end)
        pieces.extend(
            (value[cursor : match.start(1)], match.group(1) + "=" + _REDACTED)
        )
        cursor = end
    pieces.append(value[cursor:])
    return "".join(pieces)


def _clean_diagnostic_text(
    value: str, redactor: Redactor, encoded_secrets: tuple[str, ...]
) -> str:
    safe = redactor.redact_text(value)
    for secret in encoded_secrets:
        safe = safe.replace(secret, _REDACTED)
    safe = _DIAGNOSTIC_AUTH_RE.sub("[REDACTED_AUTHORIZATION]", safe)
    safe = _redact_labeled_secrets(safe)
    safe = re.sub(
        r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
        "[REDACTED_TOKEN]",
        safe,
    )
    safe = _DIAGNOSTIC_PRIVATE_KEY_RE.sub("[REDACTED_PRIVATE_KEY]", safe)
    return _DIAGNOSTIC_DATA_URL_RE.sub("[OMITTED_BINARY]", safe)


def _clean_diagnostic_value(
    value: Any, redactor: Redactor, encoded_secrets: tuple[str, ...], depth: int = 0
) -> Any:
    if depth >= 40:
        return {"truncated": True, "reason": "depth_limit"}
    if isinstance(value, str):
        return _clean_diagnostic_string(value, redactor, encoded_secrets, depth)
    if isinstance(value, dict):
        return _clean_diagnostic_mapping(value, redactor, encoded_secrets, depth)
    if isinstance(value, (list, tuple)):
        return [
            _clean_diagnostic_value(child, redactor, encoded_secrets, depth + 1)
            for child in value
        ]
    if isinstance(value, bytes):
        return {"omitted_binary_bytes": len(value)}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _clean_diagnostic_text(str(value), redactor, encoded_secrets)


def _clean_diagnostic_string(
    value: str, redactor: Redactor, encoded_secrets: tuple[str, ...], depth: int
) -> str:
    if value.lstrip().startswith(("{", "[")):
        try:
            decoded = json.loads(value)
        except (ValueError, RecursionError):
            pass
        else:
            return json.dumps(
                _clean_diagnostic_value(decoded, redactor, encoded_secrets, depth + 1),
                ensure_ascii=False,
            )
    return _clean_diagnostic_text(value, redactor, encoded_secrets)


def _clean_diagnostic_mapping(
    value: dict[Any, Any],
    redactor: Redactor,
    encoded_secrets: tuple[str, ...],
    depth: int,
) -> dict[str, Any]:
    result = {}
    for key, child in value.items():
        name = re.sub(r"[^a-z0-9]", "", str(key).casefold())
        result[_clean_diagnostic_text(str(key), redactor, encoded_secrets)] = (
            _clean_diagnostic_field(name, child, redactor, encoded_secrets, depth + 1)
        )
    return result


def _clean_diagnostic_field(
    name: str,
    value: Any,
    redactor: Redactor,
    encoded_secrets: tuple[str, ...],
    depth: int,
) -> Any:
    if name in _DIAGNOSTIC_SECRET_FIELDS or name.endswith(_DIAGNOSTIC_SECRET_SUFFIXES):
        return _REDACTED
    if name in _DIAGNOSTIC_BINARY_FIELDS:
        return "[OMITTED_BINARY]"
    return _clean_diagnostic_value(value, redactor, encoded_secrets, depth)


class JsonLogFormatter(logging.Formatter):
    """Serialize log records as compact JSON after redacting all values."""

    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self._redactor = redactor

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(
                record.created, timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", "log"),
            "message": record.getMessage(),
        }
        context = getattr(record, "context", None)
        if context:
            entry["context"] = context
        if record.exc_info:
            entry["traceback"] = self.formatException(record.exc_info)
        return json.dumps(
            self._redactor.sanitize_log_value(entry),
            ensure_ascii=False,
            separators=(",", ":"),
        )


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

    file_handler = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
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
    allowed = {
        "window_start",
        "window_end",
        "date",
        "latest",
        "range_supported",
        "email_configured",
        "tokenstore_exists",
    }
    for key, item in value.items():
        key_text = str(key)[:80]
        if key_text in allowed:
            safe[key_text] = (
                item
                if item is None or isinstance(item, (bool, int, float))
                else str(item)[:40]
            )
    return safe


def diagnostic_mapping_shape(value: dict[Any, Any], depth: int) -> dict[str, Any]:
    fields = [
        text[:80]
        if re.fullmatch(r"(?a:[A-Za-z][\w-]{0,79})", text)
        else "[nonstandard]"
        for key in list(value)[:50]
        for text in (str(key),)
    ]
    result: dict[str, Any] = {
        "type": "object",
        "field_count": len(value),
        "fields": fields,
    }
    if depth < 1 and value:
        result["sample"] = diagnostic_response_shape(
            next(iter(value.values())), depth + 1
        )
    return result


def diagnostic_sequence_shape(
    value: list[Any] | tuple[Any, ...], depth: int
) -> dict[str, Any]:
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
    for attribute, key in (
        ("provider_error_type", "provider_error_type"),
        ("provider_response_status", "provider_response_status"),
        ("provider_incomplete_reason", "provider_incomplete_reason"),
    ):
        value = getattr(exc, attribute, None)
        if isinstance(value, str) and re.fullmatch(r"[a-z0-9_.\[\]-]{1,160}", value):
            result[key] = value
    return result


class DiagnosticCapture:
    """Keep secret-redacted diagnostic evidence within count and byte limits."""

    def __init__(
        self,
        get_kv: Callable[[str], str | None],
        set_kv: Callable[[str, str], None],
        redactor: Redactor,
        *,
        max_entries: int = DIAGNOSTIC_CAPTURE_MAX_ENTRIES,
        entries_key: str = DIAGNOSTIC_CAPTURE_ENTRIES_KEY,
        batch_size: int = 10,
        max_bytes: int = DIAGNOSTIC_CAPTURE_MAX_BYTES,
        max_entry_bytes: int = DIAGNOSTIC_CAPTURE_MAX_ENTRY_BYTES,
    ) -> None:
        self._get_kv = get_kv
        self._set_kv = set_kv
        self._redactor = redactor
        self._max_entries = max_entries
        self._entries_key = entries_key
        self._batch_size = max(1, batch_size)
        self._max_bytes = max(2048, max_bytes)
        self._max_entry_bytes = min(self._max_bytes - 2, max(1024, max_entry_bytes))
        self._entry_sizes: list[int] = []
        self._total_bytes = 2
        self._entries_cache: list[dict[str, Any]] | None = None
        self._dirty_count = 0
        self._lock = threading.RLock()
        self._flush_lock = threading.Lock()

    def _load_entries(self) -> list[dict[str, Any]]:
        with self._lock:
            if self._entries_cache is not None:
                return self._entries_cache
        try:
            raw = json.loads(self._get_kv(self._entries_key) or "[]")
        except (TypeError, ValueError):
            raw = []
        if not isinstance(raw, list):
            raw = []
        loaded_entries = [
            self._bounded_entry(entry) for entry in raw if isinstance(entry, dict)
        ][-self._max_entries :]
        with self._lock:
            if self._entries_cache is None:
                self._entries_cache = loaded_entries
                self._entry_sizes = [
                    self._entry_bytes(entry) for entry in loaded_entries
                ]
                self._total_bytes = 2 + sum(self._entry_sizes)
                self._trim()
            return self._entries_cache

    @staticmethod
    def _entry_bytes(entry: dict[str, Any]) -> int:
        return (
            len(
                json.dumps(entry, ensure_ascii=False, separators=(",", ":")).encode(
                    "utf-8"
                )
            )
            + 1
        )

    def _bounded_entry(self, entry: dict[str, Any]) -> dict[str, Any]:
        safe = self._redactor.sanitize_diagnostic_value(entry)
        if self._entry_bytes(safe) <= self._max_entry_bytes:
            return safe
        details = safe.get("details")
        if isinstance(details, dict) and self._truncate_details(safe, details):
            return safe
        return self._compact_oversize_entry(safe, details)

    def _truncate_details(self, entry: dict[str, Any], details: dict[str, Any]) -> bool:
        protected = {"error", "provider_error", "last_error", "diagnostic_error"}
        for key in sorted(
            details,
            key=lambda name: len(json.dumps(details[name], ensure_ascii=False)),
            reverse=True,
        ):
            if key in protected:
                continue
            rendered = json.dumps(details[key], ensure_ascii=False)
            details[key] = {
                "truncated": True,
                "original_bytes": len(rendered.encode("utf-8")),
                "preview": rendered[: self._max_entry_bytes // 16],
            }
            if self._entry_bytes(entry) <= self._max_entry_bytes:
                return True
        return False

    def _compact_oversize_entry(
        self, entry: dict[str, Any], details: Any
    ) -> dict[str, Any]:
        compact_errors = {
            key: self._compact_error(details[key])
            for key in ("error", "provider_error", "last_error", "diagnostic_error")
            if isinstance(details, dict) and details.get(key) is not None
        }
        compact_details: dict[str, Any] = {
            "truncated": True,
            "reason": "entry_size_limit",
            **compact_errors,
        }
        compact = {
            "timestamp": entry.get("timestamp"),
            "event": entry.get("event"),
            "details": compact_details,
        }
        if self._entry_bytes(compact) > self._max_entry_bytes:
            compact_details.update({key: {"truncated": True} for key in compact_errors})
        return compact

    def _compact_error(self, value: Any) -> Any:
        if not isinstance(value, dict):
            return str(value)[: min(4000, self._max_entry_bytes // 64)]
        fields = ("code", "type", "param", "message", "reason", "status")
        return {
            key: self._clip_error_field(value[key])
            for key in fields
            if isinstance(value.get(key), (str, int, float, bool))
        } or {"truncated": True}

    def _clip_error_field(self, value: Any) -> Any:
        if isinstance(value, str):
            return value[: min(4000, self._max_entry_bytes // 64)]
        return value

    def _trim(self) -> None:
        while self._entries_cache and (
            len(self._entries_cache) > self._max_entries
            or self._total_bytes > self._max_bytes
        ):
            self._entries_cache.pop(0)
            self._total_bytes -= self._entry_sizes.pop(0)

    def flush(self) -> None:
        with self._flush_lock:
            with self._lock:
                if self._dirty_count <= 0 or self._entries_cache is None:
                    return
                dirty_count = self._dirty_count
                payload = json.dumps(
                    self._entries_cache, ensure_ascii=False, separators=(",", ":")
                )
            try:
                self._set_kv(self._entries_key, payload)
            except Exception:  # noqa: BLE001
                return
            with self._lock:
                self._dirty_count = max(0, self._dirty_count - dirty_count)

    def status(self) -> dict[str, Any]:
        self._load_entries()
        with self._lock:
            entries = self._entries_cache
            return {
                "active": True,
                "entries": len(entries or []),
                "maximum_entries": self._max_entries,
                "bytes": self._total_bytes,
                "maximum_bytes": self._max_bytes,
                "maximum_entry_bytes": self._max_entry_bytes,
            }

    def entries(self) -> list[dict[str, Any]]:
        self._load_entries()
        with self._lock:
            return self._redactor.sanitize_diagnostic_value(
                list(self._entries_cache or [])
            )

    def clear(self) -> dict[str, Any]:
        """Clear all captured technical diagnostic metadata."""
        with self._flush_lock:
            self._set_kv(self._entries_key, "[]")
            with self._lock:
                self._entries_cache = []
                self._entry_sizes = []
                self._total_bytes = 2
                self._dirty_count = 0
        return {"ok": True, "entries": 0}

    def capture(self, event: str, details: dict[str, Any]) -> None:
        """Redact content before it reaches the in-memory cache or database."""
        self._load_entries()
        entry = self._bounded_entry(
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": str(event)[:80],
                "details": details,
            }
        )
        with self._lock:
            entries = self._entries_cache
            assert entries is not None
            entries.append(entry)
            size = self._entry_bytes(entry)
            self._entry_sizes.append(size)
            self._total_bytes += size
            self._trim()
            self._dirty_count += 1
            should_flush = self._dirty_count >= min(self._batch_size, self._max_entries)
        if should_flush or event.endswith("_failed"):
            self.flush()
