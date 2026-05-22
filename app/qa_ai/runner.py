"""Reflective AI QA loop: design case → run → critique → retry → next case."""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from ..audit_log import AuditLogger
from ..llm import llm
from ..agents.supervisor import _next_monday
from ..audit_log import REPORTS_DIR
from ..qa_team import QAReport
from ..vision import ACCEPTANCE_CRITERIA, PRODUCTION_MANAGER_VISION
from ..cursor_handoff import attach_handoff_to_report_json, trigger_automatic_handoff
from .executor import apply_owner_retry, execute_case
from .llm_agents import critique_schedule, design_test_case, synthesize_run
from .registry import fingerprints_for_prompt, load_succeeded_cases, save_succeeded_case
from .schedule_snapshot import plan_result_context

ROOT = Path(__file__).resolve().parent.parent.parent


def _max_cases() -> int:
    return max(1, min(12, int(os.getenv("QA_MAX_CASES", "5"))))


def _max_iterations() -> int:
    return max(1, min(4, int(os.getenv("QA_MAX_ITERATIONS", "2"))))


class AIQATeamRunner:
    """Operator-style AI testing with self-reflection and non-repeating cases."""

    def __init__(self, audit: Optional[AuditLogger] = None) -> None:
        self.audit = audit or AuditLogger(label="qa_ai")

    async def run(
        self,
        *,
        auto_cursor_handoff: Optional[bool] = None,
    ) -> QAReport:
        if not llm.enabled:
            raise RuntimeError(
                "AI QA requires an LLM (set ANTHROPIC_API_KEY or OPENAI_API_KEY). "
                "Use POST /api/qa/run with mode=legacy for rule-based tests."
            )

        started = datetime.now(timezone.utc).isoformat()
        self.audit.log(
            "AIQATeam",
            "start",
            "Starting reflective AI QA (operator personas).",
            detail={"max_cases": _max_cases(), "max_iterations": _max_iterations()},
        )

        succeeded_history = fingerprints_for_prompt()
        case_results: list[dict[str, Any]] = []
        failed_fingerprints: list[dict] = []
        week_start = _next_monday()

        for case_idx in range(_max_cases()):
            case = await design_test_case(
                succeeded_fingerprints=succeeded_history + [c["fingerprint"] for c in case_results if c.get("passed")],
                failed_this_run=failed_fingerprints,
                case_index=case_idx,
            )
            if not case or not case.get("fingerprint"):
                self.audit.log("CaseDesigner", "fail", "Could not design case; stopping loop.")
                break

            fp = case["fingerprint"]
            if fp in succeeded_history:
                self.audit.log("CaseDesigner", "skip", f"Duplicate succeeded case {fp}")
                continue

            self.audit.log(
                "CaseDesigner",
                "case",
                case.get("title", fp),
                detail=case,
            )

            case_record: dict[str, Any] = {
                "fingerprint": fp,
                "title": case.get("title"),
                "persona_story": case.get("persona_story"),
                "what_good_looks_like": case.get("what_good_looks_like"),
                "iterations": [],
                "passed": False,
            }

            prior_critique: Optional[dict] = None
            for iteration in range(1, _max_iterations() + 1):
                self.audit.log(
                    "Executor",
                    "run",
                    f"Executing case {fp} iteration {iteration}",
                    detail={"steps": case.get("steps")},
                )
                if iteration == 1:
                    exec_result = await execute_case(case, week_start=week_start)
                else:
                    retry = (prior_critique or {}).get("owner_retry")
                    if not retry:
                        break
                    exec_result = await apply_owner_retry(retry, week_start=week_start)

                schedule_ctx = exec_result.to_dict().get("final_plan") or {}
                critique = await critique_schedule(
                    case=case,
                    schedule_context=schedule_ctx,
                    iteration=iteration,
                    prior_critique=prior_critique,
                )
                if not critique:
                    critique = {
                        "verdict": "fail",
                        "viability_score": 0,
                        "executive_summary": "Critic LLM returned no parseable JSON.",
                        "code_changes_for_engineers": ["Fix QA critic JSON parsing"],
                    }

                iter_record = {
                    "iteration": iteration,
                    "execution": exec_result.to_dict(),
                    "critique": critique,
                }
                case_record["iterations"].append(iter_record)

                verdict = (critique.get("verdict") or "fail").lower()
                self.audit.log(
                    "ScheduleCritic",
                    verdict,
                    critique.get("executive_summary", "")[:300],
                    detail={
                        "viability_score": critique.get("viability_score"),
                        "placement_critiques": critique.get("placement_critiques", [])[:5],
                    },
                )

                prior_critique = critique
                if verdict == "pass":
                    case_record["passed"] = True
                    case_record["final_critique"] = critique
                    save_succeeded_case(
                        fingerprint=fp,
                        title=case.get("title", fp),
                        run_id=self.audit.run_id,
                        viability_score=int(critique.get("viability_score") or 80),
                    )
                    succeeded_history.append(fp)
                    break
                if verdict == "fail" and not critique.get("owner_retry"):
                    case_record["final_critique"] = critique
                    break
                if iteration >= _max_iterations():
                    case_record["final_critique"] = critique

            if not case_record["passed"]:
                failed_fingerprints.append({"fingerprint": fp, "title": case.get("title")})

            case_results.append(case_record)

        synthesizer = await synthesize_run(cases=case_results) or {}
        self.audit.log("Synthesizer", "done", synthesizer.get("overall_assessment", "")[:200], detail=synthesizer)

        scores = [
            int((c.get("final_critique") or {}).get("viability_score") or 0)
            for c in case_results
            if c.get("final_critique")
        ]
        overall = int(sum(scores) / max(1, len(scores))) if scores else 0
        passed_cases = sum(1 for c in case_results if c.get("passed"))
        passed = passed_cases == len(case_results) and len(case_results) > 0

        recommendations: list[str] = []
        if synthesizer.get("recommended_cursor_tasks"):
            recommendations.extend(synthesizer["recommended_cursor_tasks"])
        for c in case_results:
            if c.get("passed"):
                continue
            crit = c.get("final_critique") or {}
            for bug in crit.get("code_changes_for_engineers") or []:
                recommendations.append(f"[{c.get('fingerprint')}] {bug}")
            for pc in crit.get("placement_critiques") or []:
                if pc.get("severity") == "high":
                    recommendations.append(
                        f"[{c.get('fingerprint')}] {pc.get('job_id')}: {pc.get('question')}"
                    )

        finished = datetime.now(timezone.utc).isoformat()
        report = QAReport(
            run_id=self.audit.run_id,
            started_at=started,
            finished_at=finished,
            overall_score=overall,
            passed=passed,
            scheduling_modes_tested=[],
            criteria=[],
            scenarios=case_results,
            db_checks=[],
            recommendations=recommendations[:25] or ["AI QA completed — review case critiques in report."],
            audit_path=str(REPORTS_DIR / f"audit_{self.audit.run_id}.jsonl"),
        )
        report.report_json_path = str(self._write_json_report(report, case_results, synthesizer))
        handoff_path = self._write_handoff(report, case_results, synthesizer)
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
            "AIQATeam",
            "done",
            f"AI QA: {passed_cases}/{len(case_results)} cases passed, score {overall}.",
        )
        return report

    def _write_json_report(
        self, report: QAReport, cases: list[dict], synthesizer: dict
    ) -> Path:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / f"qa_{report.run_id}.json"
        payload = report.to_dict()
        payload["mode"] = "ai"
        payload["ai_cases"] = cases
        payload["synthesizer"] = synthesizer
        payload["succeeded_registry_count"] = len(load_succeeded_cases())
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    def _write_handoff(
        self, report: QAReport, cases: list[dict], synthesizer: dict
    ) -> Path:
        path = REPORTS_DIR / f"cursor-handoff_{report.run_id}.md"
        lines = [
            "# ProductionAgent AI QA handoff",
            "",
            f"- **Run ID:** `{report.run_id}`",
            f"- **Mode:** AI operator review (reflective loop)",
            f"- **Score:** {report.overall_score}/100 ({'PASS' if report.passed else 'NEEDS WORK'})",
            f"- **Cases passed:** {sum(1 for c in cases if c.get('passed'))}/{len(cases)}",
            "",
            "## Executive synthesis (for Cursor engineering)",
            "",
            synthesizer.get("overall_assessment") or "_No synthesizer output._",
            "",
            "## Top bugs to fix",
            "",
        ]
        for bug in synthesizer.get("top_bugs") or []:
            lines.append(f"- {bug}")
        lines.extend(["", "## Recommended implementation tasks", ""])
        for task in synthesizer.get("recommended_cursor_tasks") or report.recommendations:
            lines.append(f"1. {task}")
        lines.extend(["", "## Per-case operator critiques", ""])
        for c in cases:
            lines.append(f"### {c.get('title')} (`{c.get('fingerprint')}`) — {'PASS' if c.get('passed') else 'FAIL'}")
            crit = c.get("final_critique") or {}
            lines.append(f"\n{crit.get('executive_summary', '')}\n")
            for pc in crit.get("placement_critiques") or []:
                lines.append(
                    f"- **{pc.get('severity', '?').upper()}** `{pc.get('job_id')}` on {pc.get('scheduled_day')} "
                    f"({pc.get('crew_id')}): {pc.get('question')}"
                )
                if pc.get("better_alternative"):
                    lines.append(f"  - Better: {pc['better_alternative']}")
            if crit.get("optimization_notes"):
                lines.append(f"\n_Optimization:_ {crit['optimization_notes']}")
            for code in crit.get("code_changes_for_engineers") or []:
                lines.append(f"- **Code fix:** {code}")
            lines.append("")
        lines.extend(["", "## Vision", "", PRODUCTION_MANAGER_VISION, ""])
        path.write_text("\n".join(lines), encoding="utf-8")
        return path
