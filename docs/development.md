# Development — this checkout

Development notes specific to **this** ApplyPilot workspace, not generic upstream CONTRIBUTING.md.

## Environment

| Item | Value |
|------|-------|
| OS | Windows host, **WSL** for Python/runtime |
| Python | 3.11+ (venv at `.venv/`, Linux layout: `bin/python`) |
| Install mode | Editable (`pip install -e .`) |
| User data | `~/.applypilot/` inside WSL (`/home/<user>/.applypilot/`) |

### Install / reinstall

From WSL:

```bash
cd /mnt/c/Users/elihe/Projects/applypilot
python3 -m venv .venv   # only if recreating
.venv/bin/pip install -e ".[dev]" cursor-sdk
bash scripts/install_playwright.sh
```

**Playwright / Chromium (high-quality PDFs):** ApplyPilot renders resumes and cover letters via headless Chromium. The Python package alone is not enough — Linux system libraries are required in WSL:

```bash
# One-shot (prompts for sudo password if not root):
bash scripts/install_playwright.sh

# Or as WSL root from Windows (no password prompt):
wsl -u root -e bash -lc "cd /mnt/c/Users/elihe/Projects/applypilot && bash scripts/install_playwright.sh"
```

Verify with `scripts/test_playwright_pdf.py`. Regenerate existing materials after install:

```bash
.venv/bin/python scripts/regenerate_pdfs_playwright.py
```

JobSpy (discovery):

```bash
.venv/bin/pip install --no-deps python-jobspy
.venv/bin/pip install pydantic tls-client requests markdownify regex
```

### Running from Windows

Wrap commands in WSL:

```powershell
wsl -e bash -lc "cd /mnt/c/Users/elihe/Projects/applypilot && .venv/bin/applypilot doctor"
```

PowerShell `python` and `.venv\Scripts\` paths **do not work** with this venv.

## Source of truth

Edit files under `src/applypilot/`. The editable install maps imports there — do not patch `site-packages`.

Key files for the Cursor integration:

- `src/applypilot/llm.py` — provider implementation
- `src/applypilot/config.py` — tier detection
- `src/applypilot/wizard/init.py` — setup wizard
- `src/applypilot/cli.py` — `doctor` output

## Scripts (`scripts/`)

Ad-hoc utilities for development and smoke testing. Not installed as console entry points.

| Script | Description |
|--------|-------------|
| `test_cursor_provider.py` | Asserts `CURSOR_API_KEY` wins over Gemini in `_detect_provider()` |
| `live_cursor_score_test.py` | Single synthetic scoring prompt via live Cursor Auto |
| `score_one_job.py` | `run_scoring(limit=1)` against real DB |
| `db_stats.py` | Prints `get_stats()` from SQLite |
| `update_cursor_env.py` | Writes `CURSOR_API_KEY` into `~/.applypilot/.env` (pass key as argv) |
| `try_cursor_auth.py` | Probes cursor-sdk without API key (expects failure) |
| `install_playwright.sh` | Installs Chromium + Linux deps for high-quality PDFs |
| `test_playwright_pdf.py` | Verifies Playwright can render a test PDF |
| `generate_pdfs.py` | Batch convert existing `.txt` materials to named PDFs |
| `regenerate_pdfs_playwright.py` | Re-render PDFs from source `.txt` after Playwright install |
| `reset_for_fresh_start.sh` | Clear jobs, materials, dashboard; optional config wipe |

## Linting and tests

```bash
.venv/bin/ruff check src/
.venv/bin/pytest tests/ -v
```

## Debugging LLM issues

1. Confirm provider: `applypilot doctor` → should show `Cursor Auto (auto)`.
2. Check `~/.applypilot/.env` has `CURSOR_API_KEY` and `LLM_MODEL=auto`.
3. Run `scripts/live_cursor_score_test.py` — isolates `llm.py` from pipeline.
4. Enable logging: Python `logging` for `applypilot.llm` at DEBUG if needed.
5. If output fails to parse, inspect raw response and adjust `_OUTPUT_WRAPPER` in `llm.py`.

## Database inspection

SQLite at `~/.applypilot/applypilot.db`. Quick stats:

```bash
.venv/bin/python scripts/db_stats.py
```

Stage columns drive the pipeline (`fit_score IS NULL` → pending score, etc.). See `database.py` for `get_jobs_by_stage()` conditions.

## Chrome / auto-apply on WSL

Auto-apply (Stage 6) needs Chrome/Chromium and Node.js (`npx` for Playwright MCP). The **default agent is Cursor SDK** when `CURSOR_API_KEY` is set (`APPLY_BACKEND=cursor`). Full details: [auto-apply.md](auto-apply.md).

**Chrome on WSL:** If apt Chrome is not installed, set Playwright Chromium in `.env`:

```env
CHROME_PATH=/home/<user>/.cache/ms-playwright/chromium-1228/chrome-linux64/chrome
```

Or run `scripts/fix_env_chrome.py` after `bash scripts/install_playwright.sh`.

`get_chrome_path()` also auto-detects Playwright Chromium under `~/.cache/ms-playwright/`.

Verify CDP launch:

```bash
.venv/bin/python scripts/test_chrome_cdp.py
.venv/bin/applypilot doctor   # should show Tier 3 — Full Auto-Apply
```

**No GUI in WSL:** Use headless mode for auto-apply (no `DISPLAY`):

```bash
.venv/bin/applypilot apply --headless --dry-run -l 1   # test one job
.venv/bin/applypilot apply --headless -l 5             # submit up to 5
```

**Gmail OTP:** Place Desktop OAuth client JSON at `~/.gmail-mcp/gcp-oauth.keys.json`, then run `bash scripts/gmail_oauth_readonly.sh` (not the package’s default `auth`, which requests edit/send scopes). Confirm doctor shows **Gmail MCP auth OK**. Default use is **read-only** (verification codes). **Never** update, delete, change Gmail settings, or send mail without explicit consent (`APPLY_ALLOW_GMAIL_SEND=1` for send only) — see [auto-apply.md](auto-apply.md).

**Title filters:** `exclude_titles` in `~/.applypilot/searches.yaml` skips titles containing those substrings (e.g. `junior`, `sdet`) at discovery, score, and tailor. Marketplace hosts, Lever skip (`skip_apply_hosts`), and Greenhouse/Workday-first strategy: [discovery.md](discovery.md).

Stage 6 defaults to **Cursor SDK + Playwright MCP** when `CURSOR_API_KEY` is set. Use `.venv/bin/applypilot apply`.

Ensure `LLM_MODEL=auto` and preferably `APPLY_BACKEND=cursor` in `~/.applypilot/.env`.

## PDF output and dashboard

Tailored resumes and cover letters are saved as **named PDFs** (e.g. `Hebdon_Full_Stack_Developer_indeed_Resume.pdf`) under `~/.applypilot/tailored_resumes/` and `cover_letters/`. See [pdf-and-dashboard.md](pdf-and-dashboard.md) and [resume-tailoring.md](resume-tailoring.md) (guardrails, profile fields, maintenance scripts).

```bash
.venv/bin/applypilot run pdf          # convert any remaining .txt materials
.venv/bin/applypilot dashboard        # generate HTML review page
```

Open dashboard from Windows: `\\wsl.localhost\Ubuntu\home\<user>\.applypilot\dashboard.html`

## Reset for fresh start

```bash
bash scripts/reset_for_fresh_start.sh
.venv/bin/applypilot init
```

Details: [reset-onboard.md](reset-onboard.md).

## Related docs

- [AGENTS.md](../AGENTS.md) — agent orientation
- [cursor-llm.md](cursor-llm.md) — Cursor provider design
- [pdf-and-dashboard.md](pdf-and-dashboard.md) — PDF pipeline and dashboard
- [reset-onboard.md](reset-onboard.md) — clear data and re-run wizard
- [CONTRIBUTING.md](../CONTRIBUTING.md) — upstream contribution guidelines
