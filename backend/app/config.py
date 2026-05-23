from functools import lru_cache
from pathlib import Path

from pydantic import AliasChoices, Field, PostgresDsn
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
    supabase_anon_key: str | None = Field(
        default=None,
        description="Optional anon/public key for browser clients (defaults to service key in UI bootstrap)",
        validation_alias="SUPABASE_ANON_KEY",
    )
    supabase_db_url: PostgresDsn | None = Field(
        default=None,
        description="Direct Postgres connection string (migrations, raw SQL)",
    )

    app_name: str = "Production Agent"
    debug: bool = False

    llm_provider: str = Field(default="anthropic")

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
    anthropic_qa_model: str | None = Field(default=None)

    qa_max_cases: int = Field(default=1, ge=1)
    qa_max_iterations: int = Field(default=2, ge=1)
    qa_target_test_jobs: int = Field(default=20, ge=1)
    qa_min_test_jobs: int = Field(default=15, ge=1)
    qa_max_test_jobs: int = Field(default=25, ge=1)

    cursor_api_key: str | None = Field(default=None)
    cursor_auto_handoff: bool = Field(default=False)
    cursor_handoff_model: str | None = Field(default=None)

    orchestrator_max_iterations: int = Field(
        default=4,
        ge=1,
        le=10,
        validation_alias=AliasChoices(
            "ORCHESTRATOR_MAX_ITERATIONS",
            "MAX_CRITIC_ITERATIONS",
        ),
    )
    optimizer_time_limit_seconds: int = Field(default=30, ge=1, le=300)
    default_timezone: str = Field(default="America/Toronto")

    langfuse_public_key: str | None = Field(default=None)
    langfuse_secret_key: str | None = Field(default=None)
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("LANGFUSE_HOST", "LANGFUSE_BASE_URL"),
    )


def known_env_var_names() -> frozenset[str]:
    """Every environment variable name accepted by Settings."""
    names: set[str] = set()
    for field_name, field in Settings.model_fields.items():
        alias = field.validation_alias
        if isinstance(alias, AliasChoices):
            names.update(str(choice) for choice in alias.choices)
        elif isinstance(alias, str):
            names.add(alias)
        else:
            names.add(field_name.upper())
    return frozenset(names)


@lru_cache
def get_settings() -> Settings:
    return Settings()
