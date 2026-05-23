"""Settings / environment loading."""

from app.config import Settings, get_settings, known_env_var_names


def test_langfuse_base_url_maps_to_host(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com")
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)

    settings = Settings()

    assert settings.langfuse_host == "https://us.cloud.langfuse.com"


def test_max_critic_iterations_alias(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("MAX_CRITIC_ITERATIONS", "6")
    monkeypatch.delenv("ORCHESTRATOR_MAX_ITERATIONS", raising=False)

    settings = Settings()

    assert settings.orchestrator_max_iterations == 6


def test_user_env_var_names_are_known():
    """Every key in the repo .env must map to Settings."""
    user_keys = {
        "SUPABASE_URL",
        "SUPABASE_SERVICE_KEY",
        "LLM_PROVIDER",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_MODEL",
        "ANTHROPIC_QA_MODEL",
        "QA_MAX_CASES",
        "QA_MAX_ITERATIONS",
        "QA_TARGET_TEST_JOBS",
        "QA_MIN_TEST_JOBS",
        "QA_MAX_TEST_JOBS",
        "GOOGLE_MAPS_API_KEY",
        "CURSOR_API_KEY",
        "CURSOR_AUTO_HANDOFF",
        "CURSOR_HANDOFF_MODEL",
        "MAX_CRITIC_ITERATIONS",
        "OPTIMIZER_TIME_LIMIT_SECONDS",
        "DEFAULT_TIMEZONE",
        "LANGFUSE_SECRET_KEY",
        "LANGFUSE_PUBLIC_KEY",
        "LANGFUSE_BASE_URL",
    }
    known = known_env_var_names()
    missing = sorted(user_keys - known)
    assert not missing, f"Settings missing env aliases for: {missing}"


def test_user_env_values_load(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_QA_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("QA_MAX_CASES", "1")
    monkeypatch.setenv("QA_MAX_ITERATIONS", "2")
    monkeypatch.setenv("QA_TARGET_TEST_JOBS", "20")
    monkeypatch.setenv("QA_MIN_TEST_JOBS", "15")
    monkeypatch.setenv("QA_MAX_TEST_JOBS", "25")
    monkeypatch.setenv("CURSOR_AUTO_HANDOFF", "false")
    monkeypatch.setenv("CURSOR_HANDOFF_MODEL", "claude-sonnet-4-6")
    monkeypatch.setenv("MAX_CRITIC_ITERATIONS", "4")
    monkeypatch.setenv("OPTIMIZER_TIME_LIMIT_SECONDS", "30")
    monkeypatch.setenv("DEFAULT_TIMEZONE", "America/Toronto")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com")

    settings = Settings()

    assert settings.llm_provider == "anthropic"
    assert settings.anthropic_qa_model == "claude-sonnet-4-6"
    assert settings.qa_max_cases == 1
    assert settings.optimizer_time_limit_seconds == 30
    assert settings.default_timezone == "America/Toronto"
    assert settings.langfuse_host == "https://us.cloud.langfuse.com"
    assert settings.orchestrator_max_iterations == 4
    assert settings.cursor_auto_handoff is False


def test_get_settings_is_cached(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    assert get_settings() is get_settings()
    get_settings.cache_clear()
