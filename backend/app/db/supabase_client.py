from __future__ import annotations

from functools import lru_cache
from typing import Any

import httpx
from supabase import Client, create_client

from app.config import Settings, get_settings


@lru_cache
def get_supabase_client() -> Client:
    """Supabase client for app code (REST / PostgREST, Auth, Storage, etc.)."""
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_key)


def check_supabase_connection(settings: Settings) -> dict[str, Any]:
    """Verify supabase-py / PostgREST API is reachable with the service role key."""
    url = f"{settings.supabase_url.rstrip('/')}/rest/v1/"
    headers = {
        "apikey": settings.supabase_service_key,
        "Authorization": f"Bearer {settings.supabase_service_key}",
    }
    with httpx.Client(timeout=15.0) as http:
        resp = http.get(url, headers=headers)
        resp.raise_for_status()

    # Also confirm the Python client initializes (used throughout the app).
    _ = get_supabase_client()

    return {
        "ok": True,
        "supabase_url": settings.supabase_url,
        "rest_api_status": resp.status_code,
        "note": "PostgREST reachable; tables will appear after Phase 2 migrations.",
    }
