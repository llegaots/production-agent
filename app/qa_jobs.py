"""In-memory background QA jobs — avoids browser/proxy timeouts on long AI runs."""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from .audit_log import REPORTS_DIR, AuditLogger
from .qa_team import QATeamRunner

QaJobStatus = Literal["running", "complete", "error"]


@dataclass
class QaJobRecord:
    run_id: str
    status: QaJobStatus
    mode: str
    started_at: str
    finished_at: Optional[str] = None
    report: Optional[dict[str, Any]] = None
    error: Optional[str] = None


_jobs: dict[str, QaJobRecord] = {}
_lock = asyncio.Lock()


def _audit_tail(run_id: str, limit: int = 8) -> list[dict[str, Any]]:
    path = REPORTS_DIR / f"audit_{run_id}.jsonl"
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        out: list[dict[str, Any]] = []
        for line in lines[-limit:]:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
    except OSError:
        return []


def get_job(run_id: str) -> Optional[QaJobRecord]:
    return _jobs.get(run_id)


def job_status_payload(run_id: str) -> dict[str, Any]:
    job = _jobs.get(run_id)
    if not job:
        saved = REPORTS_DIR / f"qa_{run_id}.json"
        if saved.exists():
            data = json.loads(saved.read_text(encoding="utf-8"))
            return {
                "run_id": run_id,
                "status": "complete",
                "mode": data.get("mode", "ai"),
                "report": data,
                "progress": {"entry_count": 0, "last": None},
            }
        return {"run_id": run_id, "status": "unknown", "error": "Run not found"}

    last_entries = _audit_tail(run_id)
    last = last_entries[-1] if last_entries else None
    payload: dict[str, Any] = {
        "run_id": job.run_id,
        "status": job.status,
        "mode": job.mode,
        "started_at": job.started_at,
        "finished_at": job.finished_at,
        "progress": {
            "entry_count": len(last_entries),
            "last_message": (last or {}).get("message"),
            "last_agent": (last or {}).get("agent"),
            "last_phase": (last or {}).get("phase"),
        },
    }
    if job.error:
        payload["error"] = job.error
    if job.report:
        payload["report"] = job.report
    return payload


async def _run_job(
    run_id: str,
    *,
    reset_seed: bool,
    mode: str,
    auto_cursor_handoff: Optional[bool],
) -> None:
    label = "qa_ai" if mode == "ai" else "qa"
    audit = AuditLogger(run_id=run_id, label=label)
    try:
        runner = QATeamRunner(audit=audit)
        report = await runner.run_full_suite(
            reset_seed=reset_seed,
            auto_cursor_handoff=auto_cursor_handoff,
            mode=mode,
        )
        async with _lock:
            rec = _jobs.get(run_id)
            if rec:
                rec.status = "complete"
                rec.finished_at = datetime.now(timezone.utc).isoformat()
                rec.report = report.to_dict()
    except Exception as exc:  # noqa: BLE001
        async with _lock:
            rec = _jobs.get(run_id)
            if rec:
                rec.status = "error"
                rec.finished_at = datetime.now(timezone.utc).isoformat()
                rec.error = str(exc)


async def start_background_qa(
    *,
    reset_seed: bool = True,
    mode: str = "ai",
    auto_cursor_handoff: Optional[bool] = None,
) -> dict[str, Any]:
    """Start QA in a background task; return immediately with run_id for polling."""
    label = "qa_ai" if mode == "ai" else "qa"
    audit = AuditLogger(label=label)
    run_id = audit.run_id
    started = datetime.now(timezone.utc).isoformat()

    async with _lock:
        _jobs[run_id] = QaJobRecord(
            run_id=run_id,
            status="running",
            mode=mode,
            started_at=started,
        )

    asyncio.create_task(
        _run_job(
            run_id,
            reset_seed=reset_seed,
            mode=mode,
            auto_cursor_handoff=auto_cursor_handoff,
        )
    )

    return {
        "status": "running",
        "run_id": run_id,
        "mode": mode,
        "poll_url": f"/api/qa/status/{run_id}",
        "message": "QA started in background. Poll status until complete.",
    }
