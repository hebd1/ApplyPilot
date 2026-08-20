#!/usr/bin/env python3
"""Poll Gmail (readonly) for application confirmations / rejections / interviews.

Uses ~/.gmail-mcp/credentials.json + gcp-oauth.keys.json (same tokens as Stage 6 OTP).
Never sends, modifies, deletes, or changes Gmail settings.

Usage (WSL):
  .venv/bin/python scripts/poll_application_emails.py
  .venv/bin/python scripts/poll_application_emails.py --days 21 --dry-run
"""
from __future__ import annotations

import argparse
import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

from applypilot.database import get_connection, init_db
from applypilot.job_meta import display_company

GMAIL_DIR = Path.home() / ".gmail-mcp"
CREDS_PATH = GMAIL_DIR / "credentials.json"
KEYS_PATH = GMAIL_DIR / "gcp-oauth.keys.json"

OUTCOME_PRIORITY = {
    "offer": 5,
    "interview": 4,
    "rejected": 3,
    "confirmed": 2,
    "unknown": 1,
}

INTERVIEW_RE = re.compile(
    r"\b(interview|phone screen|phone-screen|schedule (an )?interview|"
    r"invite(d)? you to interview|onsite interview|on-site interview)\b",
    re.I,
)
REJECT_RE = re.compile(
    r"\b(unfortunately|not moving forward|not selected|other candidates|"
    r"will not be progressing|no longer under consideration|decided not to)\b",
    re.I,
)
CONFIRM_RE = re.compile(
    r"\b(thank you for (your )?apply|application (has been )?received|"
    r"we received your application|application was submitted|"
    r"thanks for applying|we('ve| have) got your application)\b",
    re.I,
)
OFFER_RE = re.compile(r"\b(offer of employment|job offer|pleased to offer)\b", re.I)

ATS_HINTS = (
    "greenhouse", "myworkday", "workday", "ashbyhq", "lever.co", "smartrecruiters",
    "icims", "jobvite", "bamboohr", "successfactors", "taleo", "rippling",
)

# ATS product / board labels are not employers. Matching them in From:
# (e.g. noreply@myworkday.com) against site=Workday jobs caused false outcomes.
_GENERIC_EMPLOYERS = frozenset({
    "workday", "greenhouse", "ashby", "lever", "icims", "jobvite",
    "smartrecruiters", "bamboohr", "taleo", "rippling", "successfactors",
    "indeed", "linkedin", "unknown", "talent.com", "ziprecruiter",
    "glassdoor", "simplyhired", "dice", "google",
})

OTP_RE = re.compile(
    r"\b(security code|verification code|one[- ]time (code|password)|otp)\b",
    re.I,
)


def _load_oauth_client() -> tuple[str, str, str]:
    keys = json.loads(KEYS_PATH.read_text(encoding="utf-8"))
    installed = keys.get("installed") or keys.get("web") or {}
    client_id = installed.get("client_id")
    client_secret = installed.get("client_secret")
    token_uri = installed.get("token_uri") or "https://oauth2.googleapis.com/token"
    if not client_id or not client_secret:
        raise SystemExit(f"Invalid OAuth client keys: {KEYS_PATH}")
    return client_id, client_secret, token_uri


def _load_token() -> dict:
    if not CREDS_PATH.is_file():
        raise SystemExit(
            f"Missing {CREDS_PATH}. Run: bash scripts/gmail_oauth_readonly.sh"
        )
    return json.loads(CREDS_PATH.read_text(encoding="utf-8"))


def _save_token(token: dict) -> None:
    CREDS_PATH.write_text(json.dumps(token, indent=2) + "\n", encoding="utf-8")


def _access_token(token: dict) -> str:
    """Return a usable access token, refreshing if needed."""
    access = token.get("access_token") or token.get("token")
    refresh = token.get("refresh_token")
    expiry = token.get("expiry_date") or token.get("expiry")
    needs_refresh = False
    if not access:
        needs_refresh = True
    elif expiry:
        try:
            # google-auth-library uses ms epoch; google.oauth2 uses ISO
            if isinstance(expiry, (int, float)):
                exp_dt = datetime.fromtimestamp(expiry / 1000.0, tz=timezone.utc)
            else:
                exp_dt = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
            if exp_dt <= datetime.now(timezone.utc) + timedelta(minutes=2):
                needs_refresh = True
        except Exception:
            needs_refresh = True

    if not needs_refresh:
        return str(access)

    if not refresh:
        raise SystemExit("Gmail token expired and no refresh_token — re-auth readonly")

    client_id, client_secret, token_uri = _load_oauth_client()
    body = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh,
            "grant_type": "refresh_token",
        }
    ).encode()
    req = urllib.request.Request(
        token_uri,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    token["access_token"] = data["access_token"]
    if "expires_in" in data:
        exp = datetime.now(timezone.utc) + timedelta(seconds=int(data["expires_in"]))
        token["expiry_date"] = int(exp.timestamp() * 1000)
    if data.get("refresh_token"):
        token["refresh_token"] = data["refresh_token"]
    _save_token(token)
    return str(token["access_token"])


def _gmail_get(path: str, token: dict, params: dict | None = None) -> dict:
    access = _access_token(token)
    qs = ""
    if params:
        qs = f"?{urllib.parse.urlencode(params, doseq=True)}"
    url = f"https://gmail.googleapis.com/gmail/v1/{path}{qs}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {access}"})
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        raise SystemExit(f"Gmail API HTTP {e.code}: {detail}") from e


def _header_map(payload: dict) -> dict[str, str]:
    headers = {}
    for h in payload.get("headers") or []:
        name = (h.get("name") or "").lower()
        if name:
            headers[name] = h.get("value") or ""
    return headers


def _snippet_and_subject(msg: dict) -> tuple[str, str, str]:
    payload = msg.get("payload") or {}
    headers = _header_map(payload)
    subject = headers.get("subject", "")
    from_addr = headers.get("from", "")
    snippet = msg.get("snippet") or ""
    return subject, from_addr, snippet


def classify_email(subject: str, snippet: str, from_addr: str) -> str:
    blob = f"{subject}\n{snippet}\n{from_addr}"
    if OTP_RE.search(blob):
        return "unknown"
    if OFFER_RE.search(blob):
        return "offer"
    if INTERVIEW_RE.search(blob):
        return "interview"
    if REJECT_RE.search(blob):
        return "rejected"
    if CONFIRM_RE.search(blob):
        return "confirmed"
    if any(h in blob.lower() for h in ATS_HINTS):
        return "confirmed"
    return "unknown"


def _job_search_terms(job: dict) -> list[str]:
    company = display_company(job)
    title = (job.get("title") or "").strip()
    terms: list[str] = []
    if company and company.lower() not in {"unknown", "indeed", "linkedin"}:
        terms.append(company.split(",")[0].strip())
    # Short distinctive title tokens
    for tok in re.findall(r"[A-Za-z]{4,}", title):
        if tok.lower() not in {"senior", "staff", "engineer", "software", "developer"}:
            terms.append(tok)
            break
    return terms


def _score_match(job: dict, subject: str, snippet: str, from_addr: str) -> float:
    """Score how well an email belongs to a job.

    Company is matched against subject/snippet only — never From:. ATS vendors
    send from *@myworkday.com / *@greenhouse.io, which would otherwise attach
    every Workday-ATS rejection to every site=Workday job.
    """
    text = f"{subject} {snippet}".lower()
    from_l = (from_addr or "").lower()
    company = display_company(job).lower()
    company_core = company.split(",")[0].strip()
    company_is_generic = (not company_core) or (company_core in _GENERIC_EMPLOYERS)

    score = 0.0
    company_hit = bool(company_core) and not company_is_generic and company_core in text
    if company_hit:
        score += 0.55

    title = (job.get("title") or "").lower()
    title_norm = re.sub(r"[^a-z0-9 ]+", " ", title)
    title_norm = re.sub(r"\s+", " ", title_norm).strip()
    title_tokens = [t for t in re.findall(r"[a-z]{4,}", title) if t not in {
        "senior", "staff", "engineer", "software", "developer", "full", "stack",
    }]
    hits = sum(1 for t in title_tokens[:4] if t in text)
    title_phrase = len(title_norm) >= 12 and title_norm in text
    if title_phrase:
        hits += 2
        score += 0.25
    score += min(0.35, hits * 0.12)

    if any(h in from_l or h in text for h in ATS_HINTS):
        score += 0.1

    # Require a real employer mention or a distinctive title token.
    if not company_hit and hits == 0:
        return 0.0
    return score


def poll(*, days: int = 14, dry_run: bool = False, min_confidence: float = 0.45) -> dict:
    init_db()
    conn = get_connection()
    token = _load_token()

    after = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    jobs = conn.execute(
        """
        SELECT url, title, company, site, application_url, applied_at, outcome,
               outcome_message_id
        FROM jobs
        WHERE apply_status = 'applied' OR applied_at IS NOT NULL
        ORDER BY datetime(applied_at) DESC
        LIMIT 80
        """
    ).fetchall()
    jobs = [dict(j) for j in jobs]
    if not jobs:
        print("No applied jobs to match.")
        return {"updated": 0, "scanned": 0}

    # Broad search for recent recruiting mail
    query = (
        f"after:{after} "
        "(subject:application OR subject:applied OR subject:interview OR "
        "subject:thank you OR subject:unfortunately OR subject:offer OR "
        "from:greenhouse OR from:myworkday OR from:ashby OR from:lever "
        "OR from:noreply OR from:careers OR from:recruiting)"
    )
    listing = _gmail_get(
        "users/me/messages",
        token,
        {"q": query, "maxResults": "50"},
    )
    messages = listing.get("messages") or []
    print(f"gmail_messages={len(messages)} applied_jobs={len(jobs)}")

    updated = 0
    scanned = 0
    for meta in messages:
        mid = meta.get("id")
        if not mid:
            continue
        scanned += 1
        msg = _gmail_get(
            f"users/me/messages/{mid}",
            token,
            {"format": "metadata", "metadataHeaders": ["Subject", "From", "Date"]},
        )
        subject, from_addr, snippet = _snippet_and_subject(msg)
        if OTP_RE.search(f"{subject}\n{snippet}"):
            continue
        outcome = classify_email(subject, snippet, from_addr)
        if outcome == "unknown" and not any(h in f"{subject}{from_addr}".lower() for h in ATS_HINTS):
            continue

        best_job = None
        best_score = 0.0
        for job in jobs:
            # Skip if already matched this message
            if job.get("outcome_message_id") == mid:
                best_job = None
                best_score = 0
                break
            s = _score_match(job, subject, snippet, from_addr)
            if s > best_score:
                best_score = s
                best_job = job
        if best_job is None or best_score < min_confidence:
            continue

        prev = (best_job.get("outcome") or "").strip()
        if prev and OUTCOME_PRIORITY.get(prev, 0) > OUTCOME_PRIORITY.get(outcome, 0):
            # Don't downgrade interview → confirmed
            continue

        snippet_store = f"{subject} — {snippet}"[:400]
        now = datetime.now(timezone.utc).isoformat()
        print(
            f"MATCH {outcome} conf={best_score:.2f} | {display_company(best_job)[:40]} | "
            f"{(best_job.get('title') or '')[:40]} | {subject[:60]}"
        )
        if dry_run:
            continue

        conn.execute(
            """
            UPDATE jobs SET outcome = ?, outcome_at = ?, outcome_source = 'gmail',
                   outcome_message_id = ?, outcome_snippet = ?
            WHERE url = ?
            """,
            (outcome, now, mid, snippet_store, best_job["url"]),
        )
        best_job["outcome"] = outcome
        best_job["outcome_message_id"] = mid
        updated += 1

    if not dry_run:
        conn.commit()
    print(f"updated={updated} scanned={scanned} dry_run={dry_run}")
    return {"updated": updated, "scanned": scanned}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=14, help="Look back window (default 14)")
    parser.add_argument("--dry-run", action="store_true", help="Classify only; do not write DB")
    parser.add_argument(
        "--min-confidence",
        type=float,
        default=0.45,
        help="Minimum match score to attach an email to a job",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run matcher unit checks and exit (no Gmail / DB writes)",
    )
    args = parser.parse_args()
    if args.self_test:
        _self_test()
        return
    poll(days=args.days, dry_run=args.dry_run, min_confidence=args.min_confidence)


def _self_test() -> None:
    workday_mlops = {
        "title": "Software Development Engineer - ML Ops (US Federal)",
        "company": None,
        "site": "Workday",
        "application_url": "https://workday.wd5.myworkdayjobs.com/Workday/job/x",
    }
    nelnet = {
        "title": "Sr Staff Engineer",
        "company": "Nelnet",
        "site": "indeed",
        "application_url": "https://nelnet.wd1.myworkdayjobs.com/x",
    }
    nvidia = {
        "title": "Senior Backend Platform Engineer",
        "company": None,
        "site": "NVIDIA",
        "application_url": "https://nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite/job/x",
    }
    # False-positive case from 2026-08-20: Nelnet Workday rejection attached to ML Ops.
    nelnet_mail = (
        "Application Update",
        "DearEli, Thank you for your interest in Sr Staff Engineer. We received many candidates "
        "for this role, and unfortunately, this role was filled",
        "noreply@myworkday.com",
    )
    assert classify_email(*nelnet_mail) == "rejected"
    assert _score_match(workday_mlops, *nelnet_mail) == 0.0
    assert _score_match(nelnet, *nelnet_mail) >= 0.45

    nvidia_mail = (
        "Thank you for your interest in NVIDIA",
        "Dear Eli Hebdon - We want to confirm that your application for Senior Backend Platform Engineer",
        "noreply@myworkday.com",
    )
    assert classify_email(*nvidia_mail) == "confirmed"
    assert _score_match(nvidia, *nvidia_mail) >= 0.45
    assert _score_match(workday_mlops, *nvidia_mail) == 0.0

    otp_mail = (
        "Security code for your application to Sagent",
        "Hi Eli, Copy and paste this code into the security field",
        "noreply@sagent.com",
    )
    assert classify_email(*otp_mail) == "unknown"

    solo_mail = (
        "Solo.io - we've got your application!",
        "Hi Eli, We're glad you're interested in joining",
        "careers@solo.io",
    )
    assert classify_email(*solo_mail) == "confirmed"

    interview_mail = (
        "Interview invitation",
        "We would like to invite you to interview for the role",
        "recruiting@example.com",
    )
    assert classify_email(*interview_mail) == "interview"
    print("poll_application_emails self-test: ok")


if __name__ == "__main__":
    main()
