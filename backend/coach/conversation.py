"""Pure helpers for bounded Gemini conversation history."""
from __future__ import annotations

import json
import sqlite3
import uuid
from collections.abc import Callable
from typing import Any

from backend.coach.attachments import (
    MAX_GEMINI_INLINE_IMAGE_BYTES,
    gemini_history_parts,
    gemini_selected_raw_attachments,
)
from backend.coach.service import command_receipt
from backend.db.manager import DatabaseManager
from backend.db.repositories import ChatRepository, KeyValueRepository
from backend.errors import AppError
from backend.providers import gemini as gemini_provider
from backend.runtime.events import StateEventBuffer


MESSAGE_ATTACHMENTS_QUERY = "SELECT attachments FROM messages WHERE id=?"


class CoachAttachmentContextService:
    """Load current attachments and local evidence for a bounded Coach context."""

    def __init__(self, database_manager: DatabaseManager):
        self._database_manager = database_manager

    def load_for_receipt(self, receipt: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
        with self._database_manager.reader() as db:
            attachment_row = db.execute(
                MESSAGE_ATTACHMENTS_QUERY, (receipt.get("user_message_id"),)
            ).fetchone()
            openai_attachment_message_ids = set()
            for row in db.execute(
                "SELECT receipt FROM coach_commands WHERE receipt IS NOT NULL"
            ).fetchall():
                prior_receipt = command_receipt(row["receipt"])
                message_id = prior_receipt.get("user_message_id")
                if prior_receipt.get("ai_provider") == "openai" and isinstance(message_id, int):
                    openai_attachment_message_ids.add(message_id)
            has_prior_openai_attachments = bool(openai_attachment_message_ids and db.execute(
                "SELECT 1 FROM messages WHERE id<? AND attachments!='[]' AND id IN (%s) LIMIT 1"
                % ",".join("?" for _ in openai_attachment_message_ids),
                (receipt.get("user_message_id") or 0, *openai_attachment_message_ids),
            ).fetchone())
        attachments = json.loads(attachment_row["attachments"]) if attachment_row else []
        return attachments, has_prior_openai_attachments

    def add_evidence(self, context: dict[str, Any]) -> None:
        # Keep raw attachment bytes out of the structured dialogue context.
        with self._database_manager.reader() as db:
            context["attachment_evidence"] = []
            for item in context["messages"]:
                row = db.execute(MESSAGE_ATTACHMENTS_QUERY, (item["id"],)).fetchone()
                for attachment in json.loads(row["attachments"] or "[]") if row else []:
                    context["attachment_evidence"].append({
                        "source_message_id": item["id"], "type": attachment.get("type"),
                        "untrusted_attachment_name": attachment.get("name"),
                        **({attachment.get("type"): attachment.get("summary")}
                           if attachment.get("type") in {"gpx", "fit"} else {}),
                    })


class CoachMessageService:
    """Persist Coach chat messages and publish their committed state change."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        chat_repository: ChatRepository,
        state_event_buffer: StateEventBuffer,
    ):
        self._database_manager = database_manager
        self._chat_repository = chat_repository
        self._state_event_buffer = state_event_buffer

    def add(self, role: str, content: str) -> dict[str, Any]:
        with self._database_manager.unit_of_work() as db:
            result = self._chat_repository.add(db, role, content)
        self._state_event_buffer.publish(
            "coach", {"message_id": result.get("id"), "role": str(role)[:20]}
        )
        return result

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._database_manager.reader() as db:
            return self._chat_repository.list(db, limit)


class GeminiConversationHistoryService:
    """Persist bounded, replay-safe Gemini conversation history."""

    _HISTORY_KEY = "gemini_conversation_history"
    _CALL_NAMES_KEY = "gemini_call_names"

    def __init__(
        self,
        database_manager: DatabaseManager,
        key_values: KeyValueRepository,
    ):
        self._database_manager = database_manager
        self._key_values = key_values

    def load(self) -> list[dict[str, Any]]:
        with self._database_manager.reader() as db:
            try:
                history = json.loads(self._key_values.get(db, self._HISTORY_KEY) or "[]")
            except (TypeError, json.JSONDecodeError):
                return []
        return trim_gemini_history(history) if isinstance(history, list) else []

    def save(self, history: list[dict[str, Any]]) -> None:
        compact: list[dict[str, Any]] = []
        for entry in trim_gemini_history(history):
            parts = entry.get("parts") if isinstance(entry, dict) else None
            if not isinstance(parts, list):
                continue
            safe_parts = gemini_history_parts_without_raw_media(parts)
            if safe_parts:
                compact.append({"role": entry.get("role"), "parts": safe_parts})
        payload = json.dumps(compact, ensure_ascii=False, separators=(",", ":"))
        with self._database_manager.unit_of_work() as db:
            self._key_values.set(db, self._HISTORY_KEY, payload)

    def repair_incomplete(self, db: Any) -> None:
        """Drop a trailing unexecuted tool call within the caller's transaction."""
        try:
            raw_history = json.loads(self._key_values.get(db, self._HISTORY_KEY) or "[]")
        except (TypeError, json.JSONDecodeError):
            raw_history = []
        history = trim_gemini_history(raw_history) if isinstance(raw_history, list) else []
        if not history or history[-1].get("role") != "model":
            return
        parts = history[-1].get("parts") if isinstance(history[-1].get("parts"), list) else []
        if not any(isinstance(part, dict) and isinstance(part.get("functionCall"), dict) for part in parts):
            return
        repaired = trim_gemini_history(history[:-1])
        self._key_values.set(
            db,
            self._HISTORY_KEY,
            json.dumps(repaired, ensure_ascii=False, separators=(",", ":")),
        )
        self._key_values.set(db, self._CALL_NAMES_KEY, "{}")


class GeminiResponseNormalizationService:
    """Translate a Gemini result into the Coach Responses shape and persist local state."""

    _CALL_NAMES_KEY = "gemini_call_names"

    def __init__(
        self,
        conversation_history: GeminiConversationHistoryService,
        database_manager: DatabaseManager,
        key_values: KeyValueRepository,
        uuid_factory: Callable[[], uuid.UUID],
    ):
        self._conversation_history = conversation_history
        self._database_manager = database_manager
        self._key_values = key_values
        self._uuid_factory = uuid_factory

    def normalize(
        self,
        payload: dict[str, Any],
        history: list[dict[str, Any]],
        persistent: bool,
        result: dict[str, Any],
    ) -> dict[str, Any]:
        content = self._response_content(result)
        function_calls = self._function_calls(content)
        self._validate_function_calls(payload, function_calls)
        if persistent:
            history.append(content)
            self._conversation_history.save(history)
        text = gemini_provider.response_text(result)
        output, call_names = self._normalized_output(text, function_calls)
        self._save_call_names(call_names)
        return self._response(output, text, result)

    @staticmethod
    def _response_content(result: dict[str, Any]) -> dict[str, Any]:
        candidates = result.get("candidates") if isinstance(result.get("candidates"), list) else []
        candidate = candidates[0] if candidates and isinstance(candidates[0], dict) else None
        content = candidate.get("content") if isinstance(candidate, dict) and isinstance(candidate.get("content"), dict) else None
        if not content:
            raise AppError(502, "Gemini hat keine Coach-Antwort geliefert.", reason="invalid_response")

        return content

    @staticmethod
    def _function_calls(content: dict[str, Any]) -> list[dict[str, Any]]:
        content_parts = content.get("parts") if isinstance(content.get("parts"), list) else []
        return [
            part["functionCall"]
            for part in content_parts
            if isinstance(part, dict) and isinstance(part.get("functionCall"), dict)
        ]

    @staticmethod
    def _validate_function_calls(
        payload: dict[str, Any], function_calls: list[dict[str, Any]]
    ) -> None:
        if payload.get("parallel_tool_calls") is False and len(function_calls) > 1:
            raise AppError(502, "Gemini hat mehrere Tool-Aufrufe für eine einzelne Coach-Aktion zurückgegeben.", reason="parallel_tool_calls_unsupported")

    def _normalized_output(
        self, text: str, function_calls: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        output: list[dict[str, Any]] = []
        if text:
            output.append({"type": "message", "content": [{"type": "output_text", "text": text}]})
        call_names: dict[str, str] = {}
        for function_call in function_calls:
            name = str(function_call.get("name") or "").strip()
            if not name:
                continue
            call_id = "gemini_" + self._uuid_factory().hex
            call_names[call_id] = name
            output.append({"type": "function_call", "call_id": call_id, "name": name,
                           "arguments": json.dumps(function_call.get("args") if isinstance(function_call.get("args"), dict) else {}, ensure_ascii=False)})

        return output, call_names

    def _save_call_names(self, call_names: dict[str, str]) -> None:
        if call_names:
            with self._database_manager.unit_of_work() as db:
                self._key_values.set(db, self._CALL_NAMES_KEY, json.dumps(call_names, ensure_ascii=False))

    def _response(
        self, output: list[dict[str, Any]], text: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        usage = result.get("usageMetadata") if isinstance(result.get("usageMetadata"), dict) else {}
        return {"id": "gemini_" + self._uuid_factory().hex, "status": "completed", "output": output, "output_text": text,
                "usage": {"input_tokens": usage.get("promptTokenCount", 0), "output_tokens": usage.get("candidatesTokenCount", 0), "total_tokens": usage.get("totalTokenCount", 0)}}


class GeminiLocalChatHistoryService:
    """Project the latest local Coach messages into bounded Gemini history."""

    def __init__(
        self,
        database_manager: DatabaseManager,
        chat_repository: ChatRepository,
        max_inline_bytes: int = MAX_GEMINI_INLINE_IMAGE_BYTES,
    ):
        self._database_manager = database_manager
        self._chat_repository = chat_repository
        self._max_inline_bytes = max_inline_bytes

    def build(self) -> list[dict[str, Any]]:
        with self._database_manager.reader() as db:
            try:
                messages = self._chat_repository.list(db, limit=20)
            except sqlite3.DatabaseError as exc:
                # ChatRepository's attachment-name projection uses json_each;
                # malformed legacy attachment JSON can make that query fail.
                if "malformed JSON" not in str(exc):
                    raise
                rows = db.execute(
                    "SELECT id, role, content, client_turn_id, created_at "
                    "FROM messages ORDER BY id DESC LIMIT ?",
                    (20,),
                ).fetchall()
                messages = [dict(row) for row in reversed(rows)]

            message_attachments = []
            for message in messages:
                row = db.execute(MESSAGE_ATTACHMENTS_QUERY, (message["id"],)).fetchone()
                try:
                    attachments = json.loads(row["attachments"]) if row else []
                except (TypeError, json.JSONDecodeError):
                    attachments = []
                message_attachments.append(attachments if isinstance(attachments, list) else [])

        selected_raw = gemini_selected_raw_attachments(
            message_attachments, max_inline_bytes=self._max_inline_bytes
        )
        history: list[dict[str, Any]] = []
        for message_index, message in enumerate(messages):
            role = "model" if message.get("role") == "assistant" else "user"
            parts = gemini_history_parts(
                message,
                message_attachments[message_index],
                message_index,
                selected_raw,
            )
            if parts:
                history.append({"role": role, "parts": parts})
        return trim_gemini_history(history)


class GeminiRequestPayloadService:
    """Build Gemini request contents from durable or local Coach history."""

    _CALL_NAMES_KEY = "gemini_call_names"

    def __init__(
        self,
        conversation_history: GeminiConversationHistoryService,
        local_chat_history: GeminiLocalChatHistoryService,
        database_manager: DatabaseManager,
        key_values: KeyValueRepository,
    ):
        self._conversation_history = conversation_history
        self._local_chat_history = local_chat_history
        self._database_manager = database_manager
        self._key_values = key_values

    def build(
        self,
        payload: dict[str, Any],
        model: str,
        *,
        default_max_output_tokens: int,
        default_thinking_level: str,
        json_media_type: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
        persistent = bool(payload.get("conversation"))
        input_value = payload.get("input")
        history = self._history_for_input(payload, persistent, input_value)
        parts = self._append_input(input_value, history, payload)
        history = trim_gemini_history(history)
        self._save_tool_response_history(persistent, input_value, parts, history)
        request = gemini_provider.request_payload(
            payload,
            model=model,
            contents=history,
            default_max_output_tokens=default_max_output_tokens,
            default_thinking_level=default_thinking_level,
            json_media_type=json_media_type,
        )
        return request, history, persistent

    def _history_for_input(
        self, payload: dict[str, Any], persistent: bool, input_value: Any
    ) -> list[dict[str, Any]]:
        history = self._conversation_history.load() if persistent else []
        if persistent and isinstance(input_value, str):
            local_history = self._local_chat_history.build()
            if local_history:
                replayed_media = gemini_inline_media_from_history(local_history)
                if replayed_media:
                    payload["_gemini_transient_images"] = replayed_media
                history = local_history

        return history

    def _append_input(
        self, input_value: Any, history: list[dict[str, Any]], payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        if isinstance(input_value, str):
            last_user_text = self._last_user_text(history)
            if input_value != last_user_text:
                history.append({"role": "user", "parts": [{"text": input_value}]})
            return []
        if isinstance(input_value, list):
            return self._append_tool_response(input_value, history, payload)
        return []

    @staticmethod
    def _last_user_text(history: list[dict[str, Any]]) -> str:
        if not history or not isinstance(history[-1], dict) or history[-1].get("role") != "user":
            return ""
        parts = history[-1].get("parts") if isinstance(history[-1].get("parts"), list) else []
        if not parts or not isinstance(parts[0], dict):
            return ""
        return str(parts[0].get("text") or "")

    def _append_tool_response(
        self, input_value: list[Any], history: list[dict[str, Any]], payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        parts = gemini_provider.input_parts(
            input_value, self._call_names(), payload.get("_gemini_transient_images")
        )
        if parts:
            history.append({"role": "user", "parts": parts})
        return parts

    def _call_names(self) -> dict[str, Any]:
        with self._database_manager.reader() as db:
            try:
                call_names = json.loads(self._key_values.get(db, self._CALL_NAMES_KEY) or "{}")
            except (TypeError, json.JSONDecodeError):
                call_names = {}
        return call_names if isinstance(call_names, dict) else {}

    def _save_tool_response_history(
        self,
        persistent: bool,
        input_value: Any,
        parts: list[dict[str, Any]],
        history: list[dict[str, Any]],
    ) -> None:
        if persistent and isinstance(input_value, list) and parts:
            self._conversation_history.save(history)


def _content_has_function_response(content: dict[str, Any]) -> bool:
    parts = content.get("parts") if isinstance(content.get("parts"), list) else []
    return any(isinstance(part, dict) and isinstance(part.get("functionResponse"), dict) for part in parts)


def _history_exchange_boundary(content: dict[str, Any]) -> bool:
    if content.get("role") != "user" or _content_has_function_response(content):
        return False
    parts = content.get("parts") if isinstance(content.get("parts"), list) else []
    return any(isinstance(part, dict) and str(part.get("text") or "").strip() for part in parts)


def trim_gemini_history(history: list[dict[str, Any]], limit: int = 60) -> list[dict[str, Any]]:
    """Keep a bounded suffix that starts at a user exchange, never a tool response."""
    valid = [content for content in history if isinstance(content, dict) and content.get("role") in {"user", "model"}]
    for start in range(max(0, len(valid) - limit), len(valid)):
        if _history_exchange_boundary(valid[start]):
            return valid[start:]
    # Persisted state without a complete user exchange is unsafe to replay.
    return []


def gemini_history_parts_without_raw_media(parts: list[Any]) -> list[dict[str, Any]]:
    safe_parts = []
    for part in parts:
        if not isinstance(part, dict) or "inlineData" in part:
            continue
        text = part.get("text")
        try:
            parsed = json.loads(text) if isinstance(text, str) else None
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict) and parsed.get("untrusted_fit_raw_base64"):
            continue
        safe_parts.append(part)
    return safe_parts


def gemini_inline_media_from_history(history: list[dict[str, Any]]) -> list[dict[str, str]]:
    media = []
    for entry in history:
        parts = entry.get("parts") if isinstance(entry, dict) else None
        for part in parts if isinstance(parts, list) else []:
            inline = part.get("inlineData") if isinstance(part, dict) else None
            if not isinstance(inline, dict) or not inline.get("mimeType") or not inline.get("data"):
                continue
            media.append({"mime": str(inline["mimeType"]), "data": str(inline["data"])})
    return media
