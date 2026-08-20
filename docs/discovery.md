# Job discovery — matching and ATS-friendly sources

This checkout discovers jobs from multiple sources, then enriches, scores, and (optionally) auto-applies. The goal is **roles that match your stack** and **apply URLs that Stage 6 can actually fill** (Greenhouse / Workday first; Ashby secondary), not marketplace junk from Indeed feeds.

## Pipeline

```text
JobSpy (Indeed, ZipRecruiter, …)
    + Workday CXS API (employers.yaml)
    + smart-extract (sites.yaml + greenhouse_boards.yaml)
        → enrich (full JD + application_url)
        → score (LLM fit 1–10)
        → tailor / cover / pdf
        → apply (prefer Greenhouse-first queue)
```

Orchestration: `pipeline._run_discover()` runs JobSpy → Workday → smart-extract sequentially.

## What to put in `~/.applypilot/searches.yaml`

Keys the code **actually reads**:

| Key | Used by | Purpose |
|-----|---------|---------|
| `queries` | all discovery | `{query, tier}` search terms |
| `locations` | JobSpy / smart-extract | `{location, remote}` |
| `sites` | JobSpy | Board list: `indeed`, `zip_recruiter`, … (**not** `boards`) |
| `defaults` | JobSpy | `results_per_site`, `hours_old` |
| `exclude_titles` | discover insert, score, tailor | Case-insensitive title substrings to skip |
| `location_accept` | JobSpy / Workday / smart-extract | Allow location text |
| `location_reject_non_remote` | same | Reject non-remote mismatches |
| `workday_max_tier` | Workday | Max query tier (default 2) |
| `proxy` | JobSpy / Workday | Optional |

Example package file: [`src/applypilot/config/searches.example.yaml`](../src/applypilot/config/searches.example.yaml).

### Title exclusions

`exclude_titles` drops roles before they waste LLM tokens. This fork’s defaults include junior/intern, QA/SDET-style titles, and **cloud/devops/SRE** titles (`cloud engineer`, `devops`, `site reliability`, …).

Tailor and cover only run for jobs with a **usable `application_url`** (real ATS/career link — not LinkedIn/Indeed board pages). That keeps daily prep from burning tokens on listings Stage 6 will skip anyway.

Enforced in:

- Discovery insert (`jobspy`, `workday`, `smartextract`, `database.store_jobs`)
- Scoring short-circuit → score `1`
- Tailor skip

### Skill-oriented queries

Tune tier 1 toward your resume (e.g. Backend, Golang, TypeScript, Angular, Full Stack). Use tier 2 for broader SWE + light platform/cloud. Keep tier 3 small.

## Marketplace hosts (early drop)

**Marketplace hosts** are sites that look like jobs on Indeed/LinkedIn but are **not employer ATS applications** — contractor profiles, AI-eval labs, talent networks. Examples: `auraone.ai`, Turing/`betterteam.com`, Mercor, Toptal, Upwork.

Configured in [`sites.yaml`](../src/applypilot/config/sites.yaml) as `marketplace_hosts`. Helpers: `config.is_marketplace_url()`.

Behavior:

- Skip at discovery insert
- `classify_apply_url` → `marketplace_host`
- Stage 6 `acquire_job` → `apply_status=failed`, `apply_error=marketplace`
- Scoring short-circuit → score `1`
- Apply agent prompt refuses AuraOne / Mercor / Turing / etc. as `not_a_job_application`

## Prefer Greenhouse (and sibling ATS)

There is no global “search all Greenhouse” API without a company board list. This fork biases toward apply-friendly ATS:

1. **Queue order** (`acquire_job`): Greenhouse → Workday → Ashby → other http apply URLs → rest  
2. **Soft score boost** (+1, capped at 10) when fit ≥ 6 and apply URL is preferred ATS  
3. **Curated boards**: [`greenhouse_boards.yaml`](../src/applypilot/config/greenhouse_boards.yaml) prepended to smart-extract targets  
4. **Remote boards** in `sites.yaml` (Remotive, WeWorkRemotely, Himalayas, BuiltIn, …) often deep-link to Greenhouse/Workday  
5. **Skip Lever for now**: `skip_apply_hosts: [lever.co]` — Lever hCaptcha is unsupported by CapSolver (Bellese/Lyra failures). Jobs still discover; Stage 6 marks `skip_ats:…` and moves on.

`preferred_ats_hosts` in `sites.yaml` documents the host list (Lever omitted while skipped).

Indeed / LinkedIn posts are useful **when enrich resolves** a real ATS `application_url` (company-website apply). Board-only or Easy Apply destinations remain `weak_apply_url` / manual.

LinkedIn discovery is enabled in `searches.example.yaml`. Enrich parses LinkedIn's embedded `applyUrl` (when present) and follows redirects to Greenhouse/Workday/Ashby. Public LinkedIn pages hide that target behind a sign-in wall. Capture a session with:

```bash
.venv/bin/applypilot linkedin-auth --login     # one-time browser sign-in
.venv/bin/applypilot linkedin-auth --refresh   # pull rotated li_at from profile
.venv/bin/applypilot linkedin-auth --check     # validate current cookie
```

`scripts/daily_apply.sh` runs `--refresh` automatically each morning (`DAILY_APPLY_LINKEDIN_REFRESH=1`).

`--refresh` reads the persistent `~/.applypilot/linkedin-chrome/` profile. Doctor `--check` can still be green on `LINKEDIN_LI_AT` in `.env` while the profile is logged out — in that case morning refresh warns and LinkedIn listings often keep a missing `application_url` (no tailor/apply). Re-login with `--login` when that happens.

Or set `LINKEDIN_LI_AT` in `~/.applypilot/.env`. Easy Apply-only jobs stay manual.

## Source strategy (bot detection vs automation)

| Source | Role | Notes |
|--------|------|-------|
| Workday CXS | Discovery + apply URL | Structured JSON; location eligibility still checked at apply |
| Remotive / WWR / Himalayas / BuiltIn | Discovery | Lower bot friction than LinkedIn; often ATS deep links |
| Greenhouse / Workday boards | Discovery + apply | Best Stage 6 success so far |
| Ashby | Discovery + apply | Secondary preferred ATS |
| Lever | Discover only (skip apply) | hCaptcha unsupported by CapSolver — `skip_apply_hosts` |
| LinkedIn | Discovery + apply resolve | Best match quality; needs `linkedin-auth` / `LINKEDIN_LI_AT` for off-site ATS URLs. Easy Apply = manual |


| Indeed (JobSpy) | Discovery volume | Needs enrich + marketplace denylist |
| ZipRecruiter | Discovery | Same pattern as Indeed |
| iCIMS + Auth0/SSO | Avoid preferring | Login walls → `LOGIN_ISSUE` |

Stage 6 still uses CapSolver for CAPTCHAs and **read-only** Gmail OTP. Never send/update/delete Gmail or change settings without explicit consent — see [auto-apply.md](auto-apply.md).

## Related files

| Piece | Path |
|-------|------|
| Search example | `src/applypilot/config/searches.example.yaml` |
| Sites / marketplace / preferred ATS | `src/applypilot/config/sites.yaml` |
| Greenhouse boards | `src/applypilot/config/greenhouse_boards.yaml` |
| Workday employers | `src/applypilot/config/employers.yaml` |
| Title / marketplace helpers | `src/applypilot/config.py` |
| Apply URL quality | `src/applypilot/job_meta.py` |
| Scoring prompt | `src/applypilot/scoring/scorer.py` |
| Apply queue | `src/applypilot/apply/launcher.py` |
