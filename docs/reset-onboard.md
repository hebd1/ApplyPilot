# Reset and re-onboard

Use this when you want to **clear discovered jobs and generated materials** and run the setup wizard again with updated profile, resume, or search config.

## What gets cleared

Script: `scripts/reset_for_fresh_start.sh`

| Item | Default reset | `--keep-config` |
|------|---------------|-----------------|
| All jobs in `applypilot.db` | Deleted | Deleted |
| `tailored_resumes/*` | Deleted | Deleted |
| `cover_letters/*` | Deleted | Deleted |
| `dashboard.html` | Deleted | Deleted |
| `profile.json` | Deleted (re-enter in init) | Kept |
| `resume.txt` / `resume.pdf` | Deleted | Kept |
| `searches.yaml` | Deleted | Kept |
| `.env` (API keys) | **Always kept** | **Always kept** |
| `~/.gmail-mcp/` (Gmail OAuth) | **Not touched** | **Not touched** |
| `logs/` | Kept | Kept |

## Steps

### 1. Reset pipeline data

From WSL (repo root):

```bash
cd /mnt/c/Users/elihe/Projects/applypilot
bash scripts/reset_for_fresh_start.sh
```

If the script fails with `pipefail: invalid option`, fix Windows line endings once:

```bash
sed -i 's/\r$//' scripts/reset_for_fresh_start.sh
```

From Windows:

```powershell
wsl -e bash -lc "cd /mnt/c/Users/elihe/Projects/applypilot && bash scripts/reset_for_fresh_start.sh"
```

To clear jobs/materials only but keep existing profile and search config:

```bash
bash scripts/reset_for_fresh_start.sh --keep-config
```

### 2. Re-run setup wizard

Interactive — updates resume, profile, searches, and optionally LLM keys:

```bash
.venv/bin/applypilot init
```

The wizard **overwrites** `profile.json` and `searches.yaml` and replaces resume files when you provide new paths.

For resume tailoring guardrails, set `resume_facts.employment_history` and `skills_boundary` in `profile.json` after init — see [resume-tailoring.md](resume-tailoring.md).

### 3. Run the pipeline

```bash
.venv/bin/applypilot run              # stages 1–5
.venv/bin/applypilot dashboard        # review results
```

Or stage by stage:

```bash
.venv/bin/applypilot run discover
.venv/bin/applypilot run enrich
.venv/bin/applypilot run score
.venv/bin/applypilot run tailor cover pdf
```

## Verify empty state

```bash
.venv/bin/python scripts/db_stats.py
```

Expect `total: 0` and empty material directories after reset.
