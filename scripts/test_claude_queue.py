#!/usr/bin/env python3
"""Claude in Chrome routine queue: picking, export, result marking (temp DB, no network)."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from applypilot import config
from applypilot.apply import claude_queue as cq
from applypilot.database import close_connection, get_connection, init_db


def _job(tmp: Path, url: str, apply_url: str, *, title="Senior Backend Engineer", company="Acme",
         score=9, status=None, error=None, attempts=0, resume=True, applied_at=None) -> tuple:
    pdf = tmp / f"{abs(hash(url))}.pdf"
    if resume:
        pdf.write_bytes(b"%PDF-1.4 test")
    return (url, title, "greenhouse", company, apply_url, str(pdf), score, "Remote",
            "Build APIs in Go.", status, error, attempts, applied_at, "2026-10-25T00:00:00")


def _any_host_mode() -> None:
    """Company career pages are picked after named ATSs; account-gated hosts never."""
    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        db = tmp / "any.db"
        conn = init_db(db)
        conn.executemany(
            "INSERT INTO jobs (url, title, site, company, application_url, tailored_resume_path, "
            "fit_score, location, full_description, apply_status, apply_error, apply_attempts, "
            "applied_at, discovered_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [
                _job(tmp, "custom-moove", "https://careers.moove.io/jobs/1", company="Moove", score=9),
                _job(tmp, "gh-iota", "https://boards.greenhouse.io/iota/jobs/1", company="Iota", score=9),
                _job(tmp, "icims-kappa", "https://careers-kappa.icims.com/jobs/1", company="Kappa", score=10),
                _job(tmp, "wds-lambda", "https://wd1.myworkdaysite.com/recruiting/l/1", company="Lambda", score=10),
            ],
        )
        conn.commit()
        picked = cq.pick_batch(3, 8, check_expiry=False, conn=conn)
        assert [j["url"] for j in picked] == ["gh-iota", "custom-moove"], [j["url"] for j in picked]
        picked = cq.pick_batch(3, 8, include_workday=True, check_expiry=False, conn=conn)
        assert [j["url"] for j in picked] == ["wds-lambda"], [j["url"] for j in picked]
        close_connection(db)


def main() -> None:
    sql, params = cq.build_candidate_query(8, ["greenhouse.io", "lever.co"], 3)
    assert sql.count("?") == len(params), (sql.count("?"), len(params))
    sql, params = cq.build_candidate_query(8, ["greenhouse.io"], 3, deny_hosts=["icims.com", "taleo.net"])
    assert sql.count("?") == len(params), (sql.count("?"), len(params))
    _any_host_mode()

    with tempfile.TemporaryDirectory() as d:
        tmp = Path(d)
        db = tmp / "t.db"
        conn = init_db(db)
        rows = [
            _job(tmp, "gh-acme", "https://boards.greenhouse.io/acme/jobs/1"),
            _job(tmp, "gh-acme-2", "https://boards.greenhouse.io/acme/jobs/2"),          # same employer
            _job(tmp, "lever-beta", "https://jobs.lever.co/beta/1", company="Beta", score=8,
                 status="failed", error="skip_ats:lever.co", attempts=99),               # reopened
            _job(tmp, "wd-gamma", "https://gamma.wd5.myworkdayjobs.com/x/job/1",
                 company="Gamma", score=10),                                              # account-gated
            _job(tmp, "gh-junior", "https://boards.greenhouse.io/delta/jobs/1",
                 title="Junior Backend Engineer", company="Delta"),                       # excluded title
            _job(tmp, "ashby-low", "https://jobs.ashbyhq.com/eps/1", company="Eps", score=7),  # below min
            _job(tmp, "gh-expired", "https://boards.greenhouse.io/zeta/jobs/1", company="Zeta",
                 status="failed", error="expired", attempts=99),                          # final
            _job(tmp, "gh-noresume", "https://boards.greenhouse.io/eta/jobs/1", company="Eta",
                 resume=False),                                                           # no PDF
            _job(tmp, "gh-applied", "https://boards.greenhouse.io/theta/jobs/1", company="Theta",
                 status="applied", applied_at="2026-10-01"),
        ]
        conn.executemany(
            "INSERT INTO jobs (url, title, site, company, application_url, tailored_resume_path, "
            "fit_score, location, full_description, apply_status, apply_error, apply_attempts, "
            "applied_at, discovered_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            rows,
        )
        conn.commit()

        picked = cq.pick_batch(3, 8, check_expiry=False, conn=conn)
        assert [j["url"] for j in picked] == ["gh-acme", "lever-beta"], [j["url"] for j in picked]
        status = {r["url"]: (r["apply_status"], r["apply_error"]) for r in
                  conn.execute("SELECT url, apply_status, apply_error FROM jobs")}
        assert status["gh-acme"][0] == cq.STATUS_QUEUED
        assert status["gh-junior"] == ("failed", "excluded_title"), status["gh-junior"]
        assert status["wd-gamma"][0] is None, "workday left alone without --include-workday"
        assert status["gh-acme-2"][0] is None, "second job at same employer stays in the queue"

        # Picked jobs are not picked again; Workday comes in only on request.
        again = cq.pick_batch(3, 8, include_workday=True, check_expiry=False, conn=conn)
        assert [j["url"] for j in again] == ["wd-gamma", "gh-acme-2"], [j["url"] for j in again]

        # Export: PDFs copied under <root>/<day>/<n>-<company>/ with queue.json.
        assert "keyword_coverage" in picked[0]
        picked[0]["keyword_coverage"] = '{"score": 0.9, "missing_gap": ["Rust"]}'
        saved_dir = config.CLAUDE_DIR
        config.CLAUDE_DIR = tmp / "claude"
        try:
            payload = cq.export_batch(picked, tmp / "export", day="2026-10-26")
            assert payload["jobs"][0]["keyword_coverage"] == {"score": 0.9, "missing_gap": ["Rust"]}
            assert payload["jobs"][1]["keyword_coverage"] is None
        finally:
            config.CLAUDE_DIR = saved_dir
        day_dir = tmp / "export" / "2026-10-26"
        assert json.loads((day_dir / "queue.json").read_text())["jobs"][0]["url"] == "gh-acme"
        assert (tmp / "claude" / "queue-2026-10-26.json").is_file()
        first = payload["jobs"][0]
        assert first["resume_pdf"].endswith("_Resume.pdf"), first["resume_pdf"]
        assert list((day_dir / "1-Acme").glob("*_Resume.pdf")), list(day_dir.iterdir())
        assert "password" not in payload["applicant"].lower()

        # profile.json screening_answers reach the routine's applicant block.
        saved_profile = config.load_profile
        config.load_profile = lambda: {**saved_profile(), "screening_answers": {
            "Willing to travel occasionally": "Yes"}}
        config.CLAUDE_DIR = tmp / "claude"
        try:
            payload = cq.export_batch([], tmp / "export", day="2026-10-27", conn=conn)
        finally:
            config.load_profile = saved_profile
            config.CLAUDE_DIR = saved_dir
        assert "Willing to travel occasionally: Yes" in payload["applicant"], payload["applicant"]

        # A second queue run the same day appends instead of overwriting.
        config.CLAUDE_DIR = tmp / "claude"
        try:
            payload = cq.export_batch(again, tmp / "export", day="2026-10-26")
        finally:
            config.CLAUDE_DIR = saved_dir
        assert [j["url"] for j in payload["jobs"]] == ["gh-acme", "lever-beta", "wd-gamma", "gh-acme-2"]
        assert [j["rank"] for j in payload["jobs"]] == [1, 2, 3, 4]
        assert json.loads((day_dir / "queue.json").read_text())["jobs"][3]["url"] == "gh-acme-2"
        assert (day_dir / "1-Acme").is_dir() and (day_dir / "4-Acme").is_dir()

        assert cq.to_windows_path(Path("/mnt/c/Users/elihe/ApplyPilot/q")) == r"C:\Users\elihe\ApplyPilot\q"

        # Results from the routine.
        assert cq.mark("https://boards.greenhouse.io/acme/jobs/1", "filled", note="ready", conn=conn) == 1
        waiting = cq.pending(conn=conn)
        assert [r["url"] for r in waiting] == ["gh-acme"], waiting
        assert cq.mark("lever-beta", "needs_eli", note="captcha", conn=conn) == 1
        assert {r["url"] for r in cq.pending(conn=conn)} == {"gh-acme", "lever-beta"}
        assert cq.mark("gh-acme", "applied", evidence="shot.png", conn=conn) == 1
        row = conn.execute("SELECT apply_status, applied_at, apply_evidence FROM jobs WHERE url='gh-acme'").fetchone()
        assert row["apply_status"] == "applied" and row["applied_at"] and row["apply_evidence"] == "shot.png"
        assert cq.mark("nope", "applied", conn=conn) == 0
        try:
            cq.mark("gh-acme", "submitted", conn=conn)
            raise AssertionError("bad status accepted")
        except ValueError:
            pass

        # A later same-day export drops jobs already closed out (applied/failed),
        # keeps the rest, and numbers new jobs after the highest rank.
        config.CLAUDE_DIR = tmp / "claude"
        try:
            payload = cq.export_batch([], tmp / "export", day="2026-10-26", conn=conn)
        finally:
            config.CLAUDE_DIR = saved_dir
        assert [j["url"] for j in payload["jobs"]] == ["lever-beta", "wd-gamma", "gh-acme-2"], payload["jobs"]
        assert [j["rank"] for j in payload["jobs"]] == [2, 3, 4]

        # Stale handling: interrupted picks come back; unapproved fills expire.
        cq.mark("wd-gamma", "filled", conn=conn)
        conn.execute("UPDATE jobs SET last_attempted_at = '2026-01-01T00:00:00' "
                     "WHERE url IN ('wd-gamma', 'gh-acme-2')")
        conn.commit()
        assert cq.release_stale(conn) == {"released_queued": 1, "expired_filled": 1}
        status = {r["url"]: (r["apply_status"], r["apply_error"]) for r in
                  conn.execute("SELECT url, apply_status, apply_error FROM jobs")}
        assert status["gh-acme-2"][0] is None
        assert status["wd-gamma"] == (cq.STATUS_DECLINED, "not_approved"), status["wd-gamma"]
        close_connection(db)

    print("test_claude_queue: ok")


if __name__ == "__main__":
    main()
