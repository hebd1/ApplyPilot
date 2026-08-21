"""Persist last daily-apply health so dashboard/status can show blockers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from applypilot.config import APP_DIR

APPLY_HEALTH_PATH = APP_DIR / "apply_health.json"


def write_apply_health(
    *,
    status: str,
    reason: str,
    detail: str = "",
    log_file: str = "",
) -> Path:
    """Write ~/.applypilot/apply_health.json (status: ok | blocked | error)."""
    payload = {
        "status": status,
        "reason": reason,
        "detail": (detail or "")[:500],
        "log_file": log_file,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    APPLY_HEALTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    APPLY_HEALTH_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return APPLY_HEALTH_PATH


def read_apply_health() -> dict[str, Any] | None:
    if not APPLY_HEALTH_PATH.is_file():
        return None
    try:
        data = json.loads(APPLY_HEALTH_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def apply_is_blocked(health: dict[str, Any] | None = None) -> bool:
    data = health if health is not None else read_apply_health()
    return bool(data) and data.get("status") in ("blocked", "error")
