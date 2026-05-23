"""Phase 5 critic agent tests (deterministic + mocked LLM, no DB)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.critic.deterministic import compute_deterministic_metrics  # noqa: E402
from app.critic.llm_critic import run_llm_critic  # noqa: E402
from app.critic.review import review_schedule  # noqa: E402
from app.critic.schemas import CriticIssue, CriticVerdict, DeterministicMetrics, IssueSeverity  # noqa: E402
from app.critic.scenarios import (  # noqa: E402
    bad_drive_time_blowout,
    bad_equipment_ground_floor_ladder,
    bad_geographic_zigzag,
    bad_morning_preference_afternoon,
    bad_review_input_preference_violations,
    bad_week_fill_friday_stack,
    good_review_input,
)

pytestmark = pytest.mark.usefixtures("no_db")


@pytest.fixture
def no_db():
    """Ensure critic tests never hit Supabase."""
    yield


def _issues_of_type(metrics: DeterministicMetrics, issue_type: str) -> list[CriticIssue]:
    return [i for i in metrics.structured_issues if i.type == issue_type]


def _max_severity(issues: list[CriticIssue]) -> IssueSeverity | None:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    if not issues:
        return None
    return max((i.severity for i in issues), key=lambda s: order[s])


def assert_issue(
    metrics: DeterministicMetrics,
    issue_type: str,
    *,
    min_severity: IssueSeverity = "medium",
) -> CriticIssue:
    matches = _issues_of_type(metrics, issue_type)
    assert matches, f"Expected issue type {issue_type!r}, got {[i.type for i in metrics.structured_issues]}"
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    best = max(matches, key=lambda i: order[i.severity])
    assert order[best.severity] >= order[min_severity], (
        f"{issue_type} severity {best.severity} < {min_severity}"
    )
    return best


# --- Deterministic layer (per rule) ---


class TestDeterministicMetrics:
    def test_happy_path_no_structured_issues(self):
        metrics = compute_deterministic_metrics(good_review_input())
        assert metrics.preference_violation_count == 0
        assert metrics.week_fill_score >= 0.85
        assert metrics.equipment_fit_score >= 0.95
        assert not metrics.structured_issues
        assert not metrics.deterministic_issues

    def test_geographic_zigzag(self):
        metrics = compute_deterministic_metrics(bad_geographic_zigzag())
        issue = assert_issue(metrics, "geographic_clustering", min_severity="high")
        assert issue.crew_id == "solo"
        assert metrics.crew_days[0].geographic_spread_km > 12

    def test_week_fill_order_friday_stack(self):
        metrics = compute_deterministic_metrics(bad_week_fill_friday_stack())
        issue = assert_issue(metrics, "week_fill_order", min_severity="high")
        assert "Friday" in issue.message or "Mon/Tue" in issue.message

    def test_preference_violation_morning_afternoon(self):
        metrics = compute_deterministic_metrics(bad_morning_preference_afternoon())
        issue = assert_issue(metrics, "preference_violation", min_severity="high")
        assert issue.job_id == "morning-client"
        assert "morning" in issue.message.lower() or "afternoon" in issue.message.lower()

    def test_preference_violation_wrong_crew(self):
        metrics = compute_deterministic_metrics(bad_review_input_preference_violations())
        assert_issue(metrics, "preference_violation", min_severity="medium")
        assert metrics.preference_violation_count >= 1

    def test_equipment_necessity_ground_floor_ladder(self):
        metrics = compute_deterministic_metrics(bad_equipment_ground_floor_ladder())
        issue = assert_issue(metrics, "equipment_necessity", min_severity="high")
        assert issue.job_id == "ground-1"
        assert "ground" in issue.message.lower() or "ladder" in issue.message.lower()

    def test_drive_time_blowout(self):
        metrics = compute_deterministic_metrics(bad_drive_time_blowout())
        issue = assert_issue(metrics, "drive_time", min_severity="high")
        assert issue.crew_id == "solo"
        assert "240" in issue.message or "drive" in issue.message.lower()


# --- Rule critic (deterministic verdict path) ---


class TestRuleCritic:
    def test_approves_good_schedule(self):
        out = review_schedule(good_review_input())
        assert out.verdict.approved is True
        assert not out.verdict.issues
        assert not out.verdict.structured_issues
        assert out.reviewer == "rule_critic"

    def test_rejects_geographic_with_feedback(self):
        out = review_schedule(bad_geographic_zigzag())
        assert out.verdict.approved is False
        assert_issue(out.metrics, "geographic_clustering")
        assert out.verdict.feedback_prompt

    @pytest.mark.parametrize(
        ("factory", "issue_type"),
        [
            (bad_week_fill_friday_stack, "week_fill_order"),
            (bad_morning_preference_afternoon, "preference_violation"),
            (bad_equipment_ground_floor_ladder, "equipment_necessity"),
            (bad_drive_time_blowout, "drive_time"),
        ],
    )
    def test_rejects_bad_schedules(self, factory, issue_type: str):
        out = review_schedule(factory())
        assert out.verdict.approved is False
        assert_issue(out.metrics, issue_type)


# --- LLM layer (mocked Anthropic) ---


def _mock_anthropic_response(payload: dict[str, Any]) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {
        "content": [{"type": "text", "text": json.dumps(payload)}],
    }
    return mock_resp


class TestLlmCriticMocked:
    def test_llm_approve_when_metrics_clean(self):
        inp = good_review_input()
        inp = inp.model_copy(update={"use_llm": True})
        metrics = compute_deterministic_metrics(inp)

        with patch("app.critic.llm_critic.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = _mock_anthropic_response(
                {
                    "approved": True,
                    "issues": [],
                    "feedback_prompt": "Looks good.",
                }
            )

            verdict = run_llm_critic(metrics, inp, [], use_llm=True)

        assert verdict.approved is True
        assert not verdict.issues
        mock_client.post.assert_called_once()

    def test_llm_reject_merged_with_deterministic_flags(self):
        inp = bad_geographic_zigzag()
        inp = inp.model_copy(update={"use_llm": True})
        metrics = compute_deterministic_metrics(inp)

        with patch("app.critic.llm_critic.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_client.post.return_value = _mock_anthropic_response(
                {
                    "approved": True,
                    "issues": [],
                    "feedback_prompt": "LLM wrongly approved",
                }
            )

            verdict = run_llm_critic(metrics, inp, [], use_llm=True)

        assert verdict.approved is False
        assert_issue(metrics, "geographic_clustering")
        assert any("geographic" in m.lower() for m in verdict.issues)

    def test_llm_parse_failure_falls_back_to_rules(self):
        inp = bad_drive_time_blowout()
        inp = inp.model_copy(update={"use_llm": True})
        metrics = compute_deterministic_metrics(inp)

        with patch("app.critic.llm_critic.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__.return_value = mock_client
            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"content": [{"type": "text", "text": "not json"}]}
            mock_client.post.return_value = mock_resp

            verdict = run_llm_critic(metrics, inp, [], use_llm=True)

        assert verdict.approved is False
        assert_issue(metrics, "drive_time")

    def test_review_schedule_uses_mocked_llm(self):
        inp = bad_morning_preference_afternoon()
        inp = inp.model_copy(update={"use_llm": True, "persist": False})

        with patch("app.critic.llm_critic._call_anthropic") as mock_llm:
            mock_llm.return_value = CriticVerdict(
                approved=False,
                issues=["Morning preference ignored"],
                feedback_prompt="Reschedule to AM.",
            )
            out = review_schedule(inp)

        assert out.reviewer == "llm_critic"
        assert out.verdict.approved is False
        mock_llm.assert_called_once()
