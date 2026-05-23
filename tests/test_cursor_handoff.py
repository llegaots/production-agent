import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.cursor_client import CursorCloudClient, build_handoff_prompt, cursor_cloud
from app.cursor_handoff import attach_handoff_to_report_json, trigger_automatic_handoff


def test_build_handoff_prompt_includes_run_id():
    text = build_handoff_prompt("# QA\n\nFix things", run_id="qa_abc", passed=False, score=55)
    assert "qa_abc" in text
    assert "55/100" in text
    assert "Fix things" in text


def test_trigger_skips_without_api_key(monkeypatch):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    client = CursorCloudClient()

    async def _run():
        with patch("app.cursor_handoff.cursor_cloud", client):
            return await trigger_automatic_handoff(
                run_id="qa_test",
                handoff_path=Path("/tmp/nope.md"),
                passed=False,
                overall_score=50,
                force=False,
            )

    result = asyncio.run(_run())
    assert not result.launched
    assert result.skipped_reason


def test_trigger_skips_when_auto_handoff_disabled(tmp_path, monkeypatch):
    md = tmp_path / "cursor-handoff_qa_y.md"
    md.write_text("# handoff\n\nFix things.", encoding="utf-8")
    monkeypatch.setenv("CURSOR_API_KEY", "key_test")
    monkeypatch.setenv("CURSOR_REPOSITORY", "https://github.com/example/production-agent")
    monkeypatch.setenv("CURSOR_AUTO_HANDOFF", "false")

    client = CursorCloudClient()
    assert client.auto_handoff_default is False

    async def _run():
        with patch("app.cursor_handoff.cursor_cloud", client):
            return await trigger_automatic_handoff(
                run_id="qa_y",
                handoff_path=md,
                passed=False,
                overall_score=40,
                force=False,
                auto_handoff=None,
            )

    result = asyncio.run(_run())
    assert not result.launched
    assert "auto_handoff disabled" in (result.skipped_reason or "")


def test_trigger_launches_when_configured(tmp_path, monkeypatch):
    md = tmp_path / "cursor-handoff_qa_x.md"
    md.write_text("# handoff\n\nFix crew_fill scoring.", encoding="utf-8")
    monkeypatch.setenv("CURSOR_API_KEY", "key_test")
    monkeypatch.setenv("CURSOR_REPOSITORY", "https://github.com/example/production-agent")
    monkeypatch.setenv("CURSOR_REF", "main")

    from app.cursor_client import CursorLaunchResult

    mock_result = CursorLaunchResult(
        launched=True,
        agent_id="bc_test123",
        agent_url="https://cursor.com/agents?id=bc_test123",
        status="CREATING",
        api_version="v1",
    )

    client = CursorCloudClient()

    async def _run():
        with patch("app.cursor_handoff.cursor_cloud", client):
            with patch.object(client, "launch_agent", AsyncMock(return_value=mock_result)):
                return await trigger_automatic_handoff(
                    run_id="qa_x",
                    handoff_path=md,
                    passed=False,
                    overall_score=60,
                    force=True,
                )

    result = asyncio.run(_run())
    assert result.launched
    assert result.agent_id == "bc_test123"


def test_attach_handoff_merges_json(tmp_path):
    p = tmp_path / "qa_test.json"
    p.write_text(json.dumps({"run_id": "qa_test", "passed": False}), encoding="utf-8")
    from app.cursor_client import CursorLaunchResult

    attach_handoff_to_report_json(
        p, CursorLaunchResult(launched=True, agent_id="bc_1", agent_url="https://cursor.com/agents?id=bc_1")
    )
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["cursor_handoff"]["launched"] is True
    assert data["cursor_handoff"]["agent_id"] == "bc_1"
