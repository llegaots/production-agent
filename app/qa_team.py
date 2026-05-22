"""QA agent team — continuous validation against the production-manager vision."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from .agents import ReschedulerAgent, SupervisorAgent
from .agents.supervisor import _next_monday
from .audit_log import REPORTS_DIR, AuditLogger
from .geocode import geocoder
from .models import JobStatus, PlanResult
from .reorganize import parse_reorganize_instruction
from .scheduling_prefs import SchedulingMode
from .seed import seed
from .storage import store
from .supabase_client import supabase
from .supabase_store import fetch_plan_db_snapshot, get_last_plan_id
from .cursor_handoff import attach_handoff_to_report_json, trigger_automatic_handoff
from .vision import ACCEPTANCE_CRITERIA, PRODUCTION_MANAGER_VISION

ROOT = Path(__file__).resolve().parent.parent


@dataclass
class CriterionResult:
    id: str
    title: str
    passed: bool
    score: int  # 0-100
    evidence: str
    weight: int


@dataclass
class QAReport:
    run_id: str
    started_at: str
    finished_at: str
    overall_score: int
    passed: bool
    scheduling_modes_tested: list[str]
    criteria: list[CriterionResult] = field(default_factory=list)
    scenarios: list[dict[str, Any]] = field(default_factory=list)
    db_checks: list[dict[str, Any]] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    audit_path: str = ""
    report_json_path: str = ""
    cursor_handoff_path: str = ""
    cursor_handoff: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "overall_score": self.overall_score,
            "passed": self.passed,
            "scheduling_modes_tested": self.scheduling_modes_tested,
            "criteria": [c.__dict__ for c in self.criteria],
            "scenarios": self.scenarios,
            "db_checks": self.db_checks,
            "recommendations": self.recommendations,
            "audit_path": self.audit_path,
            "report_json_path": self.report_json_path,
            "cursor_handoff_path": self.cursor_handoff_path,
            "cursor_handoff": self.cursor_handoff,
            "vision_excerpt": PRODUCTION_MANAGER_VISION[:400] + "…",
        }


class QATeamRunner:
    """Runs scripted scenarios, scores acceptance criteria, writes human + Cursor reports."""

    def __init__(self, audit: Optional[AuditLogger] = None) -> None:
        self.audit = audit or AuditLogger(label="qa")

    async def run_full_suite(
        self,
        *,
        reset_seed: bool = True,
        auto_cursor_handoff: Optional[bool] = None,
        mode: str = "ai",
    ) -> QAReport:
        """Run QA: ``ai`` = operator LLM loop (default); ``legacy`` = rule-based scenarios."""
        if mode == "legacy":
            return await self._run_legacy_suite(
                reset_seed=reset_seed,
                auto_cursor_handoff=auto_cursor_handoff,
            )
        from .qa_ai.runner import AIQATeamRunner

        return await AIQATeamRunner(audit=self.audit).run(
            auto_cursor_handoff=auto_cursor_handoff,
        )

    async def _run_legacy_suite(
        self,
        *,
        reset_seed: bool = True,
        auto_cursor_handoff: Optional[bool] = None,
    ) -> QAReport:
        started = datetime.now(timezone.utc).isoformat()
        self.audit.log("QATeam", "start", "Starting legacy rule-based QA suite.")
        scenarios: list[dict[str, Any]] = []
        db_checks: list[dict[str, Any]] = []
        modes_tested: list[str] = []

        if reset_seed:
            seed(reset=True)
            self.audit.log("QATeam", "seed", "Reset in-memory seed data for deterministic scenarios.")

        ws = _next_monday()

        # Scenario A: geo-first plan
        geo_result = await self._scenario_plan(SchedulingMode.GEO_FIRST, ws, "plan_geo_first")
        scenarios.append(geo_result)
        modes_tested.append(SchedulingMode.GEO_FIRST.value)

        # Scenario B: crew-fill plan (compare utilization)
        seed(reset=True)
        crew_result = await self._scenario_plan(SchedulingMode.CREW_FILL, ws, "plan_crew_fill")
        scenarios.append(crew_result)
        modes_tested.append(SchedulingMode.CREW_FILL.value)

        # Scenario C: reorganize intent parsing
        intent_case = self._scenario_reorganize_parse(ws)
        scenarios.append(intent_case)

        # Scenario D: reschedule dynamics (needs a plan)
        seed(reset=True)
        plan_base = await SupervisorAgent().plan_week(ws, scheduling_mode=SchedulingMode.BALANCED)
        reschedule_case = await self._scenario_reschedule(plan_base, ws)
        scenarios.append(reschedule_case)

        # DB verification after last plan
        db_checks.append(await self._verify_database(plan_base))

        criteria = self._score_criteria(scenarios, db_checks)
        recommendations = self._build_recommendations(criteria, scenarios)
        weighted = sum(c.score * c.weight for c in criteria) / max(1, sum(c.weight for c in criteria))
        overall = int(round(weighted))
        passed = overall >= 70 and all(
            c.passed for c in criteria if c.id in ("hard_constraints", "reschedule_integrity")
        )

        finished = datetime.now(timezone.utc).isoformat()
        report = QAReport(
            run_id=self.audit.run_id,
            started_at=started,
            finished_at=finished,
            overall_score=overall,
            passed=passed,
            scheduling_modes_tested=modes_tested,
            criteria=criteria,
            scenarios=scenarios,
            db_checks=db_checks,
            recommendations=recommendations,
            audit_path=str(REPORTS_DIR / f"audit_{self.audit.run_id}.jsonl"),
        )
        report.report_json_path = str(self._write_json_report(report, mode="legacy"))
        handoff_path = self._write_cursor_handoff(report)
        report.cursor_handoff_path = str(handoff_path)

        launch = await trigger_automatic_handoff(
            run_id=report.run_id,
            handoff_path=handoff_path,
            passed=passed,
            overall_score=overall,
            audit=self.audit,
            auto_handoff=auto_cursor_handoff,
        )
        report.cursor_handoff = launch.to_dict()
        attach_handoff_to_report_json(Path(report.report_json_path), launch)

        self.audit.log(
            "QATeam",
            "done",
            f"QA complete — score {overall}/100, passed={passed}.",
            detail={
                "report_json": report.report_json_path,
                "cursor_launched": launch.launched,
                "cursor_agent_id": launch.agent_id,
            },
        )
        return report

    async def _scenario_plan(self, mode: SchedulingMode, ws: date, label: str) -> dict:
        self.audit.log("PlannerQA", "run", f"Planning week with mode={mode.value}", detail={"label": label})
        sup = SupervisorAgent()
        result = await sup.plan_week(ws, scheduling_mode=mode)
        plan = result.plan
        total = len(store.list_jobs())
        scheduled = sum(len(d.stops) for d in plan.days)
        coverage = scheduled / max(1, total)
        avg_util = (
            sum(d.utilization for d in plan.days) / max(1, len(plan.days)) if plan.days else 0.0
        )
        overbooked = sum(1 for d in plan.days if d.overbooked)
        out = {
            "label": label,
            "mode": mode.value,
            "scheduled": scheduled,
            "total_jobs": total,
            "coverage_pct": round(coverage * 100, 1),
            "unscheduled": plan.unscheduled_job_ids,
            "conflicts": len(plan.conflicts),
            "avg_utilization": round(avg_util, 2),
            "overbooked_days": overbooked,
            "crew_days": len(plan.days),
            "passed": coverage >= 0.75 and overbooked == 0,
        }
        self.audit.log(
            "PlannerQA",
            "result",
            f"{label}: {scheduled}/{total} scheduled, util avg {avg_util:.0%}.",
            detail=out,
        )
        return out

    def _scenario_reorganize_parse(self, ws: date) -> dict:
        samples = [
            "I don't like this week — reorganize and fill up the crews first",
            "Reorganize minimizing drive for job_003 on Thursday",
            "balanced schedule please",
        ]
        parsed = []
        for text in samples:
            intent = parse_reorganize_instruction(text, ws)
            parsed.append(
                {
                    "text": text,
                    "mode": intent.scheduling_mode.value,
                    "job_id": intent.job_id,
                    "target_day": intent.target_day.isoformat() if intent.target_day else None,
                }
            )
        ok = any(p["mode"] == SchedulingMode.CREW_FILL.value for p in parsed)
        ok = ok and any(p["job_id"] == "job_003" for p in parsed)
        out = {"label": "reorganize_parse", "parsed": parsed, "passed": ok}
        self.audit.log("ReorganizeQA", "parse", "Chat intent parsing checked.", detail=out)
        return out

    async def _scenario_reschedule(self, plan: PlanResult, ws: date) -> dict:
        job_id = None
        for cd in plan.plan.days:
            if cd.stops:
                job_id = cd.stops[0].job_id
                break
        if not job_id:
            return {"label": "reschedule", "passed": False, "reason": "no_scheduled_job"}

        before_day = store.find_job_day(job_id)
        agent = ReschedulerAgent()
        result = await agent.run_reschedule(
            plan,
            job_id,
            "QA: weather delay",
            new_earliest=ws,
            new_latest=ws + timedelta(days=14),
        )
        after_day = store.find_job_day(job_id)
        removed_ok = before_day is None or after_day != before_day or result.succeeded
        out = {
            "label": "reschedule",
            "job_id": job_id,
            "succeeded": result.succeeded,
            "new_day": result.new_day.isoformat() if result.new_day else None,
            "new_crew_id": result.new_crew_id,
            "events": len(result.events),
            "before_day": before_day.isoformat() if before_day else None,
            "after_day": after_day.isoformat() if after_day else None,
            "passed": result.succeeded and result.new_day is not None,
        }
        self.audit.log("RescheduleQA", "result", f"Reschedule {job_id}: ok={result.succeeded}", detail=out)
        return out

    async def _verify_database(self, plan_result: PlanResult) -> dict:
        plan_id = get_last_plan_id()
        if not supabase.enabled:
            mem = {
                "ok": True,
                "source": "memory",
                "scheduled_in_plan": sum(len(d.stops) for d in plan_result.plan.days),
                "plan_id": plan_id,
            }
            self.audit.log("DBVerify", "skip", "Supabase off — verified in-memory plan only.", detail=mem)
            return mem

        if not plan_id:
            return {"ok": False, "reason": "no_plan_id_after_persist"}

        snap = await fetch_plan_db_snapshot(plan_id)
        mem_jobs = {s.job_id for cd in plan_result.plan.days for s in cd.stops}
        db_jobs = set(snap.get("stop_job_ids") or [])
        match = mem_jobs <= db_jobs or db_jobs == mem_jobs
        snap["memory_stop_count"] = len(mem_jobs)
        snap["jobs_match"] = match
        snap["plan_id"] = plan_id
        snap["passed"] = snap.get("ok") and snap.get("crew_days", 0) > 0 and match
        self.audit.log("DBVerify", "snapshot", "Compared plan to Supabase rows.", detail=snap)
        return snap

    def _score_criteria(
        self, scenarios: list[dict], db_checks: list[dict]
    ) -> list[CriterionResult]:
        plan_geo = next((s for s in scenarios if s.get("label") == "plan_geo_first"), {})
        plan_crew = next((s for s in scenarios if s.get("label") == "plan_crew_fill"), {})
        resched = next((s for s in scenarios if s.get("label") == "reschedule"), {})
        reorganize = next((s for s in scenarios if s.get("label") == "reorganize_parse"), {})
        db = db_checks[-1] if db_checks else {}

        results: list[CriterionResult] = []
        for spec in ACCEPTANCE_CRITERIA:
            cid = spec["id"]
            passed = False
            score = 0
            evidence = ""

            if cid == "schedule_coverage":
                cov = plan_geo.get("coverage_pct", 0)
                passed = cov >= 80
                score = min(100, int(cov * 1.1))
                evidence = f"Geo-first coverage {cov}% ({plan_geo.get('scheduled')}/{plan_geo.get('total_jobs')})."

            elif cid == "hard_constraints":
                ob = plan_geo.get("overbooked_days", 99)
                passed = ob == 0 and plan_geo.get("conflicts", 99) < 20
                score = 100 if passed else max(0, 50 - ob * 10)
                evidence = f"Overbooked crew-days: {ob}; conflicts: {plan_geo.get('conflicts')}."

            elif cid == "geocode_quality":
                if geocoder.enabled:
                    passed = True
                    score = 85
                    evidence = "Google geocoding enabled in runtime."
                else:
                    passed = True
                    score = 70
                    evidence = "Geocoder off in test env — using seed coordinates."

            elif cid == "reschedule_integrity":
                passed = bool(resched.get("passed"))
                score = 100 if passed else 0
                evidence = (
                    f"Reschedule succeeded={resched.get('succeeded')}, "
                    f"events={resched.get('events')}."
                )

            elif cid == "owner_control":
                passed = bool(reorganize.get("passed"))
                crew_util = plan_crew.get("avg_utilization", 0)
                geo_util = plan_geo.get("avg_utilization", 0)
                score = 100 if passed else 40
                if passed and crew_util >= geo_util - 0.05:
                    score = min(100, score + 10)
                evidence = (
                    f"Chat modes parsed; crew-fill avg util {crew_util:.0%} vs "
                    f"geo-first {geo_util:.0%}."
                )

            if db.get("passed") is False and cid == "reschedule_integrity":
                score = max(0, score - 20)
                evidence += " DB snapshot mismatch."

            results.append(
                CriterionResult(
                    id=cid,
                    title=spec["title"],
                    passed=passed,
                    score=score,
                    evidence=evidence,
                    weight=spec["weight"],
                )
            )
        return results

    def _build_recommendations(
        self, criteria: list[CriterionResult], scenarios: list[dict]
    ) -> list[str]:
        recs: list[str] = []
        for c in criteria:
            if not c.passed:
                recs.append(f"[{c.id}] {c.title}: {c.evidence}")
        plan_geo = next((s for s in scenarios if s.get("label") == "plan_geo_first"), {})
        if plan_geo.get("unscheduled"):
            recs.append(
                f"Unscheduled jobs: {', '.join(plan_geo['unscheduled'][:5])} — "
                "consider extending date windows or adding crew capacity."
            )
        if not recs:
            recs.append("All weighted criteria passed. Monitor live owner chat reorganize flows.")
        return recs

    def _write_json_report(self, report: QAReport, *, mode: str = "ai") -> Path:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / f"qa_{report.run_id}.json"
        payload = report.to_dict()
        payload["mode"] = mode
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    def _write_cursor_handoff(self, report: QAReport) -> Path:
        """Markdown brief for humans / Cursor coding agent."""
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / f"cursor-handoff_{report.run_id}.md"
        lines = [
            "# ProductionAgent QA handoff",
            "",
            f"- **Run ID:** `{report.run_id}`",
            f"- **Score:** {report.overall_score}/100 ({'PASS' if report.passed else 'NEEDS WORK'})",
            f"- **Finished:** {report.finished_at}",
            "",
            "## Vision",
            "",
            PRODUCTION_MANAGER_VISION,
            "",
            "## Acceptance criteria",
            "",
        ]
        for c in report.criteria:
            mark = "✅" if c.passed else "❌"
            lines.append(f"- {mark} **{c.title}** ({c.score}/100): {c.evidence}")
        lines.extend(["", "## Scenarios", ""])
        for s in report.scenarios:
            lines.append(f"- **{s.get('label')}**: passed={s.get('passed', '—')} — `{json.dumps(s, default=str)[:200]}`")
        lines.extend(["", "## DB checks", ""])
        for d in report.db_checks:
            lines.append(f"- `{json.dumps(d, default=str)[:300]}`")
        lines.extend(["", "## Recommended code changes", ""])
        for r in report.recommendations:
            lines.append(f"1. {r}")
        lines.extend(
            [
                "",
                "## For Cursor",
                "",
                "When `CURSOR_API_KEY` is set, ProductionAgent auto-launches a Cursor Cloud Agent",
                "with this report as the prompt. Otherwise paste this file into a Cursor session.",
                "",
                f"Audit log: `{report.audit_path}`",
            ]
        )
        path.write_text("\n".join(lines), encoding="utf-8")
        return path


def list_qa_reports() -> list[dict]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out: list[dict] = []
    for p in sorted(REPORTS_DIR.glob("qa_*.json"), reverse=True):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            out.append(
                {
                    "run_id": data.get("run_id", p.stem.replace("qa_", "")),
                    "finished_at": data.get("finished_at"),
                    "overall_score": data.get("overall_score"),
                    "passed": data.get("passed"),
                    "path": str(p),
                }
            )
        except Exception:
            continue
    return out
