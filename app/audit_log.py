"""Structured audit logging for QA agents and human process reports."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
REPORTS_DIR = ROOT / "reports"


class AuditLogger:
    """Append-only run log (memory + JSONL file under reports/)."""

    def __init__(self, run_id: Optional[str] = None, *, label: str = "run") -> None:
        self.run_id = run_id or f"{label}_{uuid.uuid4().hex[:12]}"
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.entries: list[dict[str, Any]] = []
        self._lock = RLock()
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        self._path = REPORTS_DIR / f"audit_{self.run_id}.jsonl"

    def log(
        self,
        agent: str,
        phase: str,
        message: str,
        *,
        detail: Optional[dict] = None,
        level: str = "info",
    ) -> None:
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "run_id": self.run_id,
            "agent": agent,
            "phase": phase,
            "message": message,
            "level": level,
            "detail": detail or {},
        }
        with self._lock:
            self.entries.append(row)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, default=str) + "\n")

    def snapshot(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "entry_count": len(self.entries),
            "log_path": str(self._path),
            "entries": self.entries,
        }
