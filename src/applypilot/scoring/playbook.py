"""Eli's Resume Playbook (Notion "Job Search / Resume Playbook").

When the playbook file exists, tailoring, judging and cover letters are held
to it: bullets come only from its approved bank, skills only from its master
list, no seniority in the headline, short cover letters. The daily Claude
routine refreshes the file from Notion before prep (docs/claude-routine.md).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from applypilot import config

_SENIORITY = re.compile(
    r"\b(senior|sr\.?|staff|principal|lead|junior|jr\.?|distinguished)(?=\s|$)",
    re.IGNORECASE,
)
_LEVEL_SUFFIX = re.compile(r"(\s+(?:[IV]{1,3}|[1-5]|L\d))+$")
_QUALIFIER_SPLIT = re.compile(r"\s+[-–—|]\s+|\s*[,(|]")


def playbook_path() -> Path:
    raw = os.environ.get("RESUME_PLAYBOOK_PATH", "").strip()
    return Path(raw) if raw else config.APP_DIR / "resume_playbook.md"


def load_playbook() -> str:
    """Playbook markdown, or "" when there is none (legacy tailoring)."""
    path = playbook_path()
    try:
        return path.read_text(encoding="utf-8").strip() if path.is_file() else ""
    except OSError:
        return ""


def strip_seniority(title: str) -> str:
    """Role family only: "Staff Backend Engineer – Platform" -> "Backend Engineer".

    The playbook bans "Senior" and levels in the headline; team or location
    qualifiers after a dash, comma, pipe or parenthesis go too.
    """
    head = _QUALIFIER_SPLIT.split(title or "", maxsplit=1)[0]
    head = _SENIORITY.sub("", head)
    head = _LEVEL_SUFFIX.sub("", " ".join(head.split()))
    head = " ".join(head.split())
    return head or "Software Engineer"
