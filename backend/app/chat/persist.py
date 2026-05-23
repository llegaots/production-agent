"""Supabase persistence for chat sessions and messages."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from app.chat.schemas import ChatMessageResponse, ChatSessionResponse, CreateChatSessionRequest
from app.tools._db import tools_db


def create_session(req: CreateChatSessionRequest) -> ChatSessionResponse:
    now = datetime.now(timezone.utc)
    row = {
        "title": req.title or "Dispatcher chat",
        "metadata": req.metadata,
        "updated_at": now.isoformat(),
    }
    resp = tools_db().table("chat_sessions").insert(row).execute()
    data = resp.data[0]
    return ChatSessionResponse(
        id=UUID(data["id"]),
        title=data["title"],
        metadata=data.get("metadata") or {},
        created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
        updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")),
    )


def get_session(session_id: UUID) -> ChatSessionResponse | None:
    resp = (
        tools_db()
        .table("chat_sessions")
        .select("*")
        .eq("id", str(session_id))
        .limit(1)
        .execute()
    )
    if not resp.data:
        return None
    data = resp.data[0]
    return ChatSessionResponse(
        id=UUID(data["id"]),
        title=data["title"],
        metadata=data.get("metadata") or {},
        created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
        updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00")),
    )


def _next_sequence(session_id: UUID) -> int:
    rows = (
        tools_db()
        .table("chat_messages")
        .select("sequence_number")
        .eq("session_id", str(session_id))
        .order("sequence_number", desc=True)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        return 1
    return int(rows[0]["sequence_number"]) + 1


def insert_message(
    session_id: UUID,
    *,
    role: str,
    content: str,
    tool_calls: list[dict[str, Any]] | None = None,
    tool_results: Any = None,
    schedule_preview: dict[str, Any] | None = None,
    schedule_run_id: UUID | None = None,
) -> ChatMessageResponse:
    seq = _next_sequence(session_id)
    row: dict[str, Any] = {
        "session_id": str(session_id),
        "sequence_number": seq,
        "role": role,
        "content": content,
        "tool_calls": tool_calls or [],
        "tool_results": tool_results,
        "schedule_preview": schedule_preview,
        "schedule_run_id": str(schedule_run_id) if schedule_run_id else None,
    }
    resp = tools_db().table("chat_messages").insert(row).execute()
    data = resp.data[0]
    tools_db().table("chat_sessions").update(
        {"updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", str(session_id)).execute()
    return _row_to_message(data)


def list_messages(session_id: UUID) -> list[ChatMessageResponse]:
    rows = (
        tools_db()
        .table("chat_messages")
        .select("*")
        .eq("session_id", str(session_id))
        .order("sequence_number")
        .execute()
        .data
        or []
    )
    return [_row_to_message(r) for r in rows]


def _row_to_message(data: dict[str, Any]) -> ChatMessageResponse:
    return ChatMessageResponse(
        id=UUID(data["id"]),
        session_id=UUID(data["session_id"]),
        sequence_number=int(data["sequence_number"]),
        role=data["role"],
        content=data.get("content") or "",
        tool_calls=data.get("tool_calls") or [],
        tool_results=data.get("tool_results"),
        schedule_preview=data.get("schedule_preview"),
        schedule_run_id=UUID(data["schedule_run_id"]) if data.get("schedule_run_id") else None,
        created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00")),
    )


def messages_for_anthropic(session_id: UUID) -> list[dict[str, Any]]:
    """Build Anthropic messages array from persisted history (user/assistant only)."""
    out: list[dict[str, Any]] = []
    for msg in list_messages(session_id):
        if msg.role == "user":
            out.append({"role": "user", "content": msg.content})
        elif msg.role == "assistant":
            if msg.tool_calls:
                blocks: list[dict[str, Any]] = []
                if msg.content:
                    blocks.append({"type": "text", "text": msg.content})
                for tc in msg.tool_calls:
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["name"],
                            "input": tc.get("input") or {},
                        }
                    )
                out.append({"role": "assistant", "content": blocks})
            else:
                out.append({"role": "assistant", "content": msg.content})
        elif msg.role == "tool" and msg.tool_results:
            results = msg.tool_results
            if isinstance(results, list):
                out.append({"role": "user", "content": results})
    return out
