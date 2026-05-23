"""Chat session and streaming message endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from app.chat.agent import stream_chat_turn
from app.chat.persist import create_session, get_session, list_messages
from app.chat.schemas import (
    ChatMessageResponse,
    ChatSessionResponse,
    CreateChatSessionRequest,
    PostChatMessageRequest,
)

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/sessions", response_model=ChatSessionResponse)
def post_chat_session(body: CreateChatSessionRequest) -> ChatSessionResponse:
    return create_session(body)


@router.get("/sessions/{session_id}/messages", response_model=list[ChatMessageResponse])
def get_session_messages(session_id: UUID) -> list[ChatMessageResponse]:
    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Chat session not found")
    return list_messages(session_id)


@router.post("/sessions/{session_id}/messages")
def post_session_message(session_id: UUID, body: PostChatMessageRequest) -> StreamingResponse:
    if not get_session(session_id):
        raise HTTPException(status_code=404, detail="Chat session not found")

    def event_generator():
        yield from stream_chat_turn(session_id, body)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
