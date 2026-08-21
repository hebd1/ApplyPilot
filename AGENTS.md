# Agent guide — ApplyPilot (this fork)



This document orients AI coding agents working in **this repository**. It describes how this checkout differs from upstream ApplyPilot and where to change things safely.



## What this project is



ApplyPilot is a Python CLI that runs a 6-stage job-application pipeline:



1. **Discover** — scrape job boards and career sites

2. **Enrich** — fetch full job descriptions

3. **Score** — LLM rates fit 1–10

4. **Tailor** — LLM rewrites resume per job → validated plain text → **styled one-page PDF**

5. **Cover** — LLM writes cover letters → **styled PDF**

6. **Apply** — Cursor SDK submits applications in a browser



Upstream: [Pickle-Pixel/ApplyPilot](https://github.com/Pickle-Pixel/ApplyPilot). This checkout is an **editable fork** with:



- **Cursor Auto LLM provider** (`cursor-sdk`) to avoid Gemini API rate limits

- **Named PDF output** for resumes and cover letters (Playwright Chromium + xhtml2pdf fallback)

- **Cursor SDK auto-apply** (Stage 6) with Playwright + Gmail MCP

- **HTML dashboard** with Overview / Jobs / Applied / Failed modules and Apply / Resume / Cover links (WSL-aware file URLs for Windows)



## Critical context for agents



### Two separate AI systems



| System | Used for | Config | Entry point |

|--------|----------|--------|-------------|

| **LLM provider** (`cursor-sdk` or OpenAI-compat) | Score, tailor, cover, enrichment, smart-extract | `CURSOR_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, or `OPENAI_API_KEY`; `LLM_MODEL` | `src/applypilot/llm.py` |

| **Cursor apply agent** (`cursor-sdk` + Playwright + Gmail MCP) | Stage 6 browser auto-apply | `CURSOR_API_KEY`, `APPLY_BACKEND=cursor`; optional `CAPSOLVER_API_KEY`; Gmail OAuth in `~/.gmail-mcp/` | `src/applypilot/apply/cursor_apply.py` |



Do **not** conflate these. Cursor Automations (scheduled triggers in the Cursor UI) are **not** used here. Pipeline LLM work goes through `llm.py` → `Agent.prompt(model="auto")`. Stage 6 uses a Cursor agent with browser MCP (`cursor_apply.py`).



### LLM changes belong in one place



All pipeline LLM calls go through `get_client()` in [`src/applypilot/llm.py`](src/applypilot/llm.py). Call sites (do not duplicate provider logic):



- `src/applypilot/scoring/scorer.py`

- `src/applypilot/scoring/tailor.py`

- `src/applypilot/scoring/cover_letter.py`

- `src/applypilot/enrichment/detail.py`

- `src/applypilot/discovery/smartextract.py`



Provider priority in `_detect_provider()`:



1. `CURSOR_API_KEY` → Cursor Auto

2. `GEMINI_API_KEY` → Gemini

3. `OPENAI_API_KEY` → OpenAI

4. `LLM_URL` → local OpenAI-compatible endpoint



### User data lives outside the repo



Runtime state is under `~/.applypilot/` (WSL: `/home/<user>/.applypilot/`):



| Path | Purpose |

|------|---------|

| `applypilot.db` | SQLite job queue / pipeline state |

| `.env` | API keys (`CURSOR_API_KEY`, etc.) — **never delete on reset** |

| `profile.json` | Candidate profile for scoring/tailoring/apply |

| `resume.txt` / `resume.pdf` | Base resume |

| `searches.yaml` | Job search configuration |

| `tailored_resumes/` | Per-job `.txt` sources + `{Name}_{Role}_{Site}_Resume.pdf` |

| `cover_letters/` | Per-job `_CL.txt` sources + `{Name}_{Role}_{Site}_CoverLetter.pdf` |

| `dashboard.html` | Generated job review UI |

| `apply_health.json` | Last daily-apply result (`ok` / `blocked`) for status + dashboard |

| `logs/daily_apply-*.log` | Morning apply transcript |



Also outside the repo: `~/.gmail-mcp/` (`gcp-oauth.keys.json`, `credentials.json`) for Stage 6 OTP read. Never commit those files. Reset scripts do **not** touch Gmail tokens.



Never commit secrets from `.env`. Do not hardcode API keys in source.



### This environment runs via WSL



The `.venv` is a **Linux venv** created inside WSL (`pyvenv.cfg` → `/usr/bin/python3.11`). On Windows, run commands through WSL:



```bash

wsl -e bash -lc "cd /mnt/c/Users/elihe/Projects/applypilot && .venv/bin/applypilot doctor"

```



Do not assume `python` or `.venv\Scripts\python.exe` works from PowerShell.



Open dashboard / PDFs from Windows:



```

\\wsl.localhost\Ubuntu\home\<user>\.applypilot\dashboard.html

```



## Repository layout



```

applypilot/

├── AGENTS.md              # This file

├── docs/

│   ├── auto-apply.md      # Stage 6 Cursor apply
│   ├── cursor-llm.md      # Cursor Auto provider details
│   ├── development.md     # Dev setup, scripts, testing
│   ├── pdf-and-dashboard.md  # PDF generation + dashboard
│   ├── resume-tailoring.md   # Tailor guardrails, layout, profile fields
│   └── reset-onboard.md   # Clear data and re-run init

├── scripts/               # Ad-hoc utilities (not part of package)

├── src/applypilot/        # Package source (editable install)

│   ├── llm.py             # LLM client — Cursor/Gemini/OpenAI/local

│   ├── pipeline.py        # Stage orchestration (includes pdf stage)

│   ├── view.py            # HTML dashboard generation

│   ├── database.py        # SQLite schema and stage queries

│   ├── config.py          # Paths, tiers, env loading

│   ├── cli.py             # Typer CLI + doctor + dashboard

│   ├── apply/             # Stage 6 (Cursor SDK)

│   ├── scoring/           # Score, tailor, cover, pdf, employment, resume_format

│   ├── enrichment/        # Job description scraping

│   └── discovery/         # Job board scraping

└── pyproject.toml         # cursor-sdk, playwright, xhtml2pdf

```



Package is installed editable: `pip install -e .` (from WSL).



## Common commands



```bash

# Setup check

.venv/bin/applypilot doctor



# First-time or re-onboard setup

.venv/bin/applypilot init



# Full pipeline (stages 1–5, includes PDF conversion)

.venv/bin/applypilot run



# Single stages

.venv/bin/applypilot run score

.venv/bin/applypilot run tailor cover pdf



# Job review UI

.venv/bin/applypilot dashboard



# Stats

.venv/bin/applypilot status



# Auto-apply — use editable install (Cursor backend by default)
.venv/bin/applypilot apply --dry-run -l 1
.venv/bin/applypilot apply --headless -l 1 -w 1
# See docs/auto-apply.md

# Daily scheduled apply (08:00 Mountain — 1 quality ATS apply + Gmail outcome poll)
# Scores at most DAILY_APPLY_SCORE_LIMIT (default 8) before tailor/cover/pdf.
powershell -ExecutionPolicy Bypass -File scripts/install_daily_apply_windows_task.ps1
bash scripts/install_daily_apply_cron.sh
bash scripts/daily_apply.sh
```



## PDF and dashboard (this fork)



| Component | File | Notes |

|-----------|------|-------|

| PDF conversion | `scoring/pdf.py` | Playwright first, xhtml2pdf fallback |

| Tailor → PDF | `scoring/tailor.py` | Saves `.txt`, converts, stores PDF path in DB |

| Cover → PDF | `scoring/cover_letter.py` | Same pattern |

| Batch PDF stage | `pipeline.py` `_run_pdf()` | `batch_convert_materials()` |

| Dashboard | `view.py` | WSL `file://wsl.localhost/...` links for Windows |



Playwright system deps in WSL: `bash scripts/install_playwright.sh`



See [docs/pdf-and-dashboard.md](docs/pdf-and-dashboard.md).

## Resume tailoring (this fork)

Tailoring is **job-specific by design** but **fact-bound by validation**:

| Layer | Module | Enforces |
|-------|--------|----------|
| Prompt | `scoring/tailor.py` | JSON schema, employer rules, bullet style, skills boundary |
| Normalize | `scoring/employment.py` | Separate `company`/`title`/`dates`; fix merged Kount+Equifax |
| Validate | `scoring/validator.py` | Fabrication, preserved companies/school, banned words (mode-dependent) |
| Assemble | `scoring/resume_format.py` | Canonical layout; code-injected header |
| Judge | `scoring/tailor.py` | Subtle lies; allows rewording and minor stretches |
| PDF | `scoring/pdf.py` | One-page layout; uniform bullets; company header rows |

Profile: `resume_facts.employment_history`, `preserved_projects` (work-product), `personal_projects`, `skills_boundary`, `education_details`.

See [docs/resume-tailoring.md](docs/resume-tailoring.md).

## Reset and fresh start



To clear jobs and generated materials before re-onboarding:



```bash

bash scripts/reset_for_fresh_start.sh        # also clears profile/resume/searches

bash scripts/reset_for_fresh_start.sh --keep-config   # jobs + materials only

.venv/bin/applypilot init

```



See [docs/reset-onboard.md](docs/reset-onboard.md).



## Making changes



### Adding or changing LLM behavior



1. Edit `src/applypilot/llm.py` only unless parsers need hardening.

2. Cursor path must keep structured output compatible (`SCORE:`, JSON resume, etc.). The `_OUTPUT_WRAPPER` in `llm.py` enforces this.

3. Retry logic: `CursorAgentError` with `is_retryable` → backoff; HTTP 429 for Gemini/OpenAI.

4. Concurrency: `CURSOR_MAX_CONCURRENCY` env var (default `2`).



See [docs/cursor-llm.md](docs/cursor-llm.md).



### PDF / dashboard changes



- HTML templates and naming: `scoring/pdf.py`

- Dashboard links and WSL paths: `view.py` → `_local_file_href()`, `_material_link_html()`

- Do not store only `.txt` in DB if PDF stage is expected — tailor/cover now write PDF paths after conversion



### Tier gating



`get_tier()` in `config.py` checks `CURSOR_API_KEY` alongside other LLM keys. Wizard in `wizard/init.py` offers Cursor as default provider. Doctor in `cli.py` reports provider type.



### Pipeline / DB



Jobs progress through SQLite columns (`fit_score`, `tailored_resume_path`, `cover_letter_path`, `apply_status`, etc.). Stage queries live in `database.py`. Streaming mode in `pipeline.py` polls every 10s.



`tailored_resume_path` and `cover_letter_path` should point at **PDF** files after tailor/cover/pdf stages.



### Gmail MCP (Stage 6) — read-only unless consented



Tokens live in `~/.gmail-mcp/` (`gcp-oauth.keys.json` + `credentials.json`). Setup: [docs/auto-apply.md](docs/auto-apply.md).



**OAuth vs policy:** the stock Gmail MCP `auth` command requests Google scopes `gmail.modify` + `gmail.settings.basic` (edit/send/settings on the consent screen). Prefer `bash scripts/gmail_oauth_readonly.sh` so the token is **`gmail.readonly` only**. ApplyPilot also blocks send/mutate in the apply prompt regardless.



**Hard rule for agents working in this repo and for the apply agent:**



- **Never** update, delete, change Gmail settings, or send emails **without the user's explicit consent**.

- **Default: read-only.** Use Gmail only to `search_emails` / `read_email` for application OTP / security codes.

- Consent for outbound mail is an explicit env opt-in: `APPLY_ALLOW_GMAIL_SEND=1` in `~/.applypilot/.env`. Without it, email-only applications must fail with `email_send_requires_consent` — do not improvise sending.

- Mutate/delete/labels/filters/settings remain **forbidden even when send is enabled**.

- CapSolver is for CAPTCHAs only; it is not Gmail access.



Title filtering: `exclude_titles` in `~/.applypilot/searches.yaml` (e.g. `junior`, `sdet`, `cloud engineer`, `devops`) is enforced at discovery insert, scoring, and tailor skip. Marketplace hosts (`auraone.ai`, Turing/Betterteam, Mercor, …) are skipped via `marketplace_hosts` in `sites.yaml` / `config.is_marketplace_url()`. Stage 6 queue prefers Greenhouse → Workday → Ashby; **Lever is skipped** (`skip_apply_hosts`) until CapSolver supports its hCaptcha. Tailor/cover require a usable ATS `application_url` (not LinkedIn/Indeed board pages). See [docs/discovery.md](docs/discovery.md).



### What not to do



- Do not edit `.venv/lib/.../site-packages/applypilot/` — use `src/applypilot/`.

- Do not route LLM calls around `llm.py` with ad-hoc `cursor-sdk` imports in scoring modules.

- Do not force Stage 6 onto Cursor when it's already configured — use `.venv/bin/applypilot` and `APPLY_BACKEND=cursor`.

- Do not commit `~/.applypilot/.env`, `~/.gmail-mcp/*`, or API keys.

- Do not delete `.env` when resetting user data.

- Do not enable or use Gmail send/mutate/settings tools unless the user explicitly asked and `APPLY_ALLOW_GMAIL_SEND` is set when sending is required.



## Testing



Helper scripts in `scripts/` (run from repo root via WSL):



| Script | Purpose |

|--------|---------|

| `test_cursor_provider.py` | Provider detection unit check (no network) |

| `live_cursor_score_test.py` | Live Cursor Auto LLM smoke test |

| `score_one_job.py` | Score one DB job end-to-end |

| `db_stats.py` | Print pipeline stats from SQLite |

| `test_playwright_pdf.py` | Verify Chromium PDF rendering |

| `install_playwright.sh` | Install Chromium + Linux deps |

| `generate_pdfs.py` | Batch convert `.txt` materials to PDF |

| `regenerate_pdfs_playwright.py` | Re-render PDFs from source `.txt` |
| `regenerate_materials.py` | Clear materials; re-run tailor + cover |
| `reformat_resume_pdfs.py` | Re-layout `.txt` + regenerate PDFs |
| `sync_resume_source.py` | Sync master resume → `~/.applypilot/resume.txt` |
| `refine_bmo_resume.py` | Re-tailor reference BMO job + PDF |
| `verify_no_merged_employers.py` | Check tailored text for merged employers |
| `reset_for_fresh_start.sh` | Clear jobs + materials for re-onboard |



```bash

.venv/bin/python scripts/test_cursor_provider.py

.venv/bin/python scripts/live_cursor_score_test.py   # needs CURSOR_API_KEY in ~/.applypilot/.env

```



Upstream tests: `pytest tests/ -v` (if present).



## Performance expectations



Cursor Auto calls are **much slower** than raw Gemini HTTP (~30–40s per call in practice) but avoid Gemini free-tier 15 RPM limits. Batch scoring 100+ jobs takes hours unless concurrency is raised carefully.



PDF generation via Playwright adds ~2–4s per document after Playwright deps are installed.



## Further reading



- [docs/ops.md](docs/ops.md) — Daily apply runbook, health checks, recent ops notes

- [docs/auto-apply.md](docs/auto-apply.md) — Stage 6 Cursor apply; Gmail read-only OTP; never send/update/delete/settings without consent

- [docs/discovery.md](docs/discovery.md) — Discovery sources, exclude_titles, marketplace hosts, Greenhouse-first ATS strategy

- [docs/cursor-llm.md](docs/cursor-llm.md) — Cursor provider design and configuration

- [docs/resume-tailoring.md](docs/resume-tailoring.md) — Tailor guardrails, layout, profile fields, scripts

- [docs/pdf-and-dashboard.md](docs/pdf-and-dashboard.md) — PDF pipeline and dashboard

- [docs/reset-onboard.md](docs/reset-onboard.md) — Clear data and re-run wizard

- [docs/development.md](docs/development.md) — WSL setup, editable install, scripts

- [README.md](README.md) — user-facing overview (upstream-oriented; see Cursor section)

