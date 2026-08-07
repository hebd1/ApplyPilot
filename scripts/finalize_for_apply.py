"""Finalize materials after retry: post-process, PDFs, dashboard, apply readiness."""
import subprocess
import sys
from pathlib import Path

from applypilot.config import load_env
from applypilot.database import get_connection
from applypilot.view import generate_dashboard

load_env()
repo = Path(__file__).resolve().parent.parent
conn = get_connection()

for script in (
    "scripts/fix_additional_sections.py",
    "scripts/verify_no_merged_employers.py",
    "scripts/reformat_resume_pdfs.py",
):
    print(f"==> {script}")
    r = subprocess.run([sys.executable, str(repo / script)], cwd=repo)
    if r.returncode != 0:
        print(f"WARNING: {script} exited {r.returncode}")

print("==> dashboard")
generate_dashboard()

ready = conn.execute(
    """
    SELECT COUNT(*) FROM jobs
    WHERE fit_score >= 7
      AND tailored_resume_path IS NOT NULL
      AND cover_letter_path IS NOT NULL
      AND application_url IS NOT NULL
      AND applied_at IS NULL
      AND (apply_status IS NULL OR apply_status = 'failed')
    """
).fetchone()[0]
missing_url = conn.execute(
    """
    SELECT COUNT(*) FROM jobs
    WHERE fit_score >= 7
      AND tailored_resume_path IS NOT NULL
      AND (application_url IS NULL OR application_url = '')
    """
).fetchone()[0]
print(f"ready_to_apply={ready} missing_application_url={missing_url}")
print("Dashboard: ~/.applypilot/dashboard.html")
print("Dry-run: .venv/bin/applypilot apply --dry-run -l 1")
print("Apply:   .venv/bin/applypilot apply --headless -l 10 -w 1")
