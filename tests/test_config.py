"""Settings / environment loading."""

from app.config import Settings, get_settings


def test_langfuse_base_url_maps_to_host(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    monkeypatch.setenv("LANGFUSE_BASE_URL", "https://us.cloud.langfuse.com")
    monkeypatch.delenv("LANGFUSE_HOST", raising=False)

    settings = Settings()

    assert settings.langfuse_host == "https://us.cloud.langfuse.com"


def test_get_settings_is_cached(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "test-key")
    assert get_settings() is get_settings()
    get_settings.cache_clear()
