#!/usr/bin/env python3
"""Purge apply/tailor queue: exclude cloud/devops titles + mark weak apply URLs."""
from __future__ import annotations

from applypilot.config import title_is_excluded
from applypilot.database import get_connection
from applypilot.job_meta import job_has_usable_apply_url


def main() -> None:
    conn = get_connection()

    # Demote excluded titles (cloud engineer / devops / etc.)
    excluded = 0
    rows = conn.execute(
        "SELECT url, title, fit_score FROM jobs WHERE fit_score IS NULL OR fit_score >= 5"
    ).fetchall()
    for row in rows:
        if title_is_excluded(row["title"]):
            conn.execute(
                "UPDATE jobs SET fit_score = 1, score_reasoning = ? WHERE url = ?",
                (
                    "Excluded by searches.yaml exclude_titles (title matched a negative keyword).",
                    row["url"],
                ),
            )
            excluded += 1

    # Clear stuck in_progress claims (killed workers / interrupted daily runs)
    stuck = conn.execute(
        """
        UPDATE jobs SET apply_status = NULL, agent_id = NULL
        WHERE apply_status = 'in_progress'
          AND (
            last_attempted_at IS NULL
            OR datetime(last_attempted_at) < datetime('now', '-2 hours')
          )
        """
    ).rowcount

    # Mark tailored jobs that Stage 6 cannot actually apply to
    weak = 0
    tailored = conn.execute(
        """
        SELECT url, title, application_url, apply_status FROM jobs
        WHERE tailored_resume_path IS NOT NULL
          AND applied_at IS NULL
          AND (
            apply_status IS NULL OR apply_status = ''
            OR apply_status = 'in_progress'
            OR (apply_status = 'failed' AND IFNULL(apply_error, '') NOT LIKE 'weak_apply_url:%')
          )
        """
    ).fetchall()
    for row in tailored:
        ok, reason = job_has_usable_apply_url(dict(row))
        if ok:
            continue
        conn.execute(
            """
            UPDATE jobs SET apply_status = 'failed', apply_error = ?,
                   apply_attempts = 99, agent_id = NULL
            WHERE url = ?
            """,
            (f"weak_apply_url:{reason}", row["url"]),
        )
        weak += 1

    # Lightweight expiry check — probe tailored jobs for HTTP 404/410/451.
    expired = 0
    to_check = conn.execute(
        """
        SELECT url, application_url, apply_status FROM jobs
        WHERE tailored_resume_path IS NOT NULL
          AND applied_at IS NULL
          AND (apply_status IS NULL OR apply_status = '' OR apply_status = 'failed')
          AND apply_attempts < 3
          AND application_url LIKE 'http%'
          AND LOWER(application_url) NOT LIKE '%linkedin.com%'
          AND LOWER(application_url) NOT LIKE '%indeed.com%'
          AND LOWER(application_url) NOT LIKE '%ziprecruiter%'
          AND LOWER(application_url) NOT LIKE '%glassdoor.com%'
        """
    ).fetchall()
    if to_check:
        import httpx
        with httpx.Client(timeout=5.0) as hclient:
            for row in to_check:
                app_url = row["application_url"]
                try:
                    hresp = hclient.get(
                        app_url,
                        follow_redirects=False,
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    if hresp.status_code in (404, 410, 451):
                        conn.execute(
                            "UPDATE jobs SET apply_status = 'failed', apply_error = ?, "
                            "apply_attempts = 99 WHERE url = ?",
                            ("expired", row["url"]),
                        )
                        expired += 1
                except (httpx.ConnectTimeout, httpx.ReadTimeout):
                    pass
                except Exception:
                    pass
        conn.commit()

    conn.commit()

    ready = conn.execute(
        """
        SELECT COUNT(*) FROM jobs
        WHERE fit_score >= 7
          AND tailored_resume_path IS NOT NULL
          AND applied_at IS NULL
          AND (apply_status IS NULL OR apply_status = '' OR apply_status = 'failed')
          AND (apply_attempts IS NULL OR apply_attempts < 3)
          AND application_url IS NOT NULL AND application_url LIKE 'http%'
          AND LOWER(application_url) NOT LIKE '%linkedin.com%'
          AND LOWER(application_url) NOT LIKE '%indeed.com%'
        """
    ).fetchone()[0]

    print(f"demoted_excluded_titles={excluded}")
    print(f"cleared_stuck_in_progress={stuck}")
    print(f"marked_weak_apply_url={weak}")
    print(f"marked_expired={expired}")
    print(f"approx_apply_ready_remaining={ready}")


if __name__ == "__main__":
    main()
