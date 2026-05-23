from functools import lru_cache
from pathlib import Path

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict

# Repo root: backend/app/config.py → ../../
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ENV_FILE = _REPO_ROOT / ".env"


class Settings(BaseSettings):
    """Application settings loaded from environment / repo-root .env file."""

    model_config = SettingsConfigDict(
        env_file=str(_ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    supabase_url: str = Field(..., description="Supabase project URL")
    supabase_service_key: str = Field(
        ...,
        description="Supabase service role key (server-side only)",
    )
    supabase_db_url: PostgresDsn = Field(
        ...,
        description="Direct Postgres connection string (migrations, raw SQL)",
    )

    app_name: str = "Production Agent"
    debug: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
