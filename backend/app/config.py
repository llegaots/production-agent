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
    supabase_db_url: PostgresDsn | None = Field(
        default=None,
        description="Direct Postgres connection string (migrations, raw SQL)",
    )

    app_name: str = "Production Agent"
    debug: bool = False

    google_maps_api_key: str | None = Field(
        default=None,
        description="Google Maps Distance Matrix API key",
    )
    tomorrow_io_api_key: str | None = Field(
        default=None,
        description="Tomorrow.io weather API key",
    )
    travel_cache_ttl_hours: int = Field(default=168, ge=1)
    weather_cache_ttl_hours: int = Field(default=6, ge=1)

    anthropic_api_key: str | None = Field(default=None)
    anthropic_model: str = Field(default="claude-sonnet-4-20250514")


@lru_cache
def get_settings() -> Settings:
    return Settings()
