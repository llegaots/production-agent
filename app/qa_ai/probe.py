"""Quick LLM health check before a long AI QA run."""
from __future__ import annotations

from ..llm import llm
from .llm_agents import _chat_json, _llm_failure_message


async def probe_llm_for_qa() -> str | None:
    """
    Returns None if the LLM can respond with JSON; otherwise an error message
    (billing, auth, network, etc.).
    """
    if not llm.enabled:
        return (
            "No LLM API key loaded. Add ANTHROPIC_API_KEY or OPENAI_API_KEY to .env "
            "and restart ./run.sh — or use Legacy QA."
        )
    data, err = await _chat_json(
        'Reply with only JSON: {"probe":"ok"}',
        "health check",
        max_tokens=80,
    )
    if err:
        return err
    if not data:
        return "LLM health check failed (empty or non-JSON response)."
    return None
