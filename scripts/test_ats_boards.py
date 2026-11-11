#!/usr/bin/env python3
"""Direct ATS board discovery (Greenhouse / Ashby / Lever public APIs): parsing, filters, storage."""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from applypilot.database import close_connection, init_db
from applypilot.discovery import ats_boards as ab

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
FRESH = (NOW - timedelta(days=1)).isoformat()
STALE = (NOW - timedelta(days=30)).isoformat()


def main() -> None:
    # Titles: software/backend/platform engineering roles in; everything else out.
    for t in ("Backend Engineer", "Senior Software Engineer, Identity", "Software Engineer II (Go)",
              "Staff Platform Engineer", "Full Stack Engineer", "Golang Developer", "API Engineer"):
        assert ab.title_ok(t), t
    for t in ("Engineering Manager", "Director of Engineering", "iOS Engineer", "Android Developer",
              "Machine Learning Engineer", "Solutions Engineer", "Recruiter", "Data Scientist",
              "Product Designer", "Software Engineering Intern", "Sales Engineer", "Frontend Engineer"):
        assert not ab.title_ok(t), t

    # Location: US remote or Eli's accepted places; word-boundary country matching.
    accept = ["Remote", "United States", "USA", "US", "Idaho", "Utah", "Boise"]
    for loc, want in {
        "Remote - US": True, "Remote (United States)": True, "US Remote": True, "Remote": True,
        "Remote, Americas": True, "Remote - US or Canada": True, "Boise, ID": True, "Salt Lake City, Utah": True,
        "Remote - UK": False, "Remote, India": False, "Remote (EMEA)": False, "London": False,
        "San Francisco, CA": False, "Sydney, Australia": False, "Remote - Canada": False, "": True,
    }.items():
        assert ab.location_ok(loc, accept) is want, (loc, want)

    # Parsers: one job per ATS shape.
    gh = ab.parse_greenhouse("acme", "Acme", {"jobs": [{
        "title": "Backend Engineer", "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/1",
        "location": {"name": "Remote - US"}, "updated_at": FRESH, "first_published": FRESH,
        "content": "&lt;p&gt;Build Go services &amp;amp; APIs&lt;/p&gt;"}]})
    assert gh[0]["application_url"] == "https://job-boards.greenhouse.io/acme/jobs/1"
    assert gh[0]["full_description"] == "Build Go services & APIs", gh[0]["full_description"]
    assert gh[0]["company"] == "Acme" and gh[0]["site"] == "Greenhouse"

    ash = ab.parse_ashby("acme", "Acme", {"jobs": [{
        "title": "Software Engineer", "jobUrl": "https://jobs.ashbyhq.com/acme/1",
        "applyUrl": "https://jobs.ashbyhq.com/acme/1/application", "location": "Remote", "isRemote": True,
        "publishedAt": FRESH, "descriptionPlain": "Go and Postgres",
        "compensation": {"compensationTierSummary": "$150K – $190K"}}]})
    assert ash[0]["url"] == "https://jobs.ashbyhq.com/acme/1"
    assert ash[0]["application_url"] == "https://jobs.ashbyhq.com/acme/1/application"
    assert ash[0]["salary"] == "$150K – $190K"

    lev = ab.parse_lever("acme", "Acme", [{
        "text": "Platform Engineer", "hostedUrl": "https://jobs.lever.co/acme/1",
        "applyUrl": "https://jobs.lever.co/acme/1/apply", "categories": {"location": "Boise, ID"},
        "createdAt": int((NOW - timedelta(days=2)).timestamp() * 1000),
        "descriptionPlain": "Intro", "lists": [{"text": "You will", "content": "<li>Build APIs</li>"}],
        "salaryRange": {"min": 140000, "max": 170000, "currency": "USD"}}])
    assert lev[0]["application_url"] == "https://jobs.lever.co/acme/1/apply"
    assert "Build APIs" in lev[0]["full_description"]
    assert lev[0]["salary"] == "$140,000 – $170,000 USD"

    # Freshness + filters together.
    jobs = gh + ash + lev + ab.parse_greenhouse("acme", "Acme", {"jobs": [
        {"title": "Backend Engineer", "absolute_url": "https://x/old", "location": {"name": "Remote"},
         "updated_at": STALE, "content": ""},
        {"title": "Engineering Manager", "absolute_url": "https://x/mgr", "location": {"name": "Remote"},
         "updated_at": FRESH, "content": ""},
        {"title": "Backend Engineer", "absolute_url": "https://x/uk", "location": {"name": "London, UK"},
         "updated_at": FRESH, "content": ""}]})
    kept = ab.select_jobs(jobs, max_age_days=3, accept=accept, now=NOW)
    assert [j["url"] for j in kept] == [
        "https://job-boards.greenhouse.io/acme/jobs/1", "https://jobs.ashbyhq.com/acme/1",
        "https://jobs.lever.co/acme/1"], [j["url"] for j in kept]

    # Storage: enriched and apply-ready on insert; idempotent.
    with tempfile.TemporaryDirectory() as d:
        db = Path(d) / "t.db"
        conn = init_db(db)
        assert ab.store(conn, kept) == (3, 0)
        assert ab.store(conn, kept) == (0, 3)
        row = conn.execute("SELECT * FROM jobs WHERE url = ?", (kept[0]["url"],)).fetchone()
        assert row["application_url"] == kept[0]["application_url"]
        assert row["full_description"] and row["detail_scraped_at"] and row["company"] == "Acme"
        assert row["strategy"] == "ats_api" and row["fit_score"] is None
        close_connection(db)

    # The shipped board list loads and every entry names a known ATS.
    boards = ab.load_boards()
    assert len(boards) >= 80, len(boards)
    assert all(b["ats"] in ab.FETCHERS for b in boards)

    print("test_ats_boards: ok")


if __name__ == "__main__":
    main()
