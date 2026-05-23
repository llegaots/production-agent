"""Deterministic workload balance metrics for QA critics."""
from app.qa_ai.schedule_snapshot import (
    compute_workload_balance,
    deterministic_workload_verdict,
    enrich_schedule_context,
)


def _ctx_from_schedule():
    """Schedule similar to the user's 'well balanced' QA board."""
    return {
        "crew_days": [
            {"crew_id": "crew_alpha", "day": "2026-07-07", "total_work_minutes": 90},
            {"crew_id": "crew_delta", "day": "2026-07-07", "total_work_minutes": 180},
            {"crew_id": "crew_alpha", "day": "2026-07-08", "total_work_minutes": 180},
            {"crew_id": "crew_delta", "day": "2026-07-08", "total_work_minutes": 200},
            {"crew_id": "crew_alpha", "day": "2026-07-09", "total_work_minutes": 270},
            {"crew_id": "crew_delta", "day": "2026-07-09", "total_work_minutes": 360},
            {"crew_id": "crew_bravo", "day": "2026-07-09", "total_work_minutes": 300},
        ],
    }


def test_compute_workload_balance_spread():
    metrics = compute_workload_balance(_ctx_from_schedule())
    assert metrics["max_alpha_delta_spread_minutes"] == 90
    assert metrics["balanced_within_150min"] is True
    assert not metrics["alpha_idle_while_delta_works"]


def test_enrich_schedule_context_adds_metrics():
    ctx = enrich_schedule_context(_ctx_from_schedule())
    assert "workload_balance" in ctx
    assert ctx["workload_balance"]["balanced_within_150min"] is True


def test_deterministic_override_when_llm_contradicts_metrics():
    case = {"theme": "balanced_workload", "persona_story": "Alpha has 11 hours Tuesday"}
    ctx = enrich_schedule_context(_ctx_from_schedule())
    bad_critique = {
        "verdict": "fail",
        "viability_score": 0,
        "executive_summary": "Alpha overloaded Tuesday, Delta idle until Thursday.",
    }
    override = deterministic_workload_verdict(case, ctx, bad_critique)
    assert override is not None
    assert override["verdict"] == "pass"
    assert override["viability_score"] >= 78


def test_no_override_when_spread_too_wide():
    ctx = {
        "crew_days": [
            {"crew_id": "crew_alpha", "day": "2026-07-07", "total_work_minutes": 30},
            {"crew_id": "crew_delta", "day": "2026-07-07", "total_work_minutes": 420},
        ],
    }
    case = {"theme": "balanced_workload"}
    bad = {"verdict": "fail", "viability_score": 10, "executive_summary": "Unbalanced"}
    assert deterministic_workload_verdict(case, enrich_schedule_context(ctx), bad) is None
