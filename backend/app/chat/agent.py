"""Chat turn processor with SSE streaming."""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from typing import Any
from uuid import UUID

from anthropic import Anthropic

from app.chat.persist import insert_message, messages_for_anthropic
from app.chat.schemas import PostChatMessageRequest
from app.chat.tools import (
    SCHEDULING_TOOL_DEFINITION,
    execute_scheduling_tool,
    wants_scheduling,
)
from app.config import get_settings

SYSTEM_PROMPT = """You are the Production Agent dispatcher assistant for a window-cleaning company.

When the user asks to schedule work (e.g. next week's jobs), call `run_scheduling_orchestrator`
with their request. Summarize results clearly and mention if human review is required.

Do not invent crew assignments — rely on the tool output. Be concise and professional."""


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _emit_text_chunks(text: str) -> Iterator[str]:
    step = 48
    for i in range(0, len(text), step):
        yield _sse("text_delta", {"text": text[i : i + step]})


def _fallback_stream(
    session_id: UUID,
    user_text: str,
    *,
    use_orchestrator_agent: bool | None,
) -> Iterator[str]:
    """Deterministic assistant when Anthropic is unavailable (CI / rate limits)."""
    assistant_text = ""
    tool_calls: list[dict[str, Any]] = []
    schedule_preview: dict[str, Any] | None = None
    schedule_run_id: UUID | None = None

    if wants_scheduling(user_text):
        tool_id = f"toolu_{uuid.uuid4().hex[:12]}"
        tool_input = {"user_request": user_text, "max_iterations": 2}
        tool_calls.append({"id": tool_id, "name": "run_scheduling_orchestrator", "input": tool_input})
        yield _sse(
            "tool_call",
            {"id": tool_id, "name": "run_scheduling_orchestrator", "input": tool_input},
        )

        result = execute_scheduling_tool(tool_input, use_orchestrator_agent=use_orchestrator_agent)
        yield _sse("tool_result", {"tool_use_id": tool_id, "result": result})
        schedule_preview = result.get("schedule_preview")
        if schedule_preview:
            yield _sse("schedule_preview", schedule_preview)
        schedule_run_id = UUID(result["schedule_run_id"])

        status = result.get("status", "unknown")
        assistant_text = (
            f"I ran the scheduling orchestrator for your request. Status: {status}. "
            f"{result.get('summary', '')} "
        )
        if result.get("approved"):
            assistant_text += "The critic approved this plan — you can confirm with Approve."
        else:
            assistant_text += "Please review the schedule preview and approve or reject."
    else:
        assistant_text = (
            'I can help you schedule crews. Try: "Schedule next week\'s jobs" '
            "and I will run the orchestrator."
        )

    yield from _emit_text_chunks(assistant_text)
    saved = insert_message(
        session_id,
        role="assistant",
        content=assistant_text,
        tool_calls=tool_calls,
        schedule_preview=schedule_preview,
        schedule_run_id=schedule_run_id,
    )
    yield _sse("message_complete", {"message_id": str(saved.id), "role": "assistant"})


def _stream_anthropic_turn(
    session_id: UUID,
    user_text: str,
    *,
    use_orchestrator_agent: bool | None,
) -> Iterator[str]:
    settings = get_settings()
    client = Anthropic(api_key=settings.anthropic_api_key, timeout=120.0)
    messages = messages_for_anthropic(session_id)
    messages.append({"role": "user", "content": user_text})

    tool_calls: list[dict[str, Any]] = []
    schedule_preview: dict[str, Any] | None = None
    schedule_run_id: UUID | None = None

    for _ in range(4):
        response = client.messages.create(
            model=settings.anthropic_model,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=messages,
            tools=[SCHEDULING_TOOL_DEFINITION],
        )

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        text_blocks = [b.text for b in response.content if b.type == "text"]

        if tool_uses:
            assistant_blocks: list[dict[str, Any]] = []
            if text_blocks:
                assistant_blocks.append({"type": "text", "text": "\n".join(text_blocks)})
            tool_result_blocks = []
            for block in tool_uses:
                tc = {"id": block.id, "name": block.name, "input": block.input}
                tool_calls.append(tc)
                assistant_blocks.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )
                yield _sse("tool_call", tc)

                if block.name == "run_scheduling_orchestrator":
                    inp = block.input if isinstance(block.input, dict) else {}
                    result = execute_scheduling_tool(inp, use_orchestrator_agent=use_orchestrator_agent)
                else:
                    result = {"error": f"Unknown tool: {block.name}"}
                yield _sse("tool_result", {"tool_use_id": block.id, "result": result})
                if result.get("schedule_preview"):
                    schedule_preview = result["schedule_preview"]
                    schedule_run_id = UUID(result["schedule_run_id"])
                    yield _sse("schedule_preview", schedule_preview)
                tool_result_blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(result),
                    }
                )

            messages.append({"role": "assistant", "content": assistant_blocks})
            insert_message(
                session_id,
                role="assistant",
                content="\n".join(text_blocks) if text_blocks else "",
                tool_calls=[{"id": b.id, "name": b.name, "input": b.input} for b in tool_uses],
            )
            insert_message(session_id, role="tool", content="", tool_results=tool_result_blocks)
            messages.append({"role": "user", "content": tool_result_blocks})
            continue

        assistant_text = "\n".join(text_blocks).strip()
        if not assistant_text:
            assistant_text = "Done."
        yield from _emit_text_chunks(assistant_text)
        saved = insert_message(
            session_id,
            role="assistant",
            content=assistant_text,
            tool_calls=tool_calls,
            schedule_preview=schedule_preview,
            schedule_run_id=schedule_run_id,
        )
        yield _sse("message_complete", {"message_id": str(saved.id), "role": "assistant"})
        return

    yield from _fallback_stream(session_id, user_text, use_orchestrator_agent=use_orchestrator_agent)


def stream_chat_turn(
    session_id: UUID,
    req: PostChatMessageRequest,
) -> Iterator[str]:
    insert_message(session_id, role="user", content=req.content)

    settings = get_settings()
    if settings.anthropic_api_key:
        try:
            yield from _stream_anthropic_turn(
                session_id,
                req.content,
                use_orchestrator_agent=req.use_orchestrator_agent,
            )
            return
        except Exception as exc:
            yield _sse("error", {"message": str(exc), "fallback": True})

    yield from _fallback_stream(
        session_id,
        req.content,
        use_orchestrator_agent=req.use_orchestrator_agent,
    )
