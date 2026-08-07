# Resume tailoring — guardrails and job matching

ApplyPilot's tailor stage rewrites your base resume for each high-scoring job, validates the output, and renders an upload-ready one-page PDF. The design goal is **strong job-specific tailoring** within **hard factual guardrails** — reorder and reframe real work, never invent employers or skills.

Implementation lives in `src/applypilot/scoring/`:

| Module | Role |
|--------|------|
| `tailor.py` | LLM prompt, JSON extraction, LLM judge, batch runner |
| `validator.py` | Structural checks, fabrication detection, banned words |
| `employment.py` | Employer separation guardrails (Equifax ≠ Kount Inc) |
| `resume_format.py` | Plain-text layout assembly (canonical resume format) |
| `pdf.py` | HTML template, one-page compaction, PDF render |

See also [pdf-and-dashboard.md](pdf-and-dashboard.md) for PDF output paths and dashboard links.

## Pipeline flow

```
resume.txt + profile.json + job description
        ↓
   LLM → JSON (title, summary, skills, experience[], education, …)
        ↓
   normalize_experience_entries()  — fix merged headers, fill company/location/dates
        ↓
   validate_json_fields()         — structure, skills, employers, school
        ↓
   assemble_resume_text()          — code-injected header + canonical layout
        ↓
   validate_tailored_resume()      — sections, company header lines, merged employers (live path)
        ↓
   judge_tailored_resume()         — catch subtle fabrication (skipped in lenient mode)
        ↓
   save .txt → convert_to_pdf()    — Playwright Chromium, one-page fill
        ↓
   DB: tailored_resume_path → PDF
```

Header contact info (name, location, email, phone) is **always code-injected** from `profile.json` — the LLM never generates it.

## What tailoring is allowed to change

These are intentional — they improve fit for the job posting:

| Area | Allowed |
|------|---------|
| **Title line** | Match target role and seniority (e.g. "Senior Cloud Engineer") |
| **Summary** | Rewrite from scratch for the job; lead with relevant skills |
| **Skills** | Reorder categories; put job must-haves first |
| **Experience bullets** | Reframe every bullet for the role; vary verbs; emphasize relevant outcomes |
| **Bullet length** | Full sentences (~28–45 words); Equifax 4 bullets, Kount 3, CHPC 1–2 |
| **Related tools** | Add 2–3 *learnable* tools adjacent to your stack (e.g. Redis if PostgreSQL) |
| **Projects** | Work-product initiatives fold into employer bullets; personal apps stay in a `PROJECTS` section (reorder/drop by relevance) |

The LLM judge explicitly **allows** rewording, reordering, combining/splitting bullets, and minor stretches of closely related skills. It **fails** major lies: fake companies, fake degrees, invented projects, wildly inflated numbers, unrelated-domain skills.

## Hard guardrails (validation errors)

These trigger retries (or failed validation on last attempt):

### Employers — never merge

Kount Inc and Equifax are **separate employers**. The validator rejects:

- Merged headers: `Kount Inc (Equifax)`, `Kount, an Equifax Company`, etc.
- Missing separate `experience[]` entry per row in `employment_history`
- Missing company name on its own header line in rendered text

Canonical source: `profile.json` → `resume_facts.employment_history`:

```json
"employment_history": [
  { "company": "Equifax", "title": "Software Development Engineer", "subtitle": "Boise, ID | June 2025-Present" },
  { "company": "Kount Inc", "title": "Software Development Engineer / SDET", "subtitle": "Boise, ID | May 2021-June 2025" },
  { "company": "Center for High Performance Computing (CHPC)", "title": "IT Intern", "subtitle": "Salt Lake City, UT | 2019-2020" }
]
```

Each JSON experience entry uses **`company`, `location`, `title`, `dates`, `bullets`** — not a merged `"Title at Company"` header.

### Skills — no fabrication

- Skills must come from `profile.json` → `skills_boundary` (plus a small related set). Soft allowlist warns in normal mode; strict mode errors.
- `FABRICATION_WATCHLIST` flags unrelated languages/frameworks **only when they are not in your `skills_boundary`**.
- Banned filler words: **strict** = errors/retries; **normal** = warnings; **lenient** = ignored. Prefer concrete verbs in the base resume and profile `additional_information`.
- Scanning focuses on the TECHNICAL SKILLS block and full-document watchlist vs. base resume.

### Facts — preserved entities

From `resume_facts`:

| Field | Rule |
|-------|------|
| `preserved_companies` | Each must appear as its own experience entry |
| `preserved_school` | Must appear in education |
| `preserved_projects` | Warn if renamed/dropped (not a hard error) |
| `real_metrics` | Numbers must not be inflated (judge + validator) |

### Structure and voice

- Required JSON fields: `title`, `summary`, `skills`, `experience`, `education` (`projects` optional)
- Banned filler words — severity depends on validation mode (see below)
- LLM meta-commentary (`"here is the revised"`, etc.) is always an error
- No em dashes in output (auto-sanitized to commas)

## Validation modes

Pass to `applypilot run --validation {strict|normal|lenient}`:

| Mode | Banned words | Fabrication / structure | Judge |
|------|--------------|-------------------------|-------|
| **strict** | Hard errors → retry | Hard errors | Runs |
| **normal** (default) | Warnings only | Hard errors | Runs |
| **lenient** | Ignored | Hard errors | Skipped |

Use **normal** for Cursor Auto. Use **lenient** only when the provider struggles with stylistic rules but facts are correct.

## Canonical resume layout

Tailored plain text and PDFs follow a fixed layout (see `resume_format.py` + `pdf.py`):

```
Name
Role Title
City, State ZIP • email • phone

PROFESSIONAL SUMMARY
…

TECHNICAL SKILLS
* Category: skill, skill, …

PROFESSIONAL EXPERIENCE

EQUIFAX                              Boise, ID
Software Development Engineer        June 2025-Present
* …

KOUNT INC                            Boise, ID
Software Development Engineer / SDET May 2021-June 2025
* …

PROJECTS
* AnyWidget: …
* BrainLock: …
* Pellego: …

EDUCATION
UNIVERSITY OF UTAH                   Salt Lake City, UT
Bachelor of Science …                2021

ADDITIONAL INFORMATION  (optional when space allows)
* Proficient Russian speaker, …
```

PDF rendering uses uniform disc-list bullets across experience, education, and additional info. One-page fit uses content compaction first, then slight typography scale-up when space allows.

## Profile setup for tailoring

After `applypilot init`, extend `~/.applypilot/profile.json` as needed:

```json
"resume_facts": {
  "preserved_companies": ["Equifax", "Kount Inc", "Center for High Performance Computing (CHPC)"],
  "preserved_school": "University of Utah",
  "preserved_projects": ["Reusable Identity Platform", "MultiFactor Authentication Service", "…"],
  "personal_projects": [
    {"name": "AnyWidget", "description": "Android home screen widget app. …"},
    {"name": "BrainLock", "description": "iOS App locker featuring brain puzzles. …"},
    {"name": "Pellego", "description": "Java e-reading application with AWS Cognito & DynamoDB. …"}
  ],
  "real_metrics": ["99.9%", "~30k daily users", "sub-100ms", "25%", "30%", "1k downloads", "20%"],
  "employment_history": [ … ],
  "education_details": {
    "school": "University of Utah",
    "location": "Salt Lake City, UT",
    "degree": "Bachelor of Science in Computer Science, Minor in Russian",
    "year": "2021",
    "highlights": ["Recipient of the Utah Flagship Scholarship", "…"]
  },
  "additional_information": "Proficient Russian speaker, Google Play Store application developer, Passionate digital artist"
},
"skills_boundary": {
  "programming_languages": ["Golang", "Typescript", "Javascript", "Python", "Kotlin", "Java", …],
  "frameworks": ["Angular", "RxJS", "Node.js", "Kotlin Multiplatform"],
  "tools": ["Docker", "AWS", "Gitlab CI/CD", "Firebase", "MySQL", …]
}
```

`preserved_projects` = work-product initiatives (identity platform, MFA, K360) referenced inside experience bullets.
`personal_projects` = AnyWidget / BrainLock / Pellego for the standalone `PROJECTS` section.

Keep `~/.applypilot/resume.txt` aligned with your canonical resume (separate Equifax / Kount sections). Sync from a master file:

```bash
.venv/bin/python scripts/sync_resume_source.py
```

## Output files

| File | Purpose |
|------|---------|
| `{site}_{title}.txt` | Source tailored text (debug / re-render) |
| `{LastName}_{Title}_{Site}_Resume.pdf` | Upload-ready PDF (DB path) |
| `{site}_{title}_REPORT.json` | Validator + judge result per job |

**Dashboard links always use the PDF path** in `applypilot.db`. If layout code changes, re-run PDF conversion — stale PDFs can show old formatting even when `.txt` sources are updated.

```bash
.venv/bin/applypilot run pdf
# or
.venv/bin/python scripts/reformat_resume_pdfs.py
```

## Maintenance scripts

| Script | Purpose |
|--------|---------|
| `scripts/sync_resume_source.py` | Copy master resume → `~/.applypilot/resume.txt` (+ PDF); update `employment_history`, `personal_projects`, skills |
| `scripts/regenerate_materials.py` | Clear DB material paths; re-run tailor + cover |
| `scripts/reformat_resume_pdfs.py` | Re-layout existing `.txt` + regenerate PDFs |
| `scripts/refine_bmo_resume.py` | Re-tailor one reference job (BMO Senior Cloud Engineer) |
| `scripts/verify_no_merged_employers.py` | Fail if any tailored text merges Kount + Equifax |
| `scripts/summarize_tailor_failures.py` | Aggregate validation errors from `_REPORT.json` files |

## Tuning tailoring behavior

| Goal | Where to change |
|------|-----------------|
| Job-specific emphasis | `_build_tailor_prompt()` in `tailor.py` |
| Employer rules | `employment.py` + tailor prompt EMPLOYER RULES block |
| Allowed skills | `profile.json` → `skills_boundary` |
| Bullet length / density | Tailor prompt BULLETS section; `_COMPACT_LIMITS` in `pdf.py` |
| PDF layout / fonts | `_resume_css()`, `build_html()` in `pdf.py` |
| Strictness | `--validation` flag or `validation_mode=` in `run_tailoring()` |

When adding guardrails, prefer **validator errors for facts** and **prompt guidance for style** — over-restricting bullet wording blocks legitimate job matching.

## Common issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| Company names missing in PDF | Stale PDF or compaction bug | `applypilot run pdf` or `reformat_resume_pdfs.py` |
| `Kount Inc (Equifax)` in output | Old resume source or prompt drift | Run `sync_resume_source.py`; check `employment_history` |
| Tailor fails on `angular` / `golang` | Skill not in `skills_boundary` | Add to boundary if true, or remove from base resume |
| Inconsistent bullet styling | Mixed HTML render paths | Fixed in `pdf.py` — regenerate PDFs |
| PDF has empty bottom half | Content too sparse | Re-tailor with denser bullets; check one-page scale-up in `render_resume_pdf_one_page()` |

## Commands

```bash
# Tailor jobs scored 7+ (default threshold)
.venv/bin/applypilot run tailor

# Tailor + cover + PDF in one go
.venv/bin/applypilot run tailor cover pdf

# Relax validation for flaky LLM output
.venv/bin/applypilot run tailor --validation lenient

# Re-tailor everything from scratch
.venv/bin/python scripts/regenerate_materials.py
```
