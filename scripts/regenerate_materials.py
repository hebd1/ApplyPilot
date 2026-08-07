"""Clear materials, re-run tailor + cover, post-process, dashboard, apply readiness."""
from pathlib import Path

from applypilot.config import COVER_LETTER_DIR, TAILORED_DIR, load_env
from applypilot.database import get_connection, init_db
from applypilot.scoring.cover_letter import run_cover_letters
from applypilot.scoring.tailor import run_tailoring

load_env()
init_db()
conn = get_connection()
MIN_SCORE = 7
LIMIT = 100

print("==> Clearing material paths in database...")
conn.execute(
    """
    UPDATE jobs SET
        tailored_resume_path = NULL,
        tailored_at = NULL,
        tailor_attempts = 0,
        cover_letter_path = NULL,
        cover_letter_at = NULL,
        cover_attempts = 0
    WHERE fit_score >= ?
    """,
    (MIN_SCORE,),
)
conn.commit()

for directory in (TAILORED_DIR, COVER_LETTER_DIR):
    directory.mkdir(parents=True, exist_ok=True)
    for f in directory.iterdir():
        if f.is_file():
            f.unlink()
    print(f"    cleared {directory}")

print("==> Running tailor (with PDF)...")
tailor_stats = run_tailoring(min_score=MIN_SCORE, limit=LIMIT)
print(tailor_stats)

print("==> Running cover letters (with PDF)...")
cover_stats = run_cover_letters(min_score=MIN_SCORE, limit=LIMIT)
print(cover_stats)

print("==> Post-processing (additional sections + employer check)...")
import subprocess
import sys

repo = Path(__file__).resolve().parent.parent
for script in ("scripts/fix_additional_sections.py", "scripts/verify_no_merged_employers.py"):
    r = subprocess.run([sys.executable, str(repo / script)], cwd=repo)
    if r.returncode != 0:
        print(f"WARNING: {script} exited {r.returncode}")

print("==> Re-rendering PDFs from final text...")
r = subprocess.run([sys.executable, str(repo / "scripts/reformat_resume_pdfs.py")], cwd=repo)
if r.returncode != 0:
    print(f"WARNING: reformat_resume_pdfs exited {r.returncode}")

print("==> Regenerating dashboard...")
from applypilot.view import generate_dashboard

generate_dashboard()

eligible = conn.execute("SELECT COUNT(*) FROM jobs WHERE fit_score >= ?", (MIN_SCORE,)).fetchone()[0]
tailored = conn.execute(
    "SELECT COUNT(*) FROM jobs WHERE fit_score >= ? AND tailored_resume_path IS NOT NULL",
    (MIN_SCORE,),
).fetchone()[0]
covers = conn.execute(
    "SELECT COUNT(*) FROM jobs WHERE fit_score >= ? AND cover_letter_path IS NOT NULL",
    (MIN_SCORE,),
).fetchone()[0]
ready_apply = conn.execute(
    """
    SELECT COUNT(*) FROM jobs
    WHERE fit_score >= ?
      AND tailored_resume_path IS NOT NULL
      AND cover_letter_path IS NOT NULL
      AND application_url IS NOT NULL
      AND applied_at IS NULL
      AND (apply_status IS NULL OR apply_status = 'failed')
    """,
    (MIN_SCORE,),
).fetchone()[0]

print("\n==> Summary")
print(f"    eligible (score>={MIN_SCORE}): {eligible}")
print(f"    tailored PDFs:                 {tailored}")
print(f"    cover letter PDFs:             {covers}")
print(f"    ready to apply:                {ready_apply}")
print("\n==> Next: dry-run one application")
print("    .venv/bin/applypilot apply --dry-run -l 1")
print("==> Then full run:")
print("    .venv/bin/applypilot apply --headless -l 10 -w 1")
