"""Cursor Cloud Agents API client — launch coding agents from QA handoff reports."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import httpx

ROOT = Path(__file__).resolve().parent.parent


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name, "").strip().lower()
    if not v:
        return default
    return v in ("1", "true", "yes", "on")


def _normalize_repo_url(url: str) -> str:
    url = url.strip()
    if "@" in url:
        url = "https://" + url.split("@", 1)[1]
    if url.endswith(".git"):
        url = url[:-4]
    return url.rstrip("/")


def detect_git_repository() -> Optional[str]:
    """Best-effort GitHub URL from origin remote (no credentials)."""
    configured = os.getenv("CURSOR_REPOSITORY", "").strip()
    if configured:
        return _normalize_repo_url(configured)
    try:
        out = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return _normalize_repo_url(out.stdout.strip())
    except Exception:
        pass
    return None


def detect_git_ref() -> str:
    ref = os.getenv("CURSOR_REF", "").strip()
    if ref:
        return ref
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if out.returncode == 0 and out.stdout.strip():
            return out.stdout.strip()
    except Exception:
        pass
    return "main"


@dataclass
class CursorLaunchResult:
    launched: bool
    agent_id: Optional[str] = None
    agent_url: Optional[str] = None
    status: Optional[str] = None
    branch_name: Optional[str] = None
    pr_url: Optional[str] = None
    error: Optional[str] = None
    skipped_reason: Optional[str] = None
    api_version: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "launched": self.launched,
            "agent_id": self.agent_id,
            "agent_url": self.agent_url,
            "status": self.status,
            "branch_name": self.branch_name,
            "pr_url": self.pr_url,
            "error": self.error,
            "skipped_reason": self.skipped_reason,
            "api_version": self.api_version,
        }


class CursorCloudClient:
    """Thin async wrapper for Cursor Cloud Agents API (v1 with v0 fallback)."""

    def __init__(self) -> None:
        self.api_key = os.getenv("CURSOR_API_KEY", "").strip()
        self.repository = detect_git_repository()
        self.ref = detect_git_ref()
        self.api_version = os.getenv("CURSOR_API_VERSION", "v1").strip().lower()
        self.auto_create_pr = _env_bool("CURSOR_AUTO_CREATE_PR", False)
        self.model = os.getenv("CURSOR_HANDOFF_MODEL", "").strip() or None
        self.timeout = float(os.getenv("CURSOR_API_TIMEOUT", "60"))

    @property
    def enabled(self) -> bool:
        return bool(self.api_key and self.repository)

    @property
    def auto_handoff_default(self) -> bool:
        if not self.enabled:
            return False
        if os.getenv("CURSOR_AUTO_HANDOFF", "").strip() == "":
            return True
        return _env_bool("CURSOR_AUTO_HANDOFF", True)

    @property
    def handoff_on_fail_only(self) -> bool:
        return _env_bool("CURSOR_AUTO_HANDOFF_ON_FAIL_ONLY", False)

    def _auth(self) -> tuple[str, str]:
        return (self.api_key, "")

    async def launch_agent(self, prompt_text: str) -> CursorLaunchResult:
        if not self.api_key:
            return CursorLaunchResult(
                launched=False, skipped_reason="CURSOR_API_KEY not set"
            )
        if not self.repository:
            return CursorLaunchResult(
                launched=False,
                skipped_reason="CURSOR_REPOSITORY not set and git origin not detected",
            )

        if self.api_version == "v0":
            return await self._launch_v0(prompt_text)
        return await self._launch_v1(prompt_text)

    async def _launch_v1(self, prompt_text: str) -> CursorLaunchResult:
        body: dict[str, Any] = {
            "prompt": {"text": prompt_text},
            "repos": [{"url": self.repository, "startingRef": self.ref}],
            "autoCreatePR": self.auto_create_pr,
        }
        if self.model:
            body["model"] = {"id": self.model}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    "https://api.cursor.com/v1/agents",
                    json=body,
                    auth=self._auth(),
                )
                if resp.status_code >= 400 and resp.status_code != 404:
                    return CursorLaunchResult(
                        launched=False,
                        error=f"v1 HTTP {resp.status_code}: {resp.text[:500]}",
                        api_version="v1",
                    )
                if resp.status_code == 404:
                    return await self._launch_v0(prompt_text)

                data = resp.json()
                agent = data.get("agent") or data
                agent_id = agent.get("id") or data.get("id")
                target = agent.get("target") or data.get("target") or {}
                return CursorLaunchResult(
                    launched=True,
                    agent_id=agent_id,
                    agent_url=target.get("url")
                    or (f"https://cursor.com/agents?id={agent_id}" if agent_id else None),
                    status=agent.get("status") or data.get("status"),
                    branch_name=target.get("branchName"),
                    pr_url=target.get("prUrl"),
                    api_version="v1",
                )
        except Exception as exc:  # noqa: BLE001
            return CursorLaunchResult(launched=False, error=str(exc), api_version="v1")

    async def _launch_v0(self, prompt_text: str) -> CursorLaunchResult:
        body: dict[str, Any] = {
            "prompt": {"text": prompt_text},
            "source": {"repository": self.repository, "ref": self.ref},
            "target": {"autoCreatePr": self.auto_create_pr},
        }
        if self.model:
            body["model"] = self.model

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    "https://api.cursor.com/v0/agents",
                    json=body,
                    auth=self._auth(),
                )
                if resp.status_code >= 400:
                    return CursorLaunchResult(
                        launched=False,
                        error=f"v0 HTTP {resp.status_code}: {resp.text[:500]}",
                        api_version="v0",
                    )
                data = resp.json()
                agent_id = data.get("id")
                target = data.get("target") or {}
                return CursorLaunchResult(
                    launched=True,
                    agent_id=agent_id,
                    agent_url=target.get("url")
                    or (f"https://cursor.com/agents?id={agent_id}" if agent_id else None),
                    status=data.get("status"),
                    branch_name=target.get("branchName"),
                    pr_url=target.get("prUrl"),
                    api_version="v0",
                )
        except Exception as exc:  # noqa: BLE001
            return CursorLaunchResult(launched=False, error=str(exc), api_version="v0")

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        version = self.api_version if self.api_version != "v0" else "v1"
        paths = [
            f"https://api.cursor.com/v1/agents/{agent_id}",
            f"https://api.cursor.com/v0/agents/{agent_id}",
        ]
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for url in paths:
                resp = await client.get(url, auth=self._auth())
                if resp.status_code == 200:
                    return resp.json()
        return {"error": "agent not found"}


def build_handoff_prompt(handoff_markdown: str, *, run_id: str, passed: bool, score: int) -> str:
    """Compose the cloud-agent task from the QA markdown report."""
    status = "PASS" if passed else "NEEDS WORK"
    return (
        "You are the coding agent for ProductionAgent (multi-agent production scheduler).\n"
        f"QA run `{run_id}` finished with score {score}/100 ({status}).\n\n"
        "Implement the recommended fixes in this repository. Requirements:\n"
        "- Minimize scope; fix root causes from the QA evidence.\n"
        "- Preserve existing conventions and tests.\n"
        "- Run `python3 -m pytest tests/ -q` before finishing.\n"
        "- Focus on schedule dynamics, rescheduling, DB persistence, and scheduling preferences "
        "(geo_first vs crew_fill).\n\n"
        "---\n\n"
        f"{handoff_markdown.strip()}\n"
    )


cursor_cloud = CursorCloudClient()
