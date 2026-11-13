"""Every Coach-use-case SQL statement on ``coach_commands`` and ``messages`` (#2119).

``ChatRepository`` and ``StateVersionRepository`` (``repositories.py``) and the
retention purge (``bootstrap.py``) keep theirs. Functions take the caller's
connection; transactions stay with the use case. Receipt and intent arguments
are dictionaries stored as JSON; rows come back unparsed.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

ACTIVE = ("queued", "running")
# Status and role literals are written into the statement text; only these pass.
_LITERALS = frozenset({"queued", "running", "completed", "user", "assistant"})
_RECEIPT = "CASE WHEN json_valid(receipt) THEN receipt END"


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _marks(values: Sequence[Any]) -> str:
    return ",".join("?" for _ in values)


def _status(statuses: Sequence[str]) -> str:
    if not statuses or not set(statuses) <= _LITERALS:
        raise ValueError("unknown Coach command status")
    if len(statuses) == 1:
        return f"status='{statuses[0]}'"
    return f"status IN ({', '.join(f"'{status}'" for status in statuses)})"


# Coach commands: reads.


def command_row(db: Any, client_turn_id: str, columns: str = "receipt") -> Any:
    return db.execute(
        f"SELECT {columns} FROM coach_commands WHERE client_turn_id=?",
        (client_turn_id,),
    ).fetchone()


def command_rows(
    db: Any,
    columns: str,
    statuses: Sequence[str] = ACTIVE,
    *,
    order: str = "",
    limit: int | None = None,
) -> list[Any]:
    """Commands in ``statuses``; ``order`` is "oldest", "newest" or unordered."""
    order_by = {"": "", "oldest": " ORDER BY created_at"}.get(
        order, " ORDER BY created_at DESC"
    )
    return db.execute(
        f"SELECT {columns} FROM coach_commands WHERE {_status(statuses)}{order_by}"
        + (f" LIMIT {int(limit)}" if limit is not None else "")
    ).fetchall()


def interrupted_foreground_rows(db: Any) -> list[Any]:
    return db.execute(
        "SELECT client_turn_id, intent FROM coach_commands WHERE status='running' "
        "AND COALESCE(json_extract(receipt, '$.mode'), '') != 'background'"
    ).fetchall()


def conversation_in_use(db: Any, conversation_id: str, client_turn_id: str) -> bool:
    return (
        db.execute(
            "SELECT 1 FROM coach_commands WHERE conversation_id=? "
            "AND client_turn_id!=? LIMIT 1",
            (conversation_id, client_turn_id),
        ).fetchone()
        is not None
    )


def recent_completed_turn_rows(db: Any) -> list[Any]:
    """The latest completed turns that still have a local message."""
    return db.execute(
        "SELECT c.client_turn_id, c.receipt FROM coach_commands c "
        "WHERE c.status='completed' AND EXISTS ("
        "SELECT 1 FROM messages m WHERE m.client_turn_id=c.client_turn_id) "
        "ORDER BY c.created_at DESC LIMIT 12"
    ).fetchall()


def command_history_rows(db: Any) -> list[Any]:
    return db.execute(
        "SELECT client_turn_id, receipt, created_at, updated_at FROM coach_commands "
        "ORDER BY created_at DESC, client_turn_id DESC LIMIT 20"
    ).fetchall()


def command_export_rows(db: Any) -> Iterable[Any]:
    return db.execute(
        "SELECT id, client_turn_id, conversation_id, intent, target_system, artifact_id, status, receipt, error_class, created_at, updated_at "
        "FROM coach_commands ORDER BY created_at"
    )


def prior_attachment_turn(db: Any, provider: str, message_id: int) -> Any:
    """The latest prior turn that sent attachments to ``provider``, how many user
    messages (including ``message_id``) follow it, and how many turns of another
    provider ran since. Receipts are filtered in SQL so a turn does not decode
    every stored receipt; the CASE guards skip malformed JSON."""
    return db.execute(
        "WITH prior AS (SELECT MAX(messages.id) AS id FROM coach_commands JOIN messages "
        f"ON messages.id=json_extract({_RECEIPT}, '$.user_message_id') "
        f"WHERE json_type({_RECEIPT}, '$.user_message_id')='integer' "
        f"AND json_extract({_RECEIPT}, '$.ai_provider')=? "
        f"AND (json_extract({_RECEIPT}, '$.openai_reached')=1 "
        f"OR json_extract({_RECEIPT}, '$.status')='completed') "
        "AND messages.id<? AND messages.attachments!='[]') "
        "SELECT prior.id AS id, (SELECT COUNT(*) FROM messages WHERE role='user' "
        "AND messages.id<=? AND messages.id>prior.id) AS turns, "
        "(SELECT COUNT(*) FROM coach_commands WHERE json_valid(receipt) "
        "AND json_extract(receipt, '$.user_message_id')>prior.id "
        "AND json_extract(receipt, '$.user_message_id')<? "
        "AND COALESCE(json_extract(receipt, '$.ai_provider'), ?)!=?) AS other_turns "
        "FROM prior",
        (provider, message_id, message_id, message_id, provider, provider),
    ).fetchone()


# Coach commands: writes.


def insert_command(
    db: Any,
    command_id: str,
    client_turn_id: str,
    conversation_id: str | None,
    intent: Mapping[str, Any],
    *,
    target_system: str,
    status: str,
    receipt: Mapping[str, Any],
    created_at: str,
    updated_at: str,
) -> None:
    db.execute(
        "INSERT INTO coach_commands(id, client_turn_id, conversation_id, intent, "
        "target_system, status, receipt, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            command_id,
            client_turn_id,
            conversation_id,
            _json(intent),
            target_system,
            status,
            _json(receipt),
            created_at,
            updated_at,
        ),
    )


def write_command(
    db: Any,
    client_turn_id: str,
    receipt: Mapping[str, Any],
    now: str,
    *,
    status: str | None = None,
    only: Sequence[str] = (),
) -> None:
    """Store the receipt, and ``status`` when given, while the status is in ``only``."""
    db.execute(
        f"UPDATE coach_commands SET {_status((status,)) + ', ' if status else ''}"
        "receipt=?, updated_at=? WHERE client_turn_id=?"
        + (f" AND {_status(only)}" if only else ""),
        (_json(receipt), now, client_turn_id),
    )


def claim_command(db: Any, client_turn_id: str, now: str) -> bool:
    return (
        db.execute(
            "UPDATE coach_commands SET status='running', updated_at=? "
            "WHERE client_turn_id=? AND status='queued'",
            (now, client_turn_id),
        ).rowcount
        == 1
    )


def resume_command(
    db: Any,
    client_turn_id: str,
    conversation_id: str,
    intent: Mapping[str, Any],
    now: str,
) -> None:
    db.execute(
        "UPDATE coach_commands SET conversation_id=?, intent=?, status='running', "
        "updated_at=? WHERE client_turn_id=?",
        (conversation_id, _json(intent), now, client_turn_id),
    )


def merge_command_receipt(
    db: Any,
    client_turn_id: str,
    updates: Mapping[str, Any],
    now: str,
    *,
    only: Sequence[str] = ACTIVE,
) -> None:
    """Write only the given top-level receipt keys while the status is in ``only``.

    ``json_set`` stores each key in place, so a progress step does not decode
    and re-encode the receipt's other, possibly large, values.
    """
    values: list[str] = []
    for key, value in updates.items():
        values += ["$." + json.dumps(str(key)), _json(value)]
    db.execute(
        "UPDATE coach_commands SET receipt=json_set("
        "CASE WHEN json_valid(receipt) AND json_type(receipt)='object' "
        f"THEN receipt ELSE '{{}}' END, {', '.join('?, json(?)' for _ in updates)}), "
        f"updated_at=? WHERE client_turn_id=? AND {_status(only)}",
        (*values, now, client_turn_id),
    )


def bind_conversation(
    db: Any,
    client_turn_id: str,
    conversation_id: str | None = None,
    *,
    rotated: bool = False,
) -> None:
    """Bind the turn to ``conversation_id`` and/or flag its conversation rotated."""
    sets = ["conversation_id=?"] if conversation_id is not None else []
    if rotated:
        sets.append(
            "receipt=json_set(receipt, '$.openai_conversation_rotated', json('true'))"
        )
    db.execute(
        f"UPDATE coach_commands SET {', '.join(sets)} WHERE client_turn_id=?",
        (*((conversation_id,) if conversation_id is not None else ()), client_turn_id),
    )


# Messages: reads.


def message_by_id(
    db: Any,
    message_id: Any,
    columns: str,
    role: str = "user",
    client_turn_id: str | None = None,
) -> Any:
    """The message with this id and role, and of this turn when one is given."""
    if role not in _LITERALS:
        raise ValueError("unknown message role")
    turn = " AND client_turn_id=?" if client_turn_id is not None else ""
    return db.execute(
        f"SELECT {columns} FROM messages WHERE id=? AND role='{role}'{turn}",
        (message_id, *((client_turn_id,) if turn else ())),
    ).fetchone()


def user_message_for_turn(db: Any, client_turn_id: str, columns: str = "id") -> Any:
    return db.execute(
        f"SELECT {columns} FROM messages WHERE client_turn_id=? AND role='user'",
        (client_turn_id,),
    ).fetchone()


def first_user_message_after(db: Any, message_id: int) -> Any:
    return db.execute(
        "SELECT MIN(id) AS id FROM messages WHERE role='user' AND id>?", (message_id,)
    ).fetchone()


def source_message_rows(db: Any, message_ids: Sequence[int]) -> list[Any]:
    """User messages with the conversation and receipt of the turn they started."""
    return db.execute(
        "SELECT m.id, m.client_turn_id, c.conversation_id, c.receipt "
        "FROM messages m LEFT JOIN coach_commands c "
        "ON c.client_turn_id=m.client_turn_id "
        f"WHERE m.role='user' AND m.id IN ({_marks(message_ids)})",
        tuple(message_ids),
    ).fetchall()


def draft_user_message_ids(db: Any) -> list[int]:
    """User messages whose turn produced a still-open plan draft."""
    return [
        row["id"]
        for row in db.execute(
            "SELECT m.id FROM messages m JOIN coach_plan_artifacts a "
            "ON a.client_turn_id=m.client_turn_id "
            "WHERE m.role='user' AND a.status='draft'"
        ).fetchall()
    ]


def draft_artifact_refs(db: Any) -> list[Any]:
    """Drafts whose turn has a local message, with the user message that started it."""
    return db.execute(
        "SELECT a.id, a.status, a.base_revision, a.created_at, "
        "(SELECT m.id FROM messages m WHERE m.client_turn_id=a.client_turn_id "
        "AND m.role='user' LIMIT 1) AS source_message_id, "
        "json_extract(a.payload, '$.plan_name') AS name "
        "FROM coach_plan_artifacts a WHERE a.status='draft' "
        "AND EXISTS (SELECT 1 FROM messages m "
        "WHERE m.client_turn_id=a.client_turn_id) "
        "ORDER BY a.created_at DESC LIMIT 20"
    ).fetchall()


def message_attachments(db: Any, message_id: Any) -> Any:
    return db.execute(
        "SELECT attachments FROM messages WHERE id=?", (message_id,)
    ).fetchone()


def attachment_evidence_rows(db: Any, message_id: int) -> list[Any]:
    """Attachment items without their encoded file data, which evidence never shows."""
    return db.execute(
        "SELECT json_each.type AS kind, CASE WHEN json_each.type='object' "
        "THEN json_remove(json_each.value, '$.data') ELSE json_each.value END AS item "
        "FROM messages, json_each(CASE WHEN json_valid(messages.attachments) "
        "AND json_type(messages.attachments)='array' THEN messages.attachments "
        "ELSE '[]' END) WHERE messages.id=? ORDER BY json_each.key",
        (message_id,),
    ).fetchall()


def stored_attachment_bytes(db: Any) -> int:
    row = db.execute(
        "SELECT COALESCE(SUM(length(attachments)), 0) AS total FROM messages"
    ).fetchone()
    return int(row["total"] or 0)


def message_export_rows(db: Any) -> Iterable[Any]:
    return db.execute(
        "SELECT role, content, attachments, created_at FROM messages ORDER BY id"
    )


# Messages: writes.


def set_message_attachments(db: Any, message_id: int, attachments: str) -> None:
    db.execute(
        "UPDATE messages SET attachments=? WHERE id=?", (attachments, message_id)
    )


def delete_messages(db: Any) -> None:
    db.execute("DELETE FROM messages")
