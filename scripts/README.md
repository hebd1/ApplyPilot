# Scripts



Development, smoke-test, and maintenance utilities. Run from repo root via WSL:



```bash

cd /mnt/c/Users/elihe/Projects/applypilot

.venv/bin/python scripts/<script>.py   # Python scripts

bash scripts/<script>.sh               # Shell scripts

```



## LLM / Cursor



| Script | Network | Purpose |

|--------|---------|---------|

| `test_cursor_provider.py` | No | Provider detection unit check |

| `live_cursor_score_test.py` | Yes | Live Cursor Auto scoring smoke test |

| `score_one_job.py` | Yes | Score one job from `~/.applypilot/applypilot.db` |

| `db_stats.py` | No | Print pipeline statistics |

| `update_cursor_env.py` | No | Add/update `CURSOR_API_KEY` in `~/.applypilot/.env` |

| `try_cursor_auth.py` | Yes | Verify cursor-sdk requires an API key |

| `check_apply_materials.py` | No | List jobs with resume/cover/apply URLs |

| `summarize_tailor_failures.py` | No | Summarize failed tailor validations |



## PDF



| Script | Network | Purpose |

|--------|---------|---------|

| `install_playwright.sh` | Yes (apt) | Install Chromium + Linux system deps for PDFs |

| `test_playwright_pdf.py` | No | Smoke-test Playwright PDF rendering |

| `test_xhtml2pdf.py` | No | Smoke-test xhtml2pdf fallback |

| `test_resume_xhtml2pdf.py` | No | Convert sample resume via xhtml2pdf |

| `generate_pdfs.py` | No | Batch convert DB materials `.txt` → PDF |

| `regenerate_pdfs_playwright.py` | No | Re-render all PDFs from source `.txt` via Playwright |

## Resume tailoring

| Script | Network | Purpose |
|--------|---------|---------|
| `sync_resume_source.py` | No | Sync master resume → `~/.applypilot/resume.txt` + `employment_history` |
| `regenerate_materials.py` | Yes | Clear DB materials; re-run tailor + cover |
| `reformat_resume_pdfs.py` | No | Re-layout existing `.txt` + regenerate PDFs |
| `refine_bmo_resume.py` | Yes | Re-tailor reference BMO Senior Cloud Engineer job |
| `refine_canonical_resume.py` | Yes | Re-tailor one job as canonical template |
| `verify_no_merged_employers.py` | No | Fail if tailored text merges Kount + Equifax |
| `fix_additional_sections.py` | No | Normalize additional-information block in `.txt` files |
| `update_employment_profile.py` | No | Update `employment_history` in profile (legacy helper) |

See [docs/resume-tailoring.md](../docs/resume-tailoring.md).



## Maintenance



| Script | Purpose |

|--------|---------|

| `reset_for_fresh_start.sh` | Delete all jobs, materials, dashboard; optional config wipe |
| `gmail_oauth_readonly.sh` | Gmail MCP OAuth with **`gmail.readonly` only** (avoid stock MCP `auth`, which requests modify/settings) |
| `purge_unapplyable_queue.py` | Demote excluded titles; mark LinkedIn/weak apply URLs failed; clear stuck in_progress |
| `poll_application_emails.py` | Gmail readonly: match inbox to applied jobs → outcome fields |
| `daily_apply.sh` | Daily prep + **1** quality ATS apply + email poll |
| `run_daily_apply.cmd` | Windows Task Scheduler wrapper → WSL daily_apply.sh |
| `install_daily_apply_cron.sh` | Install 08:00 America/Denver crontab entry (backup) |
| `install_daily_apply_windows_task.ps1` | Install 08:00 Windows Task (primary schedule) |
| `fix_env_chrome.py` | Set `CHROME_PATH` + `LLM_MODEL=auto` in `.env` |
| `test_chrome_cdp.py` | Verify Chromium launches with CDP for auto-apply |



```bash

bash scripts/reset_for_fresh_start.sh              # full re-onboard (keeps .env)

bash scripts/reset_for_fresh_start.sh --keep-config # jobs + PDFs only

```



Requires `CURSOR_API_KEY` in `~/.applypilot/.env` for live LLM tests.



See [docs/cursor-llm.md](../docs/cursor-llm.md), [docs/discovery.md](../docs/discovery.md), [docs/auto-apply.md](../docs/auto-apply.md) (Gmail: never send/update/delete/settings without explicit consent), [docs/pdf-and-dashboard.md](../docs/pdf-and-dashboard.md), [docs/resume-tailoring.md](../docs/resume-tailoring.md), [docs/reset-onboard.md](../docs/reset-onboard.md).

