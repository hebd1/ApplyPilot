# Operations — daily apply and health

> **2026-10-26:** the daily run is now the Claude routine in [claude-routine.md](claude-routine.md). This page describes the older Cursor `daily_apply.sh` flow, which nothing schedules anymore.

This checkout applied **one** high-quality ATS job each weekday morning (08:00 America/Denver) via Windows Task Scheduler + `scripts/daily_apply.sh`. Stage 6 needs the local SQLite DB, Chrome, CapSolver, and a live Gmail readonly token — it cannot run as a Cursor cloud Automation.

## Is it running?

| Check | Command / path |
|-------|----------------|
| Last daily result | `cat ~/.applypilot/apply_health.json` |
| Pipeline + apply blocker | `.venv/bin/applypilot status` |
| Doctor (Gmail / LinkedIn / CapSolver) | `.venv/bin/applypilot doctor` |
| Dashboard banner | `~/.applypilot/dashboard.html` (red banner if Gmail is dead) |
| Morning transcript | `~/.applypilot/logs/daily_apply-YYYYMMDD-*.log` |
| Windows task | `schtasks /Query /TN "ApplyPilot Daily Apply" /V /FO LIST` |

Healthy `apply_health.json` after a submit:

```json
{
  "status": "ok",
  "reason": "applied",
  "detail": "Submitted 1 application(s)"
}
```

`reason: queue_empty` means the 08:00 job ran (Gmail/LinkedIn preflight passed) but Stage 6 submitted **0** applications. ApplyPilot does not send its own “you applied” email — company confirmation only arrives after a real submit.

`status: blocked` + `reason: gmail_auth_required` means the 08:00 job exited **before** submitting. Re-auth, then run doctor and `bash scripts/daily_apply.sh`.

## Daily flow

1. Shared flock on `~/.applypilot/logs/daily_apply.lock` (Windows Task and WSL cron must share this path — `XDG_RUNTIME_DIR` differs and used to start two copies, locking SQLite).
2. Purge unapplyable / excluded / stuck `in_progress` rows.
3. Gmail readonly preflight (`gmail_mcp_token_healthy`). **Hard stop** if the refresh token is dead (`DAILY_APPLY_REQUIRE_GMAIL=1`).
4. LinkedIn `--refresh` from `linkedin-chrome`. If the profile is empty but `.env` `LINKEDIN_LI_AT` still validates, re-seed the profile from that cookie (enrich keeps working). Interactive `--login` is still the durable fix.
5. Score at most `DAILY_APPLY_SCORE_LIMIT` (default **8**) unscored jobs, then `tailor cover pdf` for score ≥ 7 with a usable ATS `application_url`. Set `DAILY_APPLY_SCORE=1` only when you want the entire backlog.
6. `apply --headless -l 1 --min-score 8` (Greenhouse / Workday / Ashby only, success quota 1). Skips a job if the same apply URL or same title+employer is already `applied`.
7. `poll_application_emails.py` (readonly outcome tags).
8. Regenerate the HTML dashboard.

Env vars are documented in [auto-apply.md](auto-apply.md).

## Recurring failure modes

| Symptom | What it is | Fix |
|---------|------------|-----|
| Morning log stops at Gmail preflight; `invalid_grant` | Refresh token expired or revoked | `bash scripts/gmail_oauth_readonly.sh` then `applypilot doctor` |
| Dashboard looks idle, no new `applied` rows | Same as above, or lock race (fixed: use `logs/daily_apply.lock`) | `applypilot status`; latest `daily_apply-*.log` |
| `Profile has no LinkedIn session` | `linkedin-chrome` empty **and** `.env` cookie missing/invalid | `--refresh` now re-seeds from a valid `.env` cookie; `--login` if both are dead |
| High-fit LinkedIn jobs with no resume | Tailor skips listings without an ATS `application_url` | Restore LinkedIn profile session so enrich can resolve company-site apply URLs |
| Applied card shows the wrong outcome | Email poller matched ATS From: to `site=Workday` / `site=Greenhouse` | Matcher now requires a real employer name or title phrase; clear the bad `outcome` if needed |
| `database is locked` at 08:00 | Windows Task + cron both started | Shared lock file; first copy wins, second should skip |
| Health says `applied` but no company email / no new DB row | Used to treat any apply exit 0 as a submit (including empty queue) | Health now records `queue_empty` when `Done: 0 applied` |
| `Queue empty` while dashboard still shows ATS-ready jobs | Stage 6 SQL bound blocked-site names into ATS `LIKE` slots | Fixed in `build_apply_queue_query`; `scripts/test_apply_queue.py` guards it |
| Email poll `HTTP 401` after a long morning run | Stale Gmail access token (~1h) after score/tailor | Poller refreshes and retries once on 401 |

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

**Open issues / follow-ups**

1. **LinkedIn Chrome profile still needs a desktop `--login` for a durable session.** `--refresh` now re-seeds from a valid `.env` cookie so morning apply no longer treats that as a hard miss. High-fit LinkedIn cards without an ATS URL still need a live session (or re-enrich) before they can be tailored.
2. **CapSolver balance** is finite; doctor reports it. Replenish before it hits $0 or CAPTCHA jobs fail closed.

**Fixes landed after this snapshot**

- Email matcher: no From:-as-employer; OTP ignored; interview regex tightened (`we've got your application` → confirmed).
- `company` persisted via `display_company` on acquire + `backfill_job_company.py`.
- Daily apply scores at most 8 unscored jobs (`DAILY_APPLY_SCORE_LIMIT`).
- Stage 6 skips `duplicate_applied` (same apply URL or same title + employer already applied).

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
