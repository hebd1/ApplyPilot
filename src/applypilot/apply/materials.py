"""Resolve tailored resume / cover letter text when DB paths point at PDFs."""

from __future__ import annotations

import re
from pathlib import Path

from applypilot import config
from applypilot.job_meta import display_company


def job_material_prefix(job: dict) -> str:
    """Filename prefix used by tailor/cover stages: ``{site}_{title}``."""
    safe_title = re.sub(r"[^\w\s-]", "", job.get("title") or "")[:50].strip().replace(" ", "_")
    safe_site = re.sub(r"[^\w\s-]", "", job.get("site") or "")[:20].strip().replace(" ", "_")
    return f"{safe_site}_{safe_title}"


def _company_material_prefix(job: dict) -> str:
    """Alternate prefix using employer label (newer / corrected naming)."""
    safe_title = re.sub(r"[^\w\s-]", "", job.get("title") or "")[:50].strip().replace(" ", "_")
    safe_co = re.sub(r"[^\w\s-]", "", display_company(job))[:20].strip().replace(" ", "_")
    return f"{safe_co}_{safe_title}"


def resolve_resume_text(job: dict) -> str:
    """Load plain-text tailored resume for the apply prompt.

    DB often stores the named PDF path after conversion. Prefer a sibling
    ``.txt``, then fall back to tailor-stage ``{site|company}_{title}.txt``.
    """
    candidates: list[Path] = []
    resume_path = job.get("tailored_resume_path")
    if resume_path:
        stored = Path(resume_path)
        candidates.append(stored.with_suffix(".txt"))
        if stored.suffix.lower() == ".txt":
            candidates.append(stored)

    for prefix in (job_material_prefix(job), _company_material_prefix(job)):
        if prefix and prefix != "_":
            candidates.append(config.TAILORED_DIR / f"{prefix}.txt")

    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return ""


def resolve_cover_letter_text(job: dict) -> str:
    """Load plain-text cover letter (PDF sibling or ``{site|company}_{title}_CL.txt``)."""
    candidates: list[Path] = []
    cl_path = job.get("cover_letter_path")
    if cl_path:
        stored = Path(cl_path)
        candidates.append(stored.with_suffix(".txt"))
        if stored.suffix.lower() == ".txt":
            candidates.append(stored)

    for prefix in (job_material_prefix(job), _company_material_prefix(job)):
        if prefix and prefix != "_":
            candidates.append(config.COVER_LETTER_DIR / f"{prefix}_CL.txt")

    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.is_file():
            return path.read_text(encoding="utf-8")
    return ""
