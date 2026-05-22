"""Load project `.env` from repo root (not process cwd).

Cursor / shell often inject ``ANTHROPIC_MODEL`` (e.g. claude-opus-4-7). Without
``override=True``, those beat values in your local ``.env`` file.
"""
from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


def load_project_env() -> bool:
    """Load ``ROOT/.env`` if present. Returns True when the file was loaded."""
    if ENV_PATH.exists():
        load_dotenv(ENV_PATH, override=True)
        return True
    load_dotenv(override=True)
    return False


# Run once on first import so all modules share the same env.
ENV_LOADED = load_project_env()
