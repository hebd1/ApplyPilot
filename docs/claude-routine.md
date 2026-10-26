# Daily Claude routine — find jobs, fill applications in Chrome

A Claude desktop scheduled task on Phobos (`applypilot-daily`, 07:00 daily) replaces the Cursor Stage 6 agent. It:

1. Runs `scripts/claude_daily_prep.sh` in WSL: discover → enrich → score (newest 40) → tailor / cover / PDF for score ≥ 8, all through `claude -p` (`LLM_PROVIDER=claude`), then `applypilot claude queue` picks the best 3 jobs (one per employer).
2. Fills each application in Eli's Chrome with Claude in Chrome, uploading the tailored resume, and **stops before Submit**.
3. Sends Eli a summary. Eli replies in that run's session (`submit all`, `submit 1,3`, `skip 2`); the routine then submits the approved ones and records the results.

The old Cursor path (`daily_apply.sh`, `cursor_apply.py`, CapSolver) is still in the repo and untouched; nothing schedules it anymore.

## Files and commands

| What | Where |
|------|-------|
| Prep log | `~/.applypilot/logs/claude_prep-*.log` (WSL) |
| Today's queue (Windows) | `C:\Users\elihe\Projects\applypilot\.apply-queue\<YYYY-MM-DD>\queue.json` (gitignored; `CLAUDE_APPLY_EXPORT_DIR`) + one folder per job with `Eli_Hebdon_Resume.pdf` / `Eli_Hebdon_Cover_Letter.pdf`. It sits inside the repo because Claude in Chrome's `file_upload` only reads files in the session's folders. |
| Queue copy (WSL) | `~/.applypilot/claude/queue-<YYYY-MM-DD>.json` |
| Hosts it applies on | `src/applypilot/config/sites.yaml`: any apply host except `claude_account_hosts` (Workday, iCIMS, Taleo, SuccessFactors, Oracle, …); `claude_apply_hosts` (Greenhouse, Ashby, Lever, …) go first within a fit score. Set `claude_apply_any_host: false` to allow only the named ATSs. |
| Resume Playbook (copy) | `.apply-queue\resume_playbook.md`, refreshed from Notion each run. While it exists, tailoring uses only its approved bullet bank and skills list, strips Senior/levels from the headline, rejects judge failures, and writes 150–200-word cover letters (`src/applypilot/scoring/playbook.py`). |
| ATS keyword coverage | Tailoring asks the model for the job's top 10 hard skills (`jd_top_skills`), matches them against the resume (`scoring/keywords.py`, alias- and word-boundary-aware), retries when a skill Eli has is missing, and stores the result in `jobs.keyword_coverage` and `queue.json`. |
| Interview Story Bank | Notion page `4056b7634ff381d1be5fcf090c1bedab` under Job Search: STAR stories from approved facts, mapped to common questions. |
| Notion | Applications table (`collection://583a8f0e-4cc1-4395-9662-3b4150ab1144`): shared board with Job Hunter (Grok). Check the company, then claim the row (Status In progress, Agent = Claude routine) before filling; status updates. Form-answer rules: the bots page. |
| Scheduled task prompt | `C:\Users\elihe\.claude\scheduled-tasks\applypilot-daily\SKILL.md` |

Run ApplyPilot commands from Windows through WSL:

```bash
MSYS_NO_PATHCONV=1 wsl.exe bash -c 'cd /mnt/c/Users/elihe/Projects/applypilot && .venv/bin/applypilot claude pending'
```

| Command | Use |
|---------|-----|
| `applypilot claude queue -n 3 --min-score 8` | Pick and export today's jobs (`--include-workday`, `--no-expiry-check`, `--json`) |
| `applypilot claude mark <url> -s <status> --note "..."` | Record a result. Status: `filled`, `applied`, `needs_eli`, `failed`, `declined`, `release` |
| `applypilot claude pending` | Jobs waiting on Eli (filled, or needs a human step), last 7 days |

`<url>` may be the job's `url` or its `apply_url` from `queue.json`.

## Status flow

```
NULL ─queue→ claude_queued ─fill→ claude_filled ─Eli approves→ applied
                     │                    └─Eli skips, or 3 days unapproved→ declined
                     ├→ needs_eli   (CAPTCHA, account sign-in, a question only Eli can answer)
                     └→ failed      (closed posting, location, broken form)
```

`claude_queued` rows older than 6 h go back to the queue on the next pick (an interrupted run).

## Routine procedure

The scheduled task follows this section. Keep it accurate when the code changes.

### 0. Preflight

- Run `~/.claude/skills/mac-session-lock/scripts/session-lock.sh status` in WSL. If the lock is held by `Game mode (Eli)`, stop: reply "Skipped today: Game mode is on." Do not open Chrome tabs while Eli is gaming.
- Run `applypilot claude pending` and keep the list for the summary.
- **Refresh the Resume Playbook from Notion** (Job Search / Resume Playbook, page `3fd6b7634ff381278e46e13f68613886`): fetch it and write its content as Markdown to `C:\Users\elihe\Projects\applypilot\.apply-queue\resume_playbook.md` (`RESUME_PLAYBOOK_PATH`). Tailoring, the judge and cover letters follow that file. If Notion is unreachable, keep yesterday's copy and say so in the summary.
- Read the Notion **bots** page (`3cd6b7634ff380e39c9cf4467039072d`) for form-answer rules. `profile.json` mirrors it (years, EEO, clearance, Go/Node years); when they disagree, the bots page wins and the summary says so.

### 1. Prep (60–90 min)

Run in the background and wait for it to finish (do not poll):

```bash
MSYS_NO_PATHCONV=1 wsl.exe bash /mnt/c/Users/elihe/Projects/applypilot/scripts/claude_daily_prep.sh
```

- Exit 3: another ApplyPilot run holds the lock; stop and say so.
- A `WARN: session lock not available` line means the heavy stages were skipped; the queue still comes from already-tailored jobs.
- If prep fails before the queue step, run `applypilot claude queue` directly.

Read `C:\Users\elihe\Projects\applypilot\.apply-queue\<today>\queue.json`. Zero jobs: send the summary and stop.

### 2. Browser

Load the Claude in Chrome tools in one ToolSearch call (`tabs_context_mcp, tabs_create_mcp, navigate, computer, read_page, find, form_input, file_upload, get_page_text`). Select the Phobos Chrome (Windows). Open a new tab for each job; never use Eli's existing tabs.

### 3. Fill each job (stop before Submit)

For each job in `queue.json`, in rank order:

0. **Notion check, then claim** (shared board with Job Hunter, the Grok bot; rules on the bots page under "Two bots, one board"). Search the Applications data source (`collection://583a8f0e-4cc1-4395-9662-3b4150ab1144`) for the company. A row for the same company and a similar role whose Status is not Skipped is taken (applied, or claimed by Job Hunter or Eli): `mark <url> -s failed --note "duplicate: Notion <row url>"` and move on. An In progress row with no Notes line for 24 h may be taken over with a Notes line. Same company, different role: continue and mention it. Otherwise **create the row now, before opening the form**: Name = job title, Company, Job URL = `url`, ATS URL = `apply_url`, Fit score, Apply type = External, Path = Cold, Status = In progress, **Agent = Claude routine**, Notes = `<YYYY-MM-DD h:mm a MT> (Claude routine): claimed`.
1. Navigate to `apply_url`. If the posting is closed: `mark <url> -s failed --note closed`.
2. Location: Remote (US) is fine; hybrid/onsite only in a `location_accept` place. Otherwise `-s failed --note not_eligible_location`.
3. Sign-in or account creation required: `-s needs_eli --note account_required`. Do not create accounts or type passwords.
4. Fill from `applicant` (name, email, phone, address, links, work authorization, sponsorship, salary, EEO). Upload `resume_pdf` with `file_upload` on the `type="file"` input (never click Attach; it opens a native picker). Cover letter: upload `cover_letter_pdf` for a file field, paste `cover_letter_text` for a text box.
   - **Never press Enter in an application form.** In a dropdown whose typed text matches no option, Enter submits the whole form (seen on Greenhouse 2026-10-26). Open the dropdown, read its options (`read_page` on the listbox), and click the option.
   - Option wording varies ("Never Employed by Praxis" for "former employee? no"); pick the option that says the true answer.
   - Text fields: `form_input`. Location autocomplete: type the city, then click the matching suggestion.
   - Check every field took (screenshot or `get_page_text`) before marking.
5. Pay: if the posting shows a range whose top is below `salary.range_min`, still fill it but flag it in the summary ("pay $X–$Y, below your range").
6. Screening questions: answer truthfully from `applicant` (including its "Screening answers" section from `profile.json` → `screening_answers`), `why_it_fits` and the resume. Short "why this company/role" answers: 2–4 sentences in Eli's voice from `job_description` + `why_it_fits`, no invented facts. A required question that the data cannot answer truthfully (clearance, a certification, a specific tool's years): leave it, `-s needs_eli --note "question: <text>"`.
7. Email verification code: open Gmail in another tab and read the newest message from that employer/ATS (read only; never send, delete, label or change settings).
8. CAPTCHA (reCAPTCHA, hCaptcha, Turnstile, puzzles): do not solve or bypass it and do not call CapSolver. Leave the tab open with everything else filled; `-s needs_eli --note captcha`.
9. Consent/terms checkboxes and acknowledgement dropdowns: leave unset; list them in the summary. They are ticked when Eli approves.
10. Review the whole form, then `-s filled --note "<one line: what was filled, any judgment calls>"`. Leave the tab open. Do not click Submit.
11. **Update the claimed row.** Resume version = Full Stack when the resume headline says Full Stack, else Backend/Identity; append Notes `<YYYY-MM-DD h:mm a MT> (Claude routine): <filled | needs Eli: why>; pay <range or not posted>; ATS coverage <score as %>: covered …; gaps …` using the job's `keyword_coverage` from `queue.json` (`covered`, `missing_gap`; `missing_on_list` should be empty because tailoring retries until those are added, so list any that remain as "fixable"). Attach the uploaded resume PDF to Resume (and the cover letter to Cover letter when one was used) with the Notion file-upload tool; if that fails, put the local path in Notes. A claimed job that turns out closed or location-ineligible: Status = Skipped with the reason.

### Notion status updates

| ApplyPilot | Notion Status | Also set |
|------------|---------------|----------|
| `filled`, `needs_eli` | In progress | Notes line |
| `applied` | Applied | Applied = today; Notes line with the confirmation text |
| `declined` | Skipped | Notes line with Eli's reason |

Keep Notes append-only: add a dated line, never rewrite earlier ones.

### 4. Summary

Reply with (and send a push notification when the tool is available):

- **Ready to submit** — numbered: title @ company, fit score, ATS keyword coverage (%), apply link, notable answers or consent boxes.
- **Needs you** — CAPTCHA / account / question jobs with the open tab or link and what is left.
- **Skipped** — closed, location, form errors.
- **Still waiting from earlier days** — from `applypilot claude pending`.
- Links to the Notion rows created or updated today.
- Last line: `Reply "submit all", "submit 1,3" or "skip 2".`

### 5. When Eli replies

For each approved job: switch to its tab (re-fill from `queue.json` if the tab was closed or the form reset), tick the consent boxes, click Submit, confirm the confirmation page or message, then `-s applied --note "<confirmation text>"` and set its Notion row to Applied (Applied = today). For each skipped job: `-s declined` and Notion Status Skipped. Report what was submitted with the Notion row links.

## Limits

- **No account creation, no passwords, no CAPTCHA solving.** Those jobs come back as `needs_eli` with the form filled.
- **Nothing is submitted without Eli's approval in that run's chat.**
- Workday is excluded by default (every tenant needs an account). `--include-workday` adds it for days Eli signs in to a tenant first.
- Scheduled tasks run while the Claude desktop app is open; a missed run starts on the next launch.
