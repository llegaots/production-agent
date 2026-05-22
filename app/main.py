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
from .row_import import build_import_batch, materialize_import
from .seed import seed
from .storage import store
from .supabase_client import supabase
from .supabase_store import (
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
        "model": llm.model if llm.enabled else None,
        "supabase_enabled": supabase.enabled,
    }


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


@app.get("/api/config")
async def get_config() -> dict:
    """Safe runtime config for the UI (no secrets)."""
    return {
        "llm_enabled": llm.enabled,
        "llm_model": llm.model if llm.enabled else None,
        "geocoding_enabled": geocoder.enabled,
        "supabase_enabled": supabase.enabled,
        "env_file": ".env",
        "env_vars": {
            "OPENAI_API_KEY": "Enables LLM summaries and client messages",
            "OPENAI_BASE_URL": "Optional OpenAI-compatible API base URL",
            "OPENAI_MODEL": "Model id (default gpt-4o-mini)",
            "GOOGLE_MAPS_API_KEY": "Google Geocoding API — address → lat/lng in Geo agent",
            "SUPABASE_URL": "Optional persistence",
            "SUPABASE_SERVICE_ROLE_KEY": "Server-only; never put in the browser",
        },
    }


# ---------- mutation / planning endpoints ----------


class PlanRequest(BaseModel):
    week_start: Optional[date] = None


@app.post("/api/plan", response_model=PlanResult)
async def plan_week(req: PlanRequest) -> PlanResult:
    supervisor = SupervisorAgent()
    result = await supervisor.plan_week(req.week_start)
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
            result = await supervisor.plan_week(req.week_start, emitter=emitter)
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
    result = await rescheduler.run_reschedule(plan, req.job_id, req.reason)
    try:
        await persist_job_status(req.job_id, JobStatus.RESCHEDULED)
        await persist_reschedule_events(None, req.job_id, result.events)
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
                plan, req.job_id, req.reason, emitter=emitter
            )
            try:
                await persist_job_status(req.job_id, JobStatus.RESCHEDULED)
                await persist_reschedule_events(None, req.job_id, result.events)
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
