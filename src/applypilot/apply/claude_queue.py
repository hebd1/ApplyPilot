"""Daily queue for the Claude in Chrome apply routine.

Stage 6 replacement for the Cursor agent: this module only picks jobs,
exports their materials where Windows Chrome can upload them, and records
what the browser routine reports back. The browser work itself happens in
a Claude desktop scheduled task (see docs/claude-routine.md).

Status flow (``jobs.apply_status``)::

    NULL --pick--> claude_queued --fill--> claude_filled --Eli approves--> applied
                                  \\--> needs_eli   (CAPTCHA, account, question)
                                  \\--> failed      (closed, location, form error)
    claude_filled --Eli says no / not approved in time--> declined
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from applypilot import config
from applypilot.database import get_connection

log = logging.getLogger(__name__)

STATUS_QUEUED = "claude_queued"
STATUS_FILLED = "claude_filled"
STATUS_NEEDS_ELI = "needs_eli"
STATUS_DECLINED = "declined"

MARK_STATUSES = ("filled", "applied", "needs_eli", "failed", "declined", "release")

# Earlier Cursor-flow failures the Claude routine can still handle.
_REOPEN_ERRORS = ("not_preferred_ats",)
_REOPEN_ERROR_PREFIXES = ("skip_ats:",)
# Failures that are final no matter who applies.
_FINAL_ERRORS = ("expired", "duplicate_applied", "excluded_title", "marketplace")

QUEUED_STALE_HOURS = 6
FILLED_TTL_DAYS = int(os.environ.get("CLAUDE_FILLED_TTL_DAYS", "3"))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Picking
# ---------------------------------------------------------------------------

def build_candidate_query(
    min_score: int,
    hosts: list[str],
    max_attempts: int,
    deny_hosts: list[str] | None = None,
) -> tuple[str, list]:
    """SELECT for apply-ready jobs, best first.

    With ``deny_hosts`` None only ``hosts`` qualify. With a list, any host
    qualifies except the denied (account-gated) ones, and ``hosts`` only set
    the order within a fit score.

    Params are appended in placeholder order (the 2026-08-21 queue bug was
    a bind-order mix-up; scripts/test_claude_queue.py guards this one).
    """
    params: list = [min_score, max_attempts]
    params.extend(_REOPEN_ERRORS)
    params.extend(f"{p}%" for p in _REOPEN_ERROR_PREFIXES)
    params.extend(_FINAL_ERRORS)

    if deny_hosts is None:
        host_clause = " OR ".join("LOWER(application_url) LIKE ?" for _ in hosts) or "0"
        params.extend(f"%{h}%" for h in hosts)
    else:
        host_clause = " AND ".join("LOWER(application_url) NOT LIKE ?" for _ in deny_hosts) or "1"
        params.extend(f"%{h}%" for h in deny_hosts)

    rank_cases = " ".join(
        f"WHEN LOWER(application_url) LIKE ? THEN {i}" for i in range(len(hosts))
    )
    params.extend(f"%{h}%" for h in hosts)
    rank_expr = f"CASE {rank_cases} ELSE 99 END" if hosts else "0"

    reopen_in = ",".join("?" * len(_REOPEN_ERRORS))
    reopen_like = " OR ".join("IFNULL(apply_error, '') LIKE ?" for _ in _REOPEN_ERROR_PREFIXES)
    final_in = ",".join("?" * len(_FINAL_ERRORS))

    sql = f"""
        SELECT url, title, site, company, application_url, tailored_resume_path,
               cover_letter_path, fit_score, score_reasoning, location,
               full_description, discovered_at
        FROM jobs
        WHERE tailored_resume_path IS NOT NULL
          AND applied_at IS NULL
          AND fit_score >= ?
          AND application_url LIKE 'http%'
          AND (
            apply_status IS NULL OR apply_status = ''
            OR (apply_status = 'failed' AND IFNULL(apply_attempts, 0) < ?)
            OR (apply_status = 'failed' AND (IFNULL(apply_error, '') IN ({reopen_in}) OR {reopen_like}))
          )
          AND IFNULL(apply_error, '') NOT IN ({final_in})
          AND ({host_clause})
        ORDER BY fit_score DESC, {rank_expr}, IFNULL(discovered_at, '') DESC, url
    """
    return sql, params


def _looks_expired(url: str) -> bool:
    """Cheap closed-posting check. Network errors count as open (the browser decides)."""
    try:
        import httpx
        resp = httpx.get(url, timeout=8.0, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0"})
    except Exception:
        return False
    if resp.status_code in (404, 410, 451):
        return True
    final = str(resp.url).lower()
    # Greenhouse redirects closed postings to the board with ?error=true.
    return "greenhouse" in final and "error=true" in final


def release_stale(conn=None) -> dict:
    """Free interrupted picks and expire fills Eli never approved."""
    conn = conn or get_connection()
    released = conn.execute(
        f"""
        UPDATE jobs SET apply_status = NULL, agent_id = NULL
        WHERE apply_status = ?
          AND (last_attempted_at IS NULL
               OR datetime(last_attempted_at) < datetime('now', '-{QUEUED_STALE_HOURS} hours'))
        """,
        (STATUS_QUEUED,),
    ).rowcount
    expired = conn.execute(
        f"""
        UPDATE jobs SET apply_status = ?, apply_error = 'not_approved', agent_id = NULL
        WHERE apply_status = ?
          AND datetime(last_attempted_at) < datetime('now', '-{FILLED_TTL_DAYS} days')
        """,
        (STATUS_DECLINED, STATUS_FILLED),
    ).rowcount
    conn.commit()
    return {"released_queued": released, "expired_filled": expired}


def _fail(conn, url: str, reason: str) -> None:
    conn.execute(
        "UPDATE jobs SET apply_status = 'failed', apply_error = ?, apply_attempts = 99 WHERE url = ?",
        (reason, url),
    )
    conn.commit()


def pick_batch(
    count: int = 3,
    min_score: int = 8,
    *,
    include_workday: bool = False,
    check_expiry: bool = True,
    conn=None,
) -> list[dict]:
    """Claim up to ``count`` jobs (one per employer) as ``claude_queued``."""
    from applypilot.config import (
        is_manual_ats, is_marketplace_url, load_claude_account_hosts, load_claude_apply_hosts,
        title_is_excluded,
    )
    from applypilot.job_meta import (
        already_applied_same_role, classify_apply_url, display_company, persist_missing_company,
    )

    conn = conn or get_connection()
    release_stale(conn)

    hosts = load_claude_apply_hosts()
    deny = load_claude_account_hosts()  # None = only the named hosts
    if include_workday:
        hosts = hosts + ["myworkdayjobs.com", "myworkdaysite.com"]
        if deny is not None:
            deny = [h for h in deny if "myworkday" not in h]
    sql, params = build_candidate_query(min_score, hosts, config.DEFAULTS["max_apply_attempts"], deny)
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

    picked: list[dict] = []
    employers: set[str] = set()
    for job in rows:
        if len(picked) >= count:
            break
        url = job["url"]
        apply_url = job["application_url"] or ""

        if title_is_excluded(job["title"]):
            _fail(conn, url, "excluded_title")
            continue
        if is_marketplace_url(apply_url) or is_manual_ats(apply_url):
            continue
        ok, _reason = classify_apply_url(apply_url)
        if not ok:
            continue
        resume = Path(job["tailored_resume_path"] or "")
        if resume.suffix.lower() != ".pdf" or not resume.is_file():
            continue

        employer = display_company(job).strip().lower()
        if employer and employer in employers:
            continue
        if already_applied_same_role(conn, job):
            _fail(conn, url, "duplicate_applied")
            continue
        if check_expiry and _looks_expired(apply_url):
            _fail(conn, url, "expired")
            continue

        persist_missing_company(conn, job)
        conn.execute(
            "UPDATE jobs SET apply_status = ?, agent_id = 'claude', last_attempted_at = ? WHERE url = ?",
            (STATUS_QUEUED, _now(), url),
        )
        conn.commit()
        job["company"] = display_company(job)
        picked.append(job)
        if employer:
            employers.add(employer)
    return picked


# ---------------------------------------------------------------------------
# Export (files Windows Chrome can upload)
# ---------------------------------------------------------------------------

def to_windows_path(path: Path) -> str:
    """``/mnt/c/Users/x`` -> ``C:\\Users\\x``; other WSL paths via ``wslpath -w``."""
    s = str(path)
    m = re.match(r"^/mnt/([a-zA-Z])/(.*)$", s)
    if m:
        return f"{m.group(1).upper()}:\\" + m.group(2).replace("/", "\\")
    if shutil.which("wslpath"):
        try:
            return subprocess.run(["wslpath", "-w", s], capture_output=True, text=True,
                                  check=True).stdout.strip()
        except Exception:
            pass
    return s


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", text or "").strip("-")[:40] or "job"


def default_export_root() -> Path:
    raw = os.environ.get("CLAUDE_APPLY_EXPORT_DIR", "").strip()
    return Path(raw) if raw else config.CLAUDE_DIR / "queue"


def export_batch(jobs: list[dict], export_root: Path | None = None, *, day: str | None = None,
                 conn=None) -> dict:
    """Copy each job's PDFs into ``<root>/<day>/<n>-<company>/`` and write queue.json.

    A second run on the same day appends to that day's queue (ranks continue
    after the highest) and drops jobs already closed out (applied / failed /
    declined), so the routine never reopens them.
    """
    from applypilot.apply.materials import resolve_cover_letter_text
    from applypilot.apply.prompt import _build_profile_summary
    from applypilot.config import load_profile, load_search_config

    profile = load_profile()
    search_cfg = load_search_config()
    name = _slug(profile["personal"]["full_name"]).replace("-", "_")
    day = day or datetime.now().strftime("%Y-%m-%d")
    out_dir = (export_root or default_export_root()) / day
    out_dir.mkdir(parents=True, exist_ok=True)

    items: list[dict] = []
    existing = out_dir / "queue.json"
    if existing.is_file():
        try:
            items = json.loads(existing.read_text(encoding="utf-8")).get("jobs") or []
        except (OSError, ValueError):
            items = []
    if items:
        conn = conn or get_connection()
        closed = {
            r["url"] for r in conn.execute(
                f"SELECT url FROM jobs WHERE apply_status IN ('applied', 'failed', ?) "
                f"AND url IN ({','.join('?' * len(items))})",
                (STATUS_DECLINED, *(item["url"] for item in items)),
            )
        }
        items = [item for item in items if item["url"] not in closed]
    next_rank = max((item.get("rank", 0) for item in items), default=0) + 1
    seen = {item["url"] for item in items}
    jobs = [j for j in jobs if j["url"] not in seen]

    for i, job in enumerate(jobs, next_rank):
        job_dir = out_dir / f"{i}-{_slug(job.get('company') or job.get('site') or '')}"
        job_dir.mkdir(exist_ok=True)
        resume = job_dir / f"{name}_Resume.pdf"
        shutil.copyfile(job["tailored_resume_path"], resume)

        cover_pdf = None
        if job.get("cover_letter_path") and Path(job["cover_letter_path"]).suffix.lower() == ".pdf" \
                and Path(job["cover_letter_path"]).is_file():
            cover_pdf = job_dir / f"{name}_Cover_Letter.pdf"
            shutil.copyfile(job["cover_letter_path"], cover_pdf)

        items.append({
            "rank": i,
            "url": job["url"],
            "apply_url": job["application_url"],
            "title": job["title"],
            "company": job.get("company") or "",
            "location": job.get("location") or "",
            "fit_score": job["fit_score"],
            "why_it_fits": (job.get("score_reasoning") or "")[:800],
            "resume_pdf": to_windows_path(resume),
            "cover_letter_pdf": to_windows_path(cover_pdf) if cover_pdf else None,
            "cover_letter_text": resolve_cover_letter_text(job),
            "job_description": (job.get("full_description") or "")[:3000],
        })

    applicant = _build_profile_summary(profile)
    answers = profile.get("screening_answers") or {}
    if answers:
        applicant += "\n\nScreening answers (Eli's own, use verbatim):\n" + "\n".join(
            f"{q}: {a}" for q, a in answers.items()
        )

    comp = profile.get("compensation", {})
    payload = {
        "generated_at": _now(),
        "day": day,
        "export_dir": to_windows_path(out_dir),
        "applicant": applicant,
        "salary": {
            "expectation": comp.get("salary_expectation"),
            "range_min": comp.get("salary_range_min"),
            "range_max": comp.get("salary_range_max"),
            "currency": comp.get("salary_currency", "USD"),
        },
        "location_accept": search_cfg.get("location_accept") or [],
        "jobs": items,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    (out_dir / "queue.json").write_text(text, encoding="utf-8")
    config.CLAUDE_DIR.mkdir(parents=True, exist_ok=True)
    (config.CLAUDE_DIR / f"queue-{day}.json").write_text(text, encoding="utf-8")
    return payload


# ---------------------------------------------------------------------------
# Results from the browser routine
# ---------------------------------------------------------------------------

def mark(url: str, status: str, note: str = "", evidence: str = "", conn=None) -> int:
    """Record a routine result. ``url`` may be the job URL or its apply URL."""
    if status not in MARK_STATUSES:
        raise ValueError(f"status must be one of {', '.join(MARK_STATUSES)}")
    conn = conn or get_connection()
    now = _now()
    where = "WHERE url = ? OR application_url = ?"
    key = (url, url)

    if status == "applied":
        cur = conn.execute(
            f"UPDATE jobs SET apply_status = 'applied', applied_at = ?, apply_error = NULL, "
            f"agent_id = 'claude', apply_notes = ?, apply_evidence = ?, "
            f"verification_confidence = 'claude_chrome' {where}",
            (now, note, evidence, *key),
        )
    elif status == "filled":
        cur = conn.execute(
            f"UPDATE jobs SET apply_status = ?, apply_notes = ?, apply_evidence = ?, "
            f"last_attempted_at = ? {where}",
            (STATUS_FILLED, note, evidence, now, *key),
        )
    elif status == "needs_eli":
        cur = conn.execute(
            f"UPDATE jobs SET apply_status = ?, apply_error = ?, apply_notes = ?, "
            f"apply_evidence = ?, last_attempted_at = ? {where}",
            (STATUS_NEEDS_ELI, note or "needs_eli", note, evidence, now, *key),
        )
    elif status == "failed":
        cur = conn.execute(
            f"UPDATE jobs SET apply_status = 'failed', apply_error = ?, apply_attempts = 99, "
            f"apply_notes = ?, apply_evidence = ?, agent_id = NULL {where}",
            (note or "failed", note, evidence, *key),
        )
    elif status == "declined":
        cur = conn.execute(
            f"UPDATE jobs SET apply_status = ?, apply_error = 'declined_by_eli', "
            f"apply_notes = ?, agent_id = NULL {where}",
            (STATUS_DECLINED, note, *key),
        )
    else:  # release
        cur = conn.execute(
            f"UPDATE jobs SET apply_status = NULL, agent_id = NULL {where}", key,
        )
    conn.commit()
    return cur.rowcount


def pending(days: int = 7, conn=None) -> list[dict]:
    """Jobs waiting on Eli: filled-awaiting-approval and needs_eli, newest first."""
    conn = conn or get_connection()
    rows = conn.execute(
        """
        SELECT url, application_url, title, company, site, fit_score, apply_status,
               apply_error, apply_notes, apply_evidence, last_attempted_at
        FROM jobs
        WHERE apply_status IN (?, ?)
          AND datetime(IFNULL(last_attempted_at, '1970-01-01')) >= datetime('now', ?)
        ORDER BY last_attempted_at DESC
        """,
        (STATUS_FILLED, STATUS_NEEDS_ELI, f"-{int(days)} days"),
    ).fetchall()
    return [dict(r) for r in rows]
