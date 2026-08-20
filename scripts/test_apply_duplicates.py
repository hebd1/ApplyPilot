#!/usr/bin/env python3
"""Unit checks for company persist + duplicate-apply skip (no network)."""
from __future__ import annotations

import sqlite3

from applypilot.job_meta import already_applied_same_role, persist_missing_company


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE jobs (url TEXT PRIMARY KEY, title TEXT, company TEXT, "
        "site TEXT, application_url TEXT, apply_status TEXT)"
    )
    return conn


def main() -> None:
    conn = _conn()
    conn.execute(
        "INSERT INTO jobs VALUES (?,?,?,?,?,?)",
        (
            "https://indeed.com/viewjob?jk=aaa",
            "Senior Software Engineer",
            "Mozilla Corporation",
            "indeed",
            "https://boards.greenhouse.io/mozilla/jobs/1",
            "applied",
        ),
    )
    dup = {
        "url": "https://indeed.com/viewjob?jk=bbb",
        "title": "Senior Software Engineer",
        "company": "Mozilla Corporation",
        "site": "indeed",
        "application_url": "https://boards.greenhouse.io/mozilla/jobs/2",
    }
    assert already_applied_same_role(conn, dup)

    other = {
        "url": "https://indeed.com/viewjob?jk=ccc",
        "title": "Senior Backend Platform Engineer",
        "company": None,
        "site": "NVIDIA",
        "application_url": "https://nvidia.wd5.myworkdayjobs.com/x/job/1",
    }
    assert not already_applied_same_role(conn, other)

    conn.execute(
        "INSERT INTO jobs VALUES (?,?,?,?,?,?)",
        (other["url"], other["title"], None, other["site"], other["application_url"], None),
    )
    persist_missing_company(conn, other)
    stored = conn.execute("SELECT company FROM jobs WHERE url=?", (other["url"],)).fetchone()
    assert stored["company"] == "NVIDIA", stored["company"]
    print("test_apply_duplicates: ok")


if __name__ == "__main__":
    main()
