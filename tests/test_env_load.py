import os
from pathlib import Path

from app import env_load


def test_dotenv_overrides_shell_anthropic_model(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("ANTHROPIC_MODEL=claude-sonnet-4.6\n", encoding="utf-8")
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-opus-4-7")
    monkeypatch.setattr(env_load, "ENV_PATH", env_file)
    monkeypatch.setattr(env_load, "ROOT", tmp_path)

    from dotenv import load_dotenv

    load_dotenv(env_file, override=True)
    assert os.getenv("ANTHROPIC_MODEL") == "claude-sonnet-4.6"
