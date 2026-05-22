"""Anthropic model ID normalization (dot/dash, friendly aliases)."""
from __future__ import annotations

from app.llm import _normalize_anthropic_model


def test_dot_form_normalizes_to_dash():
    assert _normalize_anthropic_model("claude-sonnet-4.6") == "claude-sonnet-4-6"


def test_already_dash_passes_through():
    assert _normalize_anthropic_model("claude-sonnet-4-6") == "claude-sonnet-4-6"


def test_friendly_alias_resolves():
    assert _normalize_anthropic_model("sonnet") == "claude-sonnet-4-6"
    assert _normalize_anthropic_model("opus") == "claude-opus-4-7"
    assert _normalize_anthropic_model("haiku") == "claude-haiku-4-5-20251001"


def test_sonnet_4_5_uses_dated_id():
    assert _normalize_anthropic_model("claude-sonnet-4.5") == "claude-sonnet-4-5-20250929"
    assert _normalize_anthropic_model("claude-sonnet-4-5") == "claude-sonnet-4-5-20250929"


def test_unknown_model_passes_through():
    assert _normalize_anthropic_model("claude-future-99") == "claude-future-99"


def test_empty_defaults_to_sonnet_4_6():
    assert _normalize_anthropic_model("") == "claude-sonnet-4-6"
