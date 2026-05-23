"""
CLI: python -m evals.run --scenario all --iterations 5

Runs orchestrator scenarios repeatedly and writes a markdown report plus eval_runs rows.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

SCENARIOS_DIR = ROOT / "tests" / "scenarios"
REPORTS_DIR = ROOT / "evals" / "reports"

DEFAULT_SCENARIOS = [
    "simple_week",
    "tight_constraints",
    "preference_heavy",
    "equipment_scarce",
    "infeasible",
]


def list_scenarios() -> list[str]:
    return sorted(p.stem for p in SCENARIOS_DIR.glob("*.yaml"))


def resolve_scenarios(name: str) -> list[str]:
    if name == "all":
        return list_scenarios() or DEFAULT_SCENARIOS
    if (SCENARIOS_DIR / f"{name}.yaml").is_file():
        return [name]
    raise SystemExit(f"Unknown scenario: {name}. Available: all, {', '.join(list_scenarios())}")


def run_trial(scenario, *, use_agent: bool):
    from app.orchestrator.runner import run_scheduling_mission
    from app.orchestrator.schemas import ScheduleWeekInput

    return run_scheduling_mission(
        ScheduleWeekInput(
            user_request=scenario.user_request,
            week_start=scenario.week_start,
            week_end=scenario.week_end,
            max_iterations=scenario.max_iterations,
            use_llm_critic=scenario.use_llm_critic,
            use_agent=use_agent,
            job_id_prefix=scenario.id_prefix,
            job_load_limit=len(scenario.all_job_ids),
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Orchestrator eval harness (quality tracking)")
    parser.add_argument(
        "--scenario",
        default="all",
        help="Scenario name or 'all' (default: all)",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Trials per scenario (default: 5)",
    )
    parser.add_argument(
        "--use-agent",
        action="store_true",
        default=None,
        help="Force Anthropic agent loop",
    )
    parser.add_argument(
        "--no-agent",
        action="store_true",
        help="Force programmatic orchestrator (no Anthropic)",
    )
    parser.add_argument(
        "--reports-dir",
        type=Path,
        default=REPORTS_DIR,
        help=f"Markdown output directory (default: {REPORTS_DIR})",
    )
    args = parser.parse_args(argv)

    if args.iterations < 1:
        parser.error("--iterations must be >= 1")
    if args.use_agent and args.no_agent:
        parser.error("Use only one of --use-agent / --no-agent")

    use_agent_override: bool | None = None
    if args.use_agent:
        use_agent_override = True
    elif args.no_agent:
        use_agent_override = False

    scenario_names = resolve_scenarios(args.scenario)

    from app.tools._db import tools_db
    from evals.metrics import collect_trial_metrics
    from evals.persist import insert_eval_run
    from evals.report import render_report, report_path, report_timestamp
    from evals.stats import aggregate_scenario
    from tests.e2e.scenario_loader import cleanup_scenario_prefix, load_scenario, seed_scenario_to_supabase

    db = tools_db()
    eval_batch_id = uuid.uuid4()
    ts = report_timestamp()
    out_path = report_path(args.reports_dir, ts)
    run_prefix = f"eval-{ts.lower()}-{eval_batch_id.hex[:8]}"

    all_trials: dict[str, list] = {}
    aggregates = []
    agent_mode_label = (
        "programmatic (--no-agent)"
        if use_agent_override is False
        else "Anthropic (--use-agent)"
        if use_agent_override is True
        else "per-scenario YAML"
    )

    for scenario_name in scenario_names:
        yaml_path = SCENARIOS_DIR / f"{scenario_name}.yaml"
        raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
        iteration_cap = int(raw.get("max_iterations", 4))
        trial_metrics_list = []
        print(f"=== {scenario_name} ({args.iterations} trials) ===", flush=True)

        for trial in range(1, args.iterations + 1):
            prefix = f"{run_prefix}-{scenario_name}-t{trial}-"
            scenario = load_scenario(yaml_path, run_prefix=prefix)
            use_agent = (
                use_agent_override
                if use_agent_override is not None
                else (scenario.use_agent or scenario.requires_agent)
            )

            seed_scenario_to_supabase(scenario)
            try:
                result = run_trial(scenario, use_agent=use_agent)
                metrics = collect_trial_metrics(
                    result,
                    iteration_cap=iteration_cap,
                )
                insert_eval_run(
                    db,
                    eval_batch_id=eval_batch_id,
                    report_path=str(out_path.relative_to(ROOT)),
                    scenario_name=scenario_name,
                    trial_number=trial,
                    use_agent=use_agent,
                    metrics=metrics,
                )
                trial_metrics_list.append(metrics)
                print(
                    f"  trial {trial}: status={metrics.status} approved={metrics.approved} "
                    f"iter={metrics.iteration_count} drive={metrics.total_drive_minutes}min "
                    f"pref_viol={metrics.preference_violations}",
                    flush=True,
                )
            finally:
                cleanup_scenario_prefix(scenario.id_prefix)

        all_trials[scenario_name] = trial_metrics_list
        aggregates.append(
            aggregate_scenario(
                scenario_name,
                trial_metrics_list,
                iteration_cap=iteration_cap,
            )
        )

    body = render_report(
        eval_batch_id=eval_batch_id,
        timestamp=ts,
        aggregates=aggregates,
        trial_rows=all_trials,
        iterations_per_scenario=args.iterations,
        use_agent=use_agent_override is True,
        agent_mode_label=agent_mode_label,
    )

    out_path.write_text(body, encoding="utf-8")
    print(f"\nReport: {out_path}", flush=True)
    print(f"Batch ID: {eval_batch_id}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
