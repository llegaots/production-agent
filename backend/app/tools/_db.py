from functools import lru_cache

from supabase import Client

from app.db.supabase_client import get_supabase_client


@lru_cache
def tools_db() -> Client:
    return get_supabase_client()
