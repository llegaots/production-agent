"""LLM provider selection (no live API calls)."""
import os

from app.llm import LLMClient, _OPENAI_MODEL_ALIASES, safe_json


def test_prefers_anthropic_when_both_keys(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    c = LLMClient()
    assert c.provider == "anthropic"
    assert c.enabled


def test_openai_when_provider_forced(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-key")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    c = LLMClient()
    assert c.provider == "openai"


def test_openai_model_alias_fixes_gpt55(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.5")
    c = LLMClient()
    assert c.model == _OPENAI_MODEL_ALIASES["gpt-5.5"]


def test_safe_json_strips_claude_preamble():
    raw = 'Here is the JSON:\n{"score": 88, "feedback": "clear"}'
    data = safe_json(raw)
    assert data["score"] == 88
