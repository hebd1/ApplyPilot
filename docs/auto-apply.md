# Auto-apply (Stage 6) — this checkout

Stage 6 fills and submits applications in a real browser using **Cursor SDK + Playwright MCP**. Cursor API key is required.

Implementation:

| Piece | Path |
|-------|------|
| CLI | `src/applypilot/cli.py` (`apply` command) |
| Orchestration | `src/applypilot/apply/launcher.py` |
| Cursor backend | `src/applypilot/apply/cursor_apply.py` |
| Prompt | `src/applypilot/apply/prompt.py` |
| Chrome / CDP | `src/applypilot/apply/chrome.py` |

## Backend selection

Only **Cursor SDK** is supported.

| Backend | Model flag | Notes |
|---------|------------|-------|
| **cursor** (default) | `auto` | Uses `cursor-sdk` `Agent.create` + Playwright MCP + Gmail MCP over Chrome CDP |

Set in `~/.applypilot/.env`:

```bash
CURSOR_API_KEY=...
APPLY_BACKEND=cursor
LLM_MODEL=auto
CAPSOLVER_API_KEY=...   # optional; CAPTCHA solving
# APPLY_ALLOW_GMAIL_SEND=1   # NEVER set unless you explicitly want outbound Gmail; mutate/settings still forbidden
CHROME_PATH=/home/<user>/.cache/ms-playwright/chromium-xxxx/chrome-linux64/chrome
```

`applypilot doctor` should show **Tier 3 — Full Auto-Apply** and **Apply agent: Cursor SDK + Playwright + Gmail MCP**.

## Always use the editable install

From WSL:

```bash
cd /mnt/c/Users/elihe/Projects/applypilot
.venv/bin/applypilot apply --dry-run -l 1
```

From Windows PowerShell:

```powershell
wsl -e bash -lc "cd /mnt/c/Users/elihe/Projects/applypilot && .venv/bin/applypilot apply --dry-run -l 1"
```

On launch you should see:

```text
Backend:  cursor
Model:    auto
```

## Prerequisites

Jobs are eligible when they have:

- `fit_score >= 7` (default `--min-score`)
- `tailored_resume_path` set (PDF)
- Prefer `application_url` set (queue orders these first)
- Not already applied / not permanently failed

Prepare materials:

```bash
.venv/bin/applypilot run tailor cover pdf
.venv/bin/applypilot dashboard
```

Chrome must launch with CDP. Playwright Chromium path is usually enough; see [development.md](development.md).

## Scheduled daily apply (WSL + Windows Task)

ApplyPilot Stage 6 needs your local DB, browser, CapSolver, and Gmail tokens — use a **local** schedule, not Cursor cloud Automations.

**Why not WSL cron alone?** Windows idle-shuts down the WSL VM. Hourly `wsl -e true` only wakes it for seconds (cron logs show `@reboot` every hour at `:43`), so an `08:00` crontab never fires. Fix: Windows Task Scheduler at 08:00 (wakes WSL and runs the script) plus `vmIdleTimeout=-1` in `%USERPROFILE%\.wslconfig`.

```powershell
# Primary: Windows Task at 08:00 local (Mountain on this PC)
powershell -ExecutionPolicy Bypass -File scripts\install_daily_apply_windows_task.ps1

# Optional backup: WSL crontab (needs WSL kept alive)
bash scripts/install_daily_apply_cron.sh

# Manual run
wsl -e bash /mnt/c/Users/elihe/Projects/applypilot/scripts/daily_apply.sh
```

After changing `.wslconfig`, run once: `wsl --shutdown`, then open WSL again.

| Env var | Default | Meaning |
|---------|---------|---------|
| `DAILY_APPLY_LIMIT` | `1` | Max **successful** applications per run |
| `DAILY_APPLY_MIN_SCORE` | `8` | Fit score floor for daily quality gate |
| `DAILY_APPLY_PREP` | `1` | Run `tailor cover pdf` first |
| `DAILY_APPLY_SCORE` | `0` | Also score entire unscored backlog (slow — leave off) |
| `DAILY_APPLY_DISCOVER` | `0` | Also run discovery (slow) |
| `DAILY_APPLY_ATS_ONLY` / `APPLY_ATS_ONLY` | `1` | Only Greenhouse / Workday / Ashby |
| `APPLY_SUCCESS_QUOTA` | `1` | Count only successful applies toward `-l` |
| `DAILY_APPLY_EMAIL_POLL` | `1` | After apply, poll Gmail (readonly) for outcomes |
| `DAILY_APPLY_LINKEDIN_REFRESH` | `1` | Refresh `LINKEDIN_LI_AT` from `linkedin-chrome` profile |
| `DAILY_APPLY_REQUIRE_LINKEDIN` | `0` | Exit if LinkedIn refresh fails (default: warn + continue) |

Logs: `~/.applypilot/logs/daily_apply-*.log`

Daily flow: LinkedIn cookie refresh → purge weak/excluded → tailor/cover/pdf → **one** ATS apply (success quota) → Gmail outcome poll → dashboard.

If LinkedIn refresh fails, run `applypilot linkedin-auth --login` once on the desktop; later dailies can `--refresh` headlessly.

Tailor/cover only process jobs with a usable ATS `application_url` (not LinkedIn/Indeed). Purge anytime:

```bash
.venv/bin/python scripts/purge_unapplyable_queue.py
.venv/bin/python scripts/poll_application_emails.py --dry-run
```

Check the Windows task:

```powershell
schtasks /Query /TN "ApplyPilot Daily Apply" /V /FO LIST
```


```bash
# Fill one form; do NOT click Submit (job stays eligible)
.venv/bin/applypilot apply --dry-run -l 1

# Target a specific application URL
.venv/bin/applypilot apply --dry-run -l 1 --url 'https://grnh.se/...'

# Real submit, headless (recommended on WSL without DISPLAY)
.venv/bin/applypilot apply --headless -l 1 -w 1

# Batch
.venv/bin/applypilot apply --headless -l 10 -w 1

# Ops
.venv/bin/applypilot apply --reset-failed
.venv/bin/applypilot apply --mark-applied URL
.venv/bin/applypilot apply --mark-failed URL --fail-reason '...'
```

## Dry-run vs real apply

| Mode | Submit clicked? | DB on success |
|------|-----------------|---------------|
| `--dry-run` | No | Job remains eligible (`apply_status` cleared) |
| Real apply | Yes (when form completes) | `apply_status=applied`, `applied_at` set |

Dry-run agents still emit `RESULT:APPLIED` in the prompt protocol; the launcher treats that as a dry-run success and does **not** permanently mark the job applied.

## Job acquisition notes

- Queue prefers **Greenhouse → Workday → Ashby**, then other http `application_url`s. **Lever is skipped** (`skip_apply_hosts` — CapSolver cannot solve Lever hCaptcha).
- Marketplace hosts (`auraone.ai`, Turing/Betterteam, Mercor, …) are marked `failed:marketplace` and skipped — see [discovery.md](discovery.md).
- `--url` matches `url` or `application_url` (LIKE). Rows with `apply_status IS NULL` are eligible (NULL-safe check); with `--url`, already-applied rows can be re-acquired for dry-run inspection.
- Manual ATS domains are skipped (`apply_status=manual`).
- Jobs without a usable ATS `application_url` are skipped (no LinkedIn/Indeed board fallback).

## Logs

| Path | Contents |
|------|----------|
| `~/.applypilot/logs/worker-0.log` | Live worker transcript |
| `~/.applypilot/logs/cursor_*.txt` | Per-job Cursor agent output |

Look for `RESULT:APPLIED`, `RESULT:FAILED:...`, CAPTCHA, or login issues at the end of the job log.

## CAPTCHA vs email security codes

| Challenge | What solves it |
|-----------|----------------|
| hCaptcha / reCAPTCHA / Turnstile | CapSolver (`CAPSOLVER_API_KEY` in `.env`) |
| Email OTP / “security code” | Gmail MCP (`search_emails` + `read_email` only) |

They are separate. CapSolver never reads your inbox; Gmail MCP never solves CAPTCHAs.

### Application outcome tracking (Gmail readonly poll)

After jobs are marked `applied`, a separate **read-only** poller matches inbox mail to those rows:

```bash
.venv/bin/python scripts/poll_application_emails.py
.venv/bin/python scripts/poll_application_emails.py --dry-run --days 21
```

Writes `outcome` / `outcome_snippet` / `outcome_message_id` on `jobs` (`confirmed`, `rejected`, `interview`, `offer`). Uses the same `~/.gmail-mcp/` tokens as OTP — **never** send/mutate. Dashboard Applied cards show outcome badges. Daily apply runs this poll automatically (`DAILY_APPLY_EMAIL_POLL=1`).

### Gmail MCP safety (read-only by default)

**Hard rule:** Never update, delete, change Gmail settings, or send emails without the user's **explicit consent**.

**Default posture: read-only.** The apply agent may search and read inbox messages solely to extract verification / OTP codes for an in-progress application form.

| Action | Allowed? |
|--------|----------|
| `search_emails` / `read_email` (OTP) | Yes (default) |
| `send_email` | **No** unless user explicitly opts in with `APPLY_ALLOW_GMAIL_SEND=1` in `~/.applypilot/.env` |
| Modify / delete / archive / star mail | **Never** (not even with send enabled) |
| Create / update / delete labels or filters | **Never** |
| Change Gmail settings, forwarding, signatures | **Never** |
| Draft mail or download attachments via Gmail tools | **Never** |

Email-only postings (“email your resume to …”) fail with `RESULT:FAILED:email_send_requires_consent` unless you opt in to **send only**:

```bash
# ~/.applypilot/.env — only if you intentionally want outbound mail
APPLY_ALLOW_GMAIL_SEND=1
```

That flag does **not** authorize delete/update/settings changes. The Cursor apply path enforces these rules in the agent prompt (`src/applypilot/apply/prompt.py`).

### One-time Gmail OAuth (WSL)

Apply agents mount `@gongrzhe/server-gmail-autoauth-mcp`. **Important:** that package’s built-in `auth` command always requests Google scopes `gmail.modify` + `gmail.settings.basic` (edit/send/settings). That is why the Google consent screen asks for more than read — even though ApplyPilot’s policy is read-only OTP.

**Prefer read-only tokens** (recommended):

```bash
cd /mnt/c/Users/elihe/Projects/applypilot
bash scripts/gmail_oauth_readonly.sh
```

That writes `~/.gmail-mcp/credentials.json` with **`gmail.readonly` only**. Google will then reject send/modify/settings API calls even if a tool is invoked. After switching, revoke the old broader grant at [Google Account → Third-party access](https://myaccount.google.com/permissions).

Authenticate once as the same Linux user that runs ApplyPilot (Desktop OAuth client with Gmail API enabled):

1. In [Google Cloud Console](https://console.cloud.google.com/): create/select a project, enable **Gmail API**, configure the OAuth consent screen, create an OAuth client (**Desktop app**).
2. Download the client JSON → save as `~/.gmail-mcp/gcp-oauth.keys.json` (must contain `installed` or `web` credentials).
3. Run **`bash scripts/gmail_oauth_readonly.sh`** (preferred), **not** the package’s default `auth` (which requests modify/settings).

If you already used the package’s default `auth`, your token file currently includes modify/settings. Re-run the read-only script and revoke the old grant.

Optional fallback when debugging the package itself (broad scopes — avoid for normal use):

```bash
mkdir -p ~/.gmail-mcp
# Prefer node on the package entry if npx shim hits "Permission denied":
node "$(find ~/.npm/_npx -path '*server-gmail-autoauth-mcp/dist/index.js' | head -1)" auth
```

4. Complete the browser sign-in. The callback is `http://localhost:3000/oauth2callback` (WSL2 usually exposes this to the Windows browser). Tokens land in `~/.gmail-mcp/credentials.json`.
5. Re-run `.venv/bin/applypilot doctor` — **Gmail MCP auth** should be green. Confirm the token scope is read-only:

```bash
python3 -c "import json; print(json.load(open('$HOME/.gmail-mcp/credentials.json')).get('scope'))"
# expect: https://www.googleapis.com/auth/gmail.readonly
```

ApplyPilot still **instructs and configures the agent for read-only OTP use** regardless of token scopes. With `gmail.readonly` tokens, Google enforces that boundary at the API. Outbound send (`APPLY_ALLOW_GMAIL_SEND=1`) would need a broader re-auth later — do not enable that unless you explicitly want send.

## Common failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| Model haiku / no Backend line | Wrong / old `applypilot` binary | Use `.venv/bin/applypilot` |
| `NO RESULT` in ~4s | Cursor SDK connectivity error | Check CURSOR_API_KEY quota |
| `Queue empty` with `--url` | Old NULL SQL bug or no match | Update launcher; confirm URL in DB |
| CAPTCHA | Site blocks automation | Set `CAPSOLVER_API_KEY`; otherwise mark failed / apply manually |
| Email security code | OTP in Gmail | Complete Gmail MCP OAuth above; agent uses search/read only |
| `email_send_requires_consent` | Email-only job, send disabled | Set `APPLY_ALLOW_GMAIL_SEND=1` only if you intend to allow outbound mail |
| `RESULT:FAILED:not_eligible_location` | Agent correctly refused remote/hybrid mismatch | Expected — pick a remote-eligible job |
| `RESULT:FAILED:not_a_job_application` | Marketplace / contractor / AI-eval intake | Expected — agent refuses; discovery should have dropped via `marketplace_hosts` |
| `failed:marketplace` | Apply URL host on marketplace denylist | Expected — see [discovery.md](discovery.md) |
| `skip_ats:…` / Lever `RESULT:CAPTCHA` | Lever hCaptcha unsupported | Expected — Lever in `skip_apply_hosts`; prefer Greenhouse/Workday |
| Missing `application_url` | Enrich didn't find apply link | Prefer jobs that have one; re-enrich if needed |

## Job company vs board site

`site` is the discovery board (Indeed, Talent.com, …). Employer lives in `company` when known (JobSpy field, JSON-LD hiringOrganization, or inferred from careers/ATS URL).

```bash
.venv/bin/python scripts/backfill_job_company.py --mark-weak
```

Prompts, PDF names, and the dashboard prefer `display_company(job)`.

## Weak apply URLs

`acquire_job` skips relative URLs (`/redirect?...`), Talent.com redirects, job-board-only apply links (Indeed/LinkedIn as the apply destination), and marketplace hosts. Those are marked `weak_apply_url:…` or `marketplace`.

## CAPTCHA (CapSolver)

```bash
.venv/bin/python scripts/test_capsolver.py
```

Doctor also reports CapSolver balance when the key is set.
