"""Orchestrator: Anthropic tool-use loop with critic iteration."""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from anthropic import Anthropic

from app.config import get_settings
from app.orchestrator.context import OrchestratorContext
from app.orchestrator.prompts import SYSTEM_PROMPT
from app.orchestrator.schemas import (
    ScheduleIterationSummary,
    ScheduleRunResult,
    ScheduleWeekInput,
)
from app.optimizer.models import OptimizerResult
from app.orchestrator.tool_dispatch import TOOL_DEFINITIONS, execute_tool
from app.orchestrator.week_plan import (
    eligible_jobs_for_day,
    iter_week_days,
    load_job_date_windows,
)
from app.tools._db import tools_db
from app.tools.crew_availability import get_crew_availability
from app.tools.schemas import GetCrewAvailabilityInput

logger = logging.getLogger(__name__)


def _next_week_bounds(today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    week_start = today + timedelta(days=days_until_monday)
    week_end = week_start + timedelta(days=6)
    return week_start, week_end


def _load_pending_job_ids(
    week_start: date,
    week_end: date,
    limit: int = 50,
    *,
    job_id_prefix: str | None = None,
) -> list[str]:
    q = (
        tools_db()
        .table("jobs")
        .select("id")
        .eq("status", "pending")
        .lte("earliest_date", week_end.isoformat())
        .gte("latest_date", week_start.isoformat())
    )
    if job_id_prefix:
        q = q.like("id", f"{job_id_prefix}%")
    rows = q.limit(limit).execute().data or []
    return [r["id"] for r in rows]


def _create_schedule_run(inp: ScheduleWeekInput, week_start: date, week_end: date) -> UUID:
    row = {
        "user_request": inp.user_request,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "status": "running",
    }
    resp = tools_db().table("schedule_runs").insert(row).execute()
    return UUID(resp.data[0]["id"])


def _update_schedule_run(run_id: UUID, fields: dict[str, Any]) -> None:
    tools_db().table("schedule_runs").update(fields).eq("id", str(run_id)).execute()


def _log_iteration(
    run_id: UUID,
    iteration: int,
    *,
    attempt_id: UUID | None,
    critic_feedback_id: str | None,
    approved: bool,
    feedback_prompt: str,
    issues: list[str],
) -> None:
    tools_db().table("schedule_run_iterations").insert(
        {
            "schedule_run_id": str(run_id),
            "iteration_number": iteration,
            "schedule_attempt_id": str(attempt_id) if attempt_id else None,
            "critic_feedback_id": critic_feedback_id,
            "approved": approved,
            "feedback_prompt": feedback_prompt,
            "issues": issues,
        }
    ).execute()


def _get_langfuse_trace():
    settings = get_settings()
    if not settings.langfuse_public_key or not settings.langfuse_secret_key:
        logger.debug("Langfuse disabled: LANGFUSE_PUBLIC_KEY or LANGFUSE_SECRET_KEY not set")
        return None
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("Langfuse client initialized (host=%s)", settings.langfuse_host)
        return client
    except Exception:
        logger.exception("Failed to initialize Langfuse client (host=%s)", settings.langfuse_host)
        return None


def _anthropic_client() -> Anthropic:
    settings = get_settings()
    if not settings.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY required for orchestrator")
    return Anthropic(api_key=settings.anthropic_api_key, timeout=120.0)


def _anthropic_messages_create(
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    system: str,
) -> dict[str, Any]:
    settings = get_settings()
    response = _anthropic_client().messages.create(
        model=settings.anthropic_model,
        max_tokens=4096,
        system=system,
        messages=messages,
        tools=tools,
    )
    return response.model_dump()


def _run_tool_loop(
    ctx: OrchestratorContext,
    messages: list[dict[str, Any]],
    *,
    langfuse_span: Any = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """Process one agent turn cycle until end_turn or max inner steps."""
    final_text: str | None = None
    for _ in range(25):
        response = _anthropic_messages_create(
            messages=messages,
            tools=TOOL_DEFINITIONS,
            system=SYSTEM_PROMPT,
        )
        assistant_content = response.get("content") or []
        messages.append({"role": "assistant", "content": assistant_content})

        stop = response.get("stop_reason")
        tool_uses = [b for b in assistant_content if b.get("type") == "tool_use"]
        text_blocks = [b.get("text", "") for b in assistant_content if b.get("type") == "text"]
        if text_blocks:
            final_text = "\n".join(text_blocks).strip()

        if stop == "end_turn" and not tool_uses:
            break

        if not tool_uses:
            break

        tool_results = []
        for block in tool_uses:
            name = block["name"]
            tool_input = block.get("input") or {}
            tool_id = block["id"]
            try:
                result = execute_tool(name, tool_input, ctx)
            except Exception as exc:
                result = {"error": str(exc)}
            if langfuse_span:
                langfuse_span.event(name=f"tool:{name}", input=tool_input, output=result)
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": json.dumps(result),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    return messages, final_text


def _iteration_user_message(ctx: OrchestratorContext) -> str:
    primary_day = ctx.week_start.isoformat()
    msg = (
        f"Iteration {ctx.current_iteration} of {ctx.max_iterations}.\n"
        f"Schedule week: {ctx.week_start} to {ctx.week_end}.\n"
        f"Primary target_date for optimizer: {primary_day}.\n"
        f"Job IDs to schedule: {json.dumps(ctx.job_ids)}.\n"
        f"Crew IDs (if empty, discover via get_crew_availability): {json.dumps(ctx.crew_ids)}.\n"
        "Follow the iteration pattern: constraints → run_optimizer → save_schedule_attempt → critique_schedule.\n"
    )
    if ctx.critic_feedback:
        msg += (
            f"\nPrevious critic feedback_prompt (incorporate into this iteration):\n"
            f"{ctx.critic_feedback}\n"
        )
    return msg


def _merge_optimizer_results(
    accumulated: OptimizerResult | None,
    addition: OptimizerResult,
) -> OptimizerResult:
    from app.optimizer.models import OptimizerResult as OR

    if accumulated is None:
        return addition
    routes = [r for r in list(accumulated.routes) + list(addition.routes) if r.stops]
    assigned = set(accumulated.assigned_job_ids) | set(addition.assigned_job_ids)
    unassigned = set(accumulated.unassigned_job_ids) | set(addition.unassigned_job_ids)
    unassigned -= assigned
    status = addition.status if not routes else ("feasible" if unassigned else accumulated.status)
    return OR(
        status=status,
        routes=routes,
        unassigned_job_ids=sorted(unassigned),
        messages=list(accumulated.messages) + list(addition.messages),
        objective_cost=addition.objective_cost or accumulated.objective_cost,
    )


def _ensure_crew_ids(ctx: OrchestratorContext, day: date) -> None:
    if ctx.crew_ids:
        return
    avail = get_crew_availability(
        GetCrewAvailabilityInput(target_date=day, crew_ids=None),
    )
    ctx.crew_ids = [c.crew_id for c in avail.crews if c.is_available]


def _run_week_programmatic(ctx: OrchestratorContext) -> None:
    """Schedule across Mon–Fri with batched daily optimizer runs."""
    from app.optimizer.models import OptimizerResult

    all_job_ids = list(ctx.job_ids)
    windows = load_job_date_windows(all_job_ids)
    remaining = list(all_job_ids)
    merged: OptimizerResult | None = None
    last_target = ctx.week_start

    for day in iter_week_days(ctx.week_start, ctx.week_end):
        if not remaining:
            break
        _ensure_crew_ids(ctx, day)
        batch = eligible_jobs_for_day(remaining, day, windows=windows, limit=12)
        if not batch:
            continue

        execute_tool(
            "get_crew_availability",
            {"target_date": day.isoformat(), "crew_ids": ctx.crew_ids or None},
            ctx,
        )
        execute_tool(
            "check_equipment",
            {"job_ids": batch, "crew_ids": ctx.crew_ids},
            ctx,
        )
        execute_tool(
            "run_optimizer",
            {
                "target_date": day.isoformat(),
                "job_ids": batch,
                "crew_ids": ctx.crew_ids,
                "time_limit_seconds": 15,
            },
            ctx,
        )
        if ctx.last_optimizer_output:
            merged = _merge_optimizer_results(merged, ctx.last_optimizer_output.result)
            assigned = set(ctx.last_optimizer_output.result.assigned_job_ids)
            remaining = [j for j in remaining if j not in assigned]
            last_target = day

    if merged and ctx.last_optimizer_output:
        ctx.last_optimizer_output = ctx.last_optimizer_output.model_copy(
            update={"result": merged, "target_date": last_target},
        )
    elif remaining:
        _run_iteration_programmatic(ctx, target_date=ctx.week_start)
        return

    if not ctx.last_optimizer_output:
        _run_iteration_programmatic(ctx, target_date=ctx.week_start)
        return

    execute_tool(
        "save_schedule_attempt",
        {
            "target_date": last_target.isoformat(),
            "job_ids": all_job_ids,
            "crew_ids": ctx.crew_ids,
        },
        ctx,
    )
    execute_tool(
        "critique_schedule",
        {
            "target_date": last_target.isoformat(),
            "schedule_attempt_id": str(ctx.last_save_output.attempt_id),
        },
        ctx,
    )


def _run_iteration_programmatic(
    ctx: OrchestratorContext,
    *,
    target_date: date | None = None,
) -> None:
    """Deterministic tool sequence when Anthropic API is unavailable."""
    primary = (target_date or ctx.week_start).isoformat()
    execute_tool(
        "get_crew_availability",
        {"target_date": primary, "crew_ids": ctx.crew_ids or None},
        ctx,
    )
    execute_tool("check_equipment", {"job_ids": ctx.job_ids, "crew_ids": ctx.crew_ids}, ctx)
    execute_tool(
        "run_optimizer",
        {
            "target_date": primary,
            "job_ids": ctx.job_ids,
            "crew_ids": ctx.crew_ids,
            "time_limit_seconds": 10,
        },
        ctx,
    )
    execute_tool(
        "save_schedule_attempt",
        {
            "target_date": primary,
            "job_ids": ctx.job_ids,
            "crew_ids": ctx.crew_ids,
        },
        ctx,
    )
    execute_tool(
        "critique_schedule",
        {"target_date": primary, "schedule_attempt_id": str(ctx.last_save_output.attempt_id)},
        ctx,
    )


def run_scheduling_mission(inp: ScheduleWeekInput) -> ScheduleRunResult:
    """
    End-to-end scheduling: tool-use agent per iteration, critic gate, max 4 loops.
    """
    settings = get_settings()
    week_start, week_end = inp.week_start, inp.week_end
    if not week_start or not week_end:
        week_start, week_end = _next_week_bounds()

    load_limit = inp.job_load_limit or 200
    if inp.job_ids:
        job_ids = list(inp.job_ids)
    else:
        job_ids = _load_pending_job_ids(
            week_start,
            week_end,
            limit=load_limit,
            job_id_prefix=inp.job_id_prefix,
        )
    if not job_ids:
        raise ValueError(f"No pending jobs found for week {week_start} – {week_end}")

    max_iter = inp.max_iterations or settings.orchestrator_max_iterations
    run_id = _create_schedule_run(inp, week_start, week_end)

    ctx = OrchestratorContext(
        schedule_run_id=run_id,
        user_request=inp.user_request,
        week_start=week_start,
        week_end=week_end,
        job_ids=job_ids,
        crew_ids=list(inp.crew_ids or []),
        max_iterations=max_iter,
        use_llm_critic=inp.use_llm_critic,
    )

    langfuse = _get_langfuse_trace()
    trace = None
    trace_id: str | None = None
    if langfuse:
        trace = langfuse.trace(
            name="schedule_week",
            input={"user_request": inp.user_request, "week_start": str(week_start)},
            metadata={"schedule_run_id": str(run_id)},
        )
        trace_id = trace.id
        _update_schedule_run(run_id, {"langfuse_trace_id": trace_id})

    iterations_summary: list[ScheduleIterationSummary] = []
    approved = False
    final_text = ""

    use_anthropic = inp.use_agent and bool(settings.anthropic_api_key)
    messages: list[dict[str, Any]] = []
    if use_anthropic:
        messages = [
            {
                "role": "user",
                "content": (
                    f"{inp.user_request}\n\n"
                    f"Scheduling window: {week_start} to {week_end}.\n"
                    f"Pending job IDs in window: {json.dumps(job_ids)}.\n"
                    f"Maximum critic iterations: {max_iter}."
                ),
            }
        ]

    primary_target = inp.target_date or week_start

    for iteration in range(1, max_iter + 1):
        ctx.current_iteration = iteration

        span = trace.span(name=f"iteration_{iteration}") if trace else None
        if use_anthropic:
            messages.append({"role": "user", "content": _iteration_user_message(ctx)})
            messages, final_text = _run_tool_loop(ctx, messages, langfuse_span=span)
        else:
            _run_week_programmatic(ctx)
            assigned = 0
            if ctx.last_optimizer_output:
                assigned = len(ctx.last_optimizer_output.result.assigned_job_ids)
            final_text = (
                f"Programmatic week scheduling: {assigned}/{len(job_ids)} jobs assigned "
                f"across daily optimizer passes."
            )
            if span:
                span.event(
                    name="programmatic_iteration",
                    metadata={"approved": ctx.last_critique_approved},
                )
        if span:
            span.end(output={"approved": ctx.last_critique_approved})

        if ctx.last_save_output and ctx.last_critique_approved is not None:
            _log_iteration(
                run_id,
                iteration,
                attempt_id=ctx.last_save_output.attempt_id,
                critic_feedback_id=(
                    str(ctx.last_critic_feedback_id) if ctx.last_critic_feedback_id else None
                ),
                approved=bool(ctx.last_critique_approved),
                feedback_prompt=ctx.critic_feedback,
                issues=ctx.last_critique_issues,
            )
            iterations_summary.append(
                ScheduleIterationSummary(
                    iteration_number=iteration,
                    schedule_attempt_id=ctx.last_save_output.attempt_id,
                    approved=bool(ctx.last_critique_approved),
                    issues=list(ctx.last_critique_issues),
                    feedback_prompt=ctx.critic_feedback,
                )
            )

        if ctx.last_critique_approved:
            approved = True
            break

    if langfuse:
        langfuse.flush()

    status = "approved" if approved else "needs_human_review"
    completed = datetime.now(timezone.utc)
    summary = final_text or (
        "Schedule approved by critic." if approved else "Max iterations reached without approval."
    )

    _update_schedule_run(
        run_id,
        {
            "status": status,
            "approved": approved,
            "iteration_count": len(iterations_summary),
            "best_schedule_attempt_id": str(ctx.best_attempt_id) if ctx.best_attempt_id else None,
            "final_schedule_attempt_id": (
                str(ctx.last_save_output.attempt_id) if ctx.last_save_output else None
            ),
            "summary": summary,
            "completed_at": completed.isoformat(),
        },
    )

    return ScheduleRunResult(
        schedule_run_id=run_id,
        status=status,
        approved=approved,
        iteration_count=len(iterations_summary),
        week_start=week_start,
        week_end=week_end,
        iterations=iterations_summary,
        best_schedule_attempt_id=ctx.best_attempt_id,
        final_schedule_attempt_id=(
            ctx.last_save_output.attempt_id if ctx.last_save_output else None
        ),
        langfuse_trace_id=trace_id,
        summary=summary,
        needs_human_review=not approved,
        completed_at=completed,
        final_output={"messages_tail": messages[-2:] if messages else []},
    )
