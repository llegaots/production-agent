"""FastAPI entrypoint for ProductionAgent."""
from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from typing import AsyncIterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .agents import ReschedulerAgent, SupervisorAgent
from .geocode import geocoder
from .llm import llm
from .models import (
    AgentEvent,
    Client,
    Crew,
    Equipment,
    ImportConfirmRequest,
    ImportParseRequest,
    Job,
    JobStatus,
    PlanResult,
    RescheduleRequest,
    RescheduleResult,
)
from .env_load import ENV_PATH
from .cursor_client import cursor_cloud
from .cursor_handoff import attach_handoff_to_report_json, trigger_automatic_handoff
from .qa_jobs import job_status_payload, start_background_qa
from .qa_team import QATeamRunner, list_qa_reports
from .reorganize import parse_reorganize_instruction
from .row_import import build_import_batch, materialize_import
from .scheduling_prefs import parse_mode
from .seed import seed
from .storage import store
from .vision import ACCEPTANCE_CRITERIA, PRODUCTION_MANAGER_VISION
from .supabase_client import supabase
from .supabase_store import (
    get_last_plan_id,
    hydrate_from_supabase,
    persist_job_status,
    persist_plan,
    persist_reschedule_events,
)

app = FastAPI(title="ProductionAgent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

ROOT = Path(__file__).resolve().parent.parent
STATIC_DIR = ROOT / "static"


@app.on_event("startup")
async def _startup() -> None:
    # If Supabase is configured, hydrate from the database so the agents
    # see real persisted data. Otherwise fall back to the in-memory seed
    # so the demo still runs offline.
    #
    # Cap wait at 8s so a bad SUPABASE_URL cannot block the server from
    # accepting connections (which browsers report as ERR_EMPTY_RESPONSE).
    if supabase.enabled:
        try:
            info = await asyncio.wait_for(hydrate_from_supabase(), timeout=8.0)
            if not info.get("jobs"):
                seed(reset=True)
        except Exception:
            seed(reset=True)
    else:
        seed(reset=True)


@app.get("/api/ping")
async def ping() -> dict:
    """Lightweight liveness check (no store access)."""
    return {"pong": True}


# ---------- read endpoints ----------


@app.get("/api/health")
async def health() -> dict:
    return {
        "ok": True,
        "llm_enabled": llm.enabled,
        "llm_provider": llm.provider if llm.enabled else None,
        "model": llm.model if llm.enabled else None,
        "model_source": getattr(llm, "model_source", None) if llm.enabled else None,
        "env_file": str(ENV_PATH) if ENV_PATH.exists() else None,
        "supabase_enabled": supabase.enabled,
        "cursor_handoff_enabled": cursor_cloud.enabled,
        "qa_api": True,
        "qa_modes": ["ai", "legacy"],
    }


@app.get("/api/qa/ping")
async def qa_ping() -> dict:
    """Liveness check for QA routes (use to detect stale server processes)."""
    return {"qa": True, "run": "POST /api/qa/run"}


@app.get("/api/jobs", response_model=list[Job])
async def list_jobs() -> list[Job]:
    return store.list_jobs()


@app.get("/api/crews", response_model=list[Crew])
async def list_crews() -> list[Crew]:
    return store.list_crews()


@app.get("/api/equipment", response_model=list[Equipment])
async def list_equipment() -> list[Equipment]:
    return store.list_equipment()


@app.get("/api/clients", response_model=list[Client])
async def list_clients() -> list[Client]:
    return store.list_clients()


@app.get("/api/plan", response_model=Optional[PlanResult])
async def get_plan() -> Optional[PlanResult]:
    return store.get_plan()


@app.get("/api/plan/confirmed", response_model=Optional[PlanResult])
async def get_confirmed_plan() -> Optional[PlanResult]:
    return store.get_confirmed_plan()


@app.post("/api/plan/confirm", response_model=PlanResult)
async def confirm_plan() -> PlanResult:
    """Publish the latest draft plan to the live schedule tab."""
    plan = store.get_plan()
    if not plan:
        raise HTTPException(status_code=400, detail="No draft plan yet. Plan the week in chat first.")
    published = plan.model_copy(deep=True)
    store.set_confirmed_plan(published)
    return published


@app.get("/api/preferences/scheduling")
async def get_scheduling_preference() -> dict:
    return {"mode": store.scheduling_mode.value}


@app.put("/api/preferences/scheduling")
async def set_scheduling_preference(body: dict) -> dict:
    mode = parse_mode(body.get("mode"))
    store.scheduling_mode = mode
    return {"mode": mode.value}


@app.get("/api/vision")
async def get_vision() -> dict:
    return {
        "vision": PRODUCTION_MANAGER_VISION,
        "acceptance_criteria": ACCEPTANCE_CRITERIA,
    }


@app.get("/api/config")
async def get_config() -> dict:
    """Safe runtime config for the UI (no secrets)."""
    return {
        "llm_enabled": llm.enabled,
        "llm_provider": llm.provider if llm.enabled else None,
        "llm_provider_label": llm.provider_label if llm.enabled else None,
        "llm_model": llm.model if llm.enabled else None,
        "llm_model_source": getattr(llm, "model_source", None) if llm.enabled else None,
        "env_file_path": str(ENV_PATH) if ENV_PATH.exists() else None,
        "geocoding_enabled": geocoder.enabled,
        "supabase_enabled": supabase.enabled,
        "cursor_handoff_enabled": cursor_cloud.enabled,
        "cursor_auto_handoff": cursor_cloud.auto_handoff_default,
        "cursor_repository": cursor_cloud.repository,
        "cursor_ref": cursor_cloud.ref,
        "env_file": ".env",
        "env_vars": {
            "ANTHROPIC_API_KEY": "Claude agents (recommended) — summaries & client messages",
            "ANTHROPIC_MODEL": "Claude model (default claude-sonnet-4-20250514)",
            "LLM_PROVIDER": "anthropic | openai (auto-detect if unset)",
            "OPENAI_API_KEY": "Optional OpenAI instead of Claude",
            "OPENAI_MODEL": "OpenAI model (default gpt-4o-mini)",
            "GOOGLE_MAPS_API_KEY": "Google Geocoding API — address → lat/lng in Geo agent",
            "SUPABASE_URL": "Optional persistence",
            "SUPABASE_SERVICE_ROLE_KEY": "Server-only; never put in the browser",
            "CURSOR_API_KEY": "Cloud Agents API key — auto-launch coding agent after QA",
            "CURSOR_REPOSITORY": "GitHub repo URL (optional if git origin is set)",
            "CURSOR_REF": "Branch/ref for cloud agent (default: current git branch)",
            "CURSOR_AUTO_HANDOFF": "true/false — launch agent after QA (default true when key set)",
            "CURSOR_AUTO_HANDOFF_ON_FAIL_ONLY": "true — only launch when QA fails",
            "CURSOR_AUTO_CREATE_PR": "true — cloud agent opens a PR with fixes",
        },
    }


# ---------- mutation / planning endpoints ----------


class PlanRequest(BaseModel):
    week_start: Optional[date] = None
    scheduling_mode: Optional[str] = None


class ReorganizeRequest(BaseModel):
    instruction: str
    week_start: Optional[date] = None


class QARunRequest(BaseModel):
    reset_seed: bool = True
    auto_cursor_handoff: Optional[bool] = None
    mode: str = "ai"  # ai | legacy
    background: bool = True  # avoid proxy/browser timeout on long AI runs


@app.post("/api/plan", response_model=PlanResult)
async def plan_week(req: PlanRequest) -> PlanResult:
    supervisor = SupervisorAgent()
    mode = parse_mode(req.scheduling_mode) if req.scheduling_mode else None
    result = await supervisor.plan_week(req.week_start, scheduling_mode=mode)
    try:
        await persist_plan(result)
    except Exception:
        # Persistence is best-effort; in-memory plan still serves the response.
        pass
    return result


@app.post("/api/plan/stream")
async def plan_week_stream(req: PlanRequest) -> StreamingResponse:
    """Server-Sent Events stream of agent reasoning while planning."""
    queue: asyncio.Queue = asyncio.Queue()
    sentinel: dict = {"_done": False, "result": None}

    async def emitter(evt: AgentEvent) -> None:
        await queue.put({"type": "event", "data": evt.model_dump(mode="json")})

    async def runner() -> None:
        try:
            supervisor = SupervisorAgent()
            mode = parse_mode(req.scheduling_mode) if req.scheduling_mode else None
            result = await supervisor.plan_week(
                req.week_start, emitter=emitter, scheduling_mode=mode
            )
            try:
                await persist_plan(result)
            except Exception:
                pass
            await queue.put({"type": "result", "data": result.model_dump(mode="json")})
        except Exception as exc:  # noqa: BLE001
            await queue.put({"type": "error", "data": {"message": str(exc)}})
        finally:
            sentinel["_done"] = True
            await queue.put(None)

    async def event_gen() -> AsyncIterator[bytes]:
        task = asyncio.create_task(runner())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n".encode()
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/reschedule", response_model=RescheduleResult)
async def reschedule(req: RescheduleRequest) -> RescheduleResult:
    plan = store.get_plan()
    if not plan:
        raise HTTPException(status_code=400, detail="No plan exists yet. Run /api/plan first.")
    rescheduler = ReschedulerAgent()
    result = await rescheduler.run_reschedule(
        plan,
        req.job_id,
        req.reason,
        new_earliest=req.new_earliest,
        new_latest=req.new_latest,
    )
    try:
        await persist_job_status(req.job_id, JobStatus.RESCHEDULED)
        await persist_reschedule_events(get_last_plan_id(), req.job_id, result.events)
    except Exception:
        pass
    return result


@app.post("/api/reschedule/stream")
async def reschedule_stream(req: RescheduleRequest) -> StreamingResponse:
    """SSE stream of reschedule agent steps."""
    plan = store.get_plan()
    if not plan:
        raise HTTPException(status_code=400, detail="No plan exists yet. Run /api/plan first.")

    queue: asyncio.Queue = asyncio.Queue()

    async def emitter(evt: AgentEvent) -> None:
        await queue.put({"type": "event", "data": evt.model_dump(mode="json")})

    async def runner() -> None:
        try:
            rescheduler = ReschedulerAgent()
            result = await rescheduler.run_reschedule(
                plan,
                req.job_id,
                req.reason,
                emitter=emitter,
                new_earliest=req.new_earliest,
                new_latest=req.new_latest,
            )
            try:
                await persist_job_status(req.job_id, JobStatus.RESCHEDULED)
                await persist_reschedule_events(get_last_plan_id(), req.job_id, result.events)
            except Exception:
                pass
            await queue.put({"type": "result", "data": result.model_dump(mode="json")})
        except Exception as exc:  # noqa: BLE001
            await queue.put({"type": "error", "data": {"message": str(exc)}})
        finally:
            await queue.put(None)

    async def event_gen() -> AsyncIterator[bytes]:
        task = asyncio.create_task(runner())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n".encode()
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/jobs/{job_id}/confirm", response_model=Job)
async def confirm_job(job_id: str) -> Job:
    job = store.set_job_status(job_id, JobStatus.CONFIRMED)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        await persist_job_status(job_id, JobStatus.CONFIRMED)
    except Exception:
        pass
    return job


@app.post("/api/jobs/{job_id}/cancel", response_model=Job)
async def cancel_job(job_id: str) -> Job:
    job = store.set_job_status(job_id, JobStatus.CANCELLED)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    plan = store.get_plan()
    if plan:
        for cd in plan.plan.days:
            cd.stops = [s for s in cd.stops if s.job_id != job_id]
        store.set_plan(plan)
    try:
        await persist_job_status(job_id, JobStatus.CANCELLED)
    except Exception:
        pass
    return job


@app.post("/api/jobs", response_model=Job)
async def create_job(job: Job) -> Job:
    return store.upsert_job(job)


@app.post("/api/seed/reset")
async def reset_seed() -> dict:
    seed(reset=True)
    return {"ok": True, "jobs": len(store.list_jobs())}


# ---------- reorganize (chat-driven) ----------


@app.post("/api/reorganize/stream")
async def reorganize_stream(req: ReorganizeRequest) -> StreamingResponse:
    """Parse owner instruction, apply scheduling mode, replan or reschedule one job."""
    from .agents.supervisor import _next_monday

    ws = req.week_start or _next_monday()
    intent = parse_reorganize_instruction(req.instruction, ws)
    store.scheduling_mode = intent.scheduling_mode
    queue: asyncio.Queue = asyncio.Queue()

    async def emitter(evt: AgentEvent) -> None:
        await queue.put({"type": "event", "data": evt.model_dump(mode="json")})

    async def runner() -> None:
        try:
            await queue.put(
                {
                    "type": "event",
                    "data": AgentEvent(
                        agent="Reorganize",
                        phase="intent",
                        message=f"Mode={intent.scheduling_mode.value}"
                        + (f", job={intent.job_id}" if intent.job_id else ", full replan"),
                        detail={
                            "scheduling_mode": intent.scheduling_mode.value,
                            "job_id": intent.job_id,
                            "target_day": intent.target_day.isoformat()
                            if intent.target_day
                            else None,
                        },
                        kind="system",
                    ).model_dump(mode="json"),
                }
            )
            if intent.job_id:
                plan = store.get_plan()
                if not plan:
                    await queue.put(
                        {
                            "type": "error",
                            "data": {"message": "No plan yet. Plan the week first."},
                        }
                    )
                    return
                rescheduler = ReschedulerAgent()
                result = await rescheduler.run_reschedule(
                    plan,
                    intent.job_id,
                    intent.reason,
                    emitter=emitter,
                    preferred_day=intent.target_day,
                )
                try:
                    await persist_job_status(intent.job_id, JobStatus.RESCHEDULED)
                    await persist_reschedule_events(
                        get_last_plan_id(), intent.job_id, result.events
                    )
                except Exception:
                    pass
                await queue.put({"type": "result", "data": result.model_dump(mode="json")})
            else:
                supervisor = SupervisorAgent()
                result = await supervisor.plan_week(
                    ws, emitter=emitter, scheduling_mode=intent.scheduling_mode
                )
                try:
                    await persist_plan(result)
                except Exception:
                    pass
                await queue.put({"type": "result", "data": result.model_dump(mode="json")})
        except Exception as exc:  # noqa: BLE001
            await queue.put({"type": "error", "data": {"message": str(exc)}})
        finally:
            await queue.put(None)

    async def event_gen() -> AsyncIterator[bytes]:
        task = asyncio.create_task(runner())
        try:
            while True:
                item = await queue.get()
                if item is None:
                    break
                yield f"data: {json.dumps(item)}\n\n".encode()
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------- QA team ----------


@app.post("/api/qa/run")
async def qa_run(req: QARunRequest) -> dict:
    """Run QA: AI operator loop (default) or legacy rule-based suite."""
    mode = (req.mode or "ai").strip().lower()
    if mode not in ("ai", "legacy"):
        raise HTTPException(status_code=400, detail="mode must be 'ai' or 'legacy'")
    if mode == "ai" and not llm.enabled:
        raise HTTPException(
            status_code=400,
            detail="AI QA requires ANTHROPIC_API_KEY or OPENAI_API_KEY in .env (then restart ./run.sh). Use mode=legacy without LLM.",
        )
    if req.background:
        try:
            return await start_background_qa(
                reset_seed=req.reset_seed,
                auto_cursor_handoff=req.auto_cursor_handoff,
                mode=mode,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=500, detail=f"QA start failed: {exc}") from exc
    try:
        runner = QATeamRunner()
        report = await runner.run_full_suite(
            reset_seed=req.reset_seed,
            auto_cursor_handoff=req.auto_cursor_handoff,
            mode=mode,
        )
        return report.to_dict()
    except HTTPException:
        raise
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"QA run failed: {exc}") from exc


@app.get("/api/qa/status/{run_id}")
async def qa_run_status(run_id: str) -> dict:
    """Poll a background QA job (or load a finished report from disk)."""
    return job_status_payload(run_id)


@app.post("/api/qa/handoff/{run_id}")
async def qa_trigger_handoff(run_id: str) -> dict:
    """Manually launch (or re-launch) a Cursor Cloud Agent for an existing QA report."""
    json_path = ROOT / "reports" / f"qa_{run_id}.json"
    md_path = ROOT / "reports" / f"cursor-handoff_{run_id}.md"
    if not md_path.exists():
        raise HTTPException(status_code=404, detail="Handoff report not found")
    passed = False
    score = 0
    if json_path.exists():
        data = json.loads(json_path.read_text(encoding="utf-8"))
        passed = bool(data.get("passed"))
        score = int(data.get("overall_score") or 0)

    result = await trigger_automatic_handoff(
        run_id=run_id,
        handoff_path=md_path,
        passed=passed,
        overall_score=score,
        force=True,
    )
    attach_handoff_to_report_json(json_path, result)
    return result.to_dict()


@app.get("/api/cursor/agents/{agent_id}")
async def cursor_agent_status(agent_id: str) -> dict:
    if not cursor_cloud.enabled:
        raise HTTPException(status_code=400, detail="CURSOR_API_KEY not configured")
    return await cursor_cloud.get_agent(agent_id)


@app.get("/api/qa/reports")
async def qa_reports_list() -> dict:
    return {"reports": list_qa_reports()}


@app.get("/api/qa/reports/{run_id}")
async def qa_report_detail(run_id: str) -> dict:
    path = ROOT / "reports" / f"qa_{run_id}.json"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------- spreadsheet import ----------


@app.post("/api/import/parse")
async def import_parse(req: ImportParseRequest) -> dict:
    """Parse pasted spreadsheet rows; normalize addresses with confidence scores."""
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Paste is empty.")
    return await build_import_batch(req.text)


@app.post("/api/import/confirm")
async def import_confirm(req: ImportConfirmRequest) -> dict:
    """After user confirms ambiguous addresses, load clients and jobs into the store."""
    if not req.rows:
        raise HTTPException(status_code=400, detail="No rows to import.")
    clients, jobs = materialize_import(req.rows, address_overrides=req.address_overrides)
    for c in clients:
        store.clients[c.id] = c
    for j in jobs:
        store.upsert_job(j)
    return {
        "ok": True,
        "clients": len(clients),
        "jobs": len(jobs),
        "job_ids": [j.id for j in jobs],
    }


# ---------- static UI ----------

if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")
