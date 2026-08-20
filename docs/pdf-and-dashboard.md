# PDF materials and dashboard

ApplyPilot generates **upload-ready PDFs** for tailored resumes and cover letters, and an HTML **dashboard** to review jobs and open materials from Windows.

## PDF pipeline

```
LLM writes .txt  →  parse + HTML template  →  Playwright Chromium  →  named .pdf
                                              ↘  xhtml2pdf (fallback if Chromium unavailable)
```

Implementation: [`src/applypilot/scoring/pdf.py`](../src/applypilot/scoring/pdf.py)

| Stage | What happens |
|-------|----------------|
| Tailor / cover | LLM output saved as `{site}_{title}.txt` or `{site}_{title}_CL.txt` |
| Convert | Text parsed into structured HTML (resume sections or cover letter layout) |
| Render | Headless Chromium via Playwright (`page.pdf()`) |
| Fallback | `xhtml2pdf` if Playwright/Chromium fails (lower fidelity, no extra deps beyond pip) |
| Store | DB column updated to PDF path; source `.txt` kept for re-render |

### Filename convention

Upload-ready names use last name + role + site + type:

```
Hebdon_Full_Stack_Developer_indeed_Resume.pdf
Hebdon_Full_Stack_Developer_indeed_CoverLetter.pdf
```

Built by `build_material_filename()` in `pdf.py`.

### Resume layout

Tailored resumes use a **canonical two-line employer block** (company + location, then title + dates) with uniform disc-list bullets. Layout is assembled in `resume_format.py` and rendered in `pdf.py`. One-page PDFs compact content first, then scale typography slightly to fill remaining space.

Employer guardrails (separate Equifax / Kount Inc entries, no merged headers) are documented in [resume-tailoring.md](resume-tailoring.md).

### When PDFs are created

- **Automatically** at end of `applypilot run tailor` and `applypilot run cover` (each approved job).
- **Batch convert** for older `.txt`-only materials: `applypilot run pdf` or `scripts/generate_pdfs.py`.
- **Re-render** after Playwright install: `scripts/regenerate_pdfs_playwright.py`.

### Playwright setup (WSL)

High-quality PDFs need Chromium **and** Linux system libraries in WSL:

```bash
bash scripts/install_playwright.sh
```

From Windows without a sudo password prompt:

```powershell
wsl -u root -e bash -lc "cd /mnt/c/Users/elihe/Projects/applypilot && bash scripts/install_playwright.sh"
```

Verify: `.venv/bin/python scripts/test_playwright_pdf.py`

### Output locations

| Path | Contents |
|------|----------|
| `~/.applypilot/tailored_resumes/` | `{LastName}_{Title}_{Site}_Resume.pdf` + source `.txt` |
| `~/.applypilot/cover_letters/` | `{LastName}_{Title}_{Site}_CoverLetter.pdf` + source `_CL.txt` |

Windows browse path (WSL Ubuntu):

```
\\wsl.localhost\Ubuntu\home\<user>\.applypilot\tailored_resumes\
```

## Dashboard

Command: `applypilot dashboard`

Generates `~/.applypilot/dashboard.html` with clickable top modules:

| Module | Contents |
|--------|----------|
| **Overview** | Pipeline counts, score distribution, source breakdown; red banner when daily apply is blocked (expired Gmail token, etc.) |
| **Jobs** | Scored listings (5+), filterable by score / search |
| **Applied** | Submitted applications with status, timestamps, JD, materials |
| **Failed** | Failed / skipped apply attempts (CAPTCHA, location, host skips, etc.) |

Deep-link with hash: `dashboard.html#applied`, `#jobs`, `#failed`, `#overview`.

Job cards show fit score, reasoning, expandable full description, and action links:

| Link | Target |
|------|--------|
| **Apply / Open Application** | Job application URL (`application_url`) |
| **Resume (PDF)** | Tailored resume PDF |
| **Cover Letter (PDF)** | Cover letter PDF |

Applied cards also surface `apply_status`, `applied_at`, any `apply_error` note, and Gmail outcome badges (`confirmed` / `rejected` / `interview` / `offer`). Treat those badges as hints — see [ops.md](ops.md) for matcher limits.

Implementation: [`src/applypilot/view.py`](../src/applypilot/view.py)

### Opening from Windows

Auto-open from WSL often fails (`gio: No application registered`). Open manually:

```
\\wsl.localhost\Ubuntu\home\<user>\.applypilot\dashboard.html
```

Material links use `file://wsl.localhost/Ubuntu/home/<user>/...` so PDFs open in the Windows browser.

Regenerate after pipeline runs or PDF conversion:

```bash
.venv/bin/applypilot dashboard
```
