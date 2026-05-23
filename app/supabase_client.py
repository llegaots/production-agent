"""Minimal PostgREST client for Supabase.

Avoids adding a heavy SDK dependency. Uses the service-role key, which
bypasses RLS — the backend is trusted to authorize requests itself. The
service-role key must NEVER be exposed to the browser.
"""
from __future__ import annotations

import os
from typing import Any, Optional

import httpx
from .env_load import load_project_env

load_project_env()


class SupabaseClient:
    def __init__(self) -> None:
        self.url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
        # Accept either modern service_role JWT or legacy SUPABASE_KEY env var.
        self.service_key = (
            os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or os.getenv("SUPABASE_KEY")
            or ""
        ).strip()

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.service_key)

    def _headers(self, prefer: Optional[str] = None) -> dict[str, str]:
        h = {
            "apikey": self.service_key,
            "Authorization": f"Bearer {self.service_key}",
            "Content-Type": "application/json",
        }
        if prefer:
            h["Prefer"] = prefer
        return h

    def _table_url(self, table: str) -> str:
        return f"{self.url}/rest/v1/{table}"

    async def select(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: Optional[dict[str, str]] = None,
        order: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> list[dict]:
        params: dict[str, Any] = {"select": columns}
        if filters:
            params.update(filters)
        if order:
            params["order"] = order
        if limit:
            params["limit"] = str(limit)
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.get(self._table_url(table), headers=self._headers(), params=params)
            r.raise_for_status()
            return r.json()

    async def insert(self, table: str, rows: list[dict] | dict) -> list[dict]:
        if isinstance(rows, dict):
            rows = [rows]
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(
                self._table_url(table),
                headers=self._headers("return=representation"),
                json=rows,
            )
            r.raise_for_status()
            return r.json()

    async def upsert(
        self, table: str, rows: list[dict] | dict, on_conflict: Optional[str] = None
    ) -> list[dict]:
        if isinstance(rows, dict):
            rows = [rows]
        params: dict[str, str] = {}
        if on_conflict:
            params["on_conflict"] = on_conflict
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.post(
                self._table_url(table),
                headers=self._headers("resolution=merge-duplicates,return=representation"),
                params=params,
                json=rows,
            )
            r.raise_for_status()
            return r.json()

    async def update(self, table: str, *, filters: dict[str, str], patch: dict) -> list[dict]:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.patch(
                self._table_url(table),
                headers=self._headers("return=representation"),
                params=filters,
                json=patch,
            )
            r.raise_for_status()
            return r.json()

    async def delete(self, table: str, *, filters: dict[str, str]) -> None:
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.delete(
                self._table_url(table),
                headers=self._headers(),
                params=filters,
            )
            r.raise_for_status()

    async def delete_where(self, table: str, column: str, values: list[str]) -> None:
        """Delete rows where `column` is in `values` (uses PostgREST `in` filter)."""
        if not values:
            return
        in_filter = f"({','.join(values)})"
        async with httpx.AsyncClient(timeout=15.0) as cli:
            r = await cli.delete(
                self._table_url(table),
                headers=self._headers(),
                params={column: f"in.{in_filter}"},
            )
            r.raise_for_status()


supabase = SupabaseClient()
