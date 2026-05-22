"""Automatic Cursor Cloud Agent launch after QA reports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .audit_log import AuditLogger
from .cursor_client import CursorLaunchResult, build_handoff_prompt, cursor_cloud


async def trigger_automatic_handoff(
    *,
    run_id: str,
    handoff_path: Path,
    passed: bool,
    overall_score: int,
    audit: Optional[AuditLogger] = None,
    force: bool = False,
    auto_handoff: Optional[bool] = None,
) -> CursorLaunchResult:
    """
    Launch a Cursor Cloud Agent with the handoff markdown as its prompt.

    Skips when CURSOR_API_KEY / repository are missing unless ``force`` is True.
    """
    if auto_handoff is None:
        auto_handoff = cursor_cloud.auto_handoff_default

    if not force:
        if not auto_handoff:
            return CursorLaunchResult(
                launched=False, skipped_reason="auto_handoff disabled"
            )
        if cursor_cloud.handoff_on_fail_only and passed:
            return CursorLaunchResult(
                launched=False,
                skipped_reason="QA passed (CURSOR_AUTO_HANDOFF_ON_FAIL_ONLY)"
            )
        if not cursor_cloud.enabled:
            return CursorLaunchResult(
                launched=False,
                skipped_reason=(
                    "Cursor Cloud not configured — set CURSOR_API_KEY and "
                    "CURSOR_REPOSITORY (or connect a GitHub origin remote)"
                ),
            )

    if not handoff_path.exists():
        return CursorLaunchResult(
            launched=False, skipped_reason=f"handoff file missing: {handoff_path}"
        )

    markdown = handoff_path.read_text(encoding="utf-8")

    # Block launch when QA produced no cases at all — the handoff has nothing
    # concrete for the Cursor agent to fix.  Without this guard, the agent
    # reads the Vision section and builds new features instead of fixing bugs.
    if not force and "Actionable findings:** NO" in markdown:
        return CursorLaunchResult(
            launched=False,
            skipped_reason=(
                "QA produced no actionable findings (0 cases ran or all passed). "
                "Cursor agent not launched — nothing concrete to fix. "
                "Check Anthropic credits or re-run QA after the LLM issue is resolved."
            ),
        )

    prompt = build_handoff_prompt(
        markdown, run_id=run_id, passed=passed, score=overall_score
    )

    if audit:
        audit.log(
            "CursorHandoff",
            "launch",
            "Launching Cursor Cloud Agent with QA handoff prompt.",
            detail={
                "run_id": run_id,
                "repository": cursor_cloud.repository,
                "ref": cursor_cloud.ref,
            },
        )

    result = await cursor_cloud.launch_agent(prompt)

    if audit:
        level = "info" if result.launched else "warning"
        audit.log(
            "CursorHandoff",
            "result",
            result.agent_url or result.error or result.skipped_reason or "skipped",
            detail=result.to_dict(),
            level=level,
        )

    return result


def attach_handoff_to_report_json(report_json_path: Path, handoff: CursorLaunchResult) -> None:
    """Merge cursor launch metadata into the saved QA JSON report."""
    if not report_json_path.exists():
        return
    try:
        data = json.loads(report_json_path.read_text(encoding="utf-8"))
        data["cursor_handoff"] = handoff.to_dict()
        report_json_path.write_text(
            json.dumps(data, indent=2, default=str), encoding="utf-8"
        )
    except Exception:
        pass
