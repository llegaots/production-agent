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
from ..seed import SEED_WEEK_START
from ..audit_log import REPORTS_DIR
from ..qa_team import QAReport
from ..vision import ACCEPTANCE_CRITERIA, PRODUCTION_MANAGER_VISION
from ..cursor_handoff import attach_handoff_to_report_json, trigger_automatic_handoff
from .executor import apply_owner_retry, execute_case
from .llm_agents import critique_schedule, design_test_case, synthesize_run
from .probe import probe_llm_for_qa
from .registry import fingerprints_for_prompt, load_succeeded_cases, save_succeeded_case, themes_covered
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

        llm_block = await probe_llm_for_qa()
        if llm_block:
            return await self._finish_aborted(
                started,
                llm_block,
                auto_cursor_handoff=auto_cursor_handoff,
            )

        succeeded_history = fingerprints_for_prompt()
        case_results: list[dict[str, Any]] = []
        failed_fingerprints: list[dict] = []
        week_start = SEED_WEEK_START
        llm_errors: list[str] = []

        for case_idx in range(_max_cases()):
            case = await design_test_case(
                succeeded_fingerprints=succeeded_history + [c["fingerprint"] for c in case_results if c.get("passed")],
                failed_this_run=failed_fingerprints,
                case_index=case_idx,
                covered_themes=themes_covered(),
            )
            if case and case.get("_error"):
                llm_errors.append(str(case["_error"]))
                self.audit.log("CaseDesigner", "error", case["_error"], level="warning")
                break
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
                    exec_result = await execute_case(
                        case, week_start=week_start, run_id=self.audit.run_id
                    )
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
                        theme=case.get("theme", ""),
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
        if llm_errors:
            recommendations.insert(
                0,
                f"LLM blocked AI QA: {llm_errors[0]} — fix billing/model, or use Legacy QA (no LLM).",
            )
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

        if not recommendations:
            if llm_errors:
                recommendations = [llm_errors[0]]
            elif not case_results:
                recommendations = [
                    "AI QA did not run any cases (finished too fast). "
                    "Check Anthropic credits or use Legacy QA."
                ]
            else:
                recommendations = ["Review case critiques in this report."]
        else:
            recommendations = recommendations[:25]

        finished_dt = datetime.now(timezone.utc)
        started_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
        duration = round((finished_dt - started_dt).total_seconds(), 2)
        report = QAReport(
            run_id=self.audit.run_id,
            started_at=started,
            finished_at=finished_dt.isoformat(),
            overall_score=overall,
            passed=passed,
            scheduling_modes_tested=[],
            criteria=[],
            scenarios=case_results,
            db_checks=[],
            recommendations=recommendations,
            audit_path=str(REPORTS_DIR / f"audit_{self.audit.run_id}.jsonl"),
            mode="ai",
            error_message=llm_errors[0] if llm_errors else "",
            duration_seconds=duration,
            aborted=bool(llm_errors),
        )
        report.report_json_path = str(
            self._write_json_report(report, case_results, synthesizer, llm_errors=llm_errors)
        )
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

    async def _finish_aborted(
        self,
        started: str,
        error: str,
        *,
        auto_cursor_handoff: Optional[bool] = None,
    ) -> QAReport:
        """Return immediately when LLM is unusable (avoids fake 1-second 'complete' runs)."""
        finished = datetime.now(timezone.utc).isoformat()
        self.audit.log("AIQATeam", "aborted", error, level="warning")
        report = QAReport(
            run_id=self.audit.run_id,
            started_at=started,
            finished_at=finished,
            overall_score=0,
            passed=False,
            scheduling_modes_tested=[],
            recommendations=[
                error,
                "Click **Legacy QA** to test scheduling without Claude (15–30 seconds).",
                "After fixing billing, restart ./run.sh and run **Run AI QA suite** again (2–5 min).",
            ],
            audit_path=str(REPORTS_DIR / f"audit_{self.audit.run_id}.jsonl"),
            mode="ai",
            error_message=error,
            duration_seconds=0.5,
            aborted=True,
        )
        report.report_json_path = str(
            self._write_json_report(report, [], {}, llm_errors=[error])
        )
        handoff_path = self._write_handoff(report, [], {})
        report.cursor_handoff_path = str(handoff_path)
        launch = await trigger_automatic_handoff(
            run_id=report.run_id,
            handoff_path=handoff_path,
            passed=False,
            overall_score=0,
            audit=self.audit,
            auto_handoff=auto_cursor_handoff,
        )
        report.cursor_handoff = launch.to_dict()
        attach_handoff_to_report_json(Path(report.report_json_path), launch)
        return report

    def _write_json_report(
        self,
        report: QAReport,
        cases: list[dict],
        synthesizer: dict,
        *,
        llm_errors: Optional[list[str]] = None,
    ) -> Path:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        path = REPORTS_DIR / f"qa_{report.run_id}.json"
        payload = report.to_dict()
        payload["mode"] = "ai"
        payload["ai_cases"] = cases
        payload["synthesizer"] = synthesizer
        payload["succeeded_registry_count"] = len(load_succeeded_cases())
        if llm_errors:
            payload["error_message"] = llm_errors[0]
            payload["llm_errors"] = llm_errors
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return path

    def _has_actionable_findings(self, cases: list[dict], synthesizer: dict) -> bool:
        """Return True only if there are concrete bugs/tasks the Cursor agent can act on."""
        if not cases:
            return False
        failed = [c for c in cases if not c.get("passed")]
        if not failed:
            return False
        has_code_changes = any(
            c.get("final_critique", {}).get("code_changes_for_engineers")
            for c in failed
        )
        has_bugs = bool(synthesizer.get("top_bugs") or synthesizer.get("recommended_cursor_tasks"))
        return has_code_changes or has_bugs

    def _write_handoff(
        self, report: QAReport, cases: list[dict], synthesizer: dict
    ) -> Path:
        path = REPORTS_DIR / f"cursor-handoff_{report.run_id}.md"
        passed_cases = sum(1 for c in cases if c.get("passed"))
        failed_cases = [c for c in cases if not c.get("passed")]
        actionable = self._has_actionable_findings(cases, synthesizer)

        lines = [
            "# ProductionAgent AI QA handoff",
            "",
            f"- **Run ID:** `{report.run_id}`",
            f"- **Score:** {report.overall_score}/100 ({'PASS' if report.passed else 'NEEDS WORK'})",
            f"- **Cases:** {passed_cases} passed, {len(failed_cases)} failed",
            f"- **Actionable findings:** {'YES' if actionable else 'NO — see note below'}",
            "",
        ]

        if not actionable:
            lines += [
                "## ⚠️ No actionable findings — DO NOT implement new features",
                "",
                "The AI QA run did not produce concrete code-change requests.",
                "This is usually because:",
                "- The LLM ran out of credits before completing any cases, OR",
                "- All tested cases passed (nothing to fix), OR",
                "- QA was aborted by the probe check.",
                "",
                "**Do NOT use the Vision section below as a task list.**",
                "**Only implement changes when there are specific `code_changes_for_engineers` entries below.**",
                "",
                "If there is nothing to fix: reply with a short summary confirming the schedule",
                "is operationally sound and run `python3 -m pytest tests/ -q` to confirm.",
                "",
            ]
            if report.error_message:
                lines += [
                    f"**Error that stopped QA:** {report.error_message}",
                    "",
                    "Fix the error first (usually: top up Anthropic credits, then restart ./run.sh).",
                    "",
                ]
        else:
            # ── ACTIONABLE: put concrete tasks up front, unambiguous ─────────
            all_code_changes: list[str] = []
            for c in failed_cases:
                crit = c.get("final_critique") or {}
                for change in crit.get("code_changes_for_engineers") or []:
                    all_code_changes.append(f"[{c.get('fingerprint')}] {change}")

            lines += [
                "## YOUR TASK — implement only these specific fixes",
                "",
                "> Fix the root causes identified by the operator critique below.",
                "> Do NOT add new features. Preserve existing conventions and tests.",
                "> Run `python3 -m pytest tests/ -q` before finishing.",
                "",
                "### Concrete code changes requested by the operator critique",
                "",
            ]
            if all_code_changes:
                for change in all_code_changes:
                    lines.append(f"- {change}")
            else:
                lines.append("_(Operator critiques contain placement issues but no explicit code changes — see per-case details below.)_")

            lines += [
                "",
                "### Synthesizer recommendations",
                "",
            ]
            for task in synthesizer.get("recommended_cursor_tasks") or []:
                lines.append(f"- {task}")
            for bug in synthesizer.get("top_bugs") or []:
                lines.append(f"- Bug: {bug}")

            lines += ["", "---", "", "## Per-case operator critiques (evidence)", ""]
            for c in cases:
                verdict = "✅ PASS" if c.get("passed") else "❌ FAIL"
                lines.append(f"### {verdict} — {c.get('title')} (`{c.get('fingerprint')}`)")
                crit = c.get("final_critique") or {}
                if crit.get("executive_summary"):
                    lines.append(f"\n**Operator verdict:** {crit['executive_summary']}\n")
                for pc in crit.get("placement_critiques") or []:
                    sev = pc.get("severity", "?").upper()
                    lines.append(
                        f"- **{sev}** `{pc.get('job_id')}` on {pc.get('scheduled_day')} "
                        f"({pc.get('crew_id')}): _{pc.get('question')}_"
                    )
                    if pc.get("better_alternative"):
                        lines.append(f"  - **Better:** {pc['better_alternative']}")
                if crit.get("optimization_notes"):
                    lines.append(f"\n_Optimization note:_ {crit['optimization_notes']}")
                for change in crit.get("code_changes_for_engineers") or []:
                    lines.append(f"- **CODE CHANGE NEEDED:** {change}")
                if c.get("iterations"):
                    last_iter = c["iterations"][-1]
                    retry = (last_iter.get("critique") or {}).get("owner_retry")
                    if retry:
                        lines.append(
                            f"\n_Operator would retry:_ {retry.get('action')} — "
                            f"{retry.get('instruction_or_mode')}"
                        )
                lines.append("")

        # Vision goes at the very end, clearly labelled as CONTEXT ONLY
        lines += [
            "---",
            "",
            "## Context only — app vision (do not use as a task list)",
            "",
            "> This section describes what the app should do in production.",
            "> It is provided as context, NOT as a list of features to implement.",
            "> Your task is defined entirely in the sections above.",
            "",
            PRODUCTION_MANAGER_VISION.strip(),
            "",
        ]

        path.write_text("\n".join(lines), encoding="utf-8")
        return path
