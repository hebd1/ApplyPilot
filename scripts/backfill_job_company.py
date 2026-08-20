#!/usr/bin/env python3
"""Backfill jobs.company from JobSpy-style URL inference + clear weak apply URLs.

Usage (WSL):
  .venv/bin/python scripts/backfill_job_company.py
  .venv/bin/python scripts/backfill_job_company.py --mark-weak
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from applypilot.database import ensure_columns, get_connection
from applypilot.job_meta import classify_apply_url, display_company


def backfill_companies(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        "SELECT url, site, company, application_url FROM jobs"
    ).fetchall()
    updated = 0
    for url, site, company, app_url in rows:
        if company and str(company).strip():
            continue
        inferred = display_company(
            {"url": url, "site": site, "company": company, "application_url": app_url}
        )
        if inferred and inferred.lower() != "unknown":
            conn.execute("UPDATE jobs SET company = ? WHERE url = ?", (inferred, url))
            updated += 1
    conn.commit()
    return updated


def mark_weak_urls(conn: sqlite3.Connection) -> int:
    rows = conn.execute(
        """
        SELECT url, application_url, apply_status, applied_at
        FROM jobs
        WHERE applied_at IS NULL
          AND (apply_status IS NULL OR apply_status IN ('failed', 'manual'))
        """
    ).fetchall()
    marked = 0
    for url, app_url, status, _applied in rows:
        ok, reason = classify_apply_url(app_url)
        if ok:
            continue
        # Don't overwrite manual ATS tags.
        if status == "manual":
            continue
        conn.execute(
            "UPDATE jobs SET apply_status = 'failed', apply_error = ?, apply_attempts = 99 "
            "WHERE url = ?",
            (f"weak_apply_url:{reason}", url),
        )
        marked += 1
    conn.commit()
    return marked


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mark-weak",
        action="store_true",
        help="Permanently fail jobs with relative/aggregator/board-only application_url",
    )
    args = parser.parse_args()

    # Ensure company column exists
    conn = get_connection()
    added = ensure_columns(conn)
    if added:
        print(f"Migrated columns: {added}")
    n = backfill_companies(conn)
    print(f"Backfilled company on {n} jobs")
    # Un-mash URL slugs when site is the same employer with nicer spacing/case.
    fixed = conn.execute(
        """
        UPDATE jobs SET company = site
        WHERE company IS NOT NULL AND site IS NOT NULL
          AND company != site
          AND LOWER(REPLACE(company, ' ', '')) = LOWER(REPLACE(site, ' ', ''))
          AND LOWER(site) NOT IN (
            'indeed','linkedin','talent.com','ziprecruiter','glassdoor',
            'simplyhired','dice','google'
          )
        """
    ).rowcount
    conn.commit()
    print(f"Normalized mashed company slugs to site label: {fixed}")

    sample = conn.execute(
        "SELECT title, site, company, application_url FROM jobs "
        "WHERE company IS NOT NULL AND company != '' LIMIT 8"
    ).fetchall()
    print("Sample companies:")
    for title, site, company, app in sample:
        print(f"  [{site}] {company}: {title[:40]} -> {(app or '')[:60]}")

    if args.mark_weak:
        m = mark_weak_urls(conn)
        print(f"Marked {m} jobs as weak_apply_url")

    # Sanity check display_company
    row = conn.execute(
        "SELECT title, site, company, application_url, url FROM jobs "
        "WHERE application_url LIKE '%upstart%' LIMIT 1"
    ).fetchone()
    if row:
        job = {
            "title": row[0], "site": row[1], "company": row[2],
            "application_url": row[3], "url": row[4],
        }
        print("Upstart display_company:", display_company(job))


if __name__ == "__main__":
    main()
