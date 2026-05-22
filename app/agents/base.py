"""Common scaffolding shared by every agent."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Awaitable, Callable, Optional

from ..models import AgentEvent, Crew, Job
from ..scheduling_prefs import DEFAULT_MODE, SchedulingMode


EventEmitter = Callable[[AgentEvent], Awaitable[None]]


@dataclass
class AgentContext:
    """Shared mutable scratchpad threaded through every agent in a run."""

    week_start: date
    crews: list[Crew]
    jobs: list[Job]
    scheduling_mode: SchedulingMode = DEFAULT_MODE
    emitter: Optional[EventEmitter] = None
    blackboard: dict = field(default_factory=dict)
    events: list[AgentEvent] = field(default_factory=list)

    async def emit(
        self,
        agent: str,
        phase: str,
        message: str,
        detail: dict | None = None,
        *,
        kind: str = "agent",
    ) -> None:
        evt = AgentEvent(agent=agent, phase=phase, message=message, detail=detail, kind=kind)
        self.events.append(evt)
        if self.emitter:
            await self.emitter(evt)

    async def emit_tool(
        self, tool: str, phase: str, message: str, detail: dict | None = None
    ) -> None:
        """Emit a tool-style step (deterministic op the agent invoked)."""
        d = dict(detail or {})
        d["tool"] = tool
        await self.emit("ToolRunner", phase, message, d, kind="tool")

    async def emit_llm(
        self, phase: str, message: str, detail: dict | None = None
    ) -> None:
        await self.emit("LLM", phase, message, detail, kind="llm")


class Agent:
    name: str = "agent"

    async def run(self, ctx: AgentContext) -> None:  # pragma: no cover - interface
        raise NotImplementedError


# ---------- shared helpers ----------

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in kilometers."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def drive_minutes(distance_km: float, avg_speed_kmh: float = 35.0) -> int:
    """Rough drive-time estimate. Add 5-minute base for stop setup."""
    return int(round((distance_km / avg_speed_kmh) * 60)) + 5


def week_days(week_start: date, n: int = 5) -> list[date]:
    return [week_start + timedelta(days=i) for i in range(n)]


def llm_trace_callback(ctx: AgentContext):
    """Build an LLM trace hook that streams via the shared agent context."""

    async def _trace(phase: str, message: str, detail: dict) -> None:
        await ctx.emit_llm(phase, message, detail)

    return _trace
