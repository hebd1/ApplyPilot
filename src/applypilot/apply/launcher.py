"""Apply orchestration: acquire jobs, spawn Cursor agent sessions, track results.

This is the main entry point for the apply pipeline. It pulls jobs from
the database, launches Chrome + Cursor agent for each one, parses the
result, and updates the database. Supports parallel workers via --workers.
"""

import atexit
import json
import logging
import os
import platform
import re
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.live import Live

from applypilot import config
from applypilot.database import get_connection
from applypilot.apply import chrome, dashboard, prompt as prompt_mod
from applypilot.apply.materials import resolve_resume_text
from applypilot.job_meta import already_applied_same_role, display_company, persist_missing_company
from applypilot.apply.chrome import (
    launch_chrome, cleanup_worker, kill_all_chrome,
    reset_worker_dir, cleanup_on_exit,
    BASE_CDP_PORT,
)
from applypilot.apply.dashboard import (
    init_worker, update_state, add_event, get_state,
    render_full, get_totals,
)

logger = logging.getLogger(__name__)

# Blocked sites loaded from config/sites.yaml
def _load_blocked():
    from applypilot.config import load_blocked_sites
    return load_blocked_sites()

# How often to poll the DB when the queue is empty (seconds)
POLL_INTERVAL = config.DEFAULTS["poll_interval"]

# Thread-safe shutdown coordination
_stop_event = threading.Event()

# Register cleanup on exit
atexit.register(cleanup_on_exit)
if platform.system() != "Windows":
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))


# ---------------------------------------------------------------------------
# MCP config
# ---------------------------------------------------------------------------

def _make_mcp_config(cdp_port: int) -> dict:
    """Build MCP config dict for a specific CDP port."""
    return {
        "mcpServers": {
            "playwright": {
                "command": "npx",
                "args": [
                    "@playwright/mcp@latest",
                    f"--cdp-endpoint=http://localhost:{cdp_port}",
                    f"--viewport-size={config.DEFAULTS['viewport']}",
                ],
            },
            "gmail": {
                "command": "npx",
                "args": ["-y", "@gongrzhe/server-gmail-autoauth-mcp"],
            },
        }
    }


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

def build_apply_queue_query(min_score: int, *, ats_only: bool) -> tuple[str, list]:
    """Build the Stage 6 candidate SELECT and bound parameters.

    Placeholder order must match ``params``: max_attempts, min_score, ATS
    hosts, blocked site names, then blocked URL patterns. Mixing that order
    binds blocked names into ``application_url LIKE ?`` and the queue looks
    empty even when Greenhouse/Workday/Ashby jobs are ready.
    """
    from applypilot.config import load_preferred_ats_hosts

    blocked_sites, blocked_patterns = _load_blocked()
    params: list = [config.DEFAULTS["max_apply_attempts"], min_score]

    ats_clause = ""
    if ats_only:
        hosts = load_preferred_ats_hosts() or [
            "greenhouse.io", "grnh.se", "myworkdayjobs.com", "ashbyhq.com",
        ]
        ats_parts = " OR ".join(
            "LOWER(IFNULL(application_url, '')) LIKE ?" for _ in hosts
        )
        ats_clause = f"AND ({ats_parts})"
        params.extend([f"%{h}%" for h in hosts])

    site_clause = ""
    if blocked_sites:
        placeholders = ",".join("?" * len(blocked_sites))
        site_clause = f"AND site NOT IN ({placeholders})"
        params.extend(blocked_sites)

    url_clauses = ""
    if blocked_patterns:
        url_clauses = " ".join(
            "AND url NOT LIKE ? AND IFNULL(application_url, '') NOT LIKE ?"
            for _ in blocked_patterns
        )
        for pattern in blocked_patterns:
            params.extend([pattern, pattern])

    sql = f"""
                    SELECT url, title, site, company, application_url, tailored_resume_path,
                           fit_score, location, full_description, cover_letter_path
                    FROM jobs
                    WHERE tailored_resume_path IS NOT NULL
                      AND (apply_status IS NULL OR apply_status = 'failed')
                      AND (apply_attempts IS NULL OR apply_attempts < ?)
                      AND fit_score >= ?
                      AND application_url IS NOT NULL AND application_url LIKE 'http%'
                      AND LOWER(application_url) NOT LIKE '%linkedin.com%'
                      AND LOWER(application_url) NOT LIKE '%indeed.com%'
                      AND LOWER(application_url) NOT LIKE '%ziprecruiter%'
                      AND LOWER(application_url) NOT LIKE '%glassdoor.com%'
                      AND LOWER(application_url) NOT LIKE '%talent.com%'
                      {ats_clause}
                      {site_clause}
                      {url_clauses}
                    ORDER BY
                      CASE
                        WHEN IFNULL(application_url, '') LIKE '%greenhouse.io%'
                          OR IFNULL(application_url, '') LIKE '%grnh.se%' THEN 0
                        WHEN IFNULL(application_url, '') LIKE '%myworkdayjobs.com%' THEN 1
                        WHEN IFNULL(application_url, '') LIKE '%ashbyhq.com%' THEN 2
                        WHEN IFNULL(application_url, '') LIKE '%lever.co%' THEN 90
                        WHEN application_url IS NOT NULL AND application_url != ''
                          AND application_url LIKE 'http%' THEN 4
                        ELSE 5
                      END,
                      fit_score DESC, url
                    LIMIT 1
                """
    return sql, params


def acquire_job(target_url: str | None = None, min_score: int = 7,
                worker_id: int = 0, *, ats_only: bool | None = None) -> dict | None:
    """Atomically acquire the next job to apply to.

    Args:
        target_url: Apply to a specific URL instead of picking from queue.
        min_score: Minimum fit_score threshold.
        worker_id: Worker claiming this job (for tracking).
        ats_only: If True, only Greenhouse / Workday / Ashby. Defaults from
            env ``APPLY_ATS_ONLY`` / ``DAILY_APPLY_ATS_ONLY`` (1/true).

    Returns:
        Job dict or None if the queue is empty.
    """
    from applypilot.config import (
        is_manual_ats,
        is_marketplace_url,
        is_skip_apply_url,
        title_is_excluded,
    )
    from applypilot.job_meta import classify_apply_url, is_preferred_ats_url

    if ats_only is None:
        ats_only = os.environ.get("APPLY_ATS_ONLY", os.environ.get("DAILY_APPLY_ATS_ONLY", "")).strip().lower() in (
            "1", "true", "yes",
        )

    conn = get_connection()
    try:
        # Skip loop: weak/manual URLs are marked and we try the next candidate.
        for _ in range(100):
            conn.execute("BEGIN IMMEDIATE")

            if target_url:
                like = f"%{target_url.split('?')[0].rstrip('/')}%"
                row = conn.execute("""
                    SELECT url, title, site, company, application_url, tailored_resume_path,
                           fit_score, location, full_description, cover_letter_path
                    FROM jobs
                    WHERE (url = ? OR application_url = ? OR application_url LIKE ? OR url LIKE ?)
                      AND tailored_resume_path IS NOT NULL
                      AND (apply_status IS NULL OR apply_status != 'in_progress')
                    LIMIT 1
                """, (target_url, target_url, like, like)).fetchone()
            else:
                # Prefer Greenhouse / Workday / Ashby; Lever is skip_apply_hosts for now.
                # Skip board hosts in SQL so we do not burn the skip-loop on LinkedIn noise.
                queue_sql, queue_params = build_apply_queue_query(
                    min_score, ats_only=ats_only,
                )
                row = conn.execute(queue_sql, queue_params).fetchone()

            if not row:
                conn.rollback()
                if not target_url:
                    logger.info(
                        "Apply queue empty after filters (min_score=%s ats_only=%s)",
                        min_score, ats_only,
                    )
                return None

            if title_is_excluded(row["title"]):
                conn.execute(
                    "UPDATE jobs SET fit_score = 1, score_reasoning = ?, "
                    "apply_status = 'failed', apply_error = ?, apply_attempts = 99 "
                    "WHERE url = ?",
                    (
                        "Excluded by searches.yaml exclude_titles (title matched a negative keyword).",
                        "excluded_title",
                        row["url"],
                    ),
                )
                conn.commit()
                logger.info("Skipping excluded title: %s", (row["title"] or "")[:80])
                if target_url:
                    return None
                continue

            apply_url = row["application_url"] or ""
            if is_skip_apply_url(apply_url) or is_skip_apply_url(row["url"]):
                from urllib.parse import urlparse
                host = (urlparse(apply_url or row["url"] or "").hostname or "ats").lower()
                conn.execute(
                    "UPDATE jobs SET apply_status = 'failed', apply_error = ?, "
                    "apply_attempts = 99 WHERE url = ?",
                    (f"skip_ats:{host}", row["url"]),
                )
                conn.commit()
                logger.info("Skipping deferred ATS host: %s", (apply_url or "")[:80])
                if target_url:
                    return None
                continue

            if is_marketplace_url(apply_url) or is_marketplace_url(row["url"]):
                conn.execute(
                    "UPDATE jobs SET apply_status = 'failed', apply_error = ?, "
                    "apply_attempts = 99 WHERE url = ?",
                    ("marketplace", row["url"]),
                )
                conn.commit()
                logger.info("Skipping marketplace host: %s", (apply_url or "")[:80])
                if target_url:
                    return None
                continue

            if is_manual_ats(apply_url):
                conn.execute(
                    "UPDATE jobs SET apply_status = 'manual', apply_error = 'manual ATS' WHERE url = ?",
                    (row["url"],),
                )
                conn.commit()
                logger.info("Skipping manual ATS: %s", row["url"][:80])
                if target_url:
                    return None
                continue

            if ats_only and not is_preferred_ats_url(apply_url):
                conn.execute(
                    "UPDATE jobs SET apply_status = 'failed', apply_error = ?, "
                    "apply_attempts = 99 WHERE url = ?",
                    ("not_preferred_ats", row["url"]),
                )
                conn.commit()
                logger.info("Skipping non-preferred ATS: %s", (apply_url or "")[:80])
                if target_url:
                    return None
                continue

            ok, reason = classify_apply_url(row["application_url"] or "")
            if not ok:
                # Do not fall back to board listing URLs — they are not applyable.
                fail_reason = reason or "missing_apply_url"
                if fail_reason == "marketplace_host":
                    fail_reason = "marketplace"
                conn.execute(
                    "UPDATE jobs SET apply_status = 'failed', apply_error = ?, "
                    "apply_attempts = 99 WHERE url = ?",
                    (f"weak_apply_url:{fail_reason}" if fail_reason != "marketplace" else "marketplace",
                     row["url"]),
                )
                conn.commit()
                logger.info(
                    "Skipping weak apply URL (%s): %s",
                    reason,
                    (row["application_url"] or row["url"] or "")[:80],
                )
                if target_url:
                    return None
                continue

            # Lightweight expiry check — quick GET with short timeout.
            apply_url = row["application_url"] or ""
            if apply_url.startswith("http"):
                try:
                    import httpx
                    hresp = httpx.get(
                        apply_url,
                        timeout=5.0,
                        follow_redirects=False,
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    if hresp.status_code in (404, 410, 451):
                        conn.execute(
                            "UPDATE jobs SET apply_status = 'failed', apply_error = ?, "
                            "apply_attempts = 99 WHERE url = ?",
                            ("expired", row["url"]),
                        )
                        conn.commit()
                        logger.info(
                            "Skipping expired job (HTTP %d): %s",
                            hresp.status_code,
                            (row["title"] or "")[:60],
                        )
                        if target_url:
                            return None
                        continue
                except (httpx.ConnectTimeout, httpx.ReadTimeout):
                    # Timeout is not a clear expiry — let the apply agent decide.
                    pass
                except Exception:
                    # Ignore transient network errors; the apply agent will retry.
                    pass

            job = dict(row)
            persist_missing_company(conn, job)
            if not target_url and already_applied_same_role(conn, job):
                conn.execute(
                    "UPDATE jobs SET apply_status = 'failed', apply_error = ?, "
                    "apply_attempts = 99 WHERE url = ?",
                    ("duplicate_applied", job["url"]),
                )
                conn.commit()
                logger.info(
                    "Skipping duplicate of an already-applied role: %s @ %s",
                    (job.get("title") or "")[:60],
                    display_company(job),
                )
                continue

            now = datetime.now(timezone.utc).isoformat()
            conn.execute("""
                UPDATE jobs SET apply_status = 'in_progress',
                               agent_id = ?,
                               last_attempted_at = ?
                WHERE url = ?
            """, (f"worker-{worker_id}", now, job["url"]))
            conn.commit()
            return job

        return None
    except Exception:
        conn.rollback()
        raise


def mark_result(url: str, status: str, error: str | None = None,
                permanent: bool = False, duration_ms: int | None = None,
                task_id: str | None = None) -> None:
    """Update a job's apply status in the database."""
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    if status == "applied":
        conn.execute("""
            UPDATE jobs SET apply_status = 'applied', applied_at = ?,
                           apply_error = NULL, agent_id = NULL,
                           apply_duration_ms = ?, apply_task_id = ?
            WHERE url = ?
        """, (now, duration_ms, task_id, url))
    else:
        attempts = 99 if permanent else "COALESCE(apply_attempts, 0) + 1"
        conn.execute(f"""
            UPDATE jobs SET apply_status = ?, apply_error = ?,
                           apply_attempts = {attempts}, agent_id = NULL,
                           apply_duration_ms = ?, apply_task_id = ?
            WHERE url = ?
        """, (status, error or "unknown", duration_ms, task_id, url))
    conn.commit()


def release_lock(url: str) -> None:
    """Release the in_progress lock without changing status."""
    conn = get_connection()
    conn.execute(
        "UPDATE jobs SET apply_status = NULL, agent_id = NULL WHERE url = ? AND apply_status = 'in_progress'",
        (url,),
    )
    conn.commit()


# ---------------------------------------------------------------------------
# Utility modes (--gen, --mark-applied, --mark-failed, --reset-failed)
# ---------------------------------------------------------------------------

def gen_prompt(target_url: str, min_score: int = 7,
               model: str = "sonnet", worker_id: int = 0) -> Path | None:
    """Generate a prompt file for manual debugging.

    Returns:
        Path to the generated prompt file, or None if no job found.
    """
    job = acquire_job(target_url=target_url, min_score=min_score, worker_id=worker_id)
    if not job:
        return None

    # Read resume text
    resume_text = resolve_resume_text(job)

    prompt = prompt_mod.build_prompt(job=job, tailored_resume=resume_text)

    # Release the lock so the job stays available
    release_lock(job["url"])

    # Write prompt file
    config.ensure_dirs()
    site_slug = (job.get("site") or "unknown")[:20].replace(" ", "_")
    prompt_file = config.LOG_DIR / f"prompt_{site_slug}_{job['title'][:30].replace(' ', '_')}.txt"
    prompt_file.write_text(prompt, encoding="utf-8")

    # Write MCP config for reference
    port = BASE_CDP_PORT + worker_id
    mcp_path = config.APP_DIR / f".mcp-apply-{worker_id}.json"
    mcp_path.write_text(json.dumps(_make_mcp_config(port)), encoding="utf-8")

    return prompt_file


def mark_job(url: str, status: str, reason: str | None = None) -> None:
    """Manually mark a job's apply status in the database.

    Args:
        url: Job URL to mark.
        status: Either 'applied' or 'failed'.
        reason: Failure reason (only for status='failed').
    """
    conn = get_connection()
    now = datetime.now(timezone.utc).isoformat()
    if status == "applied":
        conn.execute("""
            UPDATE jobs SET apply_status = 'applied', applied_at = ?,
                           apply_error = NULL, agent_id = NULL
            WHERE url = ?
        """, (now, url))
    else:
        conn.execute("""
            UPDATE jobs SET apply_status = 'failed', apply_error = ?,
                           apply_attempts = 99, agent_id = NULL
            WHERE url = ?
        """, (reason or "manual", url))
    conn.commit()


def reset_failed() -> int:
    """Reset all failed jobs so they can be retried.

    Returns:
        Number of jobs reset.
    """
    conn = get_connection()
    cursor = conn.execute("""
        UPDATE jobs SET apply_status = NULL, apply_error = NULL,
                       apply_attempts = 0, agent_id = NULL
        WHERE apply_status = 'failed'
          OR (apply_status IS NOT NULL AND apply_status != 'applied'
              AND apply_status != 'in_progress')
    """)
    conn.commit()
    return cursor.rowcount


# ---------------------------------------------------------------------------
# Per-job execution
# ---------------------------------------------------------------------------

def parse_apply_output(
    output: str, worker_id: int, job: dict, duration_ms: int,
) -> tuple[str, int]:
    """Parse RESULT: lines from agent output into apply status."""
    elapsed = duration_ms // 1000

    def _clean_reason(s: str) -> str:
        return re.sub(r'[*`"]+$', '', s).strip()

    for result_status in ["APPLIED", "EXPIRED", "CAPTCHA", "LOGIN_ISSUE"]:
        if f"RESULT:{result_status}" in output:
            add_event(f"[W{worker_id}] {result_status} ({elapsed}s): {job['title'][:30]}")
            update_state(worker_id, status=result_status.lower(),
                         last_action=f"{result_status} ({elapsed}s)")
            return result_status.lower(), duration_ms

    if "RESULT:FAILED" in output:
        for out_line in output.split("\n"):
            if "RESULT:FAILED" in out_line:
                reason = (
                    out_line.split("RESULT:FAILED:")[-1].strip()
                    if ":" in out_line[out_line.index("FAILED") + 6:]
                    else "unknown"
                )
                reason = _clean_reason(reason)
                promote = {"captcha", "expired", "login_issue"}
                if reason in promote:
                    add_event(f"[W{worker_id}] {reason.upper()} ({elapsed}s): {job['title'][:30]}")
                    update_state(worker_id, status=reason,
                                 last_action=f"{reason.upper()} ({elapsed}s)")
                    return reason, duration_ms
                add_event(f"[W{worker_id}] FAILED ({elapsed}s): {reason[:30]}")
                update_state(worker_id, status="failed",
                             last_action=f"FAILED: {reason[:25]}")
                return f"failed:{reason}", duration_ms
        return "failed:unknown", duration_ms

    add_event(f"[W{worker_id}] NO RESULT ({elapsed}s)")
    update_state(worker_id, status="failed", last_action=f"no result ({elapsed}s)")
    return "failed:no_result_line", duration_ms


def run_job(job: dict, port: int, worker_id: int = 0,
            model: str = "sonnet", dry_run: bool = False) -> tuple[str, int]:
    """Spawn a Cursor agent session for one job application."""
    from applypilot.apply.cursor_apply import run_job_cursor

    # Use composer-2.5 for the Cursor SDK apply agent
    cursor_model = "composer-2.5"
    return run_job_cursor(job, port, worker_id, model=cursor_model, dry_run=dry_run)


# ---------------------------------------------------------------------------
# Permanent failure classification
# ---------------------------------------------------------------------------

PERMANENT_FAILURES: set[str] = {
    "expired", "captcha", "login_issue",
    "not_eligible_location", "not_eligible_salary",
    "already_applied", "account_required",
    "not_a_job_application", "unsafe_permissions",
    "unsafe_verification", "sso_required",
    "site_blocked", "cloudflare_blocked", "blocked_by_cloudflare",
}

PERMANENT_PREFIXES: tuple[str, ...] = ("site_blocked", "cloudflare", "blocked_by")


def _is_permanent_failure(result: str) -> bool:
    """Determine if a failure should never be retried."""
    reason = result.split(":", 1)[-1] if ":" in result else result
    return (
        result in PERMANENT_FAILURES
        or reason in PERMANENT_FAILURES
        or any(reason.startswith(p) for p in PERMANENT_PREFIXES)
    )


# ---------------------------------------------------------------------------
# Worker loop
# ---------------------------------------------------------------------------

def worker_loop(worker_id: int = 0, limit: int = 1,
                target_url: str | None = None,
                min_score: int = 7, headless: bool = False,
                model: str = "sonnet", dry_run: bool = False,
                success_quota: bool | None = None) -> tuple[int, int]:
    """Run jobs sequentially until limit is reached or queue is empty.

    Args:
        worker_id: Numeric worker identifier.
        limit: Max jobs to process (0 = continuous). When ``success_quota``
            is True, ``limit`` is max successful applies instead of attempts.
        target_url: Apply to a specific URL.
        min_score: Minimum fit_score threshold.
        headless: Run Chrome headless.
        model: Cursor agent model name.
        dry_run: Don't click Submit.
        success_quota: Count only successful applies toward ``limit``.
            Defaults from env ``APPLY_SUCCESS_QUOTA`` (1/true).

    Returns:
        Tuple of (applied_count, failed_count).
    """
    applied = 0
    failed = 0
    continuous = limit == 0
    attempts = 0
    empty_polls = 0
    port = BASE_CDP_PORT + worker_id
    if success_quota is None:
        success_quota = os.environ.get("APPLY_SUCCESS_QUOTA", "").strip().lower() in (
            "1", "true", "yes",
        )

    while not _stop_event.is_set():
        if not continuous:
            if success_quota:
                if applied >= limit:
                    break
            elif attempts >= limit:
                break

        update_state(worker_id, status="idle", job_title="", company="",
                     last_action="waiting for job", actions=0)

        job = acquire_job(target_url=target_url, min_score=min_score,
                          worker_id=worker_id)
        if not job:
            if not continuous:
                add_event(f"[W{worker_id}] Queue empty")
                update_state(worker_id, status="done", last_action="queue empty")
                break
            empty_polls += 1
            update_state(worker_id, status="idle",
                         last_action=f"polling ({empty_polls})")
            if empty_polls == 1:
                add_event(f"[W{worker_id}] Queue empty, polling every {POLL_INTERVAL}s...")
            # Use Event.wait for interruptible sleep
            if _stop_event.wait(timeout=POLL_INTERVAL):
                break  # Stop was requested during wait
            continue

        empty_polls = 0

        chrome_proc = None
        try:
            add_event(f"[W{worker_id}] Launching Chrome...")
            chrome_proc = launch_chrome(worker_id, port=port, headless=headless)

            result, duration_ms = run_job(job, port=port, worker_id=worker_id,
                                            model=model, dry_run=dry_run)

            if result == "skipped":
                release_lock(job["url"])
                add_event(f"[W{worker_id}] Skipped: {job['title'][:30]}")
                continue
            elif result == "applied":
                if dry_run:
                    # Dry-run agents report RESULT:APPLIED without submitting;
                    # keep the job eligible for a real apply later.
                    release_lock(job["url"])
                    applied += 1
                    add_event(
                        f"[W{worker_id}] DRY-RUN OK ({duration_ms // 1000}s): "
                        f"{job['title'][:30]}"
                    )
                    update_state(worker_id, jobs_applied=applied,
                                 jobs_done=applied + failed,
                                 last_action="dry-run ok")
                else:
                    mark_result(job["url"], "applied", duration_ms=duration_ms)
                    applied += 1
                    update_state(worker_id, jobs_applied=applied,
                                 jobs_done=applied + failed)
            else:
                reason = result.split(":", 1)[-1] if ":" in result else result
                mark_result(job["url"], "failed", reason,
                            permanent=_is_permanent_failure(result),
                            duration_ms=duration_ms)
                failed += 1
                update_state(worker_id, jobs_failed=failed,
                             jobs_done=applied + failed)

        except KeyboardInterrupt:
            release_lock(job["url"])
            if _stop_event.is_set():
                break
            add_event(f"[W{worker_id}] Job skipped (Ctrl+C)")
            continue
        except Exception as e:
            logger.exception("Worker %d launcher error", worker_id)
            add_event(f"[W{worker_id}] Launcher error: {str(e)[:40]}")
            release_lock(job["url"])
            failed += 1
            update_state(worker_id, jobs_failed=failed)
        finally:
            if chrome_proc:
                cleanup_worker(worker_id, chrome_proc)

        attempts += 1
        if target_url:
            break

    update_state(worker_id, status="done", last_action="finished")
    return applied, failed


# ---------------------------------------------------------------------------
# Main entry point (called from cli.py)
# ---------------------------------------------------------------------------

def main(limit: int = 1, target_url: str | None = None,
         min_score: int = 7, headless: bool = False, model: str = "sonnet",
         dry_run: bool = False, continuous: bool = False,
         poll_interval: int = 60, workers: int = 1) -> None:
    """Launch the apply pipeline.

    Args:
        limit: Max jobs to apply to (0 or with continuous=True means run forever).
        target_url: Apply to a specific URL.
        min_score: Minimum fit_score threshold.
        headless: Run Chrome in headless mode.
        model: Cursor agent model name.
        dry_run: Don't click Submit.
        continuous: Run forever, polling for new jobs.
        poll_interval: Seconds between DB polls when queue is empty.
        workers: Number of parallel workers (default 1).
    """
    global POLL_INTERVAL
    POLL_INTERVAL = poll_interval
    _stop_event.clear()

    config.ensure_dirs()
    console = Console()

    if continuous:
        effective_limit = 0
        mode_label = "continuous"
    else:
        effective_limit = limit
        mode_label = f"{limit} jobs"

    # Initialize dashboard for all workers
    for i in range(workers):
        init_worker(i)

    worker_label = f"{workers} worker{'s' if workers > 1 else ''}"
    console.print(f"Launching apply pipeline ({mode_label}, {worker_label}, poll every {POLL_INTERVAL}s)...")
    console.print("[dim]Ctrl+C = skip current job(s) | Ctrl+C x2 = stop[/dim]")

    # Double Ctrl+C handler
    _ctrl_c_count = 0

    def _sigint_handler(sig, frame):
        nonlocal _ctrl_c_count
        _ctrl_c_count += 1
        if _ctrl_c_count == 1:
            console.print("\n[yellow]Skipping current job(s)... (Ctrl+C again to STOP)[/yellow]")
            from applypilot.apply.cursor_apply import cancel_all_active_runs
            cancel_all_active_runs()
        else:
            console.print("\n[red bold]STOPPING[/red bold]")
            _stop_event.set()
            from applypilot.apply.cursor_apply import cancel_all_active_runs
            cancel_all_active_runs()
            kill_all_chrome()
            raise KeyboardInterrupt

    signal.signal(signal.SIGINT, _sigint_handler)

    try:
        with Live(render_full(), console=console, refresh_per_second=2) as live:
            # Daemon thread for display refresh only (no business logic)
            _dashboard_running = True

            def _refresh():
                while _dashboard_running:
                    live.update(render_full())
                    time.sleep(0.5)

            refresh_thread = threading.Thread(target=_refresh, daemon=True)
            refresh_thread.start()

            if workers == 1:
                # Single worker — run directly in main thread
                total_applied, total_failed = worker_loop(
                    worker_id=0,
                    limit=effective_limit,
                    target_url=target_url,
                    min_score=min_score,
                    headless=headless,
                    model=model,
                    dry_run=dry_run,
                )
            else:
                # Multi-worker — distribute limit across workers
                if effective_limit:
                    base = effective_limit // workers
                    extra = effective_limit % workers
                    limits = [base + (1 if i < extra else 0)
                              for i in range(workers)]
                else:
                    limits = [0] * workers  # continuous mode

                with ThreadPoolExecutor(max_workers=workers,
                                        thread_name_prefix="apply-worker") as executor:
                    futures = {
                        executor.submit(
                            worker_loop,
                            worker_id=i,
                            limit=limits[i],
                            target_url=target_url,
                            min_score=min_score,
                            headless=headless,
                            model=model,
                            dry_run=dry_run,
                        ): i
                        for i in range(workers)
                    }

                    results: list[tuple[int, int]] = []
                    for future in as_completed(futures):
                        wid = futures[future]
                        try:
                            results.append(future.result())
                        except Exception:
                            logger.exception("Worker %d crashed", wid)
                            results.append((0, 0))

                total_applied = sum(r[0] for r in results)
                total_failed = sum(r[1] for r in results)

            _dashboard_running = False
            refresh_thread.join(timeout=2)
            live.update(render_full())

        totals = get_totals()
        console.print(
            f"\n[bold]Done: {total_applied} applied, {total_failed} failed "
            f"(${totals['cost']:.3f})[/bold]"
        )
        console.print(f"Logs: {config.LOG_DIR}")

    except KeyboardInterrupt:
        pass
    finally:
        _stop_event.set()
        kill_all_chrome()
