"""Retry untailored high-score jobs after validator fixes."""
from applypilot.config import load_env
from applypilot.database import get_connection, init_db
from applypilot.scoring.cover_letter import run_cover_letters
from applypilot.scoring.tailor import run_tailoring

load_env()
init_db()
conn = get_connection()

# Reset attempt counters so failed jobs can retry
conn.execute(
    """
    UPDATE jobs SET tailor_attempts = 0
    WHERE fit_score >= 7 AND (tailored_resume_path IS NULL OR tailored_resume_path = '')
    """
)
conn.execute(
    """
    UPDATE jobs SET cover_attempts = 0
    WHERE fit_score >= 7
      AND tailored_resume_path IS NOT NULL
      AND (cover_letter_path IS NULL OR cover_letter_path = '')
    """
)
conn.commit()

pending = conn.execute(
    "SELECT COUNT(*) FROM jobs WHERE fit_score >= 7 AND tailored_resume_path IS NULL"
).fetchone()[0]
print(f"==> Retrying tailor for {pending} jobs...")
print(run_tailoring(min_score=7, limit=100))

print("==> Cover letters for newly tailored...")
print(run_cover_letters(min_score=7, limit=100))

tailored = conn.execute(
    "SELECT COUNT(*) FROM jobs WHERE fit_score >= 7 AND tailored_resume_path IS NOT NULL"
).fetchone()[0]
covers = conn.execute(
    "SELECT COUNT(*) FROM jobs WHERE fit_score >= 7 AND cover_letter_path IS NOT NULL"
).fetchone()[0]
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
print(f"==> tailored={tailored} covers={covers} ready_to_apply={ready}")
