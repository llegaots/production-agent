from functools import lru_cache

from pydantic import Field, PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
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
