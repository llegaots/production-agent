"""Robust safe_json: fenced blocks, truncated bodies, preamble text."""
from __future__ import annotations

from app.llm import safe_json


def test_plain_json():
    assert safe_json('{"a": 1}') == {"a": 1}


def test_fenced_json_block():
    text = '```json\n{"a": 1, "b": [1, 2]}\n```'
    assert safe_json(text) == {"a": 1, "b": [1, 2]}


def test_fenced_no_language():
    text = '```\n{"a": 1}\n```'
    assert safe_json(text) == {"a": 1}


def test_preamble_text_before_json():
    text = 'Here is the JSON you asked for:\n{"a": 1, "b": "ok"}'
    assert safe_json(text) == {"a": 1, "b": "ok"}


def test_truncated_string_recovered():
    """Response cut off mid-string — repair should close the string and braces."""
    text = '```json\n{"fingerprint": "high_rise_skill_gap", "title": "Tuesday"'
    out = safe_json(text)
    assert out is not None
    assert out["fingerprint"] == "high_rise_skill_gap"


def test_truncated_nested_array_recovered():
    text = '```json\n{"steps": [{"action": "plan"}, {"action": "reor'
    out = safe_json(text)
    assert out is not None
    assert isinstance(out.get("steps"), list)


def test_empty_returns_none():
    assert safe_json("") is None
    assert safe_json(None) is None
