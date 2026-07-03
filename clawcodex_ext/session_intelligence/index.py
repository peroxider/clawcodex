"""Index helpers for session summaries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_summary(session_id: str, *, sessions_dir: Path | None = None) -> dict[str, Any] | None:
    from src.services.session_storage import SESSIONS_DIR

    path = Path(sessions_dir or SESSIONS_DIR) / session_id / "summary.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(data, dict) and int(data.get("schema_version", 0)) >= 1:
        return data
    return None
