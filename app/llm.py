"""Minimal LLM client.

If ``OPENAI_API_KEY`` is configured, the client makes a chat completion call
to an OpenAI-compatible endpoint. Otherwise the client falls back to
deterministic templated output so the system stays fully functional offline.

The fallback path is intentional: agents use the LLM to *narrate* their
reasoning and craft client-facing messages. The core scheduling logic is
deterministic and never depends on an LLM being present.
"""
from __future__ import annotations

import json
import os
from typing import Optional

import httpx
from dotenv import load_dotenv

load_dotenv()


class LLMClient:
    def __init__(self) -> None:
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    async def chat(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 600,
        temperature: float = 0.4,
    ) -> Optional[str]:
        if not self.enabled:
            return None
        url = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(url, headers=headers, json=payload)
                r.raise_for_status()
                data = r.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:  # noqa: BLE001 - LLM is optional
            return f"[LLM fallback after error: {exc}]"

    @staticmethod
    def render(template: str, **kwargs) -> str:
        try:
            return template.format(**kwargs)
        except KeyError:
            return template


llm = LLMClient()


def safe_json(text: str) -> Optional[dict]:
    """Best-effort JSON extraction from an LLM response."""
    if not text:
        return None
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        return json.loads(text)
    except Exception:
        return None
