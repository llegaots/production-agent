"""LLM client — Anthropic Claude (preferred) or OpenAI-compatible fallback.

Set ``ANTHROPIC_API_KEY`` to use Claude for agent narratives and client messages.
Optional ``OPENAI_API_KEY`` remains supported when ``LLM_PROVIDER=openai`` or no
Anthropic key is configured.

Without any key, agents use deterministic templates (scheduling stays rule-based).
"""
from __future__ import annotations

import json
import os
import re
from typing import Awaitable, Callable, Optional

TraceFn = Callable[[str, str, dict], Awaitable[None]]

import httpx

from .env_load import ENV_LOADED, ENV_PATH, load_project_env

load_project_env()

# OpenAI model aliases that commonly cause HTTP 400 (invalid / unreleased ids).
_OPENAI_MODEL_ALIASES = {
    "gpt-5.5": "gpt-4o-mini",
    "gpt-5": "gpt-4o-mini",
    "chatgpt-5": "gpt-4o-mini",
}


# Friendly aliases → real Anthropic model IDs (dashes, not dots).
# Anthropic accepts dateless IDs from the 4.6 generation onward; earlier
# generations require dated snapshots.
_ANTHROPIC_MODEL_ALIASES = {
    # 4.6 / 4.7 generation — dateless canonical IDs
    "claude-sonnet-4.6": "claude-sonnet-4-6",
    "claude-sonnet-4-6": "claude-sonnet-4-6",
    "claude-opus-4.7": "claude-opus-4-7",
    "claude-opus-4-7": "claude-opus-4-7",
    "claude-opus-4.6": "claude-opus-4-6",
    "claude-opus-4-6": "claude-opus-4-6",
    # 4.5 family — dated IDs / aliases
    "claude-sonnet-4.5": "claude-sonnet-4-5-20250929",
    "claude-sonnet-4-5": "claude-sonnet-4-5-20250929",
    "claude-opus-4.5": "claude-opus-4-5-20251101",
    "claude-opus-4-5": "claude-opus-4-5-20251101",
    "claude-haiku-4.5": "claude-haiku-4-5-20251001",
    "claude-haiku-4-5": "claude-haiku-4-5-20251001",
    # Convenience shortcuts users sometimes write
    "sonnet": "claude-sonnet-4-6",
    "sonnet-4.6": "claude-sonnet-4-6",
    "sonnet-4-6": "claude-sonnet-4-6",
    "opus": "claude-opus-4-7",
    "haiku": "claude-haiku-4-5-20251001",
}


def _normalize_anthropic_model(raw: str) -> str:
    """Map friendly names (with dots, missing prefix) to real Anthropic model IDs.

    Anthropic IDs use dashes (claude-sonnet-4-6), not dots (claude-sonnet-4.6).
    Users frequently write the latter — without normalization the API 400s.
    """
    key = raw.strip().lower()
    if not key:
        return "claude-sonnet-4-6"
    if key in _ANTHROPIC_MODEL_ALIASES:
        return _ANTHROPIC_MODEL_ALIASES[key]
    # Generic rule: replace dots with dashes inside any claude-* id.
    if key.startswith("claude-") and "." in key:
        return key.replace(".", "-")
    return raw


def _http_error_detail(exc: Exception) -> str:
    """Extract API error body from httpx HTTPStatusError when present."""
    resp = getattr(exc, "response", None)
    if resp is None:
        return str(exc)
    try:
        body = resp.json()
        if isinstance(body, dict):
            err = body.get("error")
            if isinstance(err, dict):
                return err.get("message") or json.dumps(err)
            return body.get("message") or json.dumps(body)[:400]
    except Exception:
        pass
    text = (getattr(resp, "text", None) or "")[:400]
    return text or str(exc)


class LLMClient:
    def __init__(self) -> None:
        self.anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        self.openai_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.openai_base = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.anthropic_base = os.getenv(
            "ANTHROPIC_BASE_URL", "https://api.anthropic.com"
        ).rstrip("/")
        self.anthropic_version = os.getenv("ANTHROPIC_API_VERSION", "2023-06-01")

        explicit = (os.getenv("LLM_PROVIDER") or "").strip().lower()
        if explicit in ("anthropic", "claude", "openai"):
            self.provider = "anthropic" if explicit in ("anthropic", "claude") else "openai"
        elif self.anthropic_key:
            self.provider = "anthropic"
        elif self.openai_key:
            self.provider = "openai"
        else:
            self.provider = "none"

        if self.provider == "anthropic":
            raw = (os.getenv("ANTHROPIC_MODEL") or "").strip()
            normalized = _normalize_anthropic_model(raw) if raw else "claude-sonnet-4-6"
            self.model = normalized
            self.model_raw = raw
            if not raw:
                self.model_source = "default"
            elif ENV_PATH.exists():
                self.model_source = "env_file"
            else:
                self.model_source = "environment"
        else:
            raw = (os.getenv("OPENAI_MODEL") or "gpt-4o-mini").strip()
            self.model = _OPENAI_MODEL_ALIASES.get(raw.lower(), raw)
            self.model_source = "default"

    @property
    def enabled(self) -> bool:
        if self.provider == "anthropic":
            return bool(self.anthropic_key)
        if self.provider == "openai":
            return bool(self.openai_key)
        return False

    @property
    def provider_label(self) -> str:
        if self.provider == "anthropic":
            return "Claude (Anthropic)"
        if self.provider == "openai":
            return "OpenAI"
        return "off"

    @property
    def qa_model(self) -> str:
        """Optional cheaper model for AI QA loops (avoids burning Opus credits)."""
        if self.provider != "anthropic":
            return self.model
        raw = (os.getenv("ANTHROPIC_QA_MODEL") or "").strip()
        if not raw:
            return self.model
        return _normalize_anthropic_model(raw)

    async def chat(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 600,
        temperature: float = 0.4,
        trace: Optional[TraceFn] = None,
        trace_label: str = "llm.chat",
        model_override: Optional[str] = None,
    ) -> Optional[str]:
        if not self.enabled:
            return None

        preview = (user[:200] + "…") if len(user) > 200 else user
        if trace:
            await trace(
                "call",
                f"Calling {self.provider_label} {self.model} ({trace_label})",
                {
                    "tool": trace_label,
                    "provider": self.provider,
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "input_preview": preview,
                },
            )

        effective_model = model_override or self.model
        try:
            if self.provider == "anthropic":
                text, usage = await self._chat_anthropic(
                    system, user, max_tokens=max_tokens, temperature=temperature,
                    model=effective_model,
                )
            else:
                text, usage = await self._chat_openai(
                    system, user, max_tokens=max_tokens, temperature=temperature,
                    model=effective_model,
                )
        except Exception as exc:  # noqa: BLE001 - LLM is optional
            detail = _http_error_detail(exc)
            if trace:
                await trace(
                    "error",
                    f"LLM error ({self.provider_label}): {detail}",
                    {"tool": trace_label, "provider": self.provider},
                )
            return f"[LLM fallback after error: {detail}]"

        if trace:
            out_preview = (text[:160] + "…") if len(text) > 160 else text
            await trace(
                "result",
                f"{self.model} returned {len(text)} chars",
                {"tool": trace_label, "output_preview": out_preview, **usage},
            )
        return text

    def _anthropic_payload(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int,
        temperature: float,
        model: Optional[str] = None,
    ) -> dict:
        model_id = model or self.model
        payload: dict = {
            "model": model_id,
            "max_tokens": max_tokens,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        # Newer Claude models (opus-4, sonnet-4-6, etc.) reject temperature.
        if not re.search(r"opus-4|claude-4-|sonnet-4-6|opus-4-6|opus-4-7", model_id, re.I):
            payload["temperature"] = temperature
        return payload

    async def _chat_anthropic(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int,
        temperature: float,
        model: Optional[str] = None,
    ) -> tuple[str, dict]:
        url = f"{self.anthropic_base}/v1/messages"
        headers = {
            "x-api-key": self.anthropic_key,
            "anthropic-version": self.anthropic_version,
            "content-type": "application/json",
        }
        payload = self._anthropic_payload(
            system, user, max_tokens=max_tokens, temperature=temperature, model=model
        )
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code == 400 and "temperature" in (r.text or "").lower():
                payload = self._anthropic_payload(
                    system, user, max_tokens=max_tokens, temperature=temperature, model=model
                )
                payload.pop("temperature", None)
                r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        blocks = data.get("content") or []
        text_parts = [b.get("text", "") for b in blocks if b.get("type") == "text"]
        text = "".join(text_parts).strip()
        usage_in = (data.get("usage") or {}).get("input_tokens")
        usage_out = (data.get("usage") or {}).get("output_tokens")
        return text, {
            "prompt_tokens": usage_in,
            "completion_tokens": usage_out,
        }

    async def _chat_openai(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int,
        temperature: float,
        model: Optional[str] = None,
    ) -> tuple[str, dict]:
        url = f"{self.openai_base}/chat/completions"
        payload = {
            "model": model or self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        headers = {
            "Authorization": f"Bearer {self.openai_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(url, headers=headers, json=payload)
            r.raise_for_status()
            data = r.json()
        text = data["choices"][0]["message"]["content"].strip()
        usage = data.get("usage") or {}
        return text, {
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }

    @staticmethod
    def render(template: str, **kwargs) -> str:
        try:
            return template.format(**kwargs)
        except KeyError:
            return template


llm = LLMClient()


def safe_json(text: str) -> Optional[dict]:
    """Best-effort JSON extraction from an LLM response.

    Handles:
    - ```json ... ``` fenced code blocks (with or without trailing fence)
    - Preamble/postscript text around the JSON object
    - Truncated responses (close braces missing) by balancing braces/brackets
    """
    if not text:
        return None
    text = text.strip()

    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()
    else:
        open_fence = re.match(r"```(?:json)?\s*", text, re.IGNORECASE)
        if open_fence:
            text = text[open_fence.end():]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

    if "{" not in text:
        return None
    text = text[text.index("{"):]

    last_close = text.rfind("}")
    candidate = text[: last_close + 1] if last_close != -1 else text
    try:
        return json.loads(candidate)
    except Exception:
        pass

    repaired = _repair_truncated_json(text)
    if repaired is not None:
        try:
            return json.loads(repaired)
        except Exception:
            return None
    return None


def _repair_truncated_json(text: str) -> Optional[str]:
    """Close any unclosed strings, arrays, and objects in a truncated JSON blob."""
    in_string = False
    escape = False
    stack: list[str] = []
    for ch in text:
        if escape:
            escape = False
            continue
        if ch == "\\" and in_string:
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch in "{[":
            stack.append(ch)
        elif ch in "}]":
            if stack and ((ch == "}" and stack[-1] == "{") or (ch == "]" and stack[-1] == "[")):
                stack.pop()

    if not stack and not in_string:
        return None

    repaired = text.rstrip()
    if repaired.endswith(","):
        repaired = repaired[:-1]
    if in_string:
        repaired += '"'
    while stack:
        opener = stack.pop()
        repaired += "}" if opener == "{" else "]"
    return repaired
