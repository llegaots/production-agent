"""Phase 5 critic agent tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.critic.deterministic import compute_deterministic_metrics
from app.critic.review import review_schedule
from app.critic.scenarios import (
    bad_review_input_equipment_mismatch,
    bad_review_input_geographic_spray,
    bad_review_input_preference_violations,
    good_review_input,
)


def test_deterministic_good_schedule_has_few_issues():
    inp = good_review_input()
    metrics = compute_deterministic_metrics(inp)
    assert metrics.preference_violation_count == 0
    assert metrics.week_fill_score >= 0.75
    assert metrics.equipment_fit_score >= 0.95
    assert not metrics.deterministic_issues


def test_bad_preference_violations_flagged():
    inp = bad_review_input_preference_violations()
    metrics = compute_deterministic_metrics(inp)
    assert metrics.preference_violation_count >= 1
    assert any("preferred crew" in i for i in metrics.deterministic_issues)


def test_bad_geographic_spray_flagged():
    inp = bad_review_input_geographic_spray()
    metrics = compute_deterministic_metrics(inp)
    assert any("geographic spread" in i for i in metrics.deterministic_issues)
    assert metrics.crew_days[0].geographic_spread_km > 12


def test_bad_equipment_mismatch_flagged():
    inp = bad_review_input_equipment_mismatch()
    metrics = compute_deterministic_metrics(inp)
    assert metrics.equipment_fit_score < 0.95 or any(
        "Unassigned" in i for i in metrics.deterministic_issues
    )


def test_rule_critic_rejects_bad_preference_schedule():
    out = review_schedule(bad_review_input_preference_violations())
    assert out.verdict.approved is False
    assert out.verdict.issues
    assert out.verdict.feedback_prompt
    assert any(
        kw in out.verdict.feedback_prompt.lower()
        for kw in ("reassign", "preferred", "revise", "crew")
    )


def test_rule_critic_approves_good_schedule():
    out = review_schedule(good_review_input())
    assert out.verdict.approved is True
    assert not out.verdict.issues


def test_rule_critic_rejects_geographic_spray_with_actionable_feedback():
    out = review_schedule(bad_review_input_geographic_spray())
    assert out.verdict.approved is False
    assert len(out.verdict.issues) >= 1
    assert "cluster" in out.verdict.feedback_prompt.lower() or "travel" in out.verdict.feedback_prompt.lower()


@pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"),
    reason="Live LLM critic test requires ANTHROPIC_API_KEY",
)
def test_llm_critic_rejects_bad_schedule_live():
    inp = bad_review_input_preference_violations()
    inp = inp.model_copy(update={"use_llm": True})
    out = review_schedule(inp)
    assert out.verdict.approved is False
    assert len(out.verdict.issues) >= 1


@pytest.mark.skipif(
    not os.getenv("SUPABASE_URL") and not (ROOT / ".env").is_file(),
    reason="Supabase required",
)
def test_persist_critic_review():
    from datetime import date

    from app.tools.optimizer_tool import run_optimizer
    from app.tools.schemas import RunOptimizerInput
    from app.tools._db import tools_db

    db = tools_db()
    crews = [r["id"] for r in db.table("crews").select("id").limit(2).execute().data]
    jobs = [
        r["id"]
        for r in db.table("jobs").select("id").eq("status", "pending").limit(2).execute().data
    ]
    opt = run_optimizer(
        RunOptimizerInput(
            target_date=date.today(),
            job_ids=jobs,
            crew_ids=crews,
            time_limit_seconds=3,
        )
    )
    from app.tools.schedule_attempts import save_schedule_attempt
    from app.tools.schemas import SaveScheduleAttemptInput

    saved = save_schedule_attempt(
        SaveScheduleAttemptInput(
            target_date=date.today(),
            job_ids=jobs,
            crew_ids=crews,
            optimizer_input=opt.optimizer_input,
            result=opt.result,
        )
    )
    from app.critic.schemas import ReviewScheduleInput

    out = review_schedule(
        ReviewScheduleInput(
            target_date=date.today(),
            optimizer_input=opt.optimizer_input,
            optimizer_result=opt.result,
            schedule_attempt_id=saved.attempt_id,
            persist=True,
            use_llm=False,
        )
    )
    assert out.critic_feedback_id is not None
