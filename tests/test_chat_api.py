"""Phase 8 chat API tests."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

pytestmark = pytest.mark.skipif(
    not os.getenv("SUPABASE_URL") and not (ROOT / ".env").is_file(),
    reason="Supabase required",
)


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


def _parse_sse(body: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    event_name = "message"
    for line in body.split("\n"):
        if line.startswith("event:"):
            event_name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            payload = json.loads(line.split(":", 1)[1].strip())
            events.append((event_name, payload))
    return events


def test_chat_scheduling_conversation_persisted(client: TestClient):
    session_resp = client.post("/chat/sessions", json={"title": "Phase 8 test"})
    assert session_resp.status_code == 200
    session_id = session_resp.json()["id"]

    with client.stream(
        "POST",
        f"/chat/sessions/{session_id}/messages",
        json={"content": "Please schedule next week's jobs.", "use_orchestrator_agent": False},
    ) as stream:
        assert stream.status_code == 200
        body = "".join(stream.iter_text())

    events = _parse_sse(body)
    event_types = {e[0] for e in events}
    assert "text_delta" in event_types or "message_complete" in event_types
    assert "tool_call" in event_types
    assert "schedule_preview" in event_types

    preview_events = [e for e in events if e[0] == "schedule_preview"]
    schedule_run_id = preview_events[0][1]["schedule_run_id"]

    from app.tools._db import tools_db

    messages = (
        tools_db()
        .table("chat_messages")
        .select("role, content, schedule_preview, schedule_run_id")
        .eq("session_id", session_id)
        .order("sequence_number")
        .execute()
        .data
    )
    assert len(messages) >= 2
    roles = [m["role"] for m in messages]
    assert "user" in roles
    assert "assistant" in roles
    assert any(m.get("schedule_preview") for m in messages)

    approve = client.post(f"/schedules/{schedule_run_id}/approve")
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    run = (
        tools_db()
        .table("schedule_runs")
        .select("status, approved")
        .eq("id", schedule_run_id)
        .single()
        .execute()
        .data
    )
    assert run["status"] == "approved"
    assert run["approved"] is True


def test_schedule_reject(client: TestClient):
    from app.tools._db import tools_db
    from datetime import date, timedelta

    week_start = date.today() + timedelta(days=7)
    row = {
        "user_request": "test reject",
        "week_start": week_start.isoformat(),
        "week_end": (week_start + timedelta(days=6)).isoformat(),
        "status": "needs_human_review",
        "approved": False,
    }
    run_id = tools_db().table("schedule_runs").insert(row).execute().data[0]["id"]

    resp = client.post(f"/schedules/{run_id}/reject")
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
