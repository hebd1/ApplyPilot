#!/usr/bin/env python3
"""Guard Stage 6 queue SQL: ATS host binds must not collide with blocked-site params."""
from __future__ import annotations

import sqlite3

from applypilot.apply.launcher import build_apply_queue_query
from applypilot.config import load_blocked_sites, load_preferred_ats_hosts


def _memory_jobs() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE jobs (
            url TEXT PRIMARY KEY,
            title TEXT,
            site TEXT,
            company TEXT,
            application_url TEXT,
            tailored_resume_path TEXT,
            fit_score INTEGER,
            location TEXT,
            full_description TEXT,
            cover_letter_path TEXT,
            apply_status TEXT,
            apply_attempts INTEGER
        )
        """
    )
    conn.execute(
        """
        INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            "https://workday.wd5.myworkdayjobs.com/Workday/job/US/SDE_JR1",
            "Software Development Engineer (US Federal)",
            "Workday",
            "Workday",
            "https://workday.wd5.myworkdayjobs.com/Workday/job/US/SDE_JR1",
            "/tmp/resume.pdf",
            9,
            "Reston, VA",
            "desc",
            "/tmp/cover.pdf",
            None,
            0,
        ),
    )
    return conn


def main() -> None:
    sql, params = build_apply_queue_query(8, ats_only=True)
    assert sql.count("?") == len(params), (sql.count("?"), len(params), params)

    hosts = load_preferred_ats_hosts() or ["greenhouse.io", "grnh.se", "myworkdayjobs.com"]
    blocked_sites, blocked_patterns = load_blocked_sites()
    ats_params = [f"%{h}%" for h in hosts]
    # ATS likes must occupy the slots immediately after max_attempts + min_score.
    assert params[0] == 3
    assert params[1] == 8
    assert params[2:2 + len(ats_params)] == ats_params, params
    # Blocked site names must not appear in those ATS slots (the 2026-08-21 bug).
    assert not (set(params[2:2 + len(ats_params)]) & set(blocked_sites)), params

    conn = _memory_jobs()
    row = conn.execute(sql, params).fetchone()
    assert row is not None, "ATS Workday job must match correctly bound queue SQL"
    assert "myworkdayjobs.com" in (row["application_url"] or "")

    # Wrong bind order (blocked names into LIKE slots) must find nothing.
    wrong = [3, 8]
    wrong.extend(blocked_sites)
    for pattern in blocked_patterns:
        wrong.extend([pattern, pattern])
    wrong.extend(ats_params)
    if len(wrong) == len(params):
        assert conn.execute(sql, wrong).fetchone() is None

    print("test_apply_queue: ok")


if __name__ == "__main__":
    main()
