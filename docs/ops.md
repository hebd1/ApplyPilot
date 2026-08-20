# Operations — daily apply and health

This checkout applies **one** high-quality ATS job each weekday morning (08:00 America/Denver) via Windows Task Scheduler + `scripts/daily_apply.sh`. Stage 6 needs the local SQLite DB, Chrome, CapSolver, and a live Gmail readonly token — it cannot run as a Cursor cloud Automation.

## Is it running?

| Check | Command / path |
|-------|----------------|
| Last daily result | `cat ~/.applypilot/apply_health.json` |
| Pipeline + apply blocker | `.venv/bin/applypilot status` |
| Doctor (Gmail / LinkedIn / CapSolver) | `.venv/bin/applypilot doctor` |
| Dashboard banner | `~/.applypilot/dashboard.html` (red banner if Gmail is dead) |
| Morning transcript | `~/.applypilot/logs/daily_apply-YYYYMMDD-*.log` |
| Windows task | `schtasks /Query /TN "ApplyPilot Daily Apply" /V /FO LIST` |

Healthy `apply_health.json` looks like:

```json
{
  "status": "ok",
  "reason": "applied",
  "detail": "Daily apply finished"
}
```

`status: blocked` + `reason: gmail_auth_required` means the 08:00 job exited **before** submitting. Re-auth, then run doctor and `bash scripts/daily_apply.sh`.

## Daily flow

1. Shared flock on `~/.applypilot/logs/daily_apply.lock` (Windows Task and WSL cron must share this path — `XDG_RUNTIME_DIR` differs and used to start two copies, locking SQLite).
2. Purge unapplyable / excluded / stuck `in_progress` rows.
3. Gmail readonly preflight (`gmail_mcp_token_healthy`). **Hard stop** if the refresh token is dead (`DAILY_APPLY_REQUIRE_GMAIL=1`).
4. LinkedIn `--refresh` from `linkedin-chrome` profile. **Warning only** if the profile is logged out (`DAILY_APPLY_REQUIRE_LINKEDIN=0`).
5. `tailor cover pdf` for score ≥ 7 jobs that already have a usable ATS `application_url`. Does **not** score the unscored backlog (`DAILY_APPLY_SCORE=0`).
6. `apply --headless -l 1 --min-score 8` (Greenhouse / Workday / Ashby only, success quota 1).
7. `poll_application_emails.py` (readonly outcome tags).
8. Regenerate the HTML dashboard.

Env vars are documented in [auto-apply.md](auto-apply.md).

## Recurring failure modes

| Symptom | What it is | Fix |
|---------|------------|-----|
| Morning log stops at Gmail preflight; `invalid_grant` | Refresh token expired or revoked | `bash scripts/gmail_oauth_readonly.sh` then `applypilot doctor` |
| Dashboard looks idle, no new `applied` rows | Same as above, or lock race (fixed: use `logs/daily_apply.lock`) | `applypilot status`; latest `daily_apply-*.log` |
| `Profile has no LinkedIn session` | `linkedin-chrome` profile logged out. `.env` `LINKEDIN_LI_AT` can still be OK | `applypilot linkedin-auth --login` on the desktop |
| High-fit LinkedIn jobs with no resume | Tailor skips listings without an ATS `application_url` | Restore LinkedIn profile session so enrich can resolve company-site apply URLs |
| Applied card shows the wrong outcome | Email poller matched ATS From: to `site=Workday` / `site=Greenhouse` | Matcher now requires a real employer name or title phrase; clear the bad `outcome` if needed |
| `database is locked` at 08:00 | Windows Task + cron both started | Shared lock file; first copy wins, second should skip |

## Gmail vs LinkedIn (two different sessions)

| Auth | Path | Used for |
|------|------|----------|
| Gmail MCP | `~/.gmail-mcp/credentials.json` | ATS email OTP during apply; outcome poll after apply |
| LinkedIn cookie | `LINKEDIN_LI_AT` in `~/.applypilot/.env` | Enrich / apply-URL resolve on LinkedIn job pages |
| LinkedIn Chrome profile | `~/.applypilot/linkedin-chrome/` | Headless `--refresh` of `li_at` each morning |

Doctor `--check` can be green on the `.env` cookie while daily `--refresh` fails because the persistent profile is logged out. That does **not** block Greenhouse/Workday applies. It does starve LinkedIn listings of ATS URLs.

Re-auth Gmail: [auto-apply.md](auto-apply.md) (readonly script only).

## Quality gates (this checkout)

| Gate | Value |
|------|--------|
| Daily min fit score | **8** (`DAILY_APPLY_MIN_SCORE`) |
| Manual `apply` default | 7 |
| ATS hosts | Greenhouse, Workday, Ashby (`APPLY_ATS_ONLY=1`) |
| Lever | Discover only — Stage 6 skips (`skip_apply_hosts`) |
| Success quota | 1 successful submit per daily run |
| Max attempts per job | 8 (`APPLY_MAX_ATTEMPTS`) |

Older rows in the DB (late July) include score-1 / cloud-devops titles applied before these gates. That is historical, not the current queue.

## Email outcomes

`scripts/poll_application_emails.py` tags `applied` rows with `confirmed` / `rejected` / `interview` / `offer` from readonly Gmail.

- OTP / “security code” mail is ignored (not an outcome).
- Company is matched in **subject + snippet only**, never `From:`. Workday/Greenhouse senders must not attach every ATS email to every job whose `site` is that product.
- Require a real employer mention or a distinctive title phrase. `min-confidence` default is `0.45`.

```bash
.venv/bin/python scripts/poll_application_emails.py --self-test
.venv/bin/python scripts/poll_application_emails.py --dry-run --days 21
```

Clear a bad tag:

```bash
.venv/bin/python - <<'PY'
from applypilot.database import get_connection
conn = get_connection()
conn.execute(
    "UPDATE jobs SET outcome=NULL, outcome_snippet=NULL, outcome_message_id=NULL, outcome_at=NULL "
    "WHERE url = ?",
    ("https://...",),
)
conn.commit()
PY
```

## Manual recover

```bash
# After Gmail re-auth
.venv/bin/applypilot doctor
bash scripts/daily_apply.sh

# LinkedIn profile (desktop browser)
.venv/bin/applypilot linkedin-auth --login

# Inspect queue
.venv/bin/applypilot status
.venv/bin/python scripts/list_ready_apply_jobs.py
```

## Ops snapshot (2026-08-20)

Taken after Gmail re-auth and a catch-up apply the same morning.

**What was healthy**

- Windows Task + cron fire at 08:00 Mountain every day (logs exist 2026-08-07 … 2026-08-20).
- Doctor: Cursor Auto, Chrome, CapSolver (~$5.89), Gmail readonly refresh OK after re-auth.
- Catch-up apply succeeded: Workday *Software Development Engineer - ML Ops (US Federal)* submitted 09:34 Mountain; Workday showed Application Submitted / In Review.
- 23 applied total. Recent quality-gate applies (Aug 7–20) are mostly score 8–9 on Greenhouse/Workday/NVIDIA/Motorola/Indeed ATS URLs.
- Email poll scanned 17 messages after the catch-up run.

**What broke applies 2026-08-15 … 2026-08-20 08:00**

- Gmail refresh token revoked (`invalid_grant`). Preflight exited; ~84 jobs stayed ready. Not a scheduler outage.
- 2026-08-13/14 first process often hit `database is locked` (Task + cron). The second process usually completed the apply. Lock file is now `~/.applypilot/logs/daily_apply.lock`.

**Open issues / improvements**

1. **LinkedIn Chrome profile logged out.** `linkedin-auth --refresh` warns every morning. `.env` `li_at` still checks OK. High-fit LinkedIn cards (~34) have no `application_url` / no tailored resume until the profile is logged in again.
2. **Email matcher false rejection (fixed in code).** The 09:34 ML Ops apply was tagged `rejected` from a Nelnet *Sr Staff Engineer* Workday email (`From: myworkday.com` + `site=Workday`). Matcher no longer uses From: for employer identity. Clear the bad outcome on that row if it is still set.
3. **`company` is NULL on 11/23 applied rows** (Workday / NVIDIA / Motorola site-discovered jobs). Dashboard and poller fall back to `site` / URL inference. `scripts/backfill_job_company.py` promotes `site` when it is not a job board — that is correct for NVIDIA, misleading when `site=Workday` the product vs Workday the employer.
4. **OTP mail was stored as `confirmed`** on LeafLink / Sagent (security-code emails). Poller now skips OTP subjects.
5. **Unscored backlog ~218** with full descriptions. Daily apply does not score them (intentional — scoring would block the 08:00 apply for hours). Run `DAILY_APPLY_SCORE=1` only when you mean to.
6. **solo.io outcome `interview`** may be a soft “we’ve got your application / next steps” match. Treat interview badges as hints, not calendar facts.
7. **Two Mozilla “Senior Software Engineer” applies** (2026-07-28) — duplicate listings, same title.
8. **CapSolver balance** is finite; doctor reports it. Replenish before it hits $0 or CAPTCHA jobs fail closed.

**Queue (same day)**

| Metric | Count |
|--------|-------|
| Total jobs | 2535 |
| Applied | 23 |
| Failed / skipped (weak URL, expired, location) | 38 |
| Ready score ≥ 8 with resume | ~31 |
| High-fit (7+) with no resume | ~34 (mostly LinkedIn, no ATS URL) |
| Unscored with description | ~218 |
| Stuck `in_progress` | 0 |
