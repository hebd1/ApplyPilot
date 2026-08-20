<!-- logo here -->

> **⚠️ ApplyPilot** is the original open-source project, created by [Pickle-Pixel](https://github.com/Pickle-Pixel) and first published on GitHub on **February 17, 2026**. We are **not affiliated** with applypilot.app, useapplypilot.com, or any other product using the "ApplyPilot" name. These sites are **not associated with this project** and may misrepresent what they offer. If you're looking for the autonomous, open-source job application agent — you're in the right place.

# ApplyPilot

**Applied to 1,000 jobs in 2 days. Fully autonomous. Open source.**

[![PyPI version](https://img.shields.io/pypi/v/applypilot?color=blue)](https://pypi.org/project/applypilot/)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: AGPL-3.0](https://img.shields.io/badge/license-AGPL--3.0-green.svg)](LICENSE)
[![GitHub stars](https://img.shields.io/github/stars/Pickle-Pixel/ApplyPilot?style=social)](https://github.com/Pickle-Pixel/ApplyPilot)
[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/S6S01UL5IO)




https://github.com/user-attachments/assets/7ee3417f-43d4-4245-9952-35df1e77f2df


---

## What It Does

ApplyPilot is a 6-stage autonomous job application pipeline. It discovers jobs across 5+ boards, scores them against your resume with AI, tailors your resume per job, writes cover letters, and **submits applications for you**. It navigates forms, uploads documents, answers screening questions, all hands-free.

Three commands. That's it.

```bash
pip install applypilot
pip install --no-deps python-jobspy && pip install pydantic tls-client requests markdownify regex
applypilot init          # one-time setup: resume, profile, preferences, API keys
applypilot doctor        # verify your setup — shows what's installed and what's missing
applypilot run           # discover > enrich > score > tailor > cover letters > PDFs
applypilot dashboard     # HTML job board with Apply / Resume / Cover links
applypilot run -w 4      # same but parallel (4 threads for discovery/enrichment)
applypilot apply         # autonomous browser-driven submission
applypilot apply -w 3    # parallel apply (3 Chrome instances)
applypilot apply --dry-run  # fill forms without submitting
```

> **Why two install commands?** `python-jobspy` pins an exact numpy version in its metadata that conflicts with pip's resolver, but works fine at runtime with any modern numpy. The `--no-deps` flag bypasses the resolver; the second command installs jobspy's actual runtime dependencies. Everything except `python-jobspy` installs normally.

---

## Two Paths

### Full Pipeline (recommended)
**Requires:** Python 3.11+, Node.js (for npx), LLM API key, Chrome

Runs all 6 stages, from job discovery to autonomous application submission. This is the full power of ApplyPilot.

### Discovery + Tailoring Only
**Requires:** Python 3.11+, LLM provider (Cursor Auto, Gemini, OpenAI, or local)

Runs stages 1-5: discovers jobs, scores them, tailors your resume, generates cover letters. You submit applications manually with the AI-prepared materials.

### Cursor Auto LLM + auto-apply (this checkout)

This workspace includes a **Cursor Auto** LLM provider for scoring/tailoring/cover letters, and a **Cursor SDK auto-apply** backend for Stage 6 (default when `CURSOR_API_KEY` is set). Configure `CURSOR_API_KEY`, `LLM_MODEL=auto`, and optionally `APPLY_BACKEND=cursor` in `~/.applypilot/.env`.

Always run via the editable install so you do not hit an older PATH binary:

```bash
.venv/bin/applypilot apply --dry-run -l 1   # fill form, do not submit
.venv/bin/applypilot apply --headless -l 1  # real submit, one job
```

See [docs/cursor-llm.md](docs/cursor-llm.md), [docs/auto-apply.md](docs/auto-apply.md), [docs/ops.md](docs/ops.md), and [AGENTS.md](AGENTS.md).

### PDF output and dashboard (this checkout)

Stages 4–5 produce **upload-ready PDFs** with professional formatting:

- Resumes: `~/.applypilot/tailored_resumes/{LastName}_{Role}_{Site}_Resume.pdf`
- Cover letters: `~/.applypilot/cover_letters/{LastName}_{Role}_{Site}_CoverLetter.pdf`

Rendered via Playwright Chromium (with xhtml2pdf fallback). Install deps in WSL: `bash scripts/install_playwright.sh`

Review jobs and open materials:

```bash
applypilot dashboard
```

Open from Windows: `\\wsl.localhost\Ubuntu\home\<user>\.applypilot\dashboard.html`

See [docs/pdf-and-dashboard.md](docs/pdf-and-dashboard.md) and [docs/resume-tailoring.md](docs/resume-tailoring.md) (guardrails, layout, profile setup).

To clear all jobs and materials and re-onboard: [docs/reset-onboard.md](docs/reset-onboard.md).

---

## The Pipeline

| Stage | What Happens |
|-------|-------------|
| **1. Discover** | JobSpy (Indeed + ZipRecruiter by default) + Workday portals + smart-extract remote boards + curated Greenhouse boards — see [docs/discovery.md](docs/discovery.md) |
| **2. Enrich** | Fetches full job descriptions via JSON-LD, CSS selectors, or AI-powered extraction |
| **3. Score** | AI rates every job 1-10 based on your resume and preferences. Only high-fit jobs proceed |
| **4. Tailor** | AI rewrites your resume per job, exports a styled **PDF** ready to upload |
| **5. Cover Letter** | AI generates a targeted cover letter per job as a styled **PDF** |
| **6. Auto-Apply** | Cursor SDK navigates forms, uploads materials, and submits |

Each stage is independent. Run them all or pick what you need.

---

## ApplyPilot vs The Alternatives

| Feature | ApplyPilot | AIHawk | Manual |
|---------|-----------|--------|--------|
| Job discovery | 5 boards + Workday + direct sites | LinkedIn only | One board at a time |
| AI scoring | 1-10 fit score per job | Basic filtering | Your gut feeling |
| Resume tailoring | Per-job AI rewrite | Template-based | Hours per application |
| Auto-apply | Full form navigation + submission | LinkedIn Easy Apply only | Click, type, repeat |
| Supported sites | Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs, 46 Workday portals, 28 direct sites | LinkedIn | Whatever you open |
| License | AGPL-3.0 | MIT | N/A |

---

## Requirements

| Component | Required For | Details |
|-----------|-------------|---------|
| Python 3.11+ | Everything | Core runtime |
| Node.js 18+ | Auto-apply | Needed for `npx` to run Playwright MCP server |
| LLM provider | Scoring, tailoring, cover letters | **Cursor Auto** (`CURSOR_API_KEY`), **Gemini** (free tier), OpenAI, or local (`LLM_URL`) |
| Chrome/Chromium | Auto-apply | Auto-detected on most systems |

**LLM providers:** This checkout prefers **Cursor Auto** (`CURSOR_API_KEY` from [cursor.com/dashboard/integrations](https://cursor.com/dashboard/integrations), `LLM_MODEL=auto`). Auto-apply also defaults to Cursor when that key is set (`APPLY_BACKEND=cursor`). Gemini is still supported ([aistudio.google.com](https://aistudio.google.com), free tier ~15 RPM). OpenAI and local models (Ollama/llama.cpp) also work.

### Optional

| Component | What It Does |
|-----------|-------------|
| CapSolver API key | Solves CAPTCHAs during auto-apply (hCaptcha, reCAPTCHA, Turnstile, FunCaptcha). Without it, CAPTCHA-blocked applications just fail gracefully |

> **Note:** python-jobspy is installed separately with `--no-deps` because it pins an exact numpy version in its metadata that conflicts with pip's resolver. It works fine with modern numpy at runtime.

---

## Configuration

All generated by `applypilot init`:

### `profile.json`
Your personal data in one structured file: contact info, work authorization, compensation, experience, **`skills_boundary`** (allowed tools for validation), and **`resume_facts`** (preserved companies, employment history, metrics, education). Powers scoring, tailoring, and form auto-fill. See [resume-tailoring.md](docs/resume-tailoring.md) for `employment_history` and guardrail fields.

### `searches.yaml`
Job search queries, target titles, locations, boards. Run multiple searches with different parameters.

### `.env`
API keys and runtime config: `CURSOR_API_KEY` (Cursor Auto + apply), `GEMINI_API_KEY`, `LLM_MODEL`, `CURSOR_MAX_CONCURRENCY` (optional), `CAPSOLVER_API_KEY` (optional), `CHROME_PATH` (optional), `APPLY_ALLOW_GMAIL_SEND` (optional; off by default — only enable with explicit consent to send mail).

### Package configs (shipped with ApplyPilot)
- `config/employers.yaml` - Workday employer registry (48 preconfigured)
- `config/sites.yaml` - Direct career sites (30+), blocked sites, base URLs, manual ATS domains
- `config/searches.example.yaml` - Example search configuration

---

## How Stages Work

### Discover
Queries Indeed / ZipRecruiter via JobSpy (LinkedIn deprioritized — bot friction / weak apply URLs). Scrapes Workday employer portals (`employers.yaml`). Hits remote career sites plus curated Greenhouse boards (`greenhouse_boards.yaml`). Drops marketplace hosts (AuraOne, Turing, …) and excluded titles (junior, SDET, …) early. Stage 6 prefers Greenhouse/Workday and **skips Lever** for now (`skip_apply_hosts`). Deduplicates by URL. Details: [docs/discovery.md](docs/discovery.md).

### Enrich
Visits each job URL and extracts the full description. 3-tier cascade: JSON-LD structured data, then CSS selector patterns, then AI-powered extraction for unknown layouts.

### Score
AI scores every job 1-10 against your profile. 9-10 = strong match, 7-8 = good, 5-6 = moderate, 1-4 = skip. Only jobs above your threshold proceed to tailoring.

### Tailor
Generates a custom resume per job: matches the role title, rewrites summary and bullets for the posting, reorders skills, and exports a styled **one-page PDF**. Hard guardrails prevent merged employers, fabricated skills, and invented experience; reframing and keyword emphasis are encouraged. See [docs/resume-tailoring.md](docs/resume-tailoring.md).

### Cover Letter
Writes a targeted cover letter per job referencing the specific company, role, and how your experience maps to their requirements.

### Auto-Apply
By default this checkout uses a **Cursor SDK agent + Playwright MCP** against Chrome CDP, with **Gmail MCP** for read-only OTP retrieval (`~/.gmail-mcp/`). The agent navigates the application page, fills fields, uploads the tailored resume (and cover letter when present), answers screening questions, and submits unless `--dry-run` is set.

Gmail is **read-only by default** (search/read for verification codes only). **Never** update, delete, change Gmail settings, or send mail without explicit consent. Outbound mail alone can be opted in with `APPLY_ALLOW_GMAIL_SEND=1`; mutate/settings remain forbidden. See [docs/auto-apply.md](docs/auto-apply.md).

```bash
# Prefer the editable install
.venv/bin/applypilot apply --dry-run -l 1
.venv/bin/applypilot apply --headless -l 5 -w 1
```

---

## CLI Reference

```
applypilot init                         # First-time setup wizard
applypilot doctor                       # Verify setup, diagnose missing requirements
applypilot run [stages...]              # Run pipeline stages (or 'all')
applypilot run --workers 4              # Parallel discovery/enrichment
applypilot run --stream                 # Concurrent stages (streaming mode)
applypilot run --min-score 8            # Override score threshold
applypilot run --dry-run                # Preview without executing
applypilot run --validation lenient     # Relax validation (recommended for Gemini free tier)
applypilot run --validation strict      # Strictest validation (retries on any banned word)
applypilot apply                        # Launch auto-apply
applypilot apply --workers 3            # Parallel browser workers
applypilot apply --dry-run              # Fill forms without submitting
applypilot apply --continuous           # Run forever, polling for new jobs
applypilot apply --headless             # Headless browser mode
applypilot apply --url URL              # Apply to a specific job
applypilot status                       # Pipeline statistics
applypilot dashboard                    # Open HTML results dashboard
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding standards, and PR guidelines.

For this checkout's Cursor integration and WSL dev workflow, see [AGENTS.md](AGENTS.md) and [docs/development.md](docs/development.md).

---

## License

ApplyPilot is licensed under the [GNU Affero General Public License v3.0](LICENSE).

You are free to use, modify, and distribute this software. If you deploy a modified version as a service, you must release your source code under the same license.
